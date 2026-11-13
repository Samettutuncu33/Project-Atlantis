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
from atlantis.intel.sources.dukascopy_live import (Fetcher, LiveFetchError, daily_bid_ask, hourly_bid_ask,
                                                    latest_quote)
from atlantis.intel.validate import clean_daily
from atlantis.engine import run_backtest
from atlantis.instruments.spec import make_instrument
from atlantis.quant.learn.knowhow import PredictionLedger
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


def CONTROLS():
    from atlantis.controls import Controls
    return Controls.load(LIVE_DIR / "controls.jsonl")


def frozen_first_year(symbol: str) -> int:
    """History span is frozen the first time a symbol is used live (live/history_years.json),
    so later downloads can't change the replay and silently rewrite recorded predictions.
    To extend history deliberately, delete the entry. That is a new trial, logged in git."""
    path = LIVE_DIR / "history_years.json"
    frozen = json.loads(path.read_text()) if path.exists() else {}
    if symbol not in frozen:
        frozen[symbol] = cached_first_year(symbol)
        if _WRITE_STATE:
            path.write_text(json.dumps(frozen, indent=1, sort_keys=True))
    return int(frozen[symbol])


_WRITE_STATE = True


def cached_first_year(symbol: str, floor: int = 2016) -> int:
    """Earliest year from which BOTH sides' yearly files are cached contiguously up to
    FIRST_YEAR. The adaptive account replays that whole history to build know-how,
    never downloading during a run, so every run replays the same years."""
    d = ROOT / "data" / "raw" / "dukascopy_live" / symbol

    def has(year: int, side: str) -> bool:
        # A cached 404 is an empty placeholder: it exists on disk but holds no data.
        f = d / str(year) / f"{side}_candles_day_1.bi5"
        return f.exists() and f.stat().st_size > 0

    y = FIRST_YEAR
    while y - 1 >= floor and all(has(y - 1, side) for side in ("BID", "ASK")):
        y -= 1
    return y


def load_data(f: Fetcher, until: date, symbols: list[str] | None = None,
              strict: bool = True, history: bool = False) -> tuple[dict, list[dict]]:
    data, checks = {}, []
    for s in symbols or UNIVERSE:
        try:
            df = daily_bid_ask(f, s, frozen_first_year(s) if history else FIRST_YEAR, until)
        except LiveFetchError as e:
            if strict:
                raise
            checks.append({"check": f"data_unavailable:{s}", "status": "WARN",
                           "detail": f"{s} skipped this run: {str(e)[:120]}"})
            continue
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
    global _WRITE_STATE
    _WRITE_STATE = write
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

    rows = {k: [] for k in ("accounts", "equity", "fills", "positions", "plan", "projection", "_closed")}
    journal_new = []
    end_of_obs = date(2026, 12, 9)
    horizon = int(np.busday_count(now.date(), end_of_obs)) if now.date() < end_of_obs else 0
    for spec in ACCOUNTS:
        if live_started:
            res = run_backtest(data, spec.strategy(), CAPITAL, start=LIVE_START, sizer=spec.make_sizer(),
                               instruments=instruments, rebalance_on_start=True, controls=CONTROLS())
            led, br = res.ledger, res.broker
            breaks = reconcile(res)
            checks.append({"check": f"reconciliation:{spec.id}", "status": "OK" if not breaks else "ERROR",
                           "detail": "; ".join(breaks) or "engine ledger == independent FIFO recomputation"})
            led.check_invariants()
            rows["_closed"].extend((spec.id, c.symbol, c.pnl_usd_gross - c.conversion_fee_usd) for c in led.closed)
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
                    "opened": book[0].opened, "q2u": q2u[s],
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
    # ---- Account E: Atlantis Adaptive (multi-asset, self-learning) ---------------------
    checks += adaptive_section(f, until, now, quotes, rows, journal_new, write)
    checks += adaptive_section(f, until, now, quotes, rows, journal_new, write, acct="F", hourly=True)
    # append-only journal verification
    jpath = LIVE_DIR / "journal.jsonl"
    old = [json.loads(x) for x in jpath.read_text().splitlines()] if jpath.exists() else []
    journal_new.sort(key=lambda j: (j["ts"], j["account"], j["symbol"], j["side"]))
    mism = journal_check(old, journal_new)
    checks.append({"check": "journal_append_only", "status": "OK" if not mism else "CRITICAL",
                   "detail": f"{len(old)} earlier fills reproduced; {len(journal_new) - len(old)} new" if not mism
                   else f"{len(mism)} earlier fills changed: {'; '.join(mism[:3])}"[:400]})
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
           "trading_mode": CONTROLS().current()["mode"],
           "control_since": CONTROLS().current().get("since"),
           "label": "SIMULATED executions on Dukascopy (non-Saxo) market data"}
    portfolio_enrich(rows)
    from atlantis.intel.news import bundle_rows
    rows.update(bundle_rows(ROOT / "knowledge" / "intel"))
    rows["agents"] = agents_rows(rows, now)
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


