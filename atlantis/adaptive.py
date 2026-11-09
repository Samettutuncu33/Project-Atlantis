"""ATLANTIS Adaptive: the self-learning, multi-asset paper account (SIMULATION ONLY).

Daily loop, bar t (all information <= t):
  1. SimBroker processes bar t (fills of yesterday's orders, financing, margin).
  2. RESOLVE: predictions whose outcome bar is t are scored (Brier), the Hedge
     weights of each predictor are updated per asset class, and a resolution
     record is appended to the hash-chained prediction ledger.
  3. RETRAIN (first bar of each month): ML predictors refit on outcomes known
     before t minus an embargo; the calibrator refits on resolved predictions.
  4. PREDICT: every predictor gives P(up in H bars) per instrument; the Hedge
     ensemble combines them; the calibrator corrects the probability. The
     prediction is written to the ledger BEFORE its outcome exists.
  5. DECIDE: quant/decide.py proposes target positions (half Kelly, edge > cost).
  6. GATE: every change becomes an OrderIntent that the central risk gate checks
     and routes to the simulated broker for execution at bar t+1's open.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from atlantis.audit.log import AuditLog
from atlantis.engine import FIELDS, build_panels
from atlantis.gate.portfolio.ledger import Ledger
from atlantis.gate.risk_gate import OrderIntent, RiskGate
from atlantis.gate.sim.broker import Broker, quote_to_usd
from atlantis.gate.sim.costs import CostModel
from atlantis.gate.sim.fills import Bar
from atlantis.gate.sim.orders import Status
from atlantis.instruments.spec import Instrument, make_instrument
from atlantis.quant.decide import propose
from atlantis.quant.learn.knowhow import Calibrator, HedgeWeights, PredictionLedger, lessons
from atlantis.quant.predict.features import FEATURES, build_features, forward_labels
from atlantis.quant.predict.models import default_predictors, training_set

HORIZON = 5           # trading bars; the predictions are about the next week
STRATEGY_ID = "adaptive"
CLASS_NAMES = {"fx_spot": "FX", "crypto_fx": "Crypto", "stock_cfd": "Stocks", "index_cfd": "Indices",
               "commodity_cfd": "Oil", "metal_cfd": "Gold"}


@dataclass
class AdaptiveResult:
    equity: pd.Series
    broker: Broker
    gate: RiskGate
    hedge: HedgeWeights
    calibrator: Calibrator
    ledger: PredictionLedger
    proposals: list[dict] = field(default_factory=list)
    weights_history: list[dict] = field(default_factory=list)

    @property
    def lessons(self) -> list[str]:
        return lessons(self.hedge, CLASS_NAMES)


def run_adaptive(data: dict[str, pd.DataFrame], capital: float = 200.0, start: str | None = None,
                 end: str | None = None, ledger_path: Path | None = None,
                 instruments: dict[str, Instrument] | None = None,
                 trade_from: str | None = None, controls=None) -> AdaptiveResult:
    """`trade_from`: before this date the account predicts and learns but never trades
    (warm-up of the know-how on real outcomes); equity stays at `capital`."""
    instruments = instruments or {s: make_instrument(s) for s in data}
    panels = build_panels(data)
    mid = panels["mid_close"]
    feats = build_features(panels)
    labels = forward_labels(panels, HORIZON)
    predictors = default_predictors()
    names = [p.name for p in predictors]
    hedge = HedgeWeights(names)
    calib = Calibrator()
    pledger = PredictionLedger(ledger_path)
    audit = AuditLog()
    broker = Broker(instruments, Ledger(capital), CostModel.saxo_classic(), audit)
    gate = RiskGate(broker, budgets={STRATEGY_ID: 1.0})
    idx = mid.index
    if start:
        idx = idx[idx >= pd.Timestamp(start, tz=idx.tz)]
    if end:
        idx = idx[idx <= pd.Timestamp(end, tz=idx.tz)]
    open_preds: list[dict] = []
    resolved_p, resolved_y = [], []
    eq_rows, props_out, w_hist = [], [], []
    prev_month = None
    for t in idx:
        ts = t.isoformat()
        bars = {}
        for s in data:
            row = [panels[f].at[t, s] for f in FIELDS]
            if not any(math.isnan(x) for x in row):
                bars[s] = Bar(ts, *row)
        broker.process_bar(ts, bars)
        gate.on_bar(ts)
        eq_rows.append((t, broker.equity()))
        # 2. resolve matured predictions
        still = []
        for pr in open_preds:
            if pd.Timestamp(pr["outcome_at"]) <= t:
                y = pr["_up"]
                hedge.update(pr["asset_class"], pr["predictor_probs"], y)
                resolved_p.append(pr["p_raw"])
                resolved_y.append(y)
                pledger.append({"kind": "resolution", "prediction_id": pr["id"], "resolved_at": ts,
                                "outcome_up": y, "fwd_log_return": pr["_ret"],
                                "brier_final": (pr["p_final"] - y) ** 2,
                                "hit": int((pr["p_final"] > 0.5) == (y > 0.5)) if pr["p_final"] != 0.5 else None})
            else:
                still.append(pr)
        open_preds = still
        # 3. monthly retrain (only on information known before t)
        if prev_month != t.month:
            X, y = training_set(feats, labels, t)
            for p in predictors:
                if p.trainable:
                    p.fit(X, y)
            calib.fit(np.array(resolved_p), np.array(resolved_y))
            w_hist.append({"ts": ts, **{f"{c}:{k}": v for c in hedge.cum_loss
                                       for k, v in hedge.weights(c).items()}})
        prev_month = t.month
        mode, flatten_now = controls.mode_at(t) if controls else ("RUNNING", False)
        gate.mode = mode
        if flatten_now:
            for o in broker.orders:
                if o.status in (Status.PENDING, Status.PARTIAL):
                    broker.cancel(ts, o)
            for s_ in list(broker.ledger.lots):
                q_ = broker.ledger.position(s_)
                if q_:
                    gate.submit(OrderIntent(STRATEGY_ID, s_, -q_, ts, tag="flatten"), ts)
            audit.event(ts, "CONTROL_FLATTEN", severity="WARN")
        if broker.halted:
            continue
        # 4. predict
        try:
            today = feats.xs(t, level="ts")
        except KeyError:
            continue
        today = today[today.index.isin(list(bars))].dropna(subset=["ret_250", "vol20"])
        if today.empty:
            continue
        raw = {p.name: (p.predict_symbols(t, list(today.index)) if hasattr(p, "predict_symbols")
                        else p.predict(today[FEATURES])) for p in predictors}
        equity = broker.equity()
        mids = dict(broker.last_mids)
        for i, sym in enumerate(today.index):
            inst = instruments[sym]
            probs = {n: (None if raw[n][i] is None else float(raw[n][i])) for n in names}
            p_raw = hedge.combine(inst.asset_class, probs)
            p_final = calib(p_raw)
            lab = labels.loc[(t, sym)] if (t, sym) in labels.index else None
            outcome_at = lab["known_at"] if lab is not None else None
            rec = pledger.append({
                "kind": "prediction", "id": f"{ts[:10]}:{sym}", "made_at": ts, "symbol": sym,
                "asset_class": inst.asset_class, "horizon_bars": HORIZON,
                "predictor_probs": {k: (None if v is None else round(v, 5)) for k, v in probs.items()},
                "weights": {k: round(v, 4) for k, v in hedge.weights(inst.asset_class).items()},
                "p_raw": round(p_raw, 5), "p_final": round(p_final, 5), "mid_at_prediction": today.at[sym, "mid"]})
            if outcome_at is not None and pd.notna(outcome_at):
                open_preds.append({**rec, "outcome_at": outcome_at, "_up": float(lab["up"]),
                                   "_ret": float(lab["fwd_ret"])})
            if (trade_from is not None and t < pd.Timestamp(trade_from, tz=t.tz)) or mode != "RUNNING":
                continue                       # predictions and learning continue while paused
            # 5. decide
            usd_per_unit = mids[sym] * quote_to_usd(inst.quote, mids)
            spread = panels["ask_close"].at[t, sym] - panels["bid_close"].at[t, sym]
            pp = propose(sym, p_final, float(today.at[sym, "vol20"]), HORIZON, equity, usd_per_unit,
                         spread, mids[sym], inst)
            cur = broker.ledger.position(sym)
            delta = pp.target_qty - cur
            props_out.append({"ts": ts, "symbol": sym, "p": round(p_final, 4), "target": pp.target_qty,
                              "current": cur, "edge_usd": round(pp.edge_usd, 2),
                              "cost_usd": round(pp.cost_usd, 2), "reason": pp.reason})
            if abs(delta) < inst.min_size / 2 or (pp.target_qty and abs(delta) < 0.25 * abs(pp.target_qty)):
                continue                       # buffer: don't pay commissions for tiny resizes
            for o in broker.orders:
                if o.symbol == sym and o.status is Status.PENDING:
                    broker.cancel(ts, o)
            reduces = cur != 0 and (pp.target_qty == 0 or (pp.target_qty > 0) != (cur > 0))
            gate.submit(OrderIntent(STRATEGY_ID, sym, delta, ts, tag="adaptive",
                                    expected_edge_usd=None if reduces or pp.target_qty == 0 else pp.edge_usd,
                                    est_cost_usd=pp.cost_usd), ts)
    equity = pd.Series(dict(eq_rows), name="equity")
    return AdaptiveResult(equity, broker, gate, hedge, calib, pledger, props_out, w_hist)
