INCONCLUSIVE

# Result: is the p -> mu_h mapping (Kelly sizing) calibrated? Plan `2026-11-21-pmu-kelly-calibration`

Simulation only. Plan: `research/plans/2026-11-21-pmu-kelly-calibration.md` (unchanged; no criterion, window, margin, block length, seed or p variant altered). Rule verdict: INCONCLUSIVE, because the 95% CI of b0 is too wide (width 2.51 > 0.75 and it contains 0.5). The UNRELIABLE-FLAGGED condition did not trigger. C1-C4 pass on the point/CI numbers but C5 fails; with the width rule applied first, the verdict is INCONCLUSIVE regardless (without it, it would have been FAIL on C5).

## Freeze record
- Ledger SHA256 (recorded before any metric): `092a3b4c63bb82a05b773559243077b695203e2c7608a6f32766907205062686`
- Git commit at generation: `5513f7b18c26346b50aa34115ae52818ac9734a3` (the plan commit). 91,722 records; hash chain verified.
- Second independent generation (scratch dir runB, via `pmu_kelly_reconcile_check.py`): identical SHA256. Reconciliation breaks: `[]`, 0 orders, equity constant 200.0.
- Generator `research/code/pmu_kelly_generate.py` is the Hedge-LOO generator copied with only the name/docstring changed (diff-checked). Same replay: `run_adaptive`, trade_from 2099-01-01, empty LLM root, horizon 5, data <= 2025, no network. The SHA256 is also identical to the one recorded in the previous (Hedge-LOO) trial, as expected for an unchanged replay.
- Scratch: `/tmp/claude-0/-home-user-project-atlantis/d9030baf-cb3e-5f48-9145-991efe979d4c/scratchpad/runA` (ledger, freeze_record.json, gates.json, metrics.json). Not committed.
- Order of work followed: freeze, regenerate, hash chain, gates stage (`gates` command computes no slope), then metrics stage.

## Gates
- G1 PASS: holdout rows 10,240 (>= 8000); dates 518 (>= 450); symbols 20 (>= 18); hash chain verified; second generation identical SHA256; ledger fwd_log_return vs recomputed from cached files: max abs diff 1.8e-15 (<= 1e-9), none missing. Dropped: 100 unresolved rows (5 bars x 20 symbols), 0 zero/NaN-vol rows.
- G2 PASS: mean |x| = 0.0739 (>= 0.04); RMS x = 0.0744 (>= 0.05).

## Criteria (holdout 2024-2025, p_final, b0 through the origin; 52 ten-date blocks, 10000 resamples, seed 20261121)
b0 = 1.396, 95% CI [0.077, 2.585].
- C1 PASS: b0 > 0 and lower bound 0.077 > 0.
- C2 PASS: CI contains 1.
- C3 PASS: 1.396 >= 0.5.
- C4 PASS: b0 > 0 in 5 of 6 classes (needs 4; all classes have >= 300 rows). fx_spot 0.311 (n 3108), crypto_fx 1.115 (1036), stock_cfd 1.293 (2485), index_cfd 2.036 (2579), commodity_cfd -0.934 (516), metal_cfd 5.476 (516).
- C5 FAIL: development b0 = -0.632 (CI [-2.187, 0.865]), opposite strict sign to the holdout b0.
- C6 (reported, not gated): implied KELLY_FRACTION = 0.5*max(b0,0) = 0.698 point, 0.038 at CI lower, 1.292 at CI upper.
- Width rule: CI width 2.508 > 0.75 and CI contains 0.5, so too wide, hence INCONCLUSIVE. The data cannot distinguish a slope of 0.08 from 2.6.

## Secondary analyses (never change the verdict)
| statistic | holdout | development |
|---|---|---|
| b0 p_final | 1.396 [0.077, 2.585] | -0.632 [-2.187, 0.865] |
| b1 (intercept) p_final | 5.607 [-2.354, 13.325] | -4.885 [-13.864, 5.317] |
| b0 p_raw | 2.093 [0.452, 3.556] | -0.494 [-2.686, 1.644] |
| b1 p_raw | 1.802 [0.013, 3.504] | -0.180 [-2.771, 2.498] |
| b0 y clipped +/-5, p_final | 1.608 [0.357, 2.716] | -0.160 [-1.584, 1.244] |
| b0 dollar-neutral, p_final | 6.310 [0.248, 11.788] | -0.096 [-9.232, 9.907] |
| b0 dollar-neutral, p_raw | 1.398 [-0.091, 2.780] | 0.044 [-2.168, 2.387] |
| mean |x| / RMS x, p_final | 0.0739 / 0.0744 | 0.0634 / 0.0643 |
| mean |x| / RMS x, p_raw | 0.0456 / 0.0563 | 0.0338 / 0.0425 |
| rows / dates / symbols / blocks | 10240 / 518 / 20 / 52 | 10289 / 520 / 20 / 52 |

Dollar-neutral b0 has the same strict sign as b0 (both positive), so the common-market-factor rule did not flag the result.

## Honest reading
The point estimate on the holdout (1.4) looks like a signal, with a lower bound just above zero, but the interval spans nearly 2.5 slope units and includes both 0.5 (over-sizing) and 1 (calibrated) and values above 2. The development window gave a negative slope of similar magnitude, so the sign is not stable across the two years-blocks; the holdout positive result may be noise, consistent with the previous plan's finding of no demonstrated skill (BSS CI containing zero). Nothing here supports changing KELLY_FRACTION in either direction, and nothing supports claiming calibrated sizing. Per the plan's stated consequence for INCONCLUSIVE: no change; keep collecting forward predictions; any rerun is a new trial. The development result was not used to choose anything. The secondary b1 values are very noisy (the intercept absorbs a lot with small |x|) and should not be interpreted.

## Checks
- `python -m pytest -q` (whole suite, including the 12 new tests in `tests/test_research_pmu_kelly.py`): 96 passed, 1 skipped, 0 failed.
- New tests cover: golden slope numbers, x/y definition, blocks, bootstrap determinism, known-slope recovery, dollar-neutral, causality (truncation) of row building, exclusions, verdict order, edge cases, no forbidden imports.
- Reconciliation: zero breaks. Nothing under `atlantis/`, `live/`, `config/`, knowledge files or `data/llm/` was touched; no 2026 data; no network.
- Deviation note: the plan said the generator is reused "unchanged"; only its module name/docstring text changed. The plan's "independent recomputation" of returns was done with a separate numpy loop over each symbol's non-NaN mid bars (not via `forward_labels`); `vol20` was recomputed with `build_panels`/`build_features` as specified.

## Trial record
Appended to `reports/trials.jsonl` (git-ignored, so not part of the commit): plan_id `2026-11-21-pmu-kelly-calibration`, n_trials_before 9, n_trials_this_plan 1 (trial 10), verdict INCONCLUSIVE, ledger SHA256 above, deflated Sharpe not applicable.

## Code
`research/code/pmu_kelly_generate.py`, `research/code/pmu_kelly_reconcile_check.py`, `research/code/pmu_kelly_analyze.py` (stages `gates`, `metrics`), `tests/test_research_pmu_kelly.py`.
