# Pre-registered plan: is the p -> mu_h mapping (and therefore Kelly sizing) calibrated?

Plan id: `2026-11-21-pmu-kelly-calibration`. Written 2026-11-21, before any result exists. SIMULATION ONLY.
Input note: `research/notes/2026-11-21-pmu-kelly-calibration.md`
(also `research/notes/2026-11-09-external-trading-ai-lessons.md` section 5 item 7, and `atlantis/quant/decide.py`).
Mechanics follow the previous plan (`2026-11-14-hedge-leave-one-out`). Caveat: this planning session could not run
`git show` on that branch, so the replay mechanics below come from the task brief and from reading
`atlantis/adaptive.py`. The generator code must reuse `hedge_loo_generate.py` unchanged for the replay itself.
If the code finds a mismatch with this text on windows, horizon or seed, the code is wrong, not the plan.

```yaml
plan_id: 2026-11-21-pmu-kelly-calibration
date: 2026-11-21
simulation_only: true
trial_accounting:
  n_trials_before: 9            # reports/trials.jsonl holds the Hedge leave-one-out plan (8 before + 1)
  n_trials_this_plan: 1         # this plan is trial number 10; a changed plan is a new trial
  deflated_sharpe: not_applicable   # no return series, no Sharpe; DSR is not a criterion here
hypothesis:
  H1: >-
    Over the frozen 2024-2025 holdout, regressing the realised h-bar log return (in sigma_h units) on the
    predicted mu_h (in sigma_h units) gives a slope > 0 whose 95% block-bootstrap CI contains 1.
  H0: >-
    The slope is <= 0 (probabilities carry no sizing signal), or its 95% CI excludes 1 (the mapping
    over- or under-sizes), or the data cannot tell.
  interpretation: "slope < 0.5 means Kelly over-sizes (scale KELLY_FRACTION by the slope); slope <= 0 means no sizing signal"
predictor_under_test:
  name: atlantis.adaptive.run_adaptive default team (default_predictors), pool="linear", horizon 5, no parameter changed
  decide_mapping: "mu_h = (2p-1) * sigma_h * sqrt(2/pi); sigma_h = sigma_daily * sqrt(5)  (atlantis/quant/decide.py, propose)"
  parameters_frozen: "all taken from the repository defaults; nothing tuned on our data"
replay:
  function: atlantis.adaptive.run_adaptive
  trade_from: "2099-01-01"      # never trades; predicts and learns only
  llm_root: empty directory     # LLMAnalyst abstains everywhere
  ledger_path: scratch directory (not committed); SHA256 recorded BEFORE any metric is computed
  horizon: 5
  data_years: "<= 2025 only"
windows_by_made_at:
  warmup: "start of data .. 2021-12-31 (learning only, never scored)"
  development: "2022-01-01 .. 2023-12-31"
  holdout: "2024-01-01 .. 2025-12-31"
  holdout_use: "scored once; no choice (threshold, window, filter, p variant) depends on it"
data:
  allowed:
    - cached daily bid/ask files, years <= 2025 (realised returns, sigma recomputation)
    - the frozen replay ledger (p_raw, p_final, fwd_log_return, made_at, symbol, asset_class)
  forbidden:
    - live/
    - knowledge/journal.md
    - knowledge/knowhow*.json
    - data/llm/
    - any 2026 data
    - any network fetch
definitions:
  row: one prediction record (made_at date t, symbol s) whose resolution record exists in the ledger
  sigma_daily: >-
    vol20(t,s) = rolling(20).std() (ddof 1) of the one-bar log difference of mid_close, using each symbol's own
    non-NaN bars, ending at made_at t. This is exactly the `today.at[sym,"vol20"]` that run_adaptive passes to
    decide.propose (atlantis/quant/predict/features.py build_features). The ledger does not store it, so it is
    recomputed from the cached bid/ask files via atlantis.engine.build_panels / build_features.
  sigma_h: sigma_daily * sqrt(5)
  realised_return: >-
    r(t,s) = log(mid_{t+5 bars} / mid_t) = the `fwd_log_return` field of the ledger resolution record
    (atlantis.quant.predict.features.forward_labels). Independently recomputed from the cached files as a check.
  y: r / sigma_h                                   # realised, in sigma_h units
  p_variants:
    primary: >-
      p_final = Calibrator(p_raw). This is the p that run_adaptive passes to decide.propose
      (`propose(sym, p_final, vol20, ...)` in atlantis/adaptive.py). Until the calibrator has 200 resolved
      predictions it returns 0.5 + 0.5*(p_raw - 0.5).
    secondary: "p_raw = the Hedge ensemble probability before calibration (also stored in the ledger as p_raw)"
  x: "mu_h / sigma_h = (2p - 1) * sqrt(2/pi)   (sigma cancels), computed once with p_final (primary) and once with p_raw (secondary)"
  exclusions: "rows without a resolved outcome (the last 5 bars before the 2025 data end) are dropped; no other exclusion, no winsorising in the primary"
metrics:
  primary_slope: "b0 = sum(x*y) / sum(x*x), regression through the origin, holdout, p_final"
  secondary_slope: "b1 = OLS slope of y on x with an intercept, holdout, p_final"
  per_asset_class: "b0 within each of the 6 classes (fx_spot, crypto_fx, stock_cfd, index_cfd, commodity_cfd, metal_cfd)"
  dollar_neutral: >-
    per date, subtract the cross-sectional mean of x and of y over the symbols present that date (dates with
    fewer than 5 symbols dropped), then through-origin slope. Removes the common market factor.
  kelly_scale_implied: >-
    implied KELLY_FRACTION = 0.5 * max(b0, 0), reported for the point estimate and for both CI bounds
    (negative bounds floored at 0)
  also_reported: >-
    the same b0, b1 on the development window; the same for p_raw; b0 with y clipped at +/-5 (sensitivity);
    mean |x|, RMS of x, number of rows, dates and symbols
bootstrap:
  unit: date
  blocks: "consecutive 10-date blocks (non-overlapping; the final block may be shorter); all instruments of a date stay together"
  resamples: 10000
  seed: 20261121                  # numpy.random.default_rng(20261121)
  ci: "percentile 2.5% / 97.5%"
  note: "the same resample indices are used for every statistic; resampling is of blocks, then rows are pooled"
costs:
  source: atlantis/config/saxo_conditions.yaml
  status: not_applicable          # no trading and no P&L; trade_from 2099. No cost enters any metric or criterion.
risk_policy: "config/risk_policy.yaml drawdown limits are not applicable (no return series)"
criteria:   # holdout, primary p (p_final), through-origin slope b0 unless stated. Each PASS/FAIL. Never weakened.
  G1_data_replay:
    all_of:
      - "scored holdout rows >= 8000"
      - "distinct holdout dates >= 450"
      - "distinct holdout symbols >= 18"
      - "hash chain of the ledger verified"
      - "second independent generation gives an identical SHA256"
      - "ledger fwd_log_return equals the value recomputed from the cached files (max abs diff <= 1e-9)"
  G2_spread_of_mu:
    all_of:
      - "mean |x| >= 0.04  (about mean |2p-1| >= 0.05)"
      - "RMS of x >= 0.05"
  C1: "b0 > 0 and the 95% CI lower bound > 0"
  C2: "95% CI of b0 contains 1"
  C3: "b0 point estimate >= 0.5"
  C4: "b0 > 0 in at least 4 of the 6 asset classes (a class with fewer than 300 holdout rows counts as not > 0)"
  C5: "development-window b0 has the same strict sign as the holdout b0 (consistency only; nothing is chosen from it)"
  C6: "reported, not gated: implied KELLY_FRACTION"
width_rule:
  W_MAX: 0.75
  too_wide: "(CI upper - CI lower) of b0 > 0.75 AND the CI contains 0.5"
verdict_rule:
  order:
    - "INCONCLUSIVE if G1 fails or G2 fails"
    - "INCONCLUSIVE if the CI is too wide (width_rule)"
    - "PASS if C1, C2, C3, C4 and C5 all pass"
    - "FAIL otherwise"
  note: "C6 and every secondary analysis (b1, p_raw, dollar-neutral, clipped, development) never change the verdict"
reject_as_unreliable:
  - "G1 or G2 fails"
  - "SHA256 differs between two generations, or the hash chain does not verify"
  - "the ledger p or returns were produced with any forbidden input, 2026 data, or a trade_from before 2099"
  - "the dollar-neutral slope has the opposite strict sign to b0 (result driven by a common market factor); flagged, verdict labelled UNRELIABLE-FLAGGED next to the rule verdict"
  - "any criterion value, threshold, window, bootstrap setting or p variant altered after the first holdout metric was seen"
```

