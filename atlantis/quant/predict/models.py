"""Predictors: each maps features known at t to P(mid higher in `horizon` bars).

Rule predictors re-express the three published strategies as probabilities
(score s in [-1, 1] -> p = 0.5 + 0.5 * k * s, with k learned by calibration
downstream). ML predictors are trained walk-forward: the training set at date t
contains only rows whose outcome was KNOWN by t (label known_at <= t), plus an
embargo, which is purged cross-validation in its simplest correct form
(Lopez de Prado 2018, ch. 7).
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from atlantis.quant.predict.features import FEATURES


class Predictor:
    name = "base"
    trainable = False

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:  # noqa: B027
        pass

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError


class TrendRule(Predictor):
    """12-month time-series momentum (Moskowitz, Ooi & Pedersen 2012)."""
    name = "rule_trend"

    def predict(self, X):
        return 0.5 + 0.1 * np.sign(X["ret_250"].fillna(0).to_numpy())


class BreakoutRule(Predictor):
    """Donchian channel position: near the 55-day high -> up, near the low -> down."""
    name = "rule_breakout"

    def predict(self, X):
        pos = X["donchian_pos_55"].fillna(0.5).to_numpy()
        return 0.5 + 0.1 * np.clip((pos - 0.5) * 2, -1, 1)


class ReversalRule(Predictor):
    """Short-term reversal (Lehmann 1990): fade the 5-day move."""
    name = "rule_reversal"

    def predict(self, X):
        return 0.5 - 0.1 * np.tanh(X["ret_5"].fillna(0).to_numpy())


class NoView(Predictor):
    """Always 50%. The honest benchmark: Brier exactly 0.25. If no predictor beats it in
    an asset class, the Hedge weights shift here and the account stops trading that class."""
    name = "no_view"

    def predict(self, X):
        return np.full(len(X), 0.5)


class _SkModel(Predictor):
    trainable = True
    min_rows = 500

    def __init__(self):
        self.model = None

    def _clean(self, X):
        return X[FEATURES].astype(float).fillna(0.0).to_numpy()

    def fit(self, X, y):
        if len(X) < self.min_rows or y.nunique() < 2:
            self.model = None
            return
        self.model = self._make()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model.fit(self._clean(X), y.astype(int).to_numpy())

    def predict(self, X):
        if self.model is None:
            return np.full(len(X), 0.5)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.model.predict_proba(self._clean(X))[:, 1]


class Logistic(_SkModel):
    name = "ml_logistic"

    def _make(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=500))


class GradientBoosting(_SkModel):
    """LightGBM with conservative, fixed hyper-parameters (no tuning on our data):
    shallow trees, strong regularisation, as recommended for noisy financial labels."""
    name = "ml_lightgbm"

    def _make(self):
        import lightgbm as lgb
        return lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=8,
                                  min_child_samples=100, subsample=0.7, subsample_freq=1,
                                  colsample_bytree=0.7, reg_lambda=5.0, verbose=-1,
                                  random_state=7, deterministic=True, n_jobs=1)


class LLMAnalyst(Predictor):
    """Claude reading the charts. FORWARD-ONLY: a scheduled run writes
    data/llm/<YYYY-MM-DD>.json = {"made_at": ..., "probs": {symbol: P(up 5 bars)}}
    BEFORE the daily step runs. On dates without such a file it abstains (None),
    so it can never be scored on history it may already know (no look-ahead)."""
    name = "llm_analyst"

    def __init__(self, root=None):
        from pathlib import Path
        self.root = Path(root) if root else Path(__file__).resolve().parents[3] / "data" / "llm"
        self._cache: dict = {}

    def for_date(self, ts) -> dict:
        import json
        key = str(ts)[:10]
        if key not in self._cache:
            p = self.root / f"{key}.json"
            self._cache[key] = json.loads(p.read_text()).get("probs", {}) if p.exists() else {}
        return self._cache[key]

    def predict_symbols(self, ts, symbols) -> list:
        d = self.for_date(ts)
        out = []
        for s in symbols:
            v = d.get(s)
            out.append(min(max(float(v), 0.02), 0.98) if v is not None else None)
        return out

    def predict(self, X):
        raise NotImplementedError("use predict_symbols(ts, symbols)")


def default_predictors() -> list[Predictor]:
    return [NoView(), TrendRule(), BreakoutRule(), ReversalRule(), Logistic(), GradientBoosting(),
            LLMAnalyst()]


def training_set(features: pd.DataFrame, labels: pd.DataFrame, asof: pd.Timestamp,
                 embargo_days: int = 5) -> tuple[pd.DataFrame, pd.Series]:
    """Rows whose outcome was known strictly before `asof - embargo` (purge + embargo)."""
    j = features.join(labels[["up", "known_at"]], how="inner")
    cutoff = asof - pd.Timedelta(days=embargo_days)
    j = j[(j["known_at"].notna()) & (j["known_at"] <= cutoff) & j["up"].notna()]
    j = j.dropna(subset=["ret_250", "vol20"])
    return j[FEATURES], j["up"]
