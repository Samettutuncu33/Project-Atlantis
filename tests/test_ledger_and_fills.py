import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from atlantis.audit.log import AuditLog
from atlantis.instruments.spec import make_instrument
from atlantis.gate.portfolio.ledger import Ledger, LedgerError
from atlantis.gate.sim.broker import Broker
from atlantis.gate.sim.costs import CostModel
from atlantis.gate.sim.fills import Bar, try_fill
from atlantis.gate.sim.orders import TIF, Order, OrderType, Status

EURUSD = make_instrument("EURUSD")
USDJPY = make_instrument("USDJPY")


def bar(ts, bo, bh, bl, bc, spread=0.0002):
    return Bar(ts, bo, bh, bl, bc, bo + spread, bh + spread, bl + spread, bc + spread)


def new_broker(capital=200.0):
    return Broker({"EURUSD": EURUSD, "USDJPY": USDJPY}, Ledger(capital), CostModel.saxo_classic(),
                  AuditLog())


# ---------- golden, hand-computed trades ------------------------------------
def test_golden_eurusd_round_trip():
    """Buy 1,000 EURUSD at ask 1.1002, sell at bid 1.1050.
    P&L = 1000 * (1.1050 - 1.1002) = 4.80 USD; commissions 2 x $1 min = 2.00 USD.
    No overnight financing: both fills happen on the same calendar day's bars? No -
    the bars are one day apart, so one night of financing is charged:
    Tom/Next markup 0.75% p.a. on notional (1000 * mid 1.1001) / 360
      = 0.0075 * 1100.10 / 360 = 0.0229188 USD
    Unrealised-P&L financing 2% p.a. on |unrealised at prior close| (long valued
    at bid 1.1000 -> unrealised = 1000*(1.1000-1.1002) = -0.20 USD)
      = 0.02 * 0.20 / 360 = 0.0000111 USD
    Final cash = 200 + 4.80 - 2.00 - 0.0229299 = 202.7770701"""
    b = new_broker()
    b.process_bar("2024-01-01T00:00:00+00:00", {"EURUSD": bar("t0", 1.1, 1.1, 1.1, 1.1)})
    b.submit("2024-01-01T00:00:00+00:00", "EURUSD", 1000)
    b.process_bar("2024-01-02T00:00:00+00:00", {"EURUSD": bar("t1", 1.1000, 1.1010, 1.0990, 1.1000)})
    assert b.ledger.position("EURUSD") == 1000
    assert b.ledger.lots["EURUSD"][0].price == pytest.approx(1.1002)
    b.submit("2024-01-02T00:00:00+00:00", "EURUSD", -1000)
    b.process_bar("2024-01-03T00:00:00+00:00", {"EURUSD": bar("t2", 1.1050, 1.1060, 1.1040, 1.1050)})
    assert b.ledger.position("EURUSD") == 0
    fin = 0.0075 * 1000 * 1.1001 / 360 + 0.02 * 0.20 / 360
    assert b.ledger.totals["commissions"] == pytest.approx(2.0)
    assert b.ledger.totals["financing"] == pytest.approx(fin, rel=1e-9)
    assert b.ledger.cash == pytest.approx(200 + 4.80 - 2.0 - fin, rel=1e-12)


def test_golden_usdjpy_conversion_fee():
    """Short 1,000 USDJPY at bid 150.00, cover at ask 149.00 -> +1,000 JPY.
    Converted at mid 149.00-ish: q2usd = 1/mid at fill. Conversion fee 0.25%."""
    led = Ledger(200.0)
    led.apply_fill("t0", USDJPY, -1000, 150.00, 1, 1 / 150.0)
    led.apply_fill("t1", USDJPY, 1000, 149.00, 2, 1 / 149.0)
    pnl_usd = 1000 * 1.0 / 149.0
    assert led.totals["realised_gross"] == pytest.approx(pnl_usd)
    assert led.totals["conversion_fees"] == pytest.approx(pnl_usd * 0.0025)
    assert led.cash == pytest.approx(200 + pnl_usd * (1 - 0.0025))
    led.check_invariants()


def test_fifo_netting_matches_saxo_example():
    """Saxo's documented example: +1M, +1M, -1M, -2M -> net -1M, FIFO matched."""
    led = Ledger(1e7)
    for i, (q, px) in enumerate([(1e6, 1.10), (1e6, 1.11), (-1e6, 1.12), (-2e6, 1.13)]):
        led.apply_fill(f"t{i}", EURUSD, q, px, i, 1.0)
    assert led.position("EURUSD") == pytest.approx(-1e6)
    # 1st long closed by 1st short: +0.02*1M; 2nd long closed by 2nd short: +0.02*1M
    assert led.totals["realised_gross"] == pytest.approx(0.02e6 + 0.02e6)
    assert led.lots["EURUSD"][0].price == 1.13


def test_invalid_inputs_rejected():
    with pytest.raises(LedgerError):
        Ledger(0)
    led = Ledger(100)
    with pytest.raises(LedgerError):
        led.apply_fill("t", EURUSD, 0, 1.1, 1, 1.0)
    with pytest.raises(LedgerError):
        led.apply_fill("t", EURUSD, 10, -1.1, 1, 1.0)


