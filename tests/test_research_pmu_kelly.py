"""Tests for the research code of plan 2026-11-21-pmu-kelly-calibration (offline, synthetic data only)."""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "code"))
import pmu_kelly_analyze as A  # noqa: E402


def _recs(n=40, seed=0):
    rng = np.random.default_rng(seed)
    recs = []
    for i in range(n):
        pid = f"p{i}"
        recs.append({"kind": "prediction", "id": pid, "made_at": f"2024-01-{i % 28 + 1:02d}T00:00:00+00:00",
                     "symbol": "X", "asset_class": "fx_spot", "p_final": float(rng.uniform(0.4, 0.6)),
                     "p_raw": 0.5})
        recs.append({"kind": "resolution", "prediction_id": pid, "fwd_log_return": float(rng.normal(0, 0.02))})
    return recs


def test_slope0_golden():
    x = np.array([1.0, 2.0, 3.0])
    assert abs(A.slope0(x, 2 * x) - 2.0) < 1e-12
    assert abs(A.slope0(x, np.array([1.0, 0.0, 1.0])) - (1 + 0 + 3) / 14) < 1e-12


def test_slope1_golden_and_intercept_invariance():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert abs(A.slope1(x, 3 * x + 5) - 3.0) < 1e-12
    assert abs(A.slope0(x, 3 * x) - 3.0) < 1e-12 and abs(A.slope0(x, 3 * x + 5) - 3.0) > 0.1


def test_x_y_golden():
    rows = [{"p_final": 0.6, "p_raw": 0.5, "r": 0.04, "vol20": 0.01}]
    x, y = A.xy_of(rows, "p_final")
    assert abs(x[0] - 0.2 * math.sqrt(2 / math.pi)) < 1e-12
    assert abs(y[0] - 0.04 / (0.01 * math.sqrt(5))) < 1e-12
    xr, _ = A.xy_of(rows, "p_raw")
    assert xr[0] == 0.0


def test_blocks_golden():
    dates = [f"2024-01-{d:02d}" for d in range(1, 26) for _ in range(2)]
    blk = A.make_blocks(dates)
    assert blk.max() == 2 and list(np.bincount(blk)) == [20, 20, 10]


def test_bootstrap_deterministic_and_shape():
    assert (A.draws_for(5, 50) == A.draws_for(5, 50)).all()
    assert A.draws_for(5, 50).shape == (50, 5)
    assert A.SEED == 20261121 and A.RESAMPLES == 10000 and A.BLOCK == 10


def test_boot_slopes_recovers_known_slope():
    rng = np.random.default_rng(1)
    n = 600
    dates = [f"2024-{1 + i // 280:02d}-{i % 28 + 1:02d}" for i in range(n)]
    x = rng.normal(0, 0.1, n)
    y = 1.0 * x + rng.normal(0, 0.5, n)
    blk = A.make_blocks(dates)
    b0, b1 = A.boot_slopes(x, y, blk, A.draws_for(int(blk.max()) + 1, 2000))
    lo, hi = A.ci(b0)
    assert lo < A.slope0(x, y) < hi
    assert abs(np.nanmedian(b1) - A.slope1(x, y)) < 0.3


def test_dollar_neutral_drops_small_dates_and_removes_common_factor():
    dates = ["a"] * 5 + ["b"] * 3
    x = np.arange(8, dtype=float)
    y = x + np.array([10.0] * 5 + [99.0] * 3)          # common per-date shifts
    xd, yd, keep = A.dollar_neutral(x, y, dates)
    assert keep.tolist() == [True] * 5 + [False] * 3
    assert abs(xd[:5].mean()) < 1e-12 and np.allclose(xd[:5], yd[:5])


def test_causality_truncation_of_rows():
    recs = _recs()
    vol = {(r["made_at"][:10], "X"): 0.01 for r in recs if r["kind"] == "prediction"}
    full, _ = A.build_rows(recs, vol, {})
    part, _ = A.build_rows(recs[:40], vol, {})
    assert full[:len(part)] == part               # later records never alter earlier rows


def test_build_rows_exclusions():
    recs = _recs(3)
    recs.append({"kind": "prediction", "id": "u", "made_at": "2025-12-30T00:00:00+00:00", "symbol": "X",
                 "asset_class": "fx_spot", "p_final": 0.5, "p_raw": 0.5})          # unresolved
    vol = {(r["made_at"][:10], "X"): 0.01 for r in recs if r["kind"] == "prediction"}
    vol[("2024-01-02", "X")] = 0.0                                                     # zero vol dropped
    rows, drop = A.build_rows(recs, vol, {})
    assert drop["unresolved"] == 1 and drop["no_vol"] == 1 and len(rows) == 2


def test_verdict_order_and_rules():
    t = dict(g1=True, g2=True, c1=True, c2=True, c3=True, c4=True, c5=True, too_wide=False)
    assert A.verdict(**t) == "PASS"
    assert A.verdict(**{**t, "g1": False}) == "INCONCLUSIVE"
    assert A.verdict(**{**t, "g2": False}) == "INCONCLUSIVE"
    assert A.verdict(**{**t, "too_wide": True}) == "INCONCLUSIVE"
    for k in ("c1", "c2", "c3", "c4", "c5"):
        assert A.verdict(**{**t, k: False}) == "FAIL"


def test_kelly_and_sign_edges():
    assert A.kelly_implied(0.8) == 0.4 and A.kelly_implied(-1) == 0.0
    assert A.sgn(0.0) == 0 and A.sgn(-2.0) == -1
    assert math.isnan(A.slope0(np.zeros(3), np.ones(3)))


def test_no_forbidden_imports():
    code = (Path(A.__file__)).read_text()
    imports = [ln for ln in code.splitlines() if ln.startswith(("import ", "from "))]
    assert not any("atlantis.live" in ln or "gate" in ln or "broker" in ln for ln in imports)
