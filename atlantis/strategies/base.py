"""Strategy interface.

A strategy maps a causal panel of daily mid prices (and optional bid/ask
panels) to a DataFrame of signals in [-1, 1] indexed like the panel. The
signal at row t may only use information up to and including t; it is
executed on bar t+1. The engine *verifies* this (look-ahead detector).

Strategies are fixed-parameter, taken from the cited literature: no parameter
search is performed in-sample. Any variant that is run is recorded in the
trial registry so the deflated Sharpe ratio accounts for it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    name: str = "base"
    rebalance: str = "D"   # "D" daily or "M" first trading day of each month
    citation: str = ""

    @abstractmethod
    def signals(self, mid: pd.DataFrame, panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
        ...

    def stops(self, mid: pd.DataFrame, panels: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
        """Optional protective stop distance (in price units) per symbol/date."""
        return None

    def params(self) -> dict:
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}
