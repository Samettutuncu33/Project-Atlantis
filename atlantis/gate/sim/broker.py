"""Simulated broker (SIMULATION ONLY — no network access, no real orders).

Processing order for each bar (timestamp t):
  1. Overnight financing for positions carried since the previous bar.
  2. Pending orders are filled against bar t (they were submitted at <= t-1).
  3. Intrabar margin check at adverse extremes; ESMA 50% margin close-out.
  4. Mark-to-market at the close (bid for longs, ask for shorts), invariants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from atlantis.audit.log import AuditLog
from atlantis.instruments.spec import Instrument, UnavailableDataError, conditions
from atlantis.gate.portfolio.ledger import Ledger
from atlantis.gate.sim.costs import CostModel
from atlantis.gate.sim.fills import Bar, try_fill
from atlantis.gate.sim.orders import TIF, Order, OrderType, Status


def quote_to_usd(ccy: str, mids: dict[str, float]) -> float:
    """USD value of one unit of `ccy`, from mid prices of pairs in `mids`."""
    if ccy == "USD":
        return 1.0
    if f"{ccy}USD" in mids:
        return mids[f"{ccy}USD"]
    if f"USD{ccy}" in mids:
        return 1.0 / mids[f"USD{ccy}"]
    raise UnavailableDataError(f"no USD conversion rate for {ccy}")


@dataclass
class Broker:
    instruments: dict[str, Instrument]
    ledger: Ledger
    costs: CostModel
    audit: AuditLog
    extra_spread_bps: float = 0.0
    orders: list[Order] = field(default_factory=list)
    _next_id: int = 1
    _last_ts: str | None = None
    last_marks: dict[str, tuple[float, float]] = field(default_factory=dict)
    last_mids: dict[str, float] = field(default_factory=dict)
    halted: bool = False
    stats: dict[str, float] = field(default_factory=lambda: {
        "fills": 0, "rejects": 0, "closeouts": 0, "slippage_usd": 0.0,
        "spread_cost_usd": 0.0, "traded_notional_usd": 0.0})

    # ---- order entry -------------------------------------------------------
    def submit(self, ts: str, symbol: str, qty: float, type_: OrderType = OrderType.MARKET,
               price: float | None = None, tif: TIF = TIF.DAY, tag: str = "") -> Order:
        o = Order(self._next_id, symbol, qty, type_, price, tif, ts, tag,
                  decision_mid=self.last_mids.get(symbol))
        self._next_id += 1
        inst = self.instruments.get(symbol)
        if self.halted:
            return self._reject(o, "ACCOUNT_HALTED")
        if inst is None:
            return self._reject(o, "UNKNOWN_INSTRUMENT")
        if abs(qty) < inst.min_size - 1e-9 and abs(qty + self.ledger.position(symbol)) > 1e-9:
            # Saxo allows closing an odd remainder; opening/adding below min size is rejected.
            return self._reject(o, f"BELOW_MIN_SIZE({inst.min_size:g})")
        o.transition(Status.ACCEPTED)
        self.orders.append(o)
        self.audit.event(ts, "ORDER_SUBMITTED", id=o.id, symbol=symbol, qty=qty,
                         type=type_.value, price=price, tag=tag)
        return o

    def cancel(self, ts: str, o: Order) -> None:
        if o.status in (Status.PENDING, Status.PARTIAL):
            o.transition(Status.CANCELLED)
            self.audit.event(ts, "ORDER_CANCELLED", id=o.id)

    def _reject(self, o: Order, reason: str) -> Order:
        o.transition(Status.REJECTED, reason)
        self.stats["rejects"] += 1
        self.audit.event(o.submitted, "ORDER_REJECTED", id=o.id, symbol=o.symbol,
                         qty=o.qty, reason=reason, severity="WARN")
        return o

    # ---- helpers -----------------------------------------------------------
    def _q2usd(self, sym: str, mids: dict[str, float]) -> float:
        return quote_to_usd(self.instruments[sym].quote, mids)

    def notional_usd(self, sym: str, qty: float, mids: dict[str, float]) -> float:
        return abs(qty) * mids[sym] * self._q2usd(sym, mids)

    def required_margin(self, mids: dict[str, float], extra: tuple[str, float] | None = None) -> float:
        pos = {s: self.ledger.position(s) for s in self.ledger.lots}
        if extra:
            pos[extra[0]] = pos.get(extra[0], 0.0) + extra[1]
        return sum(self.notional_usd(s, q, mids) * self.instruments[s].initial_margin
                   for s, q in pos.items() if q)

    def equity(self) -> float:
        if not self.ledger.lots:
            return self.ledger.cash
        q2u = {s: self._q2usd(s, self.last_mids) for s in self.ledger.lots}
        return self.ledger.equity(self.last_marks, q2u)

    # ---- bar processing ----------------------------------------------------
    def process_bar(self, ts: str, bars: dict[str, Bar]) -> None:
        mids_open = dict(self.last_mids)
        mids_open.update({s: b.mid_open for s, b in bars.items()})
        self._financing(ts)
        self._fill_orders(ts, bars, mids_open)
        self._margin_check(ts, bars, mids_open)
        for s, b in bars.items():
            self.last_marks[s] = (b.bid_close, b.ask_close)
            self.last_mids[s] = b.mid_close
        self._negative_balance(ts)
        self.ledger.check_invariants()
        self._last_ts = ts

    def _financing(self, ts: str) -> None:
        if self._last_ts is None or not self.ledger.lots:
            return
        days = (datetime.fromisoformat(ts) - datetime.fromisoformat(self._last_ts)).days
        if days <= 0:
            return
        q2u = {s: self._q2usd(s, self.last_mids) for s in self.ledger.lots}
        unreal = self.ledger.unrealised_usd(self.last_marks, q2u)
        for sym in list(self.ledger.lots):
            notional = self.notional_usd(sym, self.ledger.position(sym), self.last_mids)
            cost = self.costs.financing(notional, unreal[sym], days, self.instruments[sym],
                                        self.ledger.position(sym) > 0)
            self.ledger.charge(ts, "financing", cost, f"{sym} rollover x{days}d")

    def _fill_orders(self, ts: str, bars: dict[str, Bar], mids: dict[str, float]) -> None:
        for o in self.orders:
            if o.status not in (Status.PENDING, Status.PARTIAL) or o.submitted >= ts:
                continue
            bar = bars.get(o.symbol)
            if bar is None:
                continue  # market closed for this instrument: order waits
            inst = self.instruments[o.symbol]
            fq = try_fill(o, bar, inst, self.extra_spread_bps)
            if fq is None:
                if o.tif is TIF.DAY:
                    o.transition(Status.EXPIRED)
                    self.audit.event(ts, "ORDER_EXPIRED", id=o.id)
                continue
            pos = self.ledger.position(o.symbol)
            reduces = pos != 0 and (pos > 0) != (fq.qty > 0) and abs(fq.qty) <= abs(pos) + 1e-9
            if not reduces:
                eq = self.equity()
                need = self.required_margin(mids, (o.symbol, fq.qty))
                if need > eq:
                    o.transition(Status.REJECTED, "INSUFFICIENT_MARGIN")
                    self.stats["rejects"] += 1
                    self.audit.event(ts, "ORDER_REJECTED", id=o.id, symbol=o.symbol,
                                     reason="INSUFFICIENT_MARGIN", need=need, equity=eq,
                                     severity="WARN")
                    continue
            self._execute(ts, o, fq.qty, fq.price, mids, bar, fq.reason, fq.slippage_pips)

    def _execute(self, ts: str, o: Order, qty: float, price: float, mids: dict[str, float],
                 bar: Bar, reason: str, slip_pips: float) -> None:
        inst = self.instruments[o.symbol]
        q2u = self._q2usd(o.symbol, mids)
        notional = abs(qty) * price * q2u
        tid = o.id
        self.ledger.apply_fill(ts, inst, qty, price, tid, q2u)
        comm = self.costs.commission(notional, inst)
        self.ledger.charge(ts, "commissions", comm, f"{o.symbol} order {o.id}")
        o.filled_qty += qty
        o.transition(Status.FILLED if abs(o.remaining) < 1e-9 else Status.PARTIAL)
        half_spread = 0.5 * (bar.ask_open - bar.bid_open) if "open" in reason else \
            0.5 * (bar.ask_close - bar.bid_close)
        slip_usd = abs(qty) * slip_pips * inst.pip * q2u
        self.stats["fills"] += 1
        self.stats["slippage_usd"] += slip_usd
        self.stats["spread_cost_usd"] += abs(qty) * half_spread * q2u
        self.stats["traded_notional_usd"] += notional
        fill = {"fill_ts": ts, "qty": qty, "price": price, "reason": reason,
                "commission": comm, "slippage_usd": slip_usd,
                "decision_mid": o.decision_mid, "q2usd": q2u, "label": "SIMULATED"}
        o.fills.append(fill)
        self.audit.event(ts, "FILL", id=o.id, symbol=o.symbol, tag=o.tag, **fill)

    def _margin_check(self, ts: str, bars: dict[str, Bar], mids: dict[str, float]) -> None:
        """ESMA margin close-out, evaluated at the bar's adverse extremes (conservative)."""
        if not self.ledger.lots:
            return
        worst = {}
        for s in self.ledger.lots:
            b = bars.get(s)
            if b is None:
                worst[s] = self.last_marks[s]
                continue
            long_ = self.ledger.position(s) > 0
            worst[s] = (b.bid_low, b.ask_low) if long_ else (b.bid_high, b.ask_high)
        q2u = {s: self._q2usd(s, mids) for s in self.ledger.lots}
        eq_worst = self.ledger.equity(worst, q2u)
        req = self.required_margin(mids)
        level = conditions()["margin_retail_esma"]["margin_closeout_level"]
        if req > 0 and eq_worst < level * req:
            self.stats["closeouts"] += 1
            self.audit.event(ts, "MARGIN_CLOSEOUT", equity_worst=eq_worst, required=req,
                             severity="ERROR")
            for s in list(self.ledger.lots):
                qty = -self.ledger.position(s)
                px = worst[s][0] if qty < 0 else worst[s][1]   # sell at bid, buy at ask
                o = Order(self._next_id, s, qty, OrderType.MARKET, None, TIF.DAY, ts, "closeout")
                o.transition(Status.ACCEPTED)
                self._next_id += 1
                self.orders.append(o)
                b = bars.get(s) or Bar(ts, *([px] * 8))
                self._execute(ts, o, qty, px, mids, b, "margin_closeout", 0.0)
            for o in self.orders:
                if o.status in (Status.PENDING, Status.PARTIAL):
                    o.transition(Status.CANCELLED)

    def _negative_balance(self, ts: str) -> None:
        if not self.ledger.lots and self.ledger.cash < 0:
            self.ledger.nbp_credit(ts, -self.ledger.cash)
            self.audit.event(ts, "NEGATIVE_BALANCE_PROTECTION", severity="ERROR")
        if not self.ledger.lots and self.ledger.cash < self.costs.min_commission_usd:
            if not self.halted:
                self.audit.event(ts, "ACCOUNT_HALTED",
                                 detail="equity below one minimum commission", severity="ERROR")
            self.halted = True
