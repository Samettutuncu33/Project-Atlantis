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
    NEW = "NEW"                   # created, not yet through the pre-trade gate
    PENDING = "PENDING"           # accepted by the gate, working at the broker
    ACCEPTED = "PENDING"          # alias: ACCEPTED and PENDING are the same state
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class IllegalTransition(RuntimeError):
    pass


# Order state machine. Terminal states have no outgoing transitions.
ALLOWED: dict[Status, set[Status]] = {
    Status.NEW: {Status.PENDING, Status.REJECTED},
    Status.PENDING: {Status.PARTIAL, Status.FILLED, Status.REJECTED, Status.CANCELLED, Status.EXPIRED},
    Status.PARTIAL: {Status.PARTIAL, Status.FILLED, Status.CANCELLED, Status.EXPIRED},
    Status.FILLED: set(), Status.REJECTED: set(), Status.CANCELLED: set(), Status.EXPIRED: set(),
}


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
    status: Status = Status.NEW
    filled_qty: float = 0.0
    reject_reason: str = ""
    fills: list[dict] = field(default_factory=list)
    history: list[str] = field(default_factory=lambda: ["NEW"])

    def __post_init__(self) -> None:
        if self.qty == 0:
            raise ValueError("order qty must be non-zero")
        if self.type is not OrderType.MARKET and (self.price is None or self.price <= 0):
            raise ValueError(f"{self.type} order needs a positive price")

    def transition(self, new: Status, reason: str = "") -> None:
        if new not in ALLOWED[self.status]:
            raise IllegalTransition(f"order {self.id}: {self.status.value} -> {new.value} is not allowed")
        self.status = new
        if new is Status.REJECTED:
            self.reject_reason = reason
        self.history.append(new.value)

    @property
    def terminal(self) -> bool:
        return not ALLOWED[self.status]

    @property
    def side(self) -> int:
        return 1 if self.qty > 0 else -1

    @property
    def remaining(self) -> float:
        return self.qty - self.filled_qty
