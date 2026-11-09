"""Learning from scored predictions: the platform's "know-how".

  * PredictionLedger: append-only, hash-chained record of every prediction,
    written BEFORE its outcome exists. Outcomes are appended as separate
    resolution records, so nothing written earlier can be changed undetected.
  * HedgeWeights: exponential weights over predictors, kept separately per
    asset class (Freund & Schapire 1997; Cesa-Bianchi & Lugosi 2006). The
    learning rate eta = sqrt(8 ln N / T) is the textbook regret-optimal choice
    for horizon T, not a tuned value. Loss is the Brier score in [0, 1].
  * Calibration: the ensemble probability is passed through Platt scaling (a
    2-parameter logistic fit on the log-odds) fitted on resolved predictions only.
    Isotonic regression was tried first and rejected: it overfits the extremes
    at the sample sizes we will have (Niculescu-Mizil & Caruana 2005). With fewer
    than 200 resolved predictions the raw probability is shrunk halfway to 0.5.
  * Lessons: plain-language statements generated from the scores.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


def brier(p: float, outcome: float) -> float:
    return (p - outcome) ** 2


class PredictionLedger:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self.records: list[dict] = []
        if self.path and self.path.exists():
            self.records = [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]
            self.verify()

    def _hash(self, rec: dict) -> str:
        body = {k: v for k, v in rec.items() if k != "hash"}
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

    def append(self, rec: dict) -> dict:
        rec = dict(rec, seq=len(self.records),
                   prev_hash=self.records[-1]["hash"] if self.records else "genesis")
        rec["hash"] = self._hash(rec)
        self.records.append(rec)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        return rec

    def verify(self) -> None:
        prev = "genesis"
        for i, r in enumerate(self.records):
            if r["seq"] != i or r["prev_hash"] != prev or r["hash"] != self._hash(r):
                raise RuntimeError(f"prediction ledger tampered or corrupt at record {i}")
            prev = r["hash"]

    def predictions(self) -> list[dict]:
        return [r for r in self.records if r["kind"] == "prediction"]

    def resolutions(self) -> dict[str, dict]:
        return {r["prediction_id"]: r for r in self.records if r["kind"] == "resolution"}


@dataclass
class HedgeWeights:
    predictors: list[str]
    horizon_T: int = 500
    cum_loss: dict[str, dict[str, float]] = field(default_factory=dict)   # class -> predictor -> loss
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    hits: dict[str, dict[str, int]] = field(default_factory=dict)
    directional: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def eta(self) -> float:
        return math.sqrt(8 * math.log(len(self.predictors)) / self.horizon_T)

    def weights(self, cls: str) -> dict[str, float]:
        L = self.cum_loss.get(cls, {})
        m = min((L.get(p, 0.0) for p in self.predictors), default=0.0)
        raw = {p: math.exp(-self.eta * (L.get(p, 0.0) - m)) for p in self.predictors}
        z = sum(raw.values())
        return {p: v / z for p, v in raw.items()}

    def update(self, cls: str, probs: dict[str, float | None], outcome: float) -> None:
        """Predictors that abstained (None) are neither rewarded nor penalised."""
        probs = {k: v for k, v in probs.items() if v is not None}
        for d in (self.cum_loss, self.counts, self.hits, self.directional):
            d.setdefault(cls, {})
        for p, prob in probs.items():
            self.cum_loss[cls][p] = self.cum_loss[cls].get(p, 0.0) + brier(prob, outcome)
            self.counts[cls][p] = self.counts[cls].get(p, 0) + 1
            if prob != 0.5:
                self.directional[cls][p] = self.directional[cls].get(p, 0) + 1
                self.hits[cls][p] = self.hits[cls].get(p, 0) + int((prob > 0.5) == (outcome > 0.5))

    def combine(self, cls: str, probs: dict[str, float | None]) -> float:
        w = self.weights(cls)
        avail = [p for p in self.predictors if probs.get(p) is not None]
        z = sum(w[p] for p in avail)
        return float(sum(w[p] * probs[p] for p in avail) / z) if z > 0 else 0.5

    def to_dict(self) -> dict:
        return {"predictors": self.predictors, "eta": self.eta, "cum_loss": self.cum_loss,
                "counts": self.counts, "hits": self.hits, "directional": self.directional,
                "weights": {c: self.weights(c) for c in self.cum_loss}}


class Calibrator:
    MIN = 200

    def __init__(self):
        self.iso = None
        self.n = 0

    def fit(self, p: np.ndarray, y: np.ndarray) -> None:
        self.n = len(p)
        if self.n < self.MIN:
            self.iso = None
            return
        from sklearn.linear_model import LogisticRegression
        x = np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4))).reshape(-1, 1)
        self.iso = LogisticRegression(C=1e6).fit(x, y.astype(int))

    def __call__(self, p: float) -> float:
        if self.iso is None:
            return 0.5 + 0.5 * (p - 0.5)
        q = min(max(p, 1e-4), 1 - 1e-4)
        return float(self.iso.predict_proba([[math.log(q / (1 - q))]])[0, 1])


def lessons(h: HedgeWeights, class_names: dict[str, str]) -> list[str]:
    out = []
    for cls, counts in h.counts.items():
        w = h.weights(cls)
        best = max(w, key=w.get)
        for p in sorted(counts):
            hits = h.hits.get(cls, {}).get(p, 0)
            dn = h.directional.get(cls, {}).get(p, 0)
            rate = f"{hits / dn:.0%}" if dn else "n/a"
            out.append(f"{class_names.get(cls, cls)} · {p}: {hits}/{dn} directional calls correct "
                       f"({rate}), Brier {h.cum_loss[cls][p] / counts[p]:.4f}, weight {w[p]:.0%}")
        out.append(f"{class_names.get(cls, cls)}: currently trusts {best} most ({w[best]:.0%}).")
    return out