INTRADAY_DATA_FROM = "2026-01-01"     # hourly history start (frozen)
INTRADAY_LEARN_FROM = "2026-02-02"    # after ~250 hourly bars of feature warm-up
INTRADAY_START = "2026-11-09T17:00:00+00:00"   # first hourly bar whose close may trade (account F)
INTRADAY_HORIZON = 4                  # predictions are about the next 4 hours (pre-registered)
ADAPTIVE_LEARN_FROM = "2017-01-01"   # replay history from here when cached (needs 250 bars of warm-up)


def adaptive_section(f: Fetcher, until: date, now: datetime, quotes: dict, rows: dict,
                     journal_new: list, write: bool = True, acct: str = "E",
                     hourly: bool = False) -> list[dict]:
    """Account E: daily bars, 5-day predictions. Account F: hourly bars, 4-hour predictions,
    with daily/weekly context features and the hourly AI analyst."""
    from atlantis.adaptive import CLASS_NAMES, run_adaptive
    from atlantis.engine import BacktestResult
    from atlantis.instruments.spec import universe
    checks: list[dict] = []
    syms = list(universe()["instruments"])
    data, dchecks = load_data(f, until, syms, strict=False, history=True)
    checks += dchecks
    if hourly:
        daily = data
        data = {}
        for s_ in daily:
            try:
                h = hourly_bid_ask(f, s_, date.fromisoformat(INTRADAY_DATA_FROM), now)
            except LiveFetchError as e:
                checks.append({"check": f"hourly_data_unavailable:{s_}", "status": "WARN", "detail": str(e)[:120]})
                continue
            data[s_] = h[h.index.dayofweek < 5]            # Saxo hours: no weekend bars
        missing = [c["detail"] for c in checks if c["check"].startswith(("data_unavailable", "hourly_data_unavailable"))]
        if missing:   # a skipped instrument would change the replayed history; stop instead, next run retries
            raise RuntimeError(f"account {acct}: incomplete market data this run, nothing recorded: {missing[:3]}")
        learn_from = pd.Timestamp(INTRADAY_LEARN_FROM, tz="UTC")
        live_start = INTRADAY_START
        res = run_adaptive(data, CAPITAL, start=INTRADAY_LEARN_FROM, trade_from=INTRADAY_START,
                           controls=CONTROLS(), horizon=INTRADAY_HORIZON, bars_per_day=24.0,
                           context_daily=daily, llm_root=ROOT / "data" / "llm" / "hourly", llm_key_len=13,
                           strategy_id="intraday")
    else:
        missing = [c["detail"] for c in checks if c["check"].startswith("data_unavailable")]
        if missing:   # a skipped instrument would change the replayed history; stop instead, next run retries
            raise RuntimeError(f"account {acct}: incomplete market data this run, nothing recorded: {missing[:3]}")
        first = min(d.index[0] for d in data.values())
        learn_from = max(pd.Timestamp(ADAPTIVE_LEARN_FROM, tz="UTC"), first + pd.Timedelta(days=380))
        live_start = LIVE_START
        res = run_adaptive(data, CAPITAL, start=str(learn_from.date()), trade_from=LIVE_START,
                           controls=CONTROLS())
    checks.append({"check": f"adaptive_history:{acct}", "status": "OK",
                   "detail": f"learned on real outcomes from {learn_from.date()} ({'hourly' if hourly else 'daily'} bars) "
                             f"({len(res.ledger.resolutions())} scored predictions before/through today)"})
    br, led = res.broker, res.broker.ledger
    wrapped = BacktestResult(res.equity, None, br, None, br.audit, {}, None, None)
    rows["_closed"].extend((acct, c.symbol, c.pnl_usd_gross - c.conversion_fee_usd) for c in led.closed)
    breaks = reconcile(wrapped)
    led.check_invariants()
    checks.append({"check": f"reconciliation:{acct}", "status": "OK" if not breaks else "ERROR",
                   "detail": "; ".join(breaks) or "engine ledger == independent FIFO recomputation"})
    # prediction ledger: append-only across runs (hash chain must extend the stored one)
    ppath = LIVE_DIR / ("predictions_intraday.jsonl" if hourly else "predictions.jsonl")
    stored = [json.loads(x) for x in ppath.read_text().splitlines() if x.strip()] if ppath.exists() else []
    recs = [json.loads(json.dumps(r, default=str)) for r in res.ledger.records]
    if hourly:
        # Hourly warm-up is ~100k records: store a checkpoint (the chain hash just before the
        # live start) plus every live record. The chain still covers the whole history.
        cut = next((i for i, r in enumerate(recs)
                    if (r.get("made_at") or r.get("resolved_at") or "") >= INTRADAY_START), len(recs))
        tip = recs[cut - 1]["hash"] if cut else "genesis"
        recs = [{"kind": "checkpoint", "hash": tip, "warmup_records": cut}] + recs[cut:]
    ok, detail, merged = extend_ledger(stored, recs)
    checks.append({"check": f"prediction_ledger_append_only:{acct}", "status": "OK" if ok else "CRITICAL",
                   "detail": detail})
    if ok and write:
        ppath.write_text("".join(json.dumps(r, default=str) + "\n" for r in merged))
    mids = dict(br.last_mids)
    mids.update({s: (q["bid"] + q["ask"]) / 2 for s, q in quotes.items()})
    marks = {s: ((quotes[s]["bid"], quotes[s]["ask"]) if s in quotes else br.last_marks[s]) for s in led.lots}
    q2u = {s: quote_to_usd(br.instruments[s].quote, mids) for s in led.lots}
    unreal_by = led.unrealised_usd(marks, q2u) if led.lots else {}
    equity_live = led.cash + sum(unreal_by.values())
    for s, book in led.lots.items():
        qty = sum(l.qty for l in book)
        inst = br.instruments[s]
        rows["positions"].append({
            "account": acct, "symbol": s, "side": "LONG" if qty > 0 else "SHORT", "qty": qty,
            "avg_entry": round(sum(l.qty * l.price for l in book) / qty, 6),
            "mark_bid": marks[s][0], "mark_ask": marks[s][1], "opened": book[0].opened, "q2u": q2u[s],
            "mark_ts": quotes.get(s, {}).get("ts", str(br._last_ts)), "unrealised_usd": round(unreal_by[s], 2),
            "notional_usd": round(abs(qty) * mids[s] * q2u[s], 2),
            "margin_usd": round(abs(qty) * mids[s] * q2u[s] * inst.initial_margin, 2)})
    ls = pd.Timestamp(live_start)
    ls = ls if ls.tzinfo else ls.tz_localize("UTC")
    eq = res.equity[res.equity.index >= ls]
    for t, v in eq.items():
        rows["equity"].append({"ts": t.isoformat(), "account": acct, "equity": round(v, 4), "kind": "daily close"})
    rows["equity"].append({"ts": now.isoformat(timespec="minutes"), "account": acct,
                           "equity": round(equity_live, 4), "kind": "live mark"})
    t = led.totals
    mdd = M.max_drawdown(pd.concat([pd.Series([CAPITAL]), eq.reset_index(drop=True), pd.Series([equity_live])]))
    rows["accounts"].append({
        "account": acct, "name": ("Atlantis Intraday · hourly, news + daily/weekly context" if hourly
                 else "Atlantis Adaptive · multi-asset, self-learning"),
        "strategy": "intraday" if hourly else "adaptive", "sizing": "half Kelly, edge > cost", "start_capital": CAPITAL, "equity": round(equity_live, 2),
        "return_pct": round((equity_live / CAPITAL - 1) * 100, 2), "cash": round(led.cash, 2),
        "unrealised": round(sum(unreal_by.values()), 2), "realised": round(t["realised_gross"], 2),
        "commissions": round(t["commissions"], 2), "financing": round(t["financing"], 4),
        "conversion_fees": round(t["conversion_fees"], 4), "spread_cost_est": round(br.stats["spread_cost_usd"], 2),
        "fills": int(br.stats["fills"]), "rejects": int(br.stats["rejects"]), "open_positions": len(led.lots),
        "max_drawdown_pct": round(mdd * 100, 2), "halted": bool(br.halted)})
    for e in br.audit.events:
        if e["kind"] == "FILL":
            bar = data[e["symbol"]].loc[pd.Timestamp(e["fill_ts"])]
            rec = {"account": acct, "ts": e["fill_ts"], "symbol": e["symbol"], "side": "BUY" if e["qty"] > 0 else "SELL",
                   "qty": abs(e["qty"]), "price": round(e["price"], 6), "bar_bid_open": bar["bid_open"],
                   "bar_ask_open": bar["ask_open"],
                   "decision_mid": round(e["decision_mid"], 6) if e["decision_mid"] else None,
                   "commission_usd": e["commission"], "slippage_usd": round(e["slippage_usd"], 4),
                   "reason": e["reason"], "tag": e["tag"], "label": "SIMULATED",
                   "data_source": "Dukascopy daily bar open (00:00 UTC)"}
            rows["fills"].append(rec)
            journal_new.append({k: rec[k] for k in ("account", "ts", "symbol", "side", "qty", "price")})
    # plan: latest decision per instrument
    last_ts = max((p["ts"] for p in res.proposals), default=None)
    pend = {o.symbol: o for o in br.orders if o.status is Status.PENDING}
    for p in res.proposals:
        if p["ts"] != last_ts:
            continue
        o = pend.get(p["symbol"])
        rows["plan"].append({
            "account": acct, "symbol": p["symbol"], "signal": p["p"],
            "signal_text": f"P(up 5d) {p['p']:.0%}", "position_qty": p["current"],
            "pending_orders": (f"{'BUY' if o.qty > 0 else 'SELL'} {abs(o.qty):g} MARKET (adaptive)" if o else "none"),
            "executes_at": (str(pd.Timestamp(last_ts) + pd.Timedelta(days=1))[:16] + " UTC open") if o else "",
            "next_decision": p["reason"] if last_ts >= live_start else "learning only until live start"})
    # predictions and know-how for the dashboard
    resol = res.ledger.resolutions()
    preds = res.ledger.predictions()
    rows.setdefault("predictions", [])
    for r in preds[-(400 if not hourly else 200):]:
        z = resol.get(r["id"])
        rows["predictions"].append({
            "account": acct, "id": r["id"], "made_at": r["made_at"], "symbol": r["symbol"],
            "asset_class": CLASS_NAMES.get(r["asset_class"], r["asset_class"]),
            "p_up": r["p_final"], "call": "UP" if r["p_final"] > 0.5 else ("DOWN" if r["p_final"] < 0.5 else "NONE"),
            "status": "resolved" if z else "open",
            "outcome": (None if not z else ("UP" if z["outcome_up"] > 0.5 else "DOWN")),
            "correct": (None if not z or z["hit"] is None else bool(z["hit"])),
            "fwd_return_pct": None if not z else round(z["fwd_log_return"] * 100, 3),
            "hash": r["hash"][:12]})
    rows.setdefault("knowhow", [])
    for cls, w in res.hedge.to_dict()["weights"].items():
        for name, weight in w.items():
            n = res.hedge.counts[cls].get(name, 0)
            dn = res.hedge.directional[cls].get(name, 0)
            hits = res.hedge.hits[cls].get(name, 0)
            rows["knowhow"].append({
                "account": acct, "asset_class": CLASS_NAMES.get(cls, cls), "predictor": name, "weight": round(weight, 4),
                "scored": n, "directional_calls": dn, "correct": hits,
                "hit_rate": round(hits / dn, 4) if dn else None,
                "brier": round(res.hedge.cum_loss[cls][name] / n, 5) if n else None})
    resolved = [p for p in rows["predictions"] if p["status"] == "resolved"]
    rows.setdefault("lessons", []).extend({"account": acct, "n": i, "lesson": x}
                                          for i, x in enumerate(res.lessons))
    rows.setdefault("calibration", []).append({"account": acct, "resolved_total": len(resol), "calibrator_fitted": res.calibrator.iso is not None,
                            "recent_hit_rate": round(np.mean([p["correct"] for p in resolved
                                                              if p["correct"] is not None]), 4)
                            if resolved else None})
    knowhow_path = ROOT / "knowledge" / ("knowhow_intraday.json" if hourly else "knowhow.json")
    knowhow_path.parent.mkdir(exist_ok=True)
    if write:
        knowhow_path.write_text(json.dumps({"asof": str(res.equity.index[-1].date()), **res.hedge.to_dict(),
                                        "lessons": res.lessons}, indent=1, default=str))
    return checks


