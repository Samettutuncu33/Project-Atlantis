"""Instrument specifications and Saxo conditions loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

CONDITIONS_PATH = Path(__file__).resolve().parent.parent / "config" / "saxo_conditions.yaml"
ESMA_MAJORS = {"USD", "EUR", "JPY", "GBP", "CAD", "CHF"}


class UnavailableDataError(RuntimeError):
    """Raised when a computation needs a field marked UNAVAILABLE."""


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: str          # "fx_spot" | "fx_metal"
    base: str
    quote: str
    pip: float                # price increment that Saxo statistics are quoted in
    initial_margin: float     # fraction of notional (ESMA retail)
    min_size: float           # base units
    size_step: float
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def pnl_ccy(self) -> str:
        return self.quote


@lru_cache(maxsize=1)
def conditions() -> dict:
    return yaml.safe_load(CONDITIONS_PATH.read_text())


def _pip(base: str, quote: str) -> tuple[float, tuple[str, ...]]:
    if base == "XAU":
        return 0.01, ("A7: XAUUSD pip=0.01 assumed for Saxo stats conversion",)
    if base == "XAG":
        return 0.001, ("A7: XAGUSD pip=0.001 assumed for Saxo stats conversion",)
    return (0.01 if quote == "JPY" else 0.0001), ()


def make_instrument(symbol: str) -> Instrument:
    c = conditions()
    base, quote = symbol[:3], symbol[3:]
    m = c["margin_retail_esma"]["initial_margin"]
    if base in ("XAU",):
        cls, margin = "fx_metal", m["other_fx_and_gold"]
    elif base in ("XAG", "XPT", "XPD"):
        cls, margin = "fx_metal", m["commodity_ex_gold"]
    else:
        cls = "fx_spot"
        margin = m["major_fx"] if {base, quote} <= ESMA_MAJORS else m["other_fx_and_gold"]
    pip, notes = _pip(base, quote)
    fx = c["fx_spot"]
    if fx["min_trade_size_units"]["status"] == "UNAVAILABLE":
        raise UnavailableDataError(f"{symbol}: min trade size unavailable")
    notes = notes + ("A4: min trade size 1000 units (assumption)",)
    return Instrument(symbol, cls, base, quote, pip, margin,
                      float(fx["min_trade_size_units"]["value"]),
                      float(fx["size_increment_units"]["value"]), notes)
