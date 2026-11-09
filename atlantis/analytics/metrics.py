"""Performance metrics (formulas per the portfolio-analytics skill; cross-checked
against quantstats in tests). Daily data, 252 periods per year, rf = 0 unless given."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

P = 252


def returns_from_equity(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def cagr(equity: pd.Series) -> float:
    days = (equity.index[-1] - equity.index[0]).days
    if days <= 0 or equity.iloc[0] <= 0:
        return float("nan")
    if equity.iloc[-1] <= 0:
        return -1.0
    return (equity.iloc[-1] / equity.iloc[0]) ** (365.25 / days) - 1


def sharpe(r: pd.Series, rf: float = 0.0) -> float:
    ex = r - rf
    sd = ex.std()
    return float(ex.mean() / sd * math.sqrt(P)) if sd > 0 else 0.0


def sortino(r: pd.Series, rf: float = 0.0) -> float:
    """Sortino with downside deviation over ALL periods (Sortino & Price 1994;
    same convention as quantstats): sqrt(mean(min(r,0)^2))."""
    ex = r - rf
    dd = math.sqrt((np.minimum(ex, 0) ** 2).mean())
    return float(ex.mean() / dd * math.sqrt(P)) if dd > 0 else float("inf")


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1


def max_drawdown(equity: pd.Series) -> float:
    return float(drawdown(equity).min())


def longest_underwater_days(equity: pd.Series) -> int:
    dd = drawdown(equity) < 0
    best = cur = 0
    start = None
    for t, u in dd.items():
        if u:
            start = start or t
            cur = (t - start).days
            best = max(best, cur)
        else:
            start, cur = None, 0
    return best


def trade_stats(pnl: pd.Series) -> dict:
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gp, gl = wins.sum(), -losses.sum()
    n = len(pnl)
    return {
        "trades": n,
        "win_rate": len(wins) / n if n else float("nan"),
        "avg_win": wins.mean() if len(wins) else 0.0,
        "avg_loss": losses.mean() if len(losses) else 0.0,
        "profit_factor": gp / gl if gl > 0 else (float("inf") if gp > 0 else float("nan")),
        "expectancy": pnl.mean() if n else float("nan"),
        "largest_win": wins.max() if len(wins) else 0.0,
        "largest_loss": losses.min() if len(losses) else 0.0,
    }


def summary(equity: pd.Series) -> dict:
    r = returns_from_equity(equity)
    vol = r.std() * math.sqrt(P)
    mdd = max_drawdown(equity)
    c = cagr(equity)
    return {
        "start_equity": float(equity.iloc[0]), "end_equity": float(equity.iloc[-1]),
        "net_pnl": float(equity.iloc[-1] - equity.iloc[0]),
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "cagr": c, "ann_vol": float(vol), "sharpe": sharpe(r), "sortino": sortino(r),
        "max_drawdown": mdd, "calmar": c / abs(mdd) if mdd < 0 else float("nan"),
        "longest_underwater_days": longest_underwater_days(equity),
        "skew": float(r.skew()), "kurtosis": float(r.kurt()), "n_days": len(r),
    }
