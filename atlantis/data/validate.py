"""Market data validation. Problems are reported, never silently patched.

Each check returns Issue records; ``clean_daily`` removes only rows that are
provably non-trading (weekend placeholder candles) and reports every removal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Issue:
    severity: str  # INFO | WARN | ERROR
    check: str
    symbol: str
    ts: str
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


def clean_daily(df: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, list[Issue]]:
    """Drop weekend / zero-volume placeholder bars and validate the rest."""
    issues: list[Issue] = []
    flat = ((df["bid_open"] == df["bid_close"]) & (df["bid_high"] == df["bid_low"])
            & (df["bid_open"] == df["bid_high"]))
    placeholder = (df["bid_volume"] <= 0) | flat
    weekend = df.index.dayofweek == 5  # Saturday: FX market closed all day (UTC)
    drop = placeholder | weekend
    n = int(drop.sum())
    if n:
        issues.append(Issue("INFO", "non_trading_bar_removed", symbol, "",
                            f"removed {n} weekend/placeholder bars"))
    out = df.loc[~drop].copy()
    issues += check_daily(out, symbol)
    return out, issues


def check_daily(df: pd.DataFrame, symbol: str) -> list[Issue]:
    issues: list[Issue] = []

    def flag(mask: pd.Series, sev: str, name: str, detail: str) -> None:
        for ts in df.index[mask.to_numpy()]:
            issues.append(Issue(sev, name, symbol, ts.isoformat(), detail))

    if df.index.has_duplicates:
        flag(pd.Series(df.index.duplicated(), index=df.index), "ERROR", "duplicate_ts", "")
    if not df.index.is_monotonic_increasing:
        issues.append(Issue("ERROR", "unsorted_index", symbol, "", ""))
    for side in ("bid", "ask"):
        o, h, l, c = (df[f"{side}_{k}"] for k in ("open", "high", "low", "close"))
        flag(df[[f"{side}_{k}" for k in ("open", "high", "low", "close")]].isna().any(axis=1),
             "ERROR", f"{side}_missing", "NaN price")
        flag((h < np.maximum(o, c)) | (l > np.minimum(o, c)) | (h < l),
             "ERROR", f"{side}_ohlc_inconsistent", "high/low do not bound open/close")
        flag((o <= 0) | (c <= 0), "ERROR", f"{side}_nonpositive", "")
    flag(df["ask_close"] < df["bid_close"], "ERROR", "crossed_close",
         "ask < bid at close")
    flag(df["ask_open"] < df["bid_open"], "ERROR", "crossed_open", "ask < bid at open")
    # Spread outliers: > 10x rolling median spread (reported, not removed).
    rel_spread = (df["ask_close"] - df["bid_close"]) / df["bid_close"]
    med = rel_spread.rolling(60, min_periods=20).median()
    flag(rel_spread > 10 * med, "WARN", "spread_outlier", "spread > 10x 60d median")
    # Return outliers: |log return| > 8 robust sigmas.
    mid = (df["ask_close"] + df["bid_close"]) / 2
    r = np.log(mid).diff()
    mad = (r - r.rolling(250, min_periods=60).median()).abs().rolling(250, min_periods=60).median()
    flag((r.abs() > 8 * 1.4826 * mad).fillna(False), "WARN", "return_outlier",
         "|log return| > 8 robust sigma")
    # Gaps: more than 4 calendar days between consecutive bars (long weekend + holiday is 3-4).
    gaps = df.index.to_series().diff() > pd.Timedelta(days=4)
    flag(gaps, "WARN", "data_gap", "> 4 calendar days since previous bar")
    return issues
