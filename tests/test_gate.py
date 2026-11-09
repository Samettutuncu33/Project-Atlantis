"""Central Risk & Execution gate, order state machine, and layer boundaries."""

import ast
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from atlantis.audit.log import AuditLog
from atlantis.gate.portfolio.ledger import Ledger
from atlantis.gate.risk_gate import OrderIntent, RiskGate, policy
from atlantis.gate.sim.broker import Broker
from atlantis.gate.sim.costs import CostModel
from atlantis.gate.sim.fills import Bar
from atlantis.gate.sim.orders import ALLOWED, IllegalTransition, Order, OrderType, Status
from atlantis.instruments.spec import make_instrument

PKG = Path(__file__).resolve().parent.parent / "atlantis"
T0, T1, T2 = (f"2024-01-0{i}T00:00:00+00:00" for i in (1, 2, 3))


def bar(ts, px, spread=0.0002):
    return Bar(ts, px, px, px, px, px + spread, px + spread, px + spread, px + spread)


def setup(capital=200.0, budgets=None):
    inst = {s: make_instrument(s) for s in ("EURUSD", "GBPUSD")}
    br = Broker(inst, Ledger(capital), CostModel.saxo_classic(), AuditLog())
    g = RiskGate(br, budgets=budgets or {})
    br.process_bar(T0, {"EURUSD": bar(T0, 1.1), "GBPUSD": bar(T0, 1.3)})
    g.on_bar(T0)
    return br, g


def test_accepts_valid_intent_and_routes_to_sim_broker():
    br, g = setup()
    d = g.submit(OrderIntent("s1", "EURUSD", 1000, T0), T0)
    assert d.accepted and d.order.status is Status.PENDING and d.order.history == ["NEW", "PENDING"]


@pytest.mark.parametrize("intent,check", [
    (OrderIntent("s1", "EURUSD", 1000, "2023-12-29T00:00:00+00:00"), "intent_freshness"),
    (OrderIntent("s1", "XXXYYY", 1000, T0), "intent_validity"),
    (OrderIntent("s1", "EURUSD", 1000, T0, OrderType.LIMIT, None), "intent_validity"),
    (OrderIntent("s1", "EURUSD", 10_000, T0), "margin"),            # $366 margin > $200
    (OrderIntent("s1", "EURUSD", 1000, T0, expected_edge_usd=0.5, est_cost_usd=2.0), "edge_vs_cost"),
])
def test_gate_rejections(intent, check):
    br, g = setup()
    d = g.submit(intent, T0)
    assert not d.accepted and d.check == check
    assert any(e["kind"] == "GATE_REJECT" and e["check"] == check for e in br.audit.events)


def test_symbol_concentration_and_capital_allocation():
    br, g = setup(capital=1000.0, budgets={"s1": 0.25})
    # 1000 EURUSD margin = 1100*3.33% = 36.6 < 0.25*1000 -> ok ; 8000 units = 293 > 250 budget
    assert g.submit(OrderIntent("s1", "EURUSD", 1000, T0), T0).accepted
    d = g.submit(OrderIntent("s1", "GBPUSD", 6000, T0), T0)
    assert not d.accepted and d.check == "capital_allocation"
    br2, g2 = setup(capital=1000.0)
    d2 = g2.submit(OrderIntent("s2", "EURUSD", 15_000, T0), T0)  # 550 > 50% of 1000
    assert not d2.accepted and d2.check == "symbol_concentration"


def test_drawdown_kill_switch_blocks_new_risk_but_allows_reduction():
    br, g = setup(capital=1000.0)
    assert g.submit(OrderIntent("s1", "EURUSD", 10_000, T0), T0).accepted
    br.process_bar(T1, {"EURUSD": bar(T1, 1.1), "GBPUSD": bar(T1, 1.3)})
    g.on_bar(T1)
    br.process_bar(T2, {"EURUSD": bar(T2, 1.035), "GBPUSD": bar(T2, 1.3)})  # loss ~ $650
    g.on_bar(T2)
    assert br.equity() < policy()["drawdown_kill_switch"] * g.peak_equity
    assert g.submit(OrderIntent("s1", "GBPUSD", 1000, T2), T2).check == "drawdown_kill_switch"
    assert g.submit(OrderIntent("s1", "EURUSD", -10_000, T2), T2).accepted   # closing is allowed


# ---------- order state machine ----------------------------------------------------
def test_terminal_states_cannot_change():
    o = Order(1, "EURUSD", 1000)
    o.transition(Status.ACCEPTED)
    o.transition(Status.FILLED)
    with pytest.raises(IllegalTransition):
        o.transition(Status.CANCELLED)
    with pytest.raises(IllegalTransition):
        Order(2, "EURUSD", 1000).transition(Status.FILLED)   # NEW -> FILLED skips the gate


@settings(max_examples=300, deadline=None)
@given(st.lists(st.sampled_from(list(Status)), max_size=8))
def test_state_machine_property(seq):
    o = Order(1, "EURUSD", 1000)
    for s in seq:
        legal = s in ALLOWED[o.status]
        if legal:
            o.transition(s)
        else:
            with pytest.raises(IllegalTransition):
                o.transition(s)
    for a, b in zip(o.history, o.history[1:]):
        assert Status(b) in ALLOWED[Status(a)]


# ---------- architecture: only the gate may talk to the broker ----------------------------
def _imports(path: Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def test_quant_layer_cannot_import_broker_or_gate():
    forbidden = ("atlantis.gate", "atlantis.engine", "atlantis.live")
    for sub in ("strategies", "predict", "learn", "risk"):
        for p in (PKG / "quant" / sub).rglob("*.py") if (PKG / "quant" / sub).exists() else []:
            bad = [m for m in _imports(p) if m.startswith(forbidden)]
            assert not bad, f"{p} imports {bad}: quant layer must emit intents only"


def test_no_live_router_exists():
    for p in PKG.rglob("*.py"):
        text = p.read_text()
        assert "class LiveBroker" not in text and "live_router" not in text, p
