"""Portfolio table: hand-calculated cost, value, P&L, share of account and the bought/sold summary."""
from pathlib import Path
import pytest

from atlantis.live import portfolio_enrich


def test_portfolio_enrich_golden():
    rows = {
        "accounts": [{"account": "E", "equity": 210.0}],
        # Long 2 NVDA bought at 180.00, unrealised +6.00 (bid 183) -> cost 360, value 366, +1.67%, notional 2*183.05
        # Short 0.1 DAX at 24,000 EUR, EURUSD 1.10 -> cost 0.1*24000*1.10 = 2,640 USD, unrealised -11.00
        "positions": [
            {"account": "E", "symbol": "NVDAUSUSD", "side": "LONG", "qty": 2, "avg_entry": 180.0,
             "unrealised_usd": 6.0, "notional_usd": 366.1, "q2u": 1.0, "opened": "2026-11-10"},
            {"account": "E", "symbol": "DEUIDXEUR", "side": "SHORT", "qty": -0.1, "avg_entry": 24000.0,
             "unrealised_usd": -11.0, "notional_usd": 2651.0, "q2u": 1.10, "opened": "2026-11-11"}],
        "fills": [
            {"account": "E", "symbol": "NVDAUSUSD", "side": "BUY", "qty": 3, "price": 180.0, "commission_usd": 1.0, "ts": "2026-11-10"},
            {"account": "E", "symbol": "NVDAUSUSD", "side": "SELL", "qty": 1, "price": 190.0, "commission_usd": 1.0, "ts": "2026-11-12"}],
        "_closed": [("E", "NVDAUSUSD", 10.0)],
    }
    portfolio_enrich(rows)
    nv, dax = rows["positions"]
    assert nv["name"] == "NVIDIA" and nv["asset_class"] == "Stocks"
    assert nv["cost_usd"] == pytest.approx(360.0) and nv["value_usd"] == pytest.approx(366.0)
    assert nv["pnl_pct"] == pytest.approx(6 / 360, abs=1e-6) and nv["weight_pct"] == pytest.approx(366.1 / 210, abs=1e-6)
    assert "q2u" not in nv
    assert dax["name"].startswith("DAX") and dax["cost_usd"] == pytest.approx(2640.0)
    assert dax["pnl_pct"] == pytest.approx(-11 / 2640, abs=1e-6)
    (s,) = rows["trades_summary"]
    assert s["bought_units"] == 3 and s["sold_units"] == 1
    assert s["avg_buy_price"] == 180.0 and s["avg_sell_price"] == 190.0
    assert s["realised_usd"] == 10.0 and s["commissions_usd"] == 2.0 and s["trades"] == 2
    assert "_closed" not in rows


def test_incomplete_market_data_stops_the_adaptive_accounts(monkeypatch):
    """A symbol that fails to download must not be skipped silently: that would change the replayed
    history and the append-only prediction ledger. The run stops instead; the next run retries."""
    import pytest
    from atlantis import live
    monkeypatch.setattr(live, "load_data", lambda *a, **k: ({}, [{"check": "data_unavailable:BTCUSD",
                                                                   "status": "WARN", "detail": "BTCUSD skipped"}]))
    for acct, hourly in (("E", False), ("F", True)):
        with pytest.raises(RuntimeError, match="incomplete market data"):
            live.adaptive_section(None, None, None, {}, {}, [], write=False, acct=acct, hourly=hourly)


def _chain(n, noise=0.0):
    from atlantis.quant.learn.knowhow import PredictionLedger
    L = PredictionLedger()
    for i in range(n):
        L.append({"kind": "resolution", "prediction_id": f"p{i}", "fwd_log_return": 0.0123456789 + i + noise,
                  "outcome_up": 1.0})
    return L.records


def test_ledger_tolerates_cpu_float_noise_but_not_real_changes():
    from atlantis.live import extend_ledger
    from atlantis.quant.learn.knowhow import PredictionLedger
    stored = _chain(3)
    ok, detail, merged = extend_ledger(stored, _chain(5, noise=1e-15))     # last-bit noise + 2 new records
    assert ok and len(merged) == 5 and merged[:3] == stored                 # stored records are never rewritten
    L = PredictionLedger(); L.records = merged; L.verify()                  # chain still valid end to end
    ok, detail, merged = extend_ledger(stored, _chain(5, noise=1e-3))       # a real change
    assert not ok and "fwd_log_return" in detail and merged == stored
    ok, _, _ = extend_ledger(stored, _chain(2))                             # replay lost a record
    assert not ok


def test_journal_check_ignores_order_but_catches_changes():
    from atlantis.live import journal_check
    f = lambda a, ts, q, p: {"account": a, "ts": ts, "symbol": "X", "side": "BUY", "qty": q, "price": p}
    old = [f("F", "t1", 0.4, 100.0)]
    assert journal_check(old, [f("B", "t2", 1000, 1.1), f("F", "t1", 0.4, 100.0)]) == []   # earlier account added
    assert journal_check(old, [f("F", "t1", 0.5, 100.0)])                                    # quantity changed
    assert journal_check(old, [])                                                            # fill disappeared


def test_command_view_tables_come_from_the_run_itself():
    from atlantis.pipeline import STAGES, StageLog, activity_rows
    log = StageLog()
    log.start("market"); log.end("market", "3 files")
    log.start("simulation"); log.end("simulation", "replayed")
    log.mirror("broker", "simulation", "1 new fill")
    log.merge_ai(Path("/nonexistent/ai_stage.json"), log.rows["market"]["started_at"])
    t = {r["stage"]: r for r in log.table()}
    assert t["news"]["status"] == "idle" and t["analyst"]["status"] == "idle"     # never shown as work when none ran
    assert t["broker"]["started_at"] == t["simulation"]["started_at"]
    assert [r["stage"] for r in log.table()] == [s for s in STAGES if s in t]
    rows = {"fills": [{"account": "F", "ts": "2026-11-10T12:00:00+00:00", "symbol": "JPNIDXJPY", "side": "BUY",
                       "qty": 0.3, "price": 60121.583}]}
    checks = [{"check": "a", "status": "OK", "detail": ""}, {"check": "b", "status": "CRITICAL", "detail": "boom"}]
    rej = [{"account": "E", "ts": "2026-11-11T00:00:00+00:00", "symbol": "BTCUSD", "check": "margin", "reason": "too big"}]
    act = activity_rows(rows, checks, rej, "2026-11-13T15:00:00+00:00", {"JPNIDXJPY": "Nikkei 225"})
    msgs = " | ".join(a["msg"] for a in act)
    assert "bought 0.3 Nikkei 225" in msgs and "order rejected" in msgs and "b: boom" in msgs
    assert "1 of 2 checks passed" in msgs and act[0]["at"] >= act[-1]["at"]       # newest first