def agents_rows(rows: dict, now: datetime) -> list[dict]:
    """What each AI agent last did, read from the files it writes, so the page shows whether it is working."""
    def latest(pattern: str):
        files = sorted(p for p in ROOT.glob(pattern) if p.name != ".gitkeep")
        return files[-1] if files else None

    def made_at(p):
        try:
            return json.loads(p.read_text()).get("made_at")
        except Exception:
            return None

    def age(ts):
        if not ts:
            return None
        return round((pd.Timestamp(now) - pd.Timestamp(ts)).total_seconds() / 3600, 1)

    def score(acct):
        k = [r for r in rows.get("knowhow", []) if r["account"] == acct and r["predictor"] == "llm_analyst"]
        sc = sum(r["scored"] for r in k)
        hits = [r["hit_rate"] for r in k if r["hit_rate"] is not None]
        return f"{sc} predictions scored" + (f", hit rate {sum(hits) / len(hits):.0%}" if hits else ", none scored yet")

    out = []
    brief, flash = latest("knowledge/intel/*.json"), latest("knowledge/intel/flash/*.json")
    b = json.loads(brief.read_text()) if brief else {}
    out.append({"agent": "News & market intelligence", "role": "daily brief + hourly breaking-news flash",
                "last": made_at(flash) or b.get("made_at"), "hours_ago": age(made_at(flash) or b.get("made_at")),
                "did": (f"daily brief {brief.stem}: {len(b.get('items', []))} dated news items, "
                        f"{len(b.get('calendar', []))} calendar events" if brief else "no brief yet")
                       + (f"; latest flash {flash.stem}" if flash else "; no breaking-news flash yet")})
    d = latest("data/llm/*.json")
    dj = json.loads(d.read_text()) if d else {}
    out.append({"agent": "AI analyst (daily, account E)", "role": "reads charts + news, predicts 5 days ahead",
                "last": dj.get("made_at"), "hours_ago": age(dj.get("made_at")),
                "did": (f"{len(dj.get('probs', {}))} predictions for bar {d.stem}" if d else "no prediction yet")
                       + f" · track record: {score('E')}"})
    h = latest("data/llm/hourly/*.json")
    hj = json.loads(h.read_text()) if h else {}
    out.append({"agent": "AI analyst (hourly, account F)", "role": "reads hourly charts + daily/weekly context + news",
                "last": hj.get("made_at"), "hours_ago": age(hj.get("made_at")),
                "did": (f"{len(hj.get('probs', {}))} predictions for hour {h.stem}" if h else "no prediction yet")
                       + f" · track record: {score('F')}"})
    fills = {a["account"]: a["fills"] for a in rows["accounts"]}
    out.append({"agent": "Executor (scheduled run)", "role": "runs the simulation, checks, publishes, commits",
                "last": now.isoformat(timespec="seconds"), "hours_ago": 0.0,
                "did": f"accounts A–F replayed and reconciled; fills so far: "
                       + ", ".join(f"{k} {v}" for k, v in fills.items())})
    r = latest("research/results/*.md") or latest("research/notes/*.md")
    out.append({"agent": "Research loop (researcher → planner → tester)", "role": "one tested improvement idea per week",
                "last": r.stem[:10] if r else None, "hours_ago": None,
                "did": f"latest: {r.relative_to(ROOT)}" if r else "first run Saturday 10:23 UTC"})
    return out


