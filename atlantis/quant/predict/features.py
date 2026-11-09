"""Chart analysis: causal technical features from daily bid/ask bars.

Every feature at date t uses only bars up to and including t. That is verified
by tests/test_predict.py with the same truncation method as the look-ahead
detector. Features are scale-free (returns, z-scores, ratios), so one model
can learn across instruments and asset classes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ["ret_5", "ret_20", "ret_60", "ret_250", "ma_slope_50", "rsi_14", "macd_hist",
            "zscore_20", "boll_pos_20", "donchian_pos_55", "atr_pct_20", "vol_ratio_20_120",
            "spread_bps", "dist_high_250"]


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def symbol_features(mid: pd.Series, high: pd.Series, low: pd.Series, spread: pd.Series) -> pd.DataFrame:
    lr = np.log(mid).diff()
    vol20 = lr.rolling(20).std()
    f = pd.DataFrame(index=mid.index)
    for n in (5, 20, 60, 250):
        f[f"ret_{n}"] = np.log(mid / mid.shift(n)) / (vol20 * np.sqrt(n))       # vol-normalised
    ma50 = mid.rolling(50).mean()
    f["ma_slope_50"] = (ma50 / ma50.shift(10) - 1) / (vol20 * np.sqrt(10))
    f["rsi_14"] = (_rsi(mid) - 50) / 50
    macd = mid.ewm(span=12, adjust=False).mean() - mid.ewm(span=26, adjust=False).mean()
    f["macd_hist"] = (macd - macd.ewm(span=9, adjust=False).mean()) / (mid * vol20)
    m20, s20 = mid.rolling(20).mean(), mid.rolling(20).std()
    f["zscore_20"] = (mid - m20) / s20
    f["boll_pos_20"] = ((mid - (m20 - 2 * s20)) / (4 * s20)).clip(-1, 2)
    hi55, lo55 = high.rolling(55).max(), low.rolling(55).min()
    f["donchian_pos_55"] = (mid - lo55) / (hi55 - lo55)
    prev = mid.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    f["atr_pct_20"] = tr.rolling(20).mean() / mid
    f["vol_ratio_20_120"] = vol20 / lr.rolling(120).std()
    f["spread_bps"] = spread / mid * 1e4
    f["dist_high_250"] = mid / mid.rolling(250).max() - 1
    return f.replace([np.inf, -np.inf], np.nan)


def build_features(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Long frame indexed (ts, symbol) with FEATURES plus `vol20` and `mid`."""
    mid = panels["mid_close"]
    hi = (panels["bid_high"] + panels["ask_high"]) / 2
    lo = (panels["bid_low"] + panels["ask_low"]) / 2
    spread = panels["ask_close"] - panels["bid_close"]
    parts = []
    for s in mid.columns:
        m = mid[s].dropna()
        f = symbol_features(m, hi[s].reindex(m.index), lo[s].reindex(m.index), spread[s].reindex(m.index))
        f["vol20"] = np.log(m).diff().rolling(20).std()
        f["mid"] = m
        f["symbol"] = s
        parts.append(f)
    out = pd.concat(parts).reset_index().rename(columns={"index": "ts"})
    return out.set_index(["ts", "symbol"]).sort_index()


def forward_labels(panels: dict[str, pd.DataFrame], horizon: int) -> pd.DataFrame:
    """Outcome h trading bars ahead: log mid return and up/down. FOR TRAINING/SCORING
    ONLY. A label for date t is known only at date t+h; callers must respect that."""
    mid = panels["mid_close"]
    rows = []
    for s in mid.columns:
        m = mid[s].dropna()
        r = np.log(m.shift(-horizon) / m)
        known = pd.Series(m.index, index=m.index).shift(-horizon)
        rows.append(pd.DataFrame({"fwd_ret": r, "up": (r > 0).astype(float).where(r.notna()),
                                  "known_at": known, "symbol": s}, index=m.index))
    out = pd.concat(rows).reset_index().rename(columns={"index": "ts"})
    return out.set_index(["ts", "symbol"]).sort_index()


CONTEXT = ["d_ret_5", "d_ret_20", "d_ret_60", "d_ret_250", "d_rsi_14", "d_donchian_pos_55",
           "d_vol_ratio_20_120", "d_dist_high_250"]


def add_context(intraday: pd.DataFrame, daily_panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Attach daily/weekly context to intraday feature rows, causally.

    Daily bar D closes at D+1 00:00 UTC, so an intraday row at time ts may only see
    daily rows with D + 1 day <= ts (as-of join). d_ret_5 is the weekly move, d_ret_20 the
    monthly move, d_ret_250 the yearly trend, all normalised by volatility."""
    daily = build_features(daily_panels)
    base = [c.removeprefix("d_") for c in CONTEXT]
    out = []
    for sym, g in intraday.groupby(level="symbol"):
        g = g.reset_index()
        if sym not in daily.index.get_level_values("symbol"):
            for c in CONTEXT:
                g[c] = np.nan
            out.append(g)
            continue
        d = daily.xs(sym, level="symbol")[base].rename(columns=lambda c: "d_" + c)
        d = d.assign(avail=d.index + pd.Timedelta(days=1)).sort_values("avail")
        g = g.sort_values("ts")
        m = pd.merge_asof(g, d, left_on="ts", right_on="avail", direction="backward")
        out.append(m.drop(columns=["avail"]))
    res = pd.concat(out)
    return res.set_index(["ts", "symbol"]).sort_index()
