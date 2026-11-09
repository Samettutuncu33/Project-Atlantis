"""Test fixtures. The random-walk data below is a TEST FIXTURE only; it is never
used for research results and never written to the market-data store."""

import numpy as np
import pandas as pd
import pytest


def make_fixture(symbol: str, n: int = 600, start: float = 1.10, vol: float = 0.006,
                 spread: float = 0.00010, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n, tz="UTC", name="ts")
    mid = start * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[start, mid[:-1]]
    hi = np.maximum(o, mid) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, mid) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    h = spread / 2
    return pd.DataFrame({
        "bid_open": o - h, "bid_high": hi - h, "bid_low": lo - h, "bid_close": mid - h,
        "ask_open": o + h, "ask_high": hi + h, "ask_low": lo + h, "ask_close": mid + h,
        "bid_volume": 1.0, "ask_volume": 1.0}, index=idx)


@pytest.fixture
def fx_data():
    return {"EURUSD": make_fixture("EURUSD", seed=1),
            "USDJPY": make_fixture("USDJPY", start=110.0, spread=0.01, seed=2),
            "GBPUSD": make_fixture("GBPUSD", start=1.30, seed=3)}
