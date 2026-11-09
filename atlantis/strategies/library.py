"""Strategy library. Parameters are the published defaults of each cited study;
none were tuned on our data."""

from __future__ import annotations

import numpy as np
import pandas as pd

from atlantis.strategies.base import Strategy


class TimeSeriesMomentum(Strategy):
    """Moskowitz, Ooi & Pedersen (2012) TSMOM: sign of the trailing 12-month
    return, monthly rebalance, vol-scaled positions (vol scaling in the sizer)."""
    name = "tsmom_12m"
    rebalance = "M"
    citation = "Moskowitz, Ooi, Pedersen (2012) J. Financial Economics 104(2):228-250"

    def __init__(self, lookback_days: int = 252):
        self.lookback_days = lookback_days

    def signals(self, mid, panels):
        return np.sign(mid / mid.shift(self.lookback_days) - 1.0)


class DonchianBreakout(Strategy):
    """Channel breakout (Donchian; popularised as the 'Turtle' system, Faith 2007):
    long on a close above the prior 55-day high, short below the prior 55-day low,
    exit on the opposite 20-day channel. Stop 2x ATR(20)."""
    name = "donchian_55_20"
    rebalance = "D"
    citation = "Donchian (1960); Faith (2007) 'Way of the Turtle'"

    def __init__(self, entry: int = 55, exit: int = 20, atr_n: int = 20, atr_mult: float = 2.0):
        self.entry, self.exit, self.atr_n, self.atr_mult = entry, exit, atr_n, atr_mult

    def signals(self, mid, panels):
        hi_e = mid.rolling(self.entry).max().shift(1)
        lo_e = mid.rolling(self.entry).min().shift(1)
        hi_x = mid.rolling(self.exit).max().shift(1)
        lo_x = mid.rolling(self.exit).min().shift(1)
        out = pd.DataFrame(0.0, index=mid.index, columns=mid.columns)
        for c in mid.columns:
            pos = 0.0
            m, he, le, hx, lx = (x[c].to_numpy() for x in (mid, hi_e, lo_e, hi_x, lo_x))
            col = np.zeros(len(m))
            for i in range(len(m)):
                if np.isnan(he[i]):
                    col[i] = 0.0
                    continue
                if pos > 0 and m[i] < lx[i]:
                    pos = 0.0
                elif pos < 0 and m[i] > hx[i]:
                    pos = 0.0
                if pos == 0:
                    if m[i] > he[i]:
                        pos = 1.0
                    elif m[i] < le[i]:
                        pos = -1.0
                col[i] = pos
            out[c] = col
        return out

    def stops(self, mid, panels):
        hi = (panels["bid_high"] + panels["ask_high"]) / 2
        lo = (panels["bid_low"] + panels["ask_low"]) / 2
        prev = mid.shift(1)
        tr = pd.concat([hi - lo, (hi - prev).abs(), (lo - prev).abs()]).groupby(level=0).max()
        atr = tr.reindex(mid.index).rolling(self.atr_n).mean()
        return self.atr_mult * atr


class ShortTermReversal(Strategy):
    """Short-horizon mean reversion: fade a 5-day move measured in units of its own
    volatility (z-score). Classic short-term reversal (Lehmann 1990; Jegadeesh 1990),
    applied per instrument. Enter when |z|>1, flat when |z|<0.5."""
    name = "reversal_5d_z"
    rebalance = "D"
    citation = "Lehmann (1990) QJE; Jegadeesh (1990) J. Finance"

    def __init__(self, horizon: int = 5, vol_window: int = 60, enter: float = 1.0, exit: float = 0.5):
        self.horizon, self.vol_window, self.enter, self.exit = horizon, vol_window, enter, exit

    def signals(self, mid, panels):
        r = np.log(mid).diff()
        move = np.log(mid / mid.shift(self.horizon))
        sd = r.rolling(self.vol_window).std() * np.sqrt(self.horizon)
        z = move / sd
        out = pd.DataFrame(0.0, index=mid.index, columns=mid.columns)
        for c in mid.columns:
            zz = z[c].to_numpy()
            pos, col = 0.0, np.zeros(len(zz))
            for i, v in enumerate(zz):
                if np.isnan(v):
                    pos = 0.0
                elif pos == 0 and abs(v) > self.enter:
                    pos = -np.sign(v)
                elif pos != 0 and abs(v) < self.exit:
                    pos = 0.0
                col[i] = pos
            out[c] = col
        return out


class BuyAndHoldUSDShort(Strategy):
    """Benchmark: constant +1 signal (long base currency) in every instrument."""
    name = "always_long_benchmark"
    rebalance = "M"
    citation = "benchmark"

    def signals(self, mid, panels):
        return pd.DataFrame(1.0, index=mid.index, columns=mid.columns).where(mid.notna())


REGISTRY = {s.name: s for s in (TimeSeriesMomentum, DonchianBreakout, ShortTermReversal,
                                BuyAndHoldUSDShort)}