# ---------- fill model --------------------------------------------------------
def test_stop_gap_fills_at_open_not_trigger():
    o = Order(1, "EURUSD", -1000, OrderType.STOP, 1.0950, TIF.GTC)
    f = try_fill(o, bar("t", 1.0900, 1.0920, 1.0880, 1.0910), EURUSD)
    assert f.price == pytest.approx(1.0900)  # gapped below the stop: worse than trigger
    assert f.reason == "stop@open(gap)"


def test_limit_touch_is_not_a_fill():
    o = Order(1, "EURUSD", 1000, OrderType.LIMIT, 1.0950)
    # ask low exactly at limit (no trade-through by 1 pip)
    b = Bar("t", 1.1, 1.1, 1.0948, 1.1, 1.1002, 1.1002, 1.0950, 1.1002)
    assert try_fill(o, b, EURUSD) is None
    b2 = Bar("t", 1.1, 1.1, 1.0938, 1.1, 1.1002, 1.1002, 1.0940, 1.1002)
    assert try_fill(o, b2, EURUSD).price == pytest.approx(1.0950)


def test_metals_refused_until_saxo_min_size_known():
    from atlantis.instruments.spec import UnavailableDataError
    with pytest.raises(UnavailableDataError):
        make_instrument("XAUUSD")


def test_xauusd_market_order_uses_saxo_published_slippage():
    from atlantis.instruments.spec import Instrument
    xau = Instrument("XAUUSD", "fx_metal", "XAU", "USD", 0.01, 0.05, 1, 1)
    o = Order(1, "XAUUSD", 1, OrderType.MARKET)
    b = Bar("t", 2000, 2010, 1990, 2005, 2000.3, 2010.3, 1990.3, 2005.3)
    f = try_fill(o, b, xau)
    assert f.slippage_pips == pytest.approx(0.7)       # Saxo Aug-2026: net -0.7 pips
    assert f.price == pytest.approx(2000.3 + 0.7 * 0.01)


def test_partial_fill_participation_cap():
    o = Order(1, "EURUSD", 1000, OrderType.MARKET)
    b = Bar("t", 1.1, 1.1, 1.1, 1.1, 1.1002, 1.1002, 1.1002, 1.1002, volume=4000)
    f = try_fill(o, b, EURUSD, max_participation=0.1)
    assert f.qty == pytest.approx(400) and "partial" in f.reason


def test_orders_never_fill_on_submission_bar():
    b = new_broker()
    ts = "2024-01-01T00:00:00+00:00"
    b.process_bar(ts, {"EURUSD": bar(ts, 1.1, 1.1, 1.1, 1.1)})
    o = b.submit(ts, "EURUSD", 1000)
    b.process_bar(ts, {"EURUSD": bar(ts, 1.1, 1.1, 1.1, 1.1)})  # same timestamp again
    assert o.status is Status.PENDING


def test_below_min_size_rejected_and_insufficient_margin_rejected():
    b = new_broker(capital=10.0)
    ts = "2024-01-01T00:00:00+00:00"
    b.process_bar(ts, {"EURUSD": bar(ts, 1.1, 1.1, 1.1, 1.1)})
    assert b.submit(ts, "EURUSD", 500).reject_reason.startswith("BELOW_MIN_SIZE")
    o = b.submit(ts, "EURUSD", 10_000)   # margin 3.33% * 11,000 = $366 > $10 equity
    b.process_bar("2024-01-02T00:00:00+00:00", {"EURUSD": bar("t", 1.1, 1.1, 1.1, 1.1)})
    assert o.status is Status.REJECTED and o.reject_reason == "INSUFFICIENT_MARGIN"


def test_esma_margin_closeout_and_negative_balance_protection():
    b = new_broker(capital=200.0)
    t0, t1, t2 = (f"2024-01-0{i}T00:00:00+00:00" for i in (1, 2, 3))
    b.process_bar(t0, {"EURUSD": bar(t0, 1.1, 1.1, 1.1, 1.1)})
    b.submit(t0, "EURUSD", 5000)  # $5.5k notional, margin $183
    b.process_bar(t1, {"EURUSD": bar(t1, 1.1, 1.1, 1.1, 1.1)})
    # crash: bid low 0.9 -> loss ~ $1,000 > equity -> closeout + NBP
    b.process_bar(t2, {"EURUSD": bar(t2, 1.09, 1.09, 0.90, 0.95)})
    assert b.stats["closeouts"] == 1
    assert b.ledger.position("EURUSD") == 0
    assert b.ledger.cash >= 0
    assert any(e["kind"] == "NEGATIVE_BALANCE_PROTECTION" for e in b.audit.events)
    assert b.halted
    b.ledger.check_invariants()


# ---------- property-based: ledger invariants hold for any fill sequence ---------
fills = st.lists(st.tuples(st.sampled_from([-3000, -1000, 1000, 2000, 5000]),
                           st.floats(0.8, 1.6), st.floats(0.5, 2.0)), min_size=1, max_size=40)


@settings(max_examples=200, deadline=None)
@given(fills)
def test_ledger_invariants_property(seq):
    led = Ledger(1000.0)
    pos = 0.0
    for i, (q, px, rate) in enumerate(seq):
        led.apply_fill(f"t{i}", USDJPY, q, px, i, rate)
        pos += q
        led.check_invariants()
    assert math.isclose(led.position("USDJPY"), pos, abs_tol=1e-9)
    # closed qty + open qty conservation
    opened = sum(abs(q) for q, _, _ in seq)
    closed = sum(abs(c.qty) for c in led.closed)
    assert math.isclose(opened, 2 * closed + abs(pos), rel_tol=1e-9)
