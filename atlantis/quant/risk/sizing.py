"""Position sizing.

Method (see docs/RISK_METHOD.md for the evidence base):
  * Volatility targeting: each instrument's position is scaled so its ex-ante
    annualised volatility contribution equals `portfolio_vol / sqrt(N)` (equal
    risk, zero-correlation approximation). Ex-ante vol is an exponentially
    weighted estimate with centre of mass 60 trading days, as in Moskowitz,
    Ooi & Pedersen (2012), "Time series momentum", JFE 104(2).
  * `leverage_scale` multiplies all targets. The `max_growth` profile sets it
    from an out-of-sample fractional-Kelly estimate (research/target.py); the
    `conservative` profile uses 1.0.
  * Rounding: targets are rounded to the nearest feasible Saxo size. A target
    below half the minimum ticket rounds to zero; between half and one minimum
    it rounds UP to the minimum (nearest feasible quantity -> least tracking
    error). Every such adjustment is counted and reported.
  * Margin cap: total ESMA initial margin may not exceed equity (regulatory
    maximum). If it would, all targets are scaled down proportionally.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from atlantis.instruments.spec import Instrument

TRADING_DAYS = 252


def ewma_vol(mid: pd.DataFrame, com: float = 60.0) -> pd.DataFrame:
    """Annualised EWMA volatility of daily log returns (causal)."""
    r = np.log(mid).diff()
    return np.sqrt(r.pow(2).ewm(com=com, min_periods=int(com)).mean() * TRADING_DAYS)


@dataclass
class VolTargetSizer:
    portfolio_vol: float = 0.10
    leverage_scale: float = 1.0
    max_margin_utilisation: float = 1.0
    adjustments: dict[str, int] = field(default_factory=lambda: {
        "rounded_to_zero": 0, "rounded_up_to_min": 0, "margin_scaled": 0})

    def targets(self, signals: pd.Series, vols: pd.Series, equity: float,
                usd_per_unit: dict[str, float], instruments: dict[str, Instrument]) -> dict[str, float]:
        active = [s for s, v in signals.items() if v != 0 and np.isfinite(v)
                  and np.isfinite(vols.get(s, np.nan)) and vols[s] > 0]
        n = max(len(signals.dropna()), 1)
        per_asset = self.portfolio_vol / math.sqrt(n) * self.leverage_scale
        raw = {}
        for s in active:
            usd_vol_per_unit = vols[s] * usd_per_unit[s]
            raw[s] = float(np.clip(signals[s], -1, 1)) * per_asset * equity / usd_vol_per_unit
        # ESMA margin cap
        margin = sum(abs(q) * usd_per_unit[s] * instruments[s].initial_margin for s, q in raw.items())
        cap = self.max_margin_utilisation * equity
        if margin > cap > 0:
            k = cap / margin
            raw = {s: q * k for s, q in raw.items()}
            self.adjustments["margin_scaled"] += 1
        out = {s: 0.0 for s in signals.index}
        for s, q in raw.items():
            out[s] = self.round_qty(q, instruments[s])
        return out

    def round_qty(self, q: float, inst: Instrument) -> float:
        a = abs(q)
        if a < inst.min_size / 2:
            if a > 0:
                self.adjustments["rounded_to_zero"] += 1
            return 0.0
        if a < inst.min_size:
            self.adjustments["rounded_up_to_min"] += 1
            a = inst.min_size
        a = round(a / inst.size_step) * inst.size_step
        return math.copysign(a, q)


@dataclass
class MinTicketSizer(VolTargetSizer):
    """Diagnostic profile: trade exactly the minimum ticket in the signal's
    direction, IGNORING the volatility target. Shows what a $200 account is
    forced into by Saxo's minimum size. Realised risk is reported, not hidden."""

    def targets(self, signals, vols, equity, usd_per_unit, instruments):
        out = {}
        for s, v in signals.items():
            ok = np.isfinite(v) and v != 0 and np.isfinite(vols.get(s, np.nan))
            out[s] = math.copysign(instruments[s].min_size, v) if ok else 0.0
        return out