## Binding prose

1. **Trial accounting.** `reports/trials.jsonl` has one entry (the Hedge leave-one-out plan, `n_trials_before` 8, plus 1), so
   `n before = 9`. This plan is trial 10. Deflated Sharpe is not applicable (no Sharpe), and that is stated, not hidden.
   Any change to this plan after the first holdout number is a new trial with its own plan.
2. **Order of work.** Generate the ledger, record its SHA256 and `git` commit, generate a second time and compare, verify the hash
   chain, evaluate G1 and G2 (they use only counts and the spread of x, not any slope), and only then compute slopes.
3. **Which p.** The primary analysis uses `p_final` because `atlantis.adaptive` calls `decide.propose(sym, p_final, vol20, ...)`.
   The raw Hedge `p_raw` is analysed separately and reported next to it. Because the calibrator
   shrinks p by half before 200 resolved predictions and fits a logistic map afterwards, the slope on `p_raw` is not the
   Kelly scale; the slope on `p_final` is. The implied scale in C6 refers to `p_final` only.
4. **Expected difficulty (stated in advance).** The previous plan found holdout BSS 0.0031 with CI [-0.0098, 0.0153], so a slope
   near 0 is the likely outcome, and with small |x| the slope CI is likely wide. INCONCLUSIVE is a legitimate and plausible
   outcome and is not to be rewritten as a pass or fail afterwards.
