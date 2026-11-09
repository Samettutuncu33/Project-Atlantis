"""Order model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class TIF(str, Enum):
    DAY = "DAY"   # expires at end of the bar after submission
    GTC = "GTC"


class Status(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass
class Order:
    id: int
    symbol: str
    qty: float                    # signed base units
    type: OrderType = OrderType.MARKET
    price: float | None = None    # limit or stop trigger
    tif: TIF = TIF.DAY
    submitted: str = ""
    tag: str = ""                 # e.g. "entry", "stop", "rebalance"
    decision_mid: float | None = None   # mid at decision time, for shortfall analysis
    status: Status = Status.PENDING
    filled_qty: float = 0.0
    reject_reason: str = ""
    fills: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.qty == 0:
            raise ValueError("order qty must be non-zero")
        if self.type is not OrderType.MARKET and (self.price is None or self.price <= 0):
            raise ValueError(f"{self.type} order needs a positive price")

    @property
    def side(self) -> int:
        return 1 if self.qty > 0 else -1

    @property
    def remaining(self) -> float:
        return self.qty - self.filled_qty
