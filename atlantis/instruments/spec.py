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
    # Per-class Saxo cost parameters (None -> the FX CostModel defaults apply)
    commission_min_usd: float | None = None
    commission_rate: float | None = None
    financing_long_pa: float | None = None
    financing_short_pa: float | None = None
    financing_unrealised_pa: float | None = None

    @property
    def pnl_ccy(self) -> str:
        return self.quote


UNIVERSE_PATH = CONDITIONS_PATH.parent / "universe.yaml"


@lru_cache(maxsize=1)
def universe() -> dict:
    return yaml.safe_load(UNIVERSE_PATH.read_text())


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
    u = universe()
    spec = u["instruments"].get(symbol)
    if spec is not None and spec[0] != "fx_spot":
        cls, quote, _point, tick = spec[0], spec[1], spec[2], spec[3]
        k = u["classes"][cls]
        notes = tuple(f"{name}: {v.get('note', v.get('status'))}" for name, v in k.items()
                      if isinstance(v, dict) and v.get("status") == "ASSUMPTION")
        return Instrument(symbol, cls, symbol[:-3], quote, tick, float(k["margin"]["value"]),
                          float(k["min_size"]["value"]), float(k["step"]), notes,
                          commission_min_usd=float(k["commission"]["min_usd"]),
                          commission_rate=float(k["commission"]["rate"]),
                          financing_long_pa=float(k["financing_pa"]["long"]),
                          financing_short_pa=float(k["financing_pa"]["short"]),
                          financing_unrealised_pa=float(k["financing_pa"]["unrealised"]))
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
    if cls == "fx_metal":
        # The 1,000-unit FX assumption (A4) is meaningless for metals (1,000 oz of gold).
        # Saxo's metal minimum is not public -> refuse rather than guess.
        raise UnavailableDataError(f"{symbol}: Saxo minimum trade size for metals is unavailable")
    if fx["min_trade_size_units"]["status"] == "UNAVAILABLE":
        raise UnavailableDataError(f"{symbol}: min trade size unavailable")
    notes = notes + ("A4: min trade size 1000 units (assumption)",)
    return Instrument(symbol, cls, base, quote, pip, margin,
                      float(fx["min_trade_size_units"]["value"]),
                      float(fx["size_increment_units"]["value"]), notes)
