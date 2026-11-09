"""Event-driven daily backtest engine (SIMULATION ONLY)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from atlantis.audit.log import AuditLog, run_manifest
from atlantis.data.store import frame_hash
from atlantis.instruments.spec import Instrument, make_instrument
from atlantis.portfolio.ledger import Ledger
from atlantis.risk.sizing import VolTargetSizer, ewma_vol
from atlantis.sim.broker import Broker, quote_to_usd
from atlantis.sim.costs import CostModel
from atlantis.sim.fills import Bar
from atlantis.sim.orders import TIF, OrderType, Status
from atlantis.strategies.base import Strategy

FIELDS = [f"{s}_{k}" for s in ("bid", "ask") for k in ("open", "high", "low", "close")]


class LookAheadError(RuntimeError):
    pass


def build_panels(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    panels = {f: pd.DataFrame({s: d[f] for s, d in data.items()}).sort_index() for f in FIELDS}
    panels["mid_close"] = (panels["bid_close"] + panels["ask_close"]) / 2
    return panels


def check_causality(strategy: Strategy, mid: pd.DataFrame, panels: dict, n_checks: int = 12,
                    seed: int = 0) -> None:
    """Recompute signals on truncated history and require identical values.
    Any difference means the strategy used future data (look-ahead bias)."""
    full = strategy.signals(mid, panels)
    full_stops = strategy.stops(mid, panels)
    rng = np.random.default_rng(seed)
    valid = mid.index[300:] if len(mid) > 400 else mid.index[len(mid) // 2:]
    for d in rng.choice(valid, size=min(n_checks, len(valid)), replace=False):
        trunc = {k: v.loc[:d] for k, v in panels.items()}
        part = strategy.signals(mid.loc[:d], trunc).loc[d]
        if not np.allclose(part.fillna(-99).to_numpy(), full.loc[d].fillna(-99).to_numpy()):
            raise LookAheadError(f"{strategy.name}: signal at {d} changes when future data is removed")
        if full_stops is not None:
            ps = strategy.stops(mid.loc[:d], trunc).loc[d]
            if not np.allclose(ps.fillna(-99).to_numpy(), full_stops.loc[d].fillna(-99).to_numpy()):
                raise LookAheadError(f"{strategy.name}: stop at {d} uses future data")


@dataclass
class BacktestResult:
    equity: pd.Series
    exposure: pd.DataFrame
    broker: Broker
    sizer: VolTargetSizer
    audit: AuditLog
    manifest: dict
    signals: pd.DataFrame
    mid: pd.DataFrame
    meta: dict = field(default_factory=dict)

    @property
    def ledger(self) -> Ledger:
        return self.broker.ledger


def run_backtest(data: dict[str, pd.DataFrame], strategy: Strategy, capital: float = 200.0,
                 start: str | None = None, end: str | None = None,
                 sizer: VolTargetSizer | None = None, costs: CostModel | None = None,
                 extra_spread_bps: float = 0.0, carver_buffer: float = 0.10,
                 instruments: dict[str, Instrument] | None = None,
                 verify_causality: bool = True) -> BacktestResult:
    sizer = sizer or VolTargetSizer()
    costs = costs or CostModel.saxo_classic()
    instruments = instruments or {s: make_instrument(s) for s in data}
    panels = build_panels(data)
    mid = panels["mid_close"]
    if verify_causality:
        check_causality(strategy, mid, panels)
    sig = strategy.signals(mid, panels)
    stop_dist = strategy.stops(mid, panels)
    vols = ewma_vol(mid)
    # Warm-up uses all history; trading is restricted to [start, end].
    idx = mid.index
    if start:
        idx = idx[idx >= pd.Timestamp(start, tz=idx.tz)]
    if end:
        idx = idx[idx <= pd.Timestamp(end, tz=idx.tz)]
    audit = AuditLog()
    ledger = Ledger(capital, conversion_fee=_conv_fee(costs))
    broker = Broker(instruments, ledger, costs, audit, extra_spread_bps)
    eq_rows, expo_rows = [], []
    stop_orders: dict[str, object] = {}
    stopped_dir: dict[str, float] = {}
    prev_month = None
    for t in idx:
        ts = t.isoformat()
        bars = {}
        for s in data:
            row = [panels[f].at[t, s] for f in FIELDS]
            if not any(math.isnan(x) for x in row):
                bars[s] = Bar(ts, *row)
        pos_before = {s: ledger.position(s) for s in data}
        broker.process_bar(ts, bars)
        # detect stop-outs: position went to zero via a stop order this bar
        for s, o in list(stop_orders.items()):
            if o.status is Status.FILLED:
                stopped_dir[s] = math.copysign(1.0, pos_before[s])
                audit.event(ts, "STOPPED_OUT", symbol=s)
                del stop_orders[s]
        equity = broker.equity()
        mids = dict(broker.last_mids)
        eq_rows.append((t, equity))
        expo_rows.append({"ts": t, **{s: ledger.position(s) * mids[s] * quote_to_usd(
            instruments[s].quote, mids) if ledger.position(s) else 0.0 for s in data}})
        if broker.halted:
            continue
        month_change = prev_month is not None and t.month != prev_month
        prev_month = t.month
        if strategy.rebalance == "M" and not month_change:
            continue
        s_t = sig.loc[t].copy()
        for s in list(stopped_dir):
            if s_t.get(s, 0) == stopped_dir[s]:
                s_t[s] = 0.0              # no re-entry until the signal resets
            else:
                del stopped_dir[s]
        tradable = [s for s in data if s in bars and s in mids]
        usd_per_unit = {s: mids[s] * quote_to_usd(instruments[s].quote, mids) for s in tradable}
        tg = sizer.targets(s_t[tradable], vols.loc[t, tradable], equity, usd_per_unit,
                           {s: instruments[s] for s in tradable})
        for s, target in tg.items():
            cur = ledger.position(s)
            if strategy.rebalance == "D" and cur != 0 and np.sign(target) == np.sign(cur) \
                    and not month_change:
                continue                  # hold: resize only monthly
            if target != 0 and abs(target - cur) < carver_buffer * abs(target):
                continue                  # Carver (2015) position buffer
            delta = target - cur
            if delta == 0:
                continue
            for o in broker.orders:      # cancel stale working orders for this symbol
                if o.symbol == s and o.status is Status.PENDING and o.tag != "stop":
                    broker.cancel(ts, o)
            broker.submit(ts, s, delta, OrderType.MARKET, tag="rebalance")
            if stop_dist is not None:
                if s in stop_orders:
                    broker.cancel(ts, stop_orders.pop(s))
                dist = stop_dist.at[t, s]
                if target != 0 and np.isfinite(dist) and dist > 0:
                    lvl = mids[s] - math.copysign(dist, target)
                    stop_orders[s] = broker.submit(ts, s, -target, OrderType.STOP, lvl,
                                                   TIF.GTC, tag="stop")
    equity = pd.Series(dict(eq_rows), name="equity")
    exposure = pd.DataFrame(expo_rows).set_index("ts") if expo_rows else pd.DataFrame()
    manifest = run_manifest(
        {"strategy": strategy.name, "params": strategy.params(), "capital": capital,
         "start": str(idx[0]) if len(idx) else None, "end": str(idx[-1]) if len(idx) else None,
         "sizer": {"portfolio_vol": sizer.portfolio_vol, "leverage_scale": sizer.leverage_scale},
         "cost_multiplier": costs.cost_multiplier, "extra_spread_bps": extra_spread_bps,
         "carver_buffer": carver_buffer},
        {s: frame_hash(d) for s, d in data.items()})
    return BacktestResult(equity, exposure, broker, sizer, audit, manifest, sig, mid)


def _conv_fee(costs: CostModel) -> float:
    from atlantis.instruments.spec import conditions
    return conditions()["currency_conversion"]["fee_pct"]["value"] * costs.cost_multiplier
