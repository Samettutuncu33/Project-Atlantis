"""Turn a calibrated prediction into a target position (quant layer: proposals only).

For a horizon-h prediction with calibrated P(up) = p and daily volatility sigma:
  sigma_h   = sigma * sqrt(h)
  E|r_h|   ~= sigma_h * sqrt(2/pi)                (half-normal mean)
  mu_h      = (2p - 1) * E|r_h|                   (expected log return)
  Kelly f*  = mu_h / sigma_h^2                     (continuous Kelly, Thorp 2006)
  target    = KELLY_FRACTION * f* * equity / usd_per_unit
A target is proposed only if its expected edge (|mu_h| x notional) exceeds the
estimated round trip cost: spread + 2 commissions + financing over the horizon.
The gate re-checks every proposal; this module cannot trade.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

KELLY_FRACTION = 0.5     # half Kelly: standard allowance for estimation error (MacLean, Thorp, Ziemba 2011)


@dataclass(frozen=True)
class Proposal:
    symbol: str
    target_qty: float
    p: float
    mu_h: float
    edge_usd: float
    cost_usd: float
    reason: str


def round_to_feasible(q: float, min_size: float, step: float) -> float:
    a = abs(q)
    if a < min_size / 2:
        return 0.0
    a = max(a, min_size)
    a = round(a / step) * step
    return math.copysign(round(a, 10), q)


def propose(symbol: str, p: float, sigma_daily: float, horizon: int, equity: float,
            usd_per_unit: float, spread_price: float, price: float, inst,
            horizon_days: float | None = None) -> Proposal:
    """sigma_daily is the volatility per BAR (daily or hourly); horizon is in bars;
    horizon_days is the calendar holding period used for financing."""
    if not (sigma_daily > 0 and usd_per_unit > 0 and equity > 0):
        return Proposal(symbol, 0.0, p, 0.0, 0.0, 0.0, "no volatility or price estimate")
    sig_h = sigma_daily * math.sqrt(horizon)
    mu_h = (2 * p - 1) * sig_h * math.sqrt(2 / math.pi)
    f = mu_h / sig_h ** 2
    raw = KELLY_FRACTION * f * equity / usd_per_unit
    qty = round_to_feasible(raw, inst.min_size, inst.size_step)
    if qty == 0:
        return Proposal(symbol, 0.0, p, mu_h, 0.0, 0.0,
                        "Kelly size below half the minimum ticket" if raw else "no edge")
    notional = abs(qty) * usd_per_unit
    edge = abs(mu_h) * notional
    comm_min = inst.commission_min_usd if inst.commission_min_usd is not None else 1.0
    comm_rate = inst.commission_rate if inst.commission_rate is not None else 0.0
    commission = 2 * max(comm_min, comm_rate * notional)
    fin_pa = (inst.financing_long_pa if qty > 0 else inst.financing_short_pa)
    fin_pa = 0.0075 if fin_pa is None else fin_pa
    hold_days = horizon * 7 / 5 if horizon_days is None else horizon_days
    financing = fin_pa * notional * hold_days / 360
    spread_cost = spread_price / price * notional
    cost = commission + financing + spread_cost
    if edge <= cost:
        return Proposal(symbol, 0.0, p, mu_h, edge, cost, f"edge ${edge:.2f} <= cost ${cost:.2f}")
    return Proposal(symbol, qty, p, mu_h, edge, cost, f"edge ${edge:.2f} > cost ${cost:.2f}")
