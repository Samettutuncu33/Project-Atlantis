FAIL

# Result: Hedge leave-one-predictor-out (plan 2026-11-14-hedge-leave-one-out)

Run exactly as pre-registered; no criterion, window, margin, block length or seed was changed. Simulation only; nothing under
live/, data/llm, knowledge/journal.md or the network was read. Overall verdict: **FAIL** (G1, G2, C3 hold; C1 fails and C2 fails).

## Freeze record (recorded before any metric was computed)
- Ledger SHA256: 092a3b4c63bb82a05b773559243077b695203e2c7608a6f32766907205062686 (91,722 records; hash chain verified)
- Git commit at generation: 072469fcd6f0eb023e5237b630cebd2e63d21d60
- Generation: atlantis.adaptive.run_adaptive (unmodified), cached daily bid/ask files years <= 2025 only, 25 universe instruments loaded,
  trade_from 2099, empty llm_root, horizon 5. Code: research/code/hedge_loo_generate.py. Re-generation into a second scratch dir gave the
  identical SHA256 (deterministic). Reconcile: 0 breaks, 0 orders, equity constant 200.0 (trading disabled).
- Analysis code: research/code/hedge_loo_analyze.py. Metrics file: scratchpad/metrics.json.

## Gates
- G1 PASS: holdout scored rows 10,240 (>=5000), dates 518 (>=400), instruments 20 (>=15); full-arm replay vs ledger p_raw mean abs diff 2.6e-6
  (<=0.0005), 100% of rows within 0.002; llm_analyst None on 100% of rows; hash chain verified, SHA recorded first.
  (5 of 25 instruments have no holdout rows because they lack 120 resolved outcomes by 2024 under the base-rate rule.)
- G2 PASS: M6 mean Hedge weight of rule_trend + rule_breakout in full arm on holdout = 0.1565 (>= 0.10).

## Criteria (holdout 2024-2025, 10-date block bootstrap, 10,000 resamples, seed 20261114)
Delta = Brier(arm) - Brier(full); full holdout Brier 0.24672.
- C1 FAIL: drop rule_trend delta +0.000229, 95% CI [-0.000066, +0.000521], upper bound 0.000521 > 0.0005 (fails by 0.000021).
  drop rule_breakout delta -0.000283, CI [-0.000932, +0.000396], upper 0.000396 <= 0.0005 (passes). Both must pass, so C1 fails.
  Caveat from the plan: the CIs are wide relative to the 0.0005 margin, so this is a "cannot distinguish" situation for rule_trend, narrowly missed.
- C2 FAIL: Spearman(rule_trend, rule_breakout) = 0.362, 95% CI [0.313, 0.410] (n=10,240); needs point >= 0.50 and lower >= 0.40.
- C3 PASS: null-control (drop llm_analyst) delta -0.000004 (|.| <= 0.0005).
- C4 PASS: drop rule_trend within margin in 5 of 6 classes, drop rule_breakout in 6 of 6 (all 6 classes have >= 500 rows).
  The one class over margin for the trend arm is index_cfd (+0.000753); metal_cfd is +0.000493 (within margin).
- C5 PASS: development delta drop rule_trend -0.000374, drop rule_breakout +0.000114 (both <= 0.0005).
- C6 (reported, not gated): holdout BSS vs trailing-252 base rate: full 0.0031 [-0.0098, 0.0153]; drop trend 0.0022; drop breakout 0.0043.
  The full-ensemble BSS CI includes 0: redundancy was tested on an ensemble with no demonstrated skill.
- Drop recommendation: no DROP_candidate (neither upper CI bound < 0). No change to the ensemble is recommended.

## Secondary arms (exploratory, descriptive, no verdict; 4 extra comparisons)
Holdout delta [95% CI]: drop rule_reversal +0.000005 [-0.000267, +0.000282]; drop ml_logistic +0.000438 [+0.000089, +0.000777];
drop ml_lightgbm +0.000427 [+0.000011, +0.000849]; drop no_view -0.000348 [-0.001000, +0.000304].

## Reading
H1 is not supported as pre-registered: the two predictors are only moderately correlated (0.36, well under the 0.50 bar), and dropping
rule_trend misses non-inferiority by a hair. Note C1 failing is driven by CI width, not a significant harm (the rule_trend CI includes 0).
No skill claim is made for any predictor; this plan tests ensemble weighting only.

## Checks
Full test suite: 89 passed, 1 skipped (after installing the missing dev dependencies pytest/hypothesis in the sandbox; no repo code changed).
New tests: tests/test_research_hedge_loo.py (truncation/causality, golden, edge cases, verdict logic) - 8 passed.
Trial recorded in reports/trials.jsonl (git-ignored directory, so not committed).
