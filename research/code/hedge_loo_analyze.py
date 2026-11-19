"""Analysis for plan 2026-11-14-hedge-leave-one-out. Reads a frozen prediction ledger only.
Offline, simulation only; never reads live/. Usage: python hedge_loo_analyze.py <scratch_dir>
All parameters are those pre-registered in research/plans/2026-11-14-hedge-leave-one-out.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from atlantis.quant.learn.knowhow import HedgeWeights, PredictionLedger  # noqa: E402

FULL = ["no_view", "rule_trend", "rule_breakout", "rule_reversal", "ml_logistic", "ml_lightgbm", "llm_analyst"]
ARMS = {"full": FULL,
        "drop_rule_trend": [p for p in FULL if p != "rule_trend"],
        "drop_rule_breakout": [p for p in FULL if p != "rule_breakout"],
        "drop_rule_reversal": [p for p in FULL if p != "rule_reversal"],
        "drop_ml_logistic": [p for p in FULL if p != "ml_logistic"],
        "drop_ml_lightgbm": [p for p in FULL if p != "ml_lightgbm"],
        "drop_no_view": [p for p in FULL if p != "no_view"],
        "null_drop_llm_analyst": [p for p in FULL if p != "llm_analyst"]}
PRIMARY = ["drop_rule_trend", "drop_rule_breakout"]
SECONDARY = ["drop_rule_reversal", "drop_ml_logistic", "drop_ml_lightgbm", "drop_no_view"]
MARGIN = 0.0005
BLOCK = 10
RESAMPLES = 10000
SEED = 20261114
MIN_CLASS_ROWS = 500
WINDOWS = {"development": ("2022-01-01", "2023-12-31"), "holdout": ("2024-01-01", "2025-12-31")}
CLASSES = ["fx_spot", "crypto_fx", "stock_cfd", "index_cfd", "commodity_cfd", "metal_cfd"]


def replay(records: list[dict], arms: dict[str, list[str]], track_weights_for: str | None = None):
    """Offline replay in seq order. Returns {arm: {pred_id: p}} and weights of tracked arm per prediction id."""
    hedges = {a: HedgeWeights(list(ps)) for a, ps in arms.items()}
    open_: dict[str, tuple[str, dict]] = {}
    out: dict[str, dict[str, float]] = {a: {} for a in arms}
    wts: dict[str, dict[str, float]] = {}
    for r in records:
        if r["kind"] == "prediction":
            probs = r["predictor_probs"]
            cls = r["asset_class"]
            for a, ps in arms.items():
                out[a][r["id"]] = hedges[a].combine(cls, {k: probs.get(k) for k in ps})
            if track_weights_for:
                wts[r["id"]] = hedges[track_weights_for].weights(cls)
            open_[r["id"]] = (cls, probs)
        elif r["kind"] == "resolution":
            pid = r["prediction_id"]
            if pid not in open_:
                continue
            cls, probs = open_.pop(pid)
            for a, ps in arms.items():
                hedges[a].update(cls, {k: probs.get(k) for k in ps}, float(r["outcome_up"]))
    return out, wts


def build_rows(records: list[dict], arm_p: dict[str, dict[str, float]], wts: dict[str, dict]):
    res = {r["prediction_id"]: r for r in records if r["kind"] == "resolution"}
    preds = [r for r in records if r["kind"] == "prediction"]
    # per-symbol resolved outcomes sorted by resolved_at (ISO strings of UTC compare lexicographically)
    by_sym: dict[str, list[tuple[str, str, float]]] = {}
    for r in preds:
        q = res.get(r["id"])
        if q:
            by_sym.setdefault(r["symbol"], []).append((q["resolved_at"], r["made_at"], float(q["outcome_up"])))
    ras: dict[str, np.ndarray] = {}
    ups: dict[str, np.ndarray] = {}
    for s, lst in by_sym.items():
        lst.sort(key=lambda x: x[0])
        ras[s] = np.array([x[0] for x in lst])
        ups[s] = np.array([x[2] for x in lst])
    rows = []
    for r in preds:
        q = res.get(r["id"])
        if not q or q["resolved_at"][:10] > "2025-12-31":
            continue
        s = r["symbol"]
        n = int(np.searchsorted(ras[s], r["made_at"], side="right")) if s in ras else 0
        if n < 120:
            continue
        b = float(ups[s][max(0, n - 252):n].mean())
        pr = r["predictor_probs"]
        rows.append({"id": r["id"], "date": r["made_at"][:10], "symbol": s, "cls": r["asset_class"],
                     "y": float(q["outcome_up"]), "base": b,
                     "trend": pr.get("rule_trend"), "breakout": pr.get("rule_breakout"),
                     "llm": pr.get("llm_analyst"),
                     "p": {a: arm_p[a][r["id"]] for a in arm_p},
                     "w_tb": wts[r["id"]]["rule_trend"] + wts[r["id"]]["rule_breakout"] if r["id"] in wts else None})
    return rows


def make_blocks(dates: list[str], block: int = BLOCK) -> np.ndarray:
    """Map each row date to a non-overlapping block of `block` consecutive distinct dates."""
    ud = sorted(set(dates))
    pos = {d: i // block for i, d in enumerate(ud)}
    return np.array([pos[d] for d in dates])


def block_bootstrap_idx(blk: np.ndarray, n_resamples=RESAMPLES, seed=SEED):
    """Yields row-index arrays; paired: same seed -> same resamples for every statistic."""
    nb = int(blk.max()) + 1
    order = np.argsort(blk, kind="stable")
    bounds = np.searchsorted(blk[order], np.arange(nb + 1))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, nb, size=(n_resamples, nb))
    return order, bounds, draws


def block_sums(values: np.ndarray, blk: np.ndarray) -> np.ndarray:
    nb = int(blk.max()) + 1
    return np.bincount(blk, weights=values, minlength=nb)


def ci(x: np.ndarray):
    return float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))


def analyse_window(rows: list[dict], arms: list[str]) -> dict:
    n = len(rows)
    y = np.array([r["y"] for r in rows])
    base = np.array([r["base"] for r in rows])
    blk = make_blocks([r["date"] for r in rows])
    cnt = block_sums(np.ones(n), blk)
    se = {a: (np.array([r["p"][a] for r in rows]) - y) ** 2 for a in arms}
    se_base = (base - y) ** 2
    bs = {a: block_sums(se[a], blk) for a in arms}
    bsb = block_sums(se_base, blk)
    order, bounds, draws = block_bootstrap_idx(blk)
    out = {"n_rows": n, "n_dates": len(set(r["date"] for r in rows)), "n_blocks": int(blk.max()) + 1, "arms": {}}
    tot_n = cnt[draws].sum(axis=1)
    for a in arms:
        brier = float(se[a].mean())
        bss = 1 - brier / float(se_base.mean())
        d_pt = float((se[a] - se["full"]).mean())
        dB = bs[a] - bs["full"]
        d_bs = dB[draws].sum(axis=1) / tot_n
        bss_bs = 1 - bs[a][draws].sum(axis=1) / bsb[draws].sum(axis=1)
        out["arms"][a] = {"brier": brier, "brier_base": float(se_base.mean()), "bss": bss, "bss_ci": ci(bss_bs),
                          "delta": d_pt, "delta_ci": ci(d_bs)}
    return out


def spearman_ci(rows: list[dict]) -> dict:
    rr = [r for r in rows if r["trend"] is not None and r["breakout"] is not None]
    a = np.array([r["trend"] for r in rr])
    b = np.array([r["breakout"] for r in rr])
    pt = float(np.corrcoef(rankdata(a), rankdata(b))[0, 1])
    blk = make_blocks([r["date"] for r in rr])
    order, bounds, draws = block_bootstrap_idx(blk)
    vals = np.empty(draws.shape[0])
    for i, d in enumerate(draws):
        idx = np.concatenate([order[bounds[j]:bounds[j + 1]] for j in d])
        x, z = a[idx], b[idx]
        vals[i] = np.corrcoef(rankdata(x), rankdata(z))[0, 1] if x.std() > 0 and z.std() > 0 else np.nan
    return {"rho": pt, "ci": ci(vals[~np.isnan(vals)]), "n": len(rr), "n_nan_resamples": int(np.isnan(vals).sum())}


def per_class(rows: list[dict], arms: list[str]) -> dict:
    out = {}
    for c in CLASSES:
        rc = [r for r in rows if r["cls"] == c]
        out[c] = {"n": len(rc), "qualifies": len(rc) >= MIN_CLASS_ROWS,
                  **{a: (float(np.mean([(r["p"][a] - r["y"]) ** 2 - (r["p"]["full"] - r["y"]) ** 2 for r in rc]))
                         if rc else None) for a in arms}}
    return out


def c4_pass(pc: dict, arm: str) -> tuple[bool, int, int]:
    q = [c for c in CLASSES if pc[c]["qualifies"]]
    k = len(q)
    ok = sum(1 for c in q if pc[c][arm] <= MARGIN)
    if k < 3:
        return False, ok, k
    need = 4 if k == 6 else k
    return ok >= need, ok, k


def verdict(g1: bool, g2: bool, c1: bool, c2: bool, c3: bool, c4: bool, c5: bool) -> str:
    if g1 and g2 and c1 and c2 and c3 and c4 and c5:
        return "PASS"
    if g1 and g2 and c3 and ((not c1) or (not c2) or (c1 and not c4 and not c5)):
        return "FAIL"
    return "INCONCLUSIVE"


def main(scratch: Path) -> None:
    led = scratch / "frozen_ledger.jsonl"
    freeze = json.loads((scratch / "freeze_record.json").read_text())
    import hashlib
    sha = hashlib.sha256(led.read_bytes()).hexdigest()
    assert sha == freeze["sha256"], "ledger changed after freeze"
    pl = PredictionLedger(led)          # verify() runs in the constructor
    recs = pl.records
    arm_p, wts = replay(recs, ARMS, track_weights_for="full")
    # G1 replay check on all predictions
    diffs = np.array([abs(arm_p["full"][r["id"]] - r["p_raw"]) for r in recs if r["kind"] == "prediction"])
    all_rows = build_rows(recs, arm_p, wts)
    llm_none = all(r["llm"] is None for r in all_rows) and all(
        r["predictor_probs"].get("llm_analyst") is None for r in recs if r["kind"] == "prediction")
    win = {w: [r for r in all_rows if lo <= r["date"] <= hi] for w, (lo, hi) in WINDOWS.items()}
    ho, dev = win["holdout"], win["development"]
    g1 = {"hash_chain_verified": True, "sha256_recorded_before_metrics": sha,
          "holdout_rows": len(ho), "holdout_dates": len({r["date"] for r in ho}),
          "holdout_instruments": len({r["symbol"] for r in ho}),
          "replay_mean_abs_diff": float(diffs.mean()), "replay_frac_within_0.002": float((diffs <= 0.002).mean()),
          "llm_none_all_rows": llm_none}
    g1["pass"] = (g1["holdout_rows"] >= 5000 and g1["holdout_dates"] >= 400 and g1["holdout_instruments"] >= 15
                  and g1["replay_mean_abs_diff"] <= 0.0005 and g1["replay_frac_within_0.002"] >= 0.99 and llm_none)
    arm_names = list(ARMS)
    H = analyse_window(ho, arm_names)
    D = analyse_window(dev, arm_names)
    m5 = spearman_ci(ho)
    m6 = float(np.mean([r["w_tb"] for r in ho]))
    pc = per_class(ho, arm_names)
    g2 = m6 >= 0.10
    c1 = all(H["arms"][a]["delta_ci"][1] <= MARGIN for a in PRIMARY)
    c2 = m5["rho"] >= 0.50 and m5["ci"][0] >= 0.40
    c3 = abs(H["arms"]["null_drop_llm_analyst"]["delta"]) <= MARGIN
    c4d = {a: c4_pass(pc, a) for a in PRIMARY}
    c4 = all(v[0] for v in c4d.values())
    c5 = all(D["arms"][a]["delta"] <= MARGIN for a in PRIMARY)
    v = verdict(g1["pass"], g2, c1, c2, c3, c4, c5)
    drop = {a: bool(H["arms"][a]["delta_ci"][1] < 0 and D["arms"][a]["delta"] < 0) for a in PRIMARY}
    res = {"verdict": v, "G1": g1, "G2": {"M6": m6, "pass": g2}, "C1": c1, "C2": c2, "C3": c3,
           "C4": c4, "C4_detail": {a: {"ok": o, "qualifying": k, "pass": p} for a, (p, o, k) in c4d.items()},
           "C5": c5, "M5": m5, "holdout": H, "development": D,
           "M7_per_class_delta": pc, "drop_candidate": drop,
           "full_bss_ci_includes_zero": H["arms"]["full"]["bss_ci"][0] <= 0 <= H["arms"]["full"]["bss_ci"][1]}
    (scratch / "metrics.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("verdict", "G1", "G2", "C1", "C2", "C3", "C4", "C5")}, indent=1, default=str))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
