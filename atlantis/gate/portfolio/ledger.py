"""Double-entry, multi-currency account ledger with Saxo-style FIFO netting.

Accounting model (account currency = USD):
  * Every cash movement is a balanced journal entry (debit == credit, in USD).
  * Positions are FIFO lots (Saxo nets FX spot positions FIFO).
  * Realised P&L arises in the instrument's quote currency and is converted to
    USD at the mid rate, less the Saxo currency-conversion fee when non-USD.
  * Unrealised P&L is valued at liquidation prices: bid for longs, ask for
    shorts — i.e. what the account would actually receive on closing.

Invariant checked by ``check_invariants`` after every event:
  cash == initial_deposit + sum(realised_usd) - sum(costs) + sum(adjustments)
  and the journal balances to zero.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from atlantis.instruments.spec import Instrument

EPS = 1e-9


class LedgerError(RuntimeError):
    pass


@dataclass
class Lot:
    qty: float            # signed base units (+ long, - short)
    price: float          # entry price in quote ccy per base unit
    opened: str
    trade_id: int


@dataclass(frozen=True)
class JournalEntry:
    ts: str
    debit: str
    credit: str
    amount_usd: float
    memo: str


@dataclass
class ClosedTrade:
    symbol: str
    qty: float            # signed qty of the closed lot portion
    entry_price: float
    exit_price: float
    opened: str
    closed: str
    pnl_quote: float
    pnl_usd_gross: float  # before conversion fee
    conversion_fee_usd: float
    entry_trade_id: int
    exit_trade_id: int


@dataclass
class Ledger:
    initial_deposit: float
    base_ccy: str = "USD"
    conversion_fee: float = 0.0025
    cash: float = 0.0
    lots: dict[str, deque[Lot]] = field(default_factory=dict)
    journal: list[JournalEntry] = field(default_factory=list)
    closed: list[ClosedTrade] = field(default_factory=list)
    totals: dict[str, float] = field(default_factory=lambda: {
        "realised_gross": 0.0, "conversion_fees": 0.0, "commissions": 0.0,
        "financing": 0.0, "nbp_credit": 0.0})

    def __post_init__(self) -> None:
        if self.initial_deposit <= 0:
            raise LedgerError("initial deposit must be positive")
        self._post("start", "cash", "equity_capital", self.initial_deposit, "initial deposit")

    # ---- journal -----------------------------------------------------------
    def _post(self, ts: str, debit: str, credit: str, amount: float, memo: str) -> None:
        if amount < 0:
            debit, credit, amount = credit, debit, -amount
        if amount == 0:
            return
        self.journal.append(JournalEntry(ts, debit, credit, amount, memo))
        if debit == "cash":
            self.cash += amount
        elif credit == "cash":
            self.cash -= amount

    def journal_balance(self) -> dict[str, float]:
        bal: dict[str, float] = {}
        for e in self.journal:
            bal[e.debit] = bal.get(e.debit, 0.0) + e.amount_usd
            bal[e.credit] = bal.get(e.credit, 0.0) - e.amount_usd
        return bal

    # ---- positions ---------------------------------------------------------
    def position(self, symbol: str) -> float:
        return sum(l.qty for l in self.lots.get(symbol, ()))

    def apply_fill(self, ts: str, inst: Instrument, qty: float, price: float,
                   trade_id: int, quote_to_usd: float) -> list[ClosedTrade]:
        """Apply a fill (signed qty) using FIFO netting. Returns closed portions."""
        if qty == 0:
            raise LedgerError("zero-quantity fill")
        if price <= 0 or quote_to_usd <= 0:
            raise LedgerError(f"invalid price/rate {price}/{quote_to_usd}")
        book = self.lots.setdefault(inst.symbol, deque())
        remaining = qty
        out: list[ClosedTrade] = []
        while remaining != 0 and book and (book[0].qty > 0) != (remaining > 0):
            lot = book[0]
            close_qty = min(abs(remaining), abs(lot.qty))
            sign = 1.0 if lot.qty > 0 else -1.0
            pnl_q = sign * close_qty * (price - lot.price)
            pnl_usd = pnl_q * quote_to_usd
            fee = abs(pnl_usd) * self.conversion_fee if inst.quote != self.base_ccy else 0.0
            ct = ClosedTrade(inst.symbol, sign * close_qty, lot.price, price, lot.opened, ts,
                             pnl_q, pnl_usd, fee, lot.trade_id, trade_id)
            out.append(ct)
            self.closed.append(ct)
            self._post(ts, "cash", "realised_pnl", pnl_usd, f"{inst.symbol} realised")
            self._post(ts, "conversion_fee_expense", "cash", fee, f"{inst.symbol} ccy conversion")
            self.totals["realised_gross"] += pnl_usd
            self.totals["conversion_fees"] += fee
            lot.qty -= sign * close_qty
            remaining += sign * close_qty
            if abs(lot.qty) < EPS:
                book.popleft()
            if abs(remaining) < EPS:
                remaining = 0.0
        if remaining != 0:
            book.append(Lot(remaining, price, ts, trade_id))
        if not book:
            del self.lots[inst.symbol]
        return out

    def charge(self, ts: str, kind: str, amount_usd: float, memo: str) -> None:
        """Charge a cost (positive amount reduces cash). kind: commissions|financing."""
        if kind not in ("commissions", "financing"):
            raise LedgerError(f"unknown cost kind {kind}")
        self._post(ts, f"{kind}_expense", "cash", amount_usd, memo)
        self.totals[kind] += amount_usd

    def nbp_credit(self, ts: str, amount_usd: float) -> None:
        """Negative balance protection: broker absorbs negative cash."""
        self._post(ts, "cash", "nbp_credit", amount_usd, "negative balance protection")
        self.totals["nbp_credit"] += amount_usd

    # ---- valuation ---------------------------------------------------------
    def unrealised_usd(self, marks: dict[str, tuple[float, float]],
                       quote_to_usd: dict[str, float]) -> dict[str, float]:
        """marks: symbol -> (bid, ask). Longs valued at bid, shorts at ask."""
        out = {}
        for sym, book in self.lots.items():
            bid, ask = marks[sym]
            q = 0.0
            for l in book:
                px = bid if l.qty > 0 else ask
                q += l.qty * (px - l.price)
            out[sym] = q * quote_to_usd[sym]
        return out

    def equity(self, marks, quote_to_usd) -> float:
        return self.cash + sum(self.unrealised_usd(marks, quote_to_usd).values())

    # ---- invariants --------------------------------------------------------
    def check_invariants(self) -> None:
        t = self.totals
        expected = (self.initial_deposit + t["realised_gross"] - t["conversion_fees"]
                    - t["commissions"] - t["financing"] + t["nbp_credit"])
        if abs(expected - self.cash) > 1e-6 * max(1.0, abs(self.initial_deposit)):
            raise LedgerError(f"cash {self.cash} != reconstructed {expected}")
        bal = self.journal_balance()
        if abs(sum(bal.values())) > 1e-6:
            raise LedgerError(f"journal does not balance: {sum(bal.values())}")
        if abs(bal.get("cash", 0.0) - self.cash) > 1e-6:
            raise LedgerError("cash account balance != running cash")
        for sym, book in self.lots.items():
            signs = {l.qty > 0 for l in book}
            if len(signs) > 1:
                raise LedgerError(f"{sym}: FIFO book holds both long and short lots")
