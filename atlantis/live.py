"""Forward (paper) simulation — SIMULATION ONLY, no broker connection.

Each run:
  1. fetches near-live Dukascopy bid/ask data (completed daily bars + latest tick);
  2. replays every account deterministically from LIVE_START through the last
     completed daily bar (decisions after each bar, fills at the next open);
  3. verifies that every fill recorded by earlier runs is reproduced exactly
     (append-only journal) — any difference is a CRITICAL check failure;
  4. marks open positions to the latest tick (display only);
  5. computes the plan (pending orders, signals) and a bootstrap projection;
  6. writes CSV outputs for the dashboard into live/out/.

Usage:  python -m atlantis.live step
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from atlantis.analytics import metrics as M
from atlantis.checks.reconcile import reconcile
from atlantis.intel.sources.dukascopy_live import Fetcher, LiveFetchError, daily_bid_ask, latest_quote
from atlantis.intel.validate import clean_daily
from atlantis.engine import run_backtest
from atlantis.instruments.spec import make_instrument
from atlantis.quant.research.robustness import block_bootstrap
from atlantis.quant.risk.sizing import MinTicketSizer, VolTargetSizer
from atlantis.gate.sim.broker import quote_to_usd
from atlantis.gate.sim.orders import Status
from atlantis.quant.strategies.library import DonchianBreakout, TimeSeriesMomentum

LIVE_START = "2026-11-09"          # first daily bar whose close may trigger a decision
CAPITAL = 200.0
UNIVERSE = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
FIRST_YEAR = 2025                  # history needed for 12-month lookback + vol warm-up
ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR = ROOT / "live"
OUT = LIVE_DIR / "out"


@dataclass(frozen=True)
class AccountSpec:
    id: str
    label: str
    strategy: type
    sizing: str     # "conservative" | "min_ticket"

    def make_sizer(self):
        return VolTargetSizer() if self.sizing == "conservative" else MinTicketSizer()


ACCOUNTS = [
    AccountSpec("A", "Trend 12m · conservative", TimeSeriesMomentum, "conservative"),
    AccountSpec("B", "Trend 12m · min ticket", TimeSeriesMomentum, "min_ticket"),
    AccountSpec("C", "Breakout 55/20 · conservative", DonchianBreakout, "conservative"),
    AccountSpec("D", "Breakout 55/20 · min ticket", DonchianBreakout, "min_ticket"),
]


def load_data(f: Fetcher, until: date) -> tuple[dict, list[dict]]:
    data, checks = {}, []
    for s in UNIVERSE:
        df = daily_bid_ask(f, s, FIRST_YEAR, until)
        clean, issues = clean_daily(df, s)
        data[s] = clean
        for i in issues:
            if i.severity != "INFO" and i.ts >= LIVE_START:
                checks.append({"check": f"data:{i.check}", "status": i.severity,
                               "detail": f"{s} {i.ts[:10]} {i.detail}"})
        errs = [i for i in issues if i.severity == "ERROR"]
        if errs:
            raise RuntimeError(f"{s}: {len(errs)} data ERRORs, refusing to simulate: {errs[:3]}")
        lag = (pd.Timestamp(until, tz="UTC") - clean.index[-1]).days
        checks.append({"check": f"data_freshness:{s}", "status": "OK" if lag <= 3 else "WARN",
                       "detail": f"last completed bar {clean.index[-1].date()} ({lag}d before {until})"})
    return data, checks


def aggregation_check(f: Fetcher) -> dict:
    """Daily bars built from hourly candles must equal Dukascopy's own day candles."""
    from atlantis.intel.sources.dukascopy_live import _candles, _to_daily
    y, m = 2025, 12
    hour = f.get(f"EURUSD/{y}/{m - 1:02d}/BID_candles_hour_1.bi5", datetime(y + 1, 1, 1, tzinfo=UTC))
    day = f.get(f"EURUSD/{y}/BID_candles_day_1.bi5", datetime(y + 1, 1, 1, tzinfo=UTC))
    a = _to_daily(_candles(hour, datetime(y, m, 1, tzinfo=UTC), "EURUSD"))
    d = _candles(day, datetime(y, 1, 1, tzinfo=UTC), "EURUSD")
    d = d[(d.index >= a.index[0]) & (d["volume"] > 0)]
    j = a.join(d, lsuffix="_h", rsuffix="_d", how="inner")
    diff = max(float((j[f"{k}_h"] - j[f"{k}_d"]).abs().max()) for k in ("open", "high", "low", "close"))
    return {"check": "hourly_vs_daily_aggregation", "status": "OK" if diff < 1e-9 else "ERROR",
            "detail": f"EURUSD Dec-2025, {len(j)} days, max |diff| = {diff:.6f}"}