def portfolio_enrich(rows: dict) -> None:
    """Human-readable portfolio view: names, cost, value, P&L, share of account, and a
    per-instrument 'bought & sold' summary. Derived only from the ledger's own numbers."""
    from atlantis.adaptive import CLASS_NAMES
    from atlantis.instruments.spec import universe
    u = universe()
    names = u.get("names", {})
    cls = {sym: v[0] for sym, v in u["instruments"].items()}
    equity = {a["account"]: a["equity"] for a in rows["accounts"]}
    for p in rows["positions"]:
        q2u = p.pop("q2u", 1.0)
        cost = abs(p["qty"]) * p["avg_entry"] * q2u
        p["name"] = names.get(p["symbol"], p["symbol"])
        p["asset_class"] = CLASS_NAMES.get(cls.get(p["symbol"], ""), cls.get(p["symbol"], ""))
        p["cost_usd"] = round(cost, 2)
        p["pnl_usd"] = p["unrealised_usd"]
        p["value_usd"] = round(cost + p["unrealised_usd"], 2)
        p["pnl_pct"] = round(p["unrealised_usd"] / cost, 6) if cost else None
        eq = equity.get(p["account"])
        p["weight_pct"] = round(p["notional_usd"] / eq, 6) if eq else None
    summ: dict = {}
    for f in rows["fills"]:
        k = (f["account"], f["symbol"])
        d = summ.setdefault(k, {"account": k[0], "symbol": k[1], "name": names.get(k[1], k[1]),
                                "bought_units": 0.0, "buy_value": 0.0, "sold_units": 0.0, "sell_value": 0.0,
                                "commissions_usd": 0.0, "trades": 0, "realised_usd": 0.0,
                                "first_trade": f["ts"], "last_trade": f["ts"]})
        if f["side"] == "BUY":
            d["bought_units"] += f["qty"]
            d["buy_value"] += f["qty"] * f["price"]
        else:
            d["sold_units"] += f["qty"]
            d["sell_value"] += f["qty"] * f["price"]
        d["commissions_usd"] += f["commission_usd"]
        d["trades"] += 1
        d["last_trade"] = max(d["last_trade"], f["ts"])
    for acct, sym, pnl in rows.pop("_closed"):
        if (acct, sym) in summ:
            summ[(acct, sym)]["realised_usd"] += pnl
    out = []
    for d in summ.values():
        d["avg_buy_price"] = round(d["buy_value"] / d["bought_units"], 6) if d["bought_units"] else None
        d["avg_sell_price"] = round(d["sell_value"] / d["sold_units"], 6) if d["sold_units"] else None
        d["realised_usd"] = round(d["realised_usd"], 2)
        d["commissions_usd"] = round(d["commissions_usd"], 2)
        for k in ("buy_value", "sell_value"):
            d.pop(k)
        out.append(d)
    rows["trades_summary"] = sorted(out, key=lambda d: (d["account"], d["symbol"]))


