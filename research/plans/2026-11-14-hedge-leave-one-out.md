# Pre-registered plan: Hedge leave-one-predictor-out (redundancy of trend and breakout)

Written 2026-11-14 by the planning agent, before any result exists. Plan only: no code run, no data read for results.
Format note: the planner spec asks for `research/plans/<slug>.yaml`; this file was requested as `.md`, so the machine-readable
plan is the fenced YAML block below and the prose after it is binding commentary. Both say the same thing.
Source notes: `research/notes/2026-11-09-external-trading-ai-lessons.md` (proposal 3, section 2.3, section 4), `knowledge/journal.md` lines 20-22.
Code referenced (read only): `atlantis/quant/learn/knowhow.py` (HedgeWeights, PredictionLedger), `atlantis/adaptive.py`, `atlantis/quant/predict/models.py`.

```yaml
plan_id: 2026-11-14-hedge-leave-one-out
status: PRE-REGISTERED            # any edit after the first run = a NEW plan = a NEW trial
trial_accounting:
  counts_as_trial: true
  append_to: reports/trials.jsonl  # file does not exist yet in the repo; the tester creates it with this trial as a record
  n_trials_before_this_plan: 8     # per journal 2026-11-09 (all rule strategies)
  n_trials_this_plan: 1            # one trial, containing 8 configurations (full + 7 leave-one-out arms), all recorded in metadata
  deflated_sharpe: not_applicable  # no Sharpe is produced; multiplicity handled by the primary/secondary split below

hypothesis:
  H1: >
    Rule_trend and rule_breakout are largely redundant inside the Hedge ensemble. Therefore dropping either one
    alone does not make the ensemble Brier score worse out of sample (non-inferiority, margin below), and the
    two predictors are substantially correlated.
  H0: dropping rule_trend or rule_breakout makes the holdout ensemble Brier worse by more than the margin.
  direction_note: >
    Delta = Brier(leave-one-out arm) - Brier(full ensemble). Negative = dropping helps. Brier is lower-is-better.

data:
  allowed:
    - Cached daily bid/ask files data/raw/dukascopy_live/<SYM>/<YYYY>/{BID,ASK}_candles_day_1.bi5 for years <= 2025 only (read only)
    - atlantis/config/universe.yaml (instrument list, asset classes)
  forbidden:
    - anything under live/ (predictions.jsonl, predictions_intraday.jsonl, controls.jsonl, journal.jsonl, run_log.jsonl, history_years.json, ...)
    - knowledge/journal.md, knowledge/knowhow*.json as inputs
    - data/llm/ (forward-only LLM files), 2026 hourly or minute Dukascopy files, any network fetch
  finding_recorded_at_planning_time: >
    No frozen historical prediction ledger exists outside live/. The only prediction ledgers in the repo are the live
    ones, which are off limits. The frozen ledger is therefore REGENERATED once by a deterministic replay (below) from
    cached pre-2026 daily data. If the cache is missing too much (gate G1), the plan ends INCONCLUSIVE; it does not
    fall back to live ledgers.
  frozen_ledger_generation:
    function: atlantis.adaptive.run_adaptive          # existing code, unmodified
    args:
      data: all universe instruments with cached daily bars, bars dated <= 2025-12-31, no instrument selected or dropped by performance
      capital: 200.0
      start: earliest cached bar            # warm-up: predictions made and Hedge updated, but not scored before the dev window
      end: "2025-12-31"
      horizon: 5
      trade_from: "2099-01-01"              # never trades: predictions and learning only
      controls: null
      context_daily: null
      llm_root: an EMPTY directory in the session scratchpad   # llm_analyst abstains on every date (forward-only rule)
      ledger_path: a NEW file in the session scratchpad, never under live/ or the repo
    freeze_rule: >
      Run once. Record SHA256 of the ledger file, the git commit, and the instrument list in the result record BEFORE any
      metric is computed. A re-run with different code or data is a new plan. The hash-chain check (PredictionLedger.verify) must pass.
  windows:                                   # by prediction date (made_at)
    warmup: from earliest cached bar to 2021-12-31     # Hedge learns here; rows not scored
    development: 2022-01-01 to 2023-12-31              # consistency check only (criterion C5a); nothing is chosen from it
    holdout: 2024-01-01 to 2025-12-31                  # primary evidence; never used for any choice
  scored_rows: >
    Predictions that have a resolution record whose resolved_at <= 2025-12-31, in the window, with a defined base-rate forecast
    (see metrics). The same row set is used for every arm.

fixed_parameters:                            # all taken from existing code or the cited sources; none tuned on our data
  predictors_full_ensemble: [no_view, rule_trend, rule_breakout, rule_reversal, ml_logistic, ml_lightgbm, llm_analyst]   # default_predictors()
  hedge: {eta: "sqrt(8 ln N / t) per asset class (anytime, Cesa-Bianchi & Lugosi 2006)", N: "number of predictors in the arm", loss: Brier, sleeping_experts: true}
  calibrator: NOT used. Metrics use the raw Hedge probability, so only the ensemble weighting is evaluated.
  arms:
    full: all 7 predictors
    primary_loo: [drop rule_trend, drop rule_breakout]
    secondary_loo_descriptive: [drop rule_reversal, drop ml_logistic, drop ml_lightgbm, drop no_view]
    null_control: drop llm_analyst      # it abstains always, so this arm differs from full only through eta (N 7 -> 6). It sets the noise floor for any N effect.
  arm_replay_method: >
    Read the frozen ledger in seq order. On a resolution record, call HedgeWeights.update(asset_class, predictor_probs restricted to
    the arm's predictors, outcome_up). On a prediction record, call HedgeWeights.combine(asset_class, restricted probs) to get the arm's
    probability. Predictor outputs do not depend on Hedge, so this offline replay is exact for every arm.
  block_bootstrap: {unit: trading dates (all instruments of a date move together), block_length_dates: 10, blocks: non-overlapping, resamples: 10000, seed: 20261114, ci: percentile 2.5 and 97.5, paired: same resamples for every arm}
  non_inferiority_margin_brier: 0.0005          # 0.2% of the 0.25 no-view Brier; set before seeing data
  min_rows_per_asset_class_for_class_check: 500

metrics:
  M1_ensemble_brier: pooled mean over scored rows of (p - outcome_up)^2, per arm and window
  M2_delta_brier: Brier(arm) - Brier(full), paired per row, with block-bootstrap 95% CI
  M3_base_rate_forecaster: >
    per instrument, the frequency of up outcomes among that instrument's last 252 resolved 5-bar outcomes with resolved_at <= made_at
    (note proposal 1). Needs at least 120 such outcomes, otherwise the row is not scored in any arm.
  M4_brier_skill_score: 1 - Brier(arm)/Brier(base_rate), per arm, with block-bootstrap 95% CI (ratio recomputed in every resample)
  M5_redundancy: Spearman correlation of rule_trend and rule_breakout probabilities on holdout rows where both are awake, with block-bootstrap 95% CI
  M6_weight_mass: mean (row-weighted) Hedge weight of rule_trend + rule_breakout in the full arm on holdout rows
  M7_per_asset_class: M2 point estimate per asset class (6 classes in CLASS_NAMES), classes with fewer than 500 scored holdout rows excluded

gates_and_criteria:
  G1_data_validity:                       # failing a gate gives INCONCLUSIVE, never PASS
    - ledger hash chain verifies and the SHA256 is recorded before metrics
    - holdout scored rows >= 5000, distinct holdout dates >= 400, instruments with holdout rows >= 15
    - replay of the full arm reproduces the ledger p_raw: mean absolute difference <= 0.0005 and at least 99% of rows within 0.002
    - llm_analyst probabilities are None on 100% of rows
  G2_vacuity_guard: M6 >= 0.10            # if Hedge already gives these two predictors under 10% weight, dropping them cannot matter and non-inferiority would pass for free -> INCONCLUSIVE (not PASS)
  C1_primary_noninferiority:              # holdout, one test per primary arm, both must pass
    PASS_if: upper 95% CI bound of M2 <= +0.0005 for rule_trend AND for rule_breakout
    FAIL_if: upper 95% CI bound of M2 > +0.0005 for at least one of the two (with G1 and G2 met)
  C2_redundancy_evidence:
    PASS_if: M5 point estimate >= 0.50 AND lower 95% CI bound >= 0.40
    FAIL_otherwise
  C3_noise_floor:
    PASS_if: |M2 of the null_control arm| <= 0.0005 (point estimate); otherwise N-dependence of eta is large and C1 is reported as CONFOUNDED (overall INCONCLUSIVE)
  C4_class_consistency:
    PASS_if: for each primary arm, M7 point estimate <= +0.0005 in at least 4 of the 6 asset classes with enough rows (all of them, if fewer than 6 qualify, and at least 3 classes must qualify)
    FAIL_otherwise
  C5_dev_consistency:
    PASS_if: development-window M2 point estimate <= +0.0005 for both primary arms
    FAIL_otherwise
  C6_skill_reported_not_gated:
    report: M4 for full and every arm on holdout with CI. Not a pass condition, because the note's holdout evidence says rule edge is about zero. If the full ensemble BSS CI includes 0, the write-up must say redundancy was tested on an ensemble with no demonstrated skill.
  drop_recommendation:                    # separate from H1; only about promoting a change
    DROP_candidate_if: upper 95% CI bound of M2 < 0 (dropping is significantly better) AND C5 same sign, for that predictor
    otherwise: no change to the ensemble is recommended from this plan; any actual change is a new plan and logged as a trial
  overall_verdict:
    PASS: G1 and G2 and C1 and C2 and C3 and C4 and C5 all pass
    FAIL: G1, G2 and C3 hold and (C1 fails OR C2 fails OR (C1 passes and both C4 and C5 fail))
    INCONCLUSIVE: anything else (a gate fails, or C3 confounded)
    secondary_arms: descriptive only, no verdict, labelled exploratory because 4 extra comparisons are made

costs_and_risk:
  saxo_conditions: not applicable. Trading is disabled (trade_from 2099), so no commissions, spread or financing enter any metric. Status of atlantis/config/saxo_conditions.yaml values is irrelevant here and not used.
  risk_policy: not applicable (no equity curve). config/risk_policy.yaml is not consulted.
  sharpe_and_dsr: not produced

reject_or_downgrade_if:
  - any gate fails (INCONCLUSIVE; do not widen windows, add instruments, or loosen thresholds)
  - the full-arm replay cannot reproduce the ledger
  - the analysis reads anything under live/ or uses data/llm
  - a metric, window, margin, block length or seed is changed after the first run (new plan, new trial)
  - the result is read as skill evidence for any predictor (this plan tests ensemble weighting only)

limitations_known_in_advance:
  - the frozen ledger is a regeneration, not a record made at the time; it is valid for this offline question because predictor outputs use only information up to each bar and the ML retraining is purged and embargoed (5 days)
  - cached history depth differs by instrument (EURUSD from 2010, most others from 2020-2022, crypto and stocks mostly 2020 or later); the universe is survivorship-biased (current mega-caps)
  - 5-bar labels overlap, so rows are autocorrelated; the 10-date block bootstrap is meant to cover that but is not a proof
  - 2022-2025 is one macro regime; no result generalises beyond it
  - rule_trend and rule_breakout are 0.5 +/- 0.1 signals, so their Brier effect may be tiny; the margin of 0.0005 may be wider than the effect, in which case C1 passes and the finding is "cannot distinguish", which the write-up must say
```

## Plain-language summary of what is binding

1. Data are regenerated pre-2026 daily replay predictions only; nothing under `live/` is read.
2. Warm-up to 2021-12-31, development 2022-2023 (consistency check only), holdout 2024-2025 (the evidence).
3. Primary quantity is holdout ΔBrier (arm minus full) for dropping rule_trend and for dropping rule_breakout, with 10-date block-bootstrap 95% CI (10,000 resamples, seed 20261114).
4. PASS needs: gates G1 and G2, non-inferiority (CI upper ≤ +0.0005) for both arms, Spearman(trend, breakout) ≥ 0.50 with CI lower ≥ 0.40, null-control noise |Δ| ≤ 0.0005, at least 4 of 6 asset classes within margin, and development-window agreement.
5. BSS vs the trailing-252 base rate is reported with CI but is not a gate; a failed gate gives INCONCLUSIVE, never PASS.
