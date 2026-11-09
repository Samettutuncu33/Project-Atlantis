"""CENTRAL RISK & EXECUTION ENGINE: the mandatory security gate.

The Quant Strategy Engine produces OrderIntents. This gate is the only code
that turns an intent into an Order, and the only router is the simulated
broker (SimBroker). There is no live broker router in this project.

Every intent passes, in order:
  1. intent validity (instrument known and tradable, positive price for limits/stops)
  2. intent freshness (formed on the latest bar)
  3. data freshness (latest bar not older than policy)
  4. drawdown kill-switch (risk-increasing intents blocked below the policy level)
  5. minimum size (via the broker's instrument spec)
  6. margin after the trade vs equity x max_margin_utilisation
  7. per-symbol margin share
  8. capital allocation: the strategy's margin budget share
  9. edge vs cost (when the intent states an expected edge)
Each rejection is written to the audit log with the failing check's name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml

from atlantis.gate.sim.broker import Broker
from atlantis.gate.sim.orders import TIF, Order, OrderType, Status

POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "risk_policy.yaml"


@lru_cache(maxsize=1)
def policy() -> dict:
    return {k: v["value"] for k, v in yaml.safe_load(POLICY_PATH.read_text()).items()}


@dataclass(frozen=True)
class OrderIntent:
    """What a strategy wants. It carries no authority to trade by itself."""
    strategy_id: str
    symbol: str
    qty: float                       # signed change in base units
    formed_ts: str                   # bar timestamp the decision used
    type: OrderType = OrderType.MARKET
    price: float | None = None
    tif: TIF = TIF.DAY
    tag: str = ""
    expected_edge_usd: float | None = None   # predicted P&L of the trade, if the strategy states one
    est_cost_usd: float | None = None        # round-trip cost estimate supplied by the decider
    protective: bool = False                 # a stop protecting a position being opened (risk-reducing)


@dataclass
class GateDecision:
    intent: OrderIntent
    accepted: bool
    check: str = ""
    reason: str = ""
    order: Order | None = None


@dataclass
class RiskGate:
    broker: Broker
    budgets: dict[str, float] = field(default_factory=dict)   # strategy_id -> share of margin budget
    peak_equity: float = 0.0
    last_bar_ts: str | None = None
    attribution: dict[str, str] = field(default_factory=dict)  # symbol -> strategy holding it
    decisions: list[GateDecision] = field(default_factory=list)

    def on_bar(self, ts: str) -> None:
        self.last_bar_ts = ts
        self.peak_equity = max(self.peak_equity, self.broker.equity())

    # --------------------------------------------------------------------------
    def submit(self, it: OrderIntent, now_ts: str) -> GateDecision:
        p = policy()
        br = self.broker
        led = br.ledger
        pos = led.position(it.symbol)
        reduces = it.protective or (pos != 0 and (pos > 0) != (it.qty > 0) and abs(it.qty) <= abs(pos) + 1e-9)

        def reject(check: str, reason: str) -> GateDecision:
            d = GateDecision(it, False, check, reason)
            self.decisions.append(d)
            br.stats["rejects"] += 1
            br.audit.event(now_ts, "GATE_REJECT", severity="WARN", check=check, reason=reason,
                           strategy=it.strategy_id, symbol=it.symbol, qty=it.qty)
            return d

        if it.qty == 0 or it.symbol not in br.instruments:
            return reject("intent_validity", "zero quantity or unknown/untradable instrument")
        if it.type is not OrderType.MARKET and (it.price is None or it.price <= 0):
            return reject("intent_validity", "limit/stop intent without a positive price")
        if it.formed_ts != now_ts:
            return reject("intent_freshness", f"formed at {it.formed_ts}, now {now_ts}")
        if self.last_bar_ts is not None:
            age = (datetime.fromisoformat(now_ts) - datetime.fromisoformat(self.last_bar_ts)).days
            if age > p["max_data_staleness_days"]:
                return reject("data_freshness", f"latest bar is {age} days old")
        equity = br.equity()
        if not reduces:
            if self.peak_equity > 0 and equity < p["drawdown_kill_switch"] * self.peak_equity:
                return reject("drawdown_kill_switch",
                              f"equity {equity:.2f} < {p['drawdown_kill_switch']:.0%} of peak "
                              f"{self.peak_equity:.2f}; only risk-reducing orders allowed")
            mids = br.last_mids
            if it.symbol not in mids:
                return reject("data_freshness", "no price yet for this instrument")
            need = br.required_margin(mids, (it.symbol, it.qty))
            cap = p["max_margin_utilisation"] * equity
            if need > cap:
                return reject("margin", f"margin after trade {need:.2f} > cap {cap:.2f}")
            inst = br.instruments[it.symbol]
            sym_margin = br.notional_usd(it.symbol, pos + it.qty, mids) * inst.initial_margin
            if sym_margin > p["max_symbol_margin_share"] * cap:
                return reject("symbol_concentration",
                              f"{it.symbol} margin {sym_margin:.2f} > {p['max_symbol_margin_share']:.0%} of cap")
            share = self.budgets.get(it.strategy_id)
            if share is not None:
                used = sum(br.notional_usd(s, led.position(s), mids) * br.instruments[s].initial_margin
                           for s, sid in self.attribution.items()
                           if sid == it.strategy_id and led.position(s) and s != it.symbol)
                if used + sym_margin > share * cap + 1e-9:
                    return reject("capital_allocation",
                                  f"strategy {it.strategy_id} would use {used + sym_margin:.2f} "
                                  f"> its budget {share * cap:.2f}")
            if p["require_edge_above_cost"] and it.expected_edge_usd is not None:
                cost = it.est_cost_usd or 0.0
                if it.expected_edge_usd <= cost:
                    return reject("edge_vs_cost",
                                  f"expected edge {it.expected_edge_usd:.2f} <= cost {cost:.2f}")
        o = br.submit(now_ts, it.symbol, it.qty, it.type, it.price, it.tif, tag=it.tag)
        if o.status is Status.REJECTED:
            d = GateDecision(it, False, "broker_validation", o.reject_reason, o)
        else:
            d = GateDecision(it, True, "", "", o)
            if not reduces:
                self.attribution[it.symbol] = it.strategy_id
        self.decisions.append(d)
        return d