def projection(spec: AccountSpec, data: dict, equity_now: float, days: int) -> dict:
    """Block-bootstrap the account's own backtest returns (FIRST_YEAR..LIVE_START)."""
    r = run_backtest(data, spec.strategy(), CAPITAL, start=f"{FIRST_YEAR + 1}-01-01", end=LIVE_START,
                     sizer=spec.make_sizer(), verify_causality=False)
    rets = M.returns_from_equity(r.equity).to_numpy()
    out = {"account": spec.id, "horizon_trading_days": days, "history_days": len(rets),
           "history_from": str(r.equity.index[0].date()), "equity_now": round(equity_now, 2)}
    if len(rets) < 60 or days <= 0 or np.allclose(rets, 0):
        out.update({"p5": equity_now, "p50": equity_now, "p95": equity_now,
                    "p_double": 0.0, "p_lose_half": 0.0,
                    "note": "no trading in history at this size" if np.allclose(rets, 0) else "short history"})
        return out
    paths = block_bootstrap(np.clip(rets, -0.999, None), 4000, days, 5, np.random.default_rng(11))
    w = equity_now * np.cumprod(1 + paths, axis=1)
    end = w[:, -1]
    out.update({"p5": float(np.percentile(end, 5)), "p50": float(np.percentile(end, 50)),
                "p95": float(np.percentile(end, 95)), "p_double": float((end >= 2 * equity_now).mean()),
                "p_lose_half": float((w.min(axis=1) <= 0.5 * equity_now).mean()),
                "hist_ann_vol": float(np.std(rets) * math.sqrt(252)), "note": ""})
    return out


