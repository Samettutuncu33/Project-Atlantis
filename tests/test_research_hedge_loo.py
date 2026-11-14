"""Tests for the research code of plan 2026-11-14-hedge-leave-one-out (offline, synthetic data only)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "code"))
import hedge_loo_analyze as A  # noqa: E402


def _ledger(n=60, seed=0):
    rng = np.random.default_rng(seed)
    recs = []
    for i in range(n):
        pid = f"d{i:03d}:X"
        pr = {k: (None if k == "llm_analyst" else float(np.round(rng.uniform(0.3, 0.7), 5))) for k in A.FULL}
        recs.append({"kind": "prediction", "id": pid, "made_at": f"2024-01-{i % 28 + 1:02d}T00:00:00+00:00",
                     "symbol": "X", "asset_class": "fx_spot", "predictor_probs": pr, "p_raw": 0.5})
        if i >= 5:   # resolve prediction i-5 (5-bar lag): causal, outcome known after the fact
            recs.append({"kind": "resolution", "prediction_id": f"d{i - 5:03d}:X", "resolved_at": "x",
                         "outcome_up": float(rng.integers(0, 2))})
    return recs


def test_replay_causal_truncation():
    recs = _ledger()
    full, _ = A.replay(recs, A.ARMS)
    cut = 40
    part, _ = A.replay(recs[:cut], A.ARMS)
    for a in A.ARMS:
        for k, v in part[a].items():
            assert full[a][k] == v          # later data never changes earlier probabilities


def test_replay_first_prediction_golden():
    recs = _ledger(3)
    out, w = A.replay(recs, {"full": A.FULL}, "full")
    pr = recs[0]["predictor_probs"]
    exp = np.mean([pr[k] for k in A.FULL if k != "llm_analyst"])   # equal weights over awake predictors
    assert abs(out["full"][recs[0]["id"]] - exp) < 1e-12
    assert abs(sum(w[recs[0]["id"]].values()) - 1) < 1e-12


def test_blocks_golden():
    dates = [f"2024-01-{d:02d}" for d in range(1, 26) for _ in range(2)]
    blk = A.make_blocks(dates)
    assert blk.max() == 2 and list(np.bincount(blk)) == [20, 20, 10]


def test_bootstrap_deterministic_and_paired():
    blk = A.make_blocks([f"2024-01-{d:02d}" for d in range(1, 31)])
    _, _, d1 = A.block_bootstrap_idx(blk, 50)
    _, _, d2 = A.block_bootstrap_idx(blk, 50)
    assert (d1 == d2).all()


def test_delta_zero_for_identical_arm():
    recs = _ledger(200)
    arms = {"full": A.FULL, "same": list(A.FULL)}
    out, w = A.replay(recs, arms, "full")
    for r in recs:
        if r["kind"] == "prediction":
            assert out["full"][r["id"]] == out["same"][r["id"]]


def test_verdict_logic():
    assert A.verdict(True, True, True, True, True, True, True) == "PASS"
    assert A.verdict(False, True, True, True, True, True, True) == "INCONCLUSIVE"
    assert A.verdict(True, False, False, True, True, True, True) == "INCONCLUSIVE"
    assert A.verdict(True, True, False, True, True, True, True) == "FAIL"
    assert A.verdict(True, True, True, False, True, True, True) == "FAIL"
    assert A.verdict(True, True, True, True, False, True, True) == "INCONCLUSIVE"
    assert A.verdict(True, True, True, True, True, False, False) == "FAIL"
    assert A.verdict(True, True, True, True, True, False, True) == "INCONCLUSIVE"


def test_c4_edge_cases():
    pc = {c: {"n": 600, "qualifies": True, "a": 0.0} for c in A.CLASSES}
    assert A.c4_pass(pc, "a")[0]
    for c in A.CLASSES[:3]:
        pc[c]["a"] = 0.01
    assert not A.c4_pass(pc, "a")[0]            # 3 of 6 within margin < 4
    for c in A.CLASSES[3:]:
        pc[c]["qualifies"] = False
    assert not A.c4_pass(pc, "a")[0]            # all qualifying must pass when <6 qualify


def test_no_forbidden_imports():
    code = (Path(A.__file__).parent / "hedge_loo_analyze.py").read_text()
    imports = [ln for ln in code.splitlines() if ln.startswith(("import ", "from "))]
    assert not any("atlantis.live" in ln or "gate" in ln or "broker" in ln for ln in imports)
