"""Overfitting controls and the 2x-per-month target analysis.

* Deflated Sharpe Ratio: Bailey & Lopez de Prado (2014), "The Deflated Sharpe
  Ratio", J. Portfolio Management 40(5). Accounts for the number of trials,
  non-normality (skew/kurtosis) and sample length.
* Kelly growth: for log-utility, optimal leverage f* = mu / sigma^2 and the
  maximal growth rate g* = SR^2 / 2 (continuous-time approximation; Thorp 2006,
  "The Kelly criterion in blackjack, sports betting and the stock market").
* Target analysis: stationary block bootstrap (Politis & Romano 1994) of daily
  out-of-sample returns to estimate P(month >= +100%) and P(ruin).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

EULER = 0.5772156649015329


class TrialRegistry:
    """Append-only record of every strategy variant evaluated (for DSR)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, name: str, params: dict, sharpe_daily: float, period: str) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps({"name": name, "params": params, "sr_daily": sharpe_daily,
                                "period": period}, default=str) + "\n")

    def trials(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """E[max SR] among n independent trials with zero true SR (BLdP 2014, eq. 2)."""
    if n_trials <= 1:
        return 0.0
    return math.sqrt(var_sr) * ((1 - EULER) * norm.ppf(1 - 1 / n_trials)
                                + EULER * norm.ppf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(r: pd.Series, n_trials: int, var_sr_trials: float) -> dict:
    """Probability that the true (daily) SR exceeds the best-of-n-trials noise level."""
    r = r.dropna()
    n = len(r)
    sr = r.mean() / r.std() if r.std() > 0 else 0.0
    g3, g4 = float(r.skew()), float(r.kurt()) + 3.0
    sr0 = expected_max_sharpe(n_trials, var_sr_trials)
    denom = math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2, 1e-12))
    z = (sr - sr0) * math.sqrt(n - 1) / denom
    return {"sr_daily": sr, "sr0_daily": sr0, "dsr": float(norm.cdf(z)), "n_trials": n_trials}


def kelly(r: pd.Series) -> dict:
    mu, var = r.mean(), r.var()
    f = mu / var if var > 0 else 0.0
    sr_ann = r.mean() / r.std() * math.sqrt(252) if r.std() > 0 else 0.0
    return {"kelly_leverage": f, "growth_at_kelly_ann": sr_ann ** 2 / 2,
            "sharpe_ann": sr_ann,
            "sharpe_needed_for_2x_month": math.sqrt(2 * 12 * math.log(2))}


def block_bootstrap(r: np.ndarray, n_paths: int, horizon: int, mean_block: int,
                    rng: np.random.Generator) -> np.ndarray:
    """Stationary bootstrap paths, shape (n_paths, horizon)."""
    n = len(r)
    out = np.empty((n_paths, horizon))
    p = 1.0 / mean_block
    for i in range(n_paths):
        idx = rng.integers(n)
        for j in range(horizon):
            if j and rng.random() < p:
                idx = rng.integers(n)
            else:
                idx = (idx + 1) % n if j else idx
            out[i, j] = r[idx]
    return out


def target_analysis(r: pd.Series, leverage: float = 1.0, n_paths: int = 4000,
                    days_per_month: int = 21, months: int = 12, seed: int = 7,
                    ruin_level: float = 0.5) -> dict:
    """Bootstrap the 2x-per-month target. Returns probabilities, not promises."""
    rng = np.random.default_rng(seed)
    x = np.clip(r.dropna().to_numpy() * leverage, -0.999, None)
    if len(x) < 60:
        return {"error": "insufficient out-of-sample history"}
    paths = block_bootstrap(x, n_paths, days_per_month * months, 5, rng)
    wealth = np.cumprod(1 + paths, axis=1)
    month_end = wealth[:, days_per_month - 1::days_per_month]
    first_month = month_end[:, 0]
    monthly_ret = month_end / np.concatenate([np.ones((n_paths, 1)), month_end[:, :-1]], axis=1) - 1
    hit_2x_every_month = np.all(monthly_ret >= 1.0, axis=1)
    ruin = (wealth.min(axis=1) <= ruin_level)
    return {
        "leverage": leverage,
        "p_double_in_a_month": float((first_month >= 2).mean()),
        "p_any_month_doubles": float((monthly_ret >= 1.0).any(axis=1).mean()),
        "p_double_every_month_12m": float(hit_2x_every_month.mean()),
        "median_12m_multiple": float(np.median(wealth[:, -1])),
        "p_lose_half_within_12m": float(ruin.mean()),
        "median_monthly_return": float(np.median(monthly_ret)),
    }
