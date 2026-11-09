"""Portfolio table: hand-calculated cost, value, P&L, share of account and the bought/sold summary."""
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