LEDGER_TOL = 2e-5     # stored numbers are rounded to 5 decimals; CPUs differ in the last bits of log()/BLAS


def _close(a, b, tol: float = LEDGER_TOL) -> str | None:
    """None if two ledger records agree (hash fields ignored, floats within tolerance), else what differs."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in ("hash", "prev_hash"):
                continue
            if k not in a or k not in b:
                return f"field {k} missing"
            d = _close(a[k], b[k], tol)
            if d:
                return f"{k}: {d}" if not d.startswith("field") else d
        return None
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
        return None if a == b else f"{a!r} -> {b!r}"
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return None if abs(a - b) <= max(tol, 1e-9 * max(abs(a), abs(b))) else f"{a!r} -> {b!r}"
    return None if a == b else f"{a!r} -> {b!r}"


def extend_ledger(stored: list[dict], recomputed: list[dict]) -> tuple[bool, str, list[dict]]:
    """The stored ledger is the record of what was predicted. A replay must reproduce every stored
    record (within LEDGER_TOL: machines differ in the last bits of floating point), and may only
    ADD records. New records are chained onto the stored hash chain; stored records are never rewritten."""
    for i, old in enumerate(stored):
        if i >= len(recomputed):
            return False, f"replay has only {len(recomputed)} records, stored ledger has {len(stored)}; stored ledger kept", stored
        if old.get("kind") == "checkpoint":
            diff = None if old.get("warmup_records") == recomputed[i].get("warmup_records") else \
                f"warmup_records: {old.get('warmup_records')} -> {recomputed[i].get('warmup_records')}"
        else:
            diff = _close(old, recomputed[i])
        if diff:
            r = recomputed[i]
            return False, (f"earlier predictions changed: record {i} of {len(stored)} ({r.get('kind', '?')} "
                           f"{r.get('id') or r.get('prediction_id') or ''}) {diff}; stored ledger kept")[:400], stored
    hasher = PredictionLedger()
    merged = list(stored)
    for r in recomputed[len(stored):]:
        r = {k: v for k, v in r.items() if k != "hash"}
        if merged and r.get("kind") != "checkpoint":
            r["prev_hash"] = merged[-1]["hash"]
            r["hash"] = hasher._hash(r)
        else:
            r["hash"] = recomputed[len(merged)]["hash"]
        merged.append(r)
    return True, f"{len(stored)} earlier prediction records reproduced; {len(merged) - len(stored)} new", merged


def journal_check(old: list[dict], new: list[dict]) -> list[str]:
    """Every stored fill must still exist in the replay (matched by account, bar, symbol and side;
    order does not matter). Returns the problems found."""
    from collections import defaultdict
    key = lambda j: (j["account"], j["ts"], j["symbol"], j["side"])
    pool = defaultdict(list)
    for j in new:
        pool[key(j)].append(j)
    bad = []
    for o in old:
        c = pool.get(key(o), [])
        m = next((j for j in c if abs(j["qty"] - o["qty"]) <= 1e-6 * max(1, abs(o["qty"]))
                  and abs(j["price"] - o["price"]) <= 1e-6 * abs(o["price"])), None)
        if m is None:
            bad.append(f"{o['account']} {o['ts'][:16]} {o['symbol']} {o['side']} {o['qty']:g} @ {o['price']:g}"
                       + (f" -> now {c[0]['qty']:g} @ {c[0]['price']:g}" if c else " -> missing"))
        else:
            c.remove(m)
    return bad



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