5. **Overlap.** Windows of 5 bars overlap, so rows are autocorrelated across about 5 dates. Resampling is by 10-date blocks,
   with the instruments of one date kept together; no row-level resampling is allowed.

## Decision consequences (stated in advance; research only, this loop changes no code)

A human would consider the following. None of it is automatic.
- **PASS:** no evidence that half Kelly over-sizes on this replay; keep `KELLY_FRACTION = 0.5`. Re-test on forward-recorded 2026 predictions as a new plan.
- **FAIL with the CI upper bound < 0.5:** evidence that Kelly over-sizes; consider scaling `KELLY_FRACTION` by the slope (C6 gives the number; the CI upper bound is the conservative choice).
- **FAIL with slope <= 0 (CI lower bound <= 0 and point <= 0):** no sizing signal in p; consider a floor (quarter Kelly or no trading) until a later pre-registered test passes. This is consistent with the previous result of no demonstrated skill.
- **FAIL with the CI excluding 1 from above (slope clearly > 1):** the mapping under-sizes; this is not a recommendation to increase risk, only a note.
- **INCONCLUSIVE:** no change; keep sizing as is, keep collecting forward predictions, and plan any rerun as a new trial.

## What would make me reject the result as unreliable

See `reject_as_unreliable` in the YAML. In addition: any use of the development result to pick among variants, any slope computed
before G1 and G2 are evaluated, any change in the replay code between the two generations, or an unexplained difference between the ledger returns
and the recomputed returns.
