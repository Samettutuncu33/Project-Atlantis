"""Analysis for plan 2026-11-21-pmu-kelly-calibration (simulation only, offline).

Usage: python pmu_kelly_analyze.py <scratch_dir> gates     # G1/G2 only, no slope is computed
       python pmu_kelly_analyze.py <scratch_dir> metrics   # slopes, CIs, verdict (requires gates stage output)
All parameters are those pre-registered in research/plans/2026-11-21-pmu-kelly-calibration.md.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SQ = math.sqrt(2 / math.pi)
HORIZON = 5
BLOCK = 10
RESAMPLES = 10000
SEED = 20261121
W_MAX = 0.75
MIN_CLASS_ROWS = 300
WINDOWS = {"development": ("2022-01-01", "2023-12-31"), "holdout": ("2024-01-01", "2025-12-31")}
CLASSES = ["fx_spot", "crypto_fx", "stock_cfd", "index_cfd", "commodity_cfd", "metal_cfd"]


# ---------------------------------------------------------------- pure statistics
def make_blocks(dates: list[str], block: int = BLOCK) -> np.ndarray:
    ud = sorted(set(dates))
    pos = {d: i // block for i, d in enumerate(ud)}
    return np.array([pos[d] for d in dates])


def draws_for(nb: int, n_resamples: int = RESAMPLES, seed: int = SEED) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, nb, size=(n_resamples, nb))


def block_sums(v: np.ndarray, blk: np.ndarray, nb: int) -> np.ndarray:
    return np.bincount(blk, weights=v, minlength=nb)


def ci(v: np.ndarray) -> tuple[float, float]:
    v = v[~np.isnan(v)]
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def slope0(x: np.ndarray, y: np.ndarray) -> float:
    d = float((x * x).sum())
    return float((x * y).sum() / d) if d > 0 else float("nan")


def slope1(x: np.ndarray, y: np.ndarray) -> float:
    xc = x - x.mean()
    d = float((xc * xc).sum())
    return float((xc * (y - y.mean())).sum() / d) if d > 0 else float("nan")


def boot_slopes(x, y, blk, draws):
    """Paired block bootstrap of b0 (through origin) and b1 (with intercept)."""
    nb = int(blk.max()) + 1
    n = block_sums(np.ones(len(x)), blk, nb)
    sx, sy = block_sums(x, blk, nb), block_sums(y, blk, nb)
    sxy, sxx = block_sums(x * y, blk, nb), block_sums(x * x, blk, nb)
    with np.errstate(divide="ignore", invalid="ignore"):
        b0 = sxy[draws].sum(1) / sxx[draws].sum(1)
        N, X, Y = n[draws].sum(1), sx[draws].sum(1), sy[draws].sum(1)
        XY, XX = sxy[draws].sum(1), sxx[draws].sum(1)
        b1 = (XY - X * Y / N) / (XX - X * X / N)
    return b0, b1


def dollar_neutral(x, y, dates, min_syms=5):
    """Per-date demeaning; dates with < min_syms symbols dropped. Returns (x, y, keep_mask)."""
    dates = np.asarray(dates)
    keep = np.zeros(len(x), bool)
    xo, yo = np.zeros(len(x)), np.zeros(len(x))
    for d in np.unique(dates):
        m = dates == d
        if m.sum() < min_syms:
            continue
        keep |= m
        xo[m] = x[m] - x[m].mean()
        yo[m] = y[m] - y[m].mean()
    return xo, yo, keep


def sgn(v: float) -> int:
    return (v > 0) - (v < 0)


def verdict(g1: bool, g2: bool, c1: bool, c2: bool, c3: bool, c4: bool, c5: bool, too_wide: bool) -> str:
    if not g1 or not g2:
        return "INCONCLUSIVE"
    if too_wide:
        return "INCONCLUSIVE"
    if c1 and c2 and c3 and c4 and c5:
        return "PASS"
    return "FAIL"


def kelly_implied(b: float) -> float:
    return 0.5 * max(b, 0.0)


# ---------------------------------------------------------------- data
def build_rows(recs: list[dict], vol20: dict, fwd: dict) -> tuple[list[dict], dict]:
    res = {r["prediction_id"]: r for r in recs if r["kind"] == "resolution"}
    rows, drop = [], {"unresolved": 0, "no_vol": 0}
    for r in recs:
        if r["kind"] != "prediction":
            continue
        q = res.get(r["id"])
        if q is None:
            drop["unresolved"] += 1
            continue
        d = r["made_at"][:10]
        v = vol20.get((d, r["symbol"]))
        if v is None or not (v > 0) or math.isnan(v):
            drop["no_vol"] += 1
            continue
        rows.append({"date": d, "symbol": r["symbol"], "cls": r["asset_class"], "p_final": r["p_final"],
                     "p_raw": r["p_raw"], "r": float(q["fwd_log_return"]), "r_re": fwd.get((d, r["symbol"])),
                     "vol20": v})
    return rows, drop


def xy_of(rows: list[dict], pkey: str):
    p = np.array([r[pkey] for r in rows])
    sh = np.array([r["vol20"] for r in rows]) * math.sqrt(HORIZON)
    return (2 * p - 1) * SQ, np.array([r["r"] for r in rows]) / sh


def recompute_from_cache():
    """vol20 and fwd_log_return recomputed from cached daily files (<= 2025), no network."""
    import pandas as pd
    import pmu_kelly_generate as G
    from atlantis.engine import build_panels
    from atlantis.instruments.spec import universe
    from atlantis.quant.predict.features import build_features
    f = G.Fetcher(G.RAW)
    f.s = G._NoNet()
    data = {}
    for s in universe()["instruments"]:
        d = G.load_daily(f, s)
        if d is not None and len(d):
            data[s] = d
    panels = build_panels(data)
    feats = build_features(panels)
    vol = {(t.strftime("%Y-%m-%d"), s): float(v) for (t, s), v in feats["vol20"].items() if not pd.isna(v)}
    mid = panels["mid_close"]
    fwd = {}
    for s in mid.columns:
        m = mid[s].dropna()
        lv = np.log(m.to_numpy())
        for i in range(len(m) - HORIZON):
            fwd[(m.index[i].strftime("%Y-%m-%d"), s)] = float(lv[i + HORIZON] - lv[i])
    return vol, fwd


def load_rows(scratch: Path):
    from atlantis.quant.learn.knowhow import PredictionLedger
    led = scratch / "frozen_ledger.jsonl"
    freeze = json.loads((scratch / "freeze_record.json").read_text())
    sha = hashlib.sha256(led.read_bytes()).hexdigest()
    assert sha == freeze["sha256"], "ledger changed after freeze"
    recs = PredictionLedger(led).records          # verify() in constructor
    vol, fwd = recompute_from_cache()
    rows, drop = build_rows(recs, vol, fwd)
    return recs, rows, drop, sha, freeze


def window(rows, w):
    lo, hi = WINDOWS[w]
    return [r for r in rows if lo <= r["date"] <= hi]


# ---------------------------------------------------------------- stages
def stage_gates(scratch: Path) -> None:
    recs, rows, drop, sha, freeze = load_rows(scratch)
    ho = window(rows, "holdout")
    x, _ = xy_of(ho, "p_final")
    diffs = [abs(r["r"] - r["r_re"]) for r in rows if r["r_re"] is not None]
    miss = sum(1 for r in rows if r["r_re"] is None)
    g = {"sha256": sha, "git_commit_at_freeze": freeze["git_commit"], "hash_chain_verified": True,
         "n_records": len(recs), "rows_total": len(rows), "dropped": drop,
         "holdout_rows": len(ho), "holdout_dates": len({r["date"] for r in ho}),
         "holdout_symbols": len({r["symbol"] for r in ho}),
         "ret_recompute_max_abs_diff": max(diffs) if diffs else None, "ret_recompute_missing": miss,
         "mean_abs_x": float(np.abs(x).mean()), "rms_x": float(np.sqrt((x * x).mean()))}
    g["G1_parts"] = {"rows>=8000": g["holdout_rows"] >= 8000, "dates>=450": g["holdout_dates"] >= 450,
                     "symbols>=18": g["holdout_symbols"] >= 18, "hash_chain": True,
                     "ret_recompute<=1e-9": bool(diffs) and miss == 0 and g["ret_recompute_max_abs_diff"] <= 1e-9}
    g["G2_parts"] = {"mean|x|>=0.04": g["mean_abs_x"] >= 0.04, "rms>=0.05": g["rms_x"] >= 0.05}
    (scratch / "gates.json").write_text(json.dumps(g, indent=1))
    print(json.dumps(g, indent=1))


def window_stats(rows, draws_cache=None):
    out = {}
    blk = make_blocks([r["date"] for r in rows])
    nb = int(blk.max()) + 1
    draws = draws_for(nb)
    dates = [r["date"] for r in rows]
    for key in ("p_final", "p_raw"):
        x, y = xy_of(rows, key)
        b0, b1 = boot_slopes(x, y, blk, draws)
        yc = np.clip(y, -5, 5)
        b0c, _ = boot_slopes(x, yc, blk, draws)
        xd, yd, keep = dollar_neutral(x, y, dates)
        # dollar-neutral bootstrap uses the same blocks/draws; dropped dates contribute zero sums
        xd2, yd2 = np.where(keep, xd, 0.0), np.where(keep, yd, 0.0)
        bd, _ = boot_slopes(xd2, yd2, blk, draws)
        out[key] = {"b0": slope0(x, y), "b0_ci": ci(b0), "b1": slope1(x, y), "b1_ci": ci(b1),
                    "b0_clip5": slope0(x, yc), "b0_clip5_ci": ci(b0c),
                    "b0_dollar_neutral": slope0(xd[keep], yd[keep]), "b0_dn_ci": ci(bd),
                    "dn_rows": int(keep.sum()), "mean_abs_x": float(np.abs(x).mean()),
                    "rms_x": float(np.sqrt((x * x).mean()))}
    out["n_rows"], out["n_dates"] = len(rows), len(set(dates))
    out["n_symbols"], out["n_blocks"] = len({r["symbol"] for r in rows}), nb
    return out


def stage_metrics(scratch: Path) -> None:
    g = json.loads((scratch / "gates.json").read_text())      # gates stage must have run first
    recs, rows, drop, sha, freeze = load_rows(scratch)
    assert sha == g["sha256"]
    g1 = all(g["G1_parts"].values())
    g2 = all(g["G2_parts"].values())
    ho, dev = window(rows, "holdout"), window(rows, "development")
    H, D = window_stats(ho), window_stats(dev)
    p = H["p_final"]
    b0, (lo, hi) = p["b0"], p["b0_ci"]
    pc = {}
    for c in CLASSES:
        rc = [r for r in ho if r["cls"] == c]
        if rc:
            x, y = xy_of(rc, "p_final")
            pc[c] = {"n": len(rc), "b0": slope0(x, y)}
        else:
            pc[c] = {"n": 0, "b0": None}
    n_pos = sum(1 for c in CLASSES if pc[c]["n"] >= MIN_CLASS_ROWS and pc[c]["b0"] is not None and pc[c]["b0"] > 0)
    c1 = b0 > 0 and lo > 0
    c2 = lo <= 1 <= hi
    c3 = b0 >= 0.5
    c4 = n_pos >= 4
    bdev = D["p_final"]["b0"]
    c5 = sgn(bdev) != 0 and sgn(bdev) == sgn(b0)
    too_wide = (hi - lo) > W_MAX and lo <= 0.5 <= hi
    v = verdict(g1, g2, c1, c2, c3, c4, c5, too_wide)
    dn = p["b0_dollar_neutral"]
    flagged = sgn(dn) != 0 and sgn(b0) != 0 and sgn(dn) != sgn(b0)
    res = {"verdict": v, "UNRELIABLE_FLAGGED": bool(flagged), "G1": g1, "G2": g2,
           "C1": c1, "C2": c2, "C3": c3, "C4": c4, "C4_n_pos": n_pos, "C5": c5, "too_wide": bool(too_wide),
           "ci_width": hi - lo, "C6_kelly": {"point": kelly_implied(b0), "lo": kelly_implied(lo),
                                              "hi": kelly_implied(hi)},
           "per_class": pc, "holdout": H, "development": D, "gates": g}
    (scratch / "metrics.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("verdict", "UNRELIABLE_FLAGGED", "G1", "G2", "C1", "C2", "C3", "C4",
                                          "C4_n_pos", "C5", "too_wide", "ci_width", "C6_kelly")}, indent=1))
    print(json.dumps({"holdout_p_final": H["p_final"], "dev_p_final": D["p_final"]}, indent=1))


if __name__ == "__main__":
    {"gates": stage_gates, "metrics": stage_metrics}[sys.argv[2]](Path(sys.argv[1]))
