"""Bar-based fill model using real bid/ask OHLC.

Rules (all conservative; documented in docs/ASSUMPTIONS.md):
  * Buys execute on the ASK series, sells on the BID series.
  * Orders submitted at bar t can only fill on bar t+1 or later (no look-ahead).
  * MARKET: fills at the bar's open (ask/bid) plus Saxo-published average net
    market-order slippage for the pair (deterministic expected value).
  * LIMIT: if the open is already better than the limit, fill at the open
    (price improvement). Otherwise fill at the limit only if the bar trades
    THROUGH the limit by at least one pip ("touch is not a fill").
  * STOP: if the open gaps through the trigger, fill at the open (gap risk).
    Otherwise fill at the trigger when the bar reaches it. In both cases add
    Saxo-published average net stop slippage for the pair.
  * Partial fills: optional participation cap against bar volume. Disabled for
    FX (Dukascopy volume is not exchange volume; Saxo reports ~100% FX fill rates).
"""

from __future__ import annotations

from dataclasses import dataclass

from atlantis.instruments.spec import Instrument, conditions
from atlantis.gate.sim.orders import Order, OrderType


@dataclass(frozen=True)
class Bar:
    ts: str
    bid_open: float
    bid_high: float
    bid_low: float
    bid_close: float
    ask_open: float
    ask_high: float
    ask_low: float
    ask_close: float
    volume: float = 0.0

    @property
    def mid_close(self) -> float:
        return 0.5 * (self.bid_close + self.ask_close)

    @property
    def mid_open(self) -> float:
        return 0.5 * (self.bid_open + self.ask_open)


@dataclass(frozen=True)
class FillQuote:
    price: float
    qty: float
    slippage_pips: float  # adverse slippage applied (+ = worse for client)
    reason: str


def _stats(table: str, symbol: str) -> list[float] | None:
    return conditions()["execution_statistics"][table].get(symbol)


def market_slippage_pips(symbol: str) -> float:
    """Expected adverse slippage (pips) for market orders from Saxo statistics."""
    s = _stats("market_orders", symbol)
    return 0.0 if s is None else -float(s[3])   # net improvement -> adverse slippage


def stop_slippage_pips(symbol: str) -> float:
    s = _stats("resting_stop_orders", symbol)
    return 0.0 if s is None else float(s[3])


def try_fill(order: Order, bar: Bar, inst: Instrument, extra_spread_bps: float = 0.0,
             max_participation: float | None = None) -> FillQuote | None:
    buy = order.side > 0
    o, h, l = ((bar.ask_open, bar.ask_high, bar.ask_low) if buy
               else (bar.bid_open, bar.bid_high, bar.bid_low))
    half_extra = 0.5 * extra_spread_bps * 1e-4 * bar.mid_open
    sgn = 1.0 if buy else -1.0
    px: float | None = None
    slip = 0.0
    reason = ""
    if order.type is OrderType.MARKET:
        slip = market_slippage_pips(inst.symbol)
        px, reason = o, "market@open"
    elif order.type is OrderType.LIMIT:
        L = float(order.price)
        if (buy and o <= L) or (not buy and o >= L):
            px, reason = o, "limit@open(improved)"
        elif (buy and l <= L - inst.pip) or (not buy and h >= L + inst.pip):
            px, reason = L, "limit@level"
    elif order.type is OrderType.STOP:
        S = float(order.price)
        slip = stop_slippage_pips(inst.symbol)
        if (buy and o >= S) or (not buy and o <= S):
            px, reason = o, "stop@open(gap)"
        elif (buy and h >= S) or (not buy and l <= S):
            px, reason = S, "stop@level"
    if px is None:
        return None
    px = px + sgn * (slip * inst.pip + half_extra)
    qty = order.remaining
    if max_participation is not None:
        cap = max_participation * bar.volume
        if cap <= 0:
            return None
        if abs(qty) > cap:
            qty = sgn * cap
            reason += "+partial"
    return FillQuote(px, qty, slip, reason)
