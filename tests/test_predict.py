"""Prediction engine: causality, purge, ledger integrity, learning behaviour."""
import numpy as np
import pandas as pd
import pytest

from atlantis.engine import build_panels
from atlantis.quant.learn.knowhow import Calibrator, HedgeWeights, PredictionLedger
from atlantis.quant.predict.features import FEATURES, build_features, forward_labels
from atlantis.quant.predict.models import training_set


def test_features_are_causal(fx_data):
    p = build_panels(fx_data)
    full = build_features(p)
    for d in p["mid_close"].index[[300, 420, 599]]:
        trunc = {k: v.loc[:d] for k, v in p.items()}
        part = build_features(trunc).xs(d, level="ts")[FEATURES]
        np.testing.assert_allclose(part.to_numpy(), full.xs(d, level="ts")[FEATURES].to_numpy(),
                                   rtol=1e-9, equal_nan=True)


def test_training_set_excludes_unknown_outcomes(fx_data):
    p = build_panels(fx_data)
    f, lab = build_features(p), forward_labels(p, 5)
    asof = p["mid_close"].index[450]
    X, y = training_set(f, lab, asof, embargo_days=5)
    known = lab.loc[X.index, "known_at"]
    assert (known <= asof - pd.Timedelta(days=5)).all()
    assert X.index.get_level_values("ts").max() < asof


def test_prediction_ledger_detects_tampering(tmp_path):
    path = tmp_path / "ledger.jsonl"
    L = PredictionLedger(path)
    L.append({"kind": "prediction", "id": "a", "p_final": 0.6})
    L.append({"kind": "resolution", "prediction_id": "a", "outcome_up": 1.0})
    PredictionLedger(path)                       # reloads and verifies fine
    lines = path.read_text().splitlines()
    lines[0] = lines[0].replace("0.6", "0.9")    # rewrite history
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(RuntimeError, match="tampered"):
        PredictionLedger(path)


def test_hedge_learns_to_trust_the_accurate_predictor():
    rng = np.random.default_rng(0)
    h = HedgeWeights(["good", "noise", "bad"], horizon_T=300)
    for _ in range(300):
        y = float(rng.random() < 0.5)
        h.update("fx", {"good": 0.8 if y else 0.2, "noise": rng.random(), "bad": 0.2 if y else 0.8}, y)
    w = h.weights("fx")
    assert w["good"] > 0.9 and w["bad"] < 0.01


def test_calibrator_fixes_overconfident_probabilities():
    rng = np.random.default_rng(1)
    p = rng.uniform(0.3, 0.7, 4000)
    y = (rng.random(4000) < 0.5 + (p - 0.5) * 0.3).astype(float)     # true edge is 30% of stated
    c = Calibrator()
    c.fit(p, y)
    assert abs(c(0.7) - (0.5 + 0.2 * 0.3)) < 0.05
    c2 = Calibrator()
    c2.fit(p[:50], y[:50])                                            # too few -> shrink halfway
    assert c2(0.7) == pytest.approx(0.6)


def test_adaptive_account_end_to_end(fx_data, tmp_path):
    from atlantis.adaptive import run_adaptive
    from atlantis.checks.reconcile import reconcile
    from atlantis.engine import BacktestResult
    res = run_adaptive(fx_data, capital=20_000.0, start="2020-12-01", ledger_path=tmp_path / "l.jsonl")
    preds, resol = res.ledger.predictions(), res.ledger.resolutions()
    assert len(preds) > 100 and len(resol) > 50
    # every resolution happens at or after its outcome date, never before
    by_id = {p["id"]: p for p in preds}
    for pid, r in resol.items():
        assert r["resolved_at"] >= by_id[pid]["made_at"]
    PredictionLedger(tmp_path / "l.jsonl")          # chain verifies
    br = BacktestResult(res.equity, None, res.broker, None, res.broker.audit, {}, None, None)
    assert reconcile(br) == []
    res.broker.ledger.check_invariants()
    assert set(res.hedge.cum_loss) == {"fx_spot"}
    assert abs(sum(res.hedge.weights("fx_spot").values()) - 1) < 1e-9