def step(now: datetime | None = None, write: bool = True) -> dict:
    now = now or datetime.now(UTC)
    until = (now - timedelta(days=1)).date()
    f = Fetcher(ROOT / "data" / "raw" / "dukascopy_live", now=now)
    checks: list[dict] = []
    data, dchecks = load_data(f, until)
    checks += dchecks
    try:
        checks.append(aggregation_check(f))
    except LiveFetchError as e:
        checks.append({"check": "hourly_vs_daily_aggregation", "status": "WARN", "detail": f"skipped: {e}"})
    quotes = {}
    for s in UNIVERSE:
        q = latest_quote(f, s)
        if q:
            quotes[s] = q
    qmids = {s: (q["bid"] + q["ask"]) / 2 for s, q in quotes.items()}
    instruments = {s: make_instrument(s) for s in UNIVERSE}
    last_bar = min(d.index[-1] for d in data.values())
    live_started = last_bar >= pd.Timestamp(LIVE_START, tz="UTC")

    rows = {k: [] for k in ("accounts", "equity", "fills", "positions", "plan", "projection")}
    journal_new = []
    end_of_obs = date(2026, 12, 9)
    horizon = int(np.busday_count(now.date(), end_of_obs)) if now.date() < end_of_obs else 0
    for spec in ACCOUNTS:
        if live_started:
            res = run_backtest(data, spec.strategy(), CAPITAL, start=LIVE_START, sizer=spec.make_sizer(),
                               instruments=instruments, rebalance_on_start=True)
            led, br = res.ledger, res.broker
            breaks = reconcile(res)
            checks.append({"check": f"reconciliation:{spec.id}", "status": "OK" if not breaks else "ERROR",
                           "detail": "; ".join(breaks) or "engine ledger == independent FIFO recomputation"})
            led.check_invariants()
            eq_series = res.equity
            pending = [o for o in br.orders if o.status is Status.PENDING]
            sig = res.signals.loc[res.signals.index[res.signals.index <= last_bar][-1]]
        else:
            led = br = None
            eq_series = pd.Series(dtype=float)
            pending = []
            sig = spec.strategy().signals(*_mid_panels(data)).iloc[-1]
        # live mark-to-market at latest tick (display only; decisions use daily bars)
        cash = led.cash if led else CAPITAL
        unreal = 0.0
        if led and led.lots:
            mids = dict(br.last_mids)
            mids.update(qmids)
            marks = {s: (quotes[s]["bid"], quotes[s]["ask"]) if s in quotes else br.last_marks[s]
                     for s in led.lots}
            q2u = {s: quote_to_usd(instruments[s].quote, mids) for s in led.lots}
            u = led.unrealised_usd(marks, q2u)
            unreal = sum(u.values())
            for s, book in led.lots.items():
                qty = sum(l.qty for l in book)
                avg = sum(l.qty * l.price for l in book) / qty
                rows["positions"].append({
                    "account": spec.id, "symbol": s, "side": "LONG" if qty > 0 else "SHORT",
                    "qty": qty, "avg_entry": round(avg, 6), "mark_bid": marks[s][0], "mark_ask": marks[s][1],
                    "mark_ts": quotes.get(s, {}).get("ts", str(br._last_ts)),
                    "unrealised_usd": round(u[s], 2),
                    "notional_usd": round(abs(qty) * mids[s] * q2u[s], 2),
                    "margin_usd": round(abs(qty) * mids[s] * q2u[s] * instruments[s].initial_margin, 2)})
        equity_live = cash + unreal
        for t, v in eq_series.items():
            rows["equity"].append({"ts": t.isoformat(), "account": spec.id, "equity": round(v, 4),
                                   "kind": "daily close"})
        rows["equity"].append({"ts": now.isoformat(timespec="minutes"), "account": spec.id,
                               "equity": round(equity_live, 4), "kind": "live mark"})
        totals = led.totals if led else {"commissions": 0, "financing": 0, "conversion_fees": 0,
                                         "realised_gross": 0}
        stats = br.stats if br else {"fills": 0, "rejects": 0, "spread_cost_usd": 0, "slippage_usd": 0}
        mdd = M.max_drawdown(pd.concat([pd.Series([CAPITAL]), eq_series.reset_index(drop=True),
                                        pd.Series([equity_live])]))
        rows["accounts"].append({
            "account": spec.id, "name": spec.label, "strategy": spec.strategy.name,
            "sizing": spec.sizing, "start_capital": CAPITAL, "equity": round(equity_live, 2),
            "return_pct": round((equity_live / CAPITAL - 1) * 100, 2), "cash": round(cash, 2),
            "unrealised": round(unreal, 2), "realised": round(totals["realised_gross"], 2),
            "commissions": round(totals["commissions"], 2), "financing": round(totals["financing"], 4),
            "conversion_fees": round(totals["conversion_fees"], 4),
            "spread_cost_est": round(stats["spread_cost_usd"], 2), "fills": int(stats["fills"]),
            "rejects": int(stats["rejects"]), "open_positions": len(led.lots) if led else 0,
            "max_drawdown_pct": round(mdd * 100, 2), "halted": bool(br.halted) if br else False})
        if led:
            for e in res.audit.events:
                if e["kind"] == "FILL":
                    side = "BUY" if e["qty"] > 0 else "SELL"
                    bar = data[e["symbol"]].loc[pd.Timestamp(e["fill_ts"])]
                    rec = {"account": spec.id, "ts": e["fill_ts"], "symbol": e["symbol"], "side": side,
                           "qty": abs(e["qty"]), "price": round(e["price"], 6),
                           "bar_bid_open": bar["bid_open"], "bar_ask_open": bar["ask_open"],
                           "decision_mid": round(e["decision_mid"], 6) if e["decision_mid"] else None,
                           "commission_usd": e["commission"], "slippage_usd": round(e["slippage_usd"], 4),
                           "reason": e["reason"], "tag": e["tag"], "label": "SIMULATED",
                           "data_source": "Dukascopy daily bar open (00:00 UTC)"}
                    rows["fills"].append(rec)
                    journal_new.append({k: rec[k] for k in ("account", "ts", "symbol", "side", "qty", "price")})
        nxt = (f"after the {LIVE_START} daily bar closes (live start)" if not live_started
               else _next_decision(now, spec.strategy.rebalance))
        for s in UNIVERSE:
            cur = led.position(s) if led else 0.0
            pend = [o for o in pending if o.symbol == s]
            action = "; ".join(f"{'BUY' if o.qty > 0 else 'SELL'} {abs(o.qty):g} {o.type.value}"
                               + (f" @ {o.price:.5f}" if o.price else "") + f" ({o.tag})" for o in pend)
            rows["plan"].append({
                "account": spec.id, "symbol": s, "signal": float(sig.get(s, np.nan)),
                "signal_text": {1.0: "LONG", -1.0: "SHORT", 0.0: "FLAT"}.get(float(sig.get(s, 0)), "n/a"),
                "position_qty": cur, "pending_orders": action or "none",
                "executes_at": (str(last_bar + pd.Timedelta(days=1))[:16] + " UTC open") if pend else "",
                "next_decision": nxt})
        rows["projection"].append(projection(spec, data, equity_live, horizon))
    # append-only journal verification
    jpath = LIVE_DIR / "journal.jsonl"
    old = [json.loads(x) for x in jpath.read_text().splitlines()] if jpath.exists() else []
    mism = [i for i, o in enumerate(old) if i >= len(journal_new) or not _same(o, journal_new[i])]
    checks.append({"check": "journal_append_only", "status": "OK" if not mism else "CRITICAL",
                   "detail": f"{len(old)} earlier fills reproduced exactly" if not mism
                   else f"{len(mism)} earlier fills changed (first at line {mism[0] + 1})"})
    prices = []
    for s, d in data.items():
        for t, r in d.tail(30).iterrows():
            prices.append({"symbol": s, "ts": t.isoformat(), "kind": "daily bar", "bid_open": r.bid_open,
                           "ask_open": r.ask_open, "bid_close": r.bid_close, "ask_close": r.ask_close})
        if s in quotes:
            q = quotes[s]
            prices.append({"symbol": s, "ts": q["ts"], "kind": "latest tick", "bid_close": q["bid"],
                           "ask_close": q["ask"]})
    run = {"run_utc": now.isoformat(timespec="seconds"), "live_start": LIVE_START,
           "last_completed_bar": str(last_bar.date()), "live_started": bool(live_started),
           "universe": UNIVERSE, "files_used": len(f.provenance),
           "label": "SIMULATED executions on Dukascopy (non-Saxo) market data"}
    checks = [{"run_utc": run["run_utc"], **c} for c in checks]
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        for k, v in rows.items():
            pd.DataFrame(v).to_csv(OUT / f"{k}.csv", index=False)
        pd.DataFrame(prices).to_csv(OUT / "prices.csv", index=False)
        pd.DataFrame(checks).to_csv(OUT / "checks.csv", index=False)
        (OUT / "run.json").write_text(json.dumps(run, indent=1))
        bundle = {k: json.loads(pd.DataFrame(v).to_json(orient="records")) for k, v in rows.items()}
        bundle["prices"] = json.loads(pd.DataFrame(prices).to_json(orient="records"))
        bundle["checks"] = json.loads(pd.DataFrame(checks).to_json(orient="records"))
        bundle["run"] = [run | {"universe": ", ".join(UNIVERSE)}]
        (OUT / "live.json").write_text(json.dumps(bundle))
        if not mism:
            jpath.write_text("".join(json.dumps(j) + "\n" for j in journal_new))
        with (LIVE_DIR / "run_log.jsonl").open("a") as fh:
            fh.write(json.dumps({**run, "checks_failed": [c for c in checks if c["status"]
                                                          not in ("OK", "INFO")]}, default=str) + "\n")
    return {"run": run, "rows": rows, "checks": checks}


def _same(a: dict, b: dict) -> bool:
    return all((abs(a[k] - b[k]) < 1e-9) if isinstance(a[k], float) else a[k] == b[k] for k in a)


def _mid_panels(data):
    from atlantis.engine import build_panels
    p = build_panels(data)
    return p["mid_close"], p


def _next_decision(now: datetime, rebalance: str) -> str:
    d = now.date() + timedelta(days=1)
    if rebalance == "M":
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1) if now.day > 1 else d
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return f"after the {d - timedelta(days=1 if rebalance == 'D' else 0)} daily bar closes"


if __name__ == "__main__":
    if sys.argv[1:] != ["step"]:
        raise SystemExit("usage: python -m atlantis.live step")
    out = step()
    bad = [c for c in out["checks"] if c["status"] in ("ERROR", "CRITICAL")]
    print(json.dumps(out["run"], indent=1))
    for a in out["rows"]["accounts"]:
        print(a["account"], a["name"], a["equity"], a["fills"], "fills")
    print("checks failing:", bad or "none")
    sys.exit(2 if bad else 0)
