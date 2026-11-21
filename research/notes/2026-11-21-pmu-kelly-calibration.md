# Research note: is the p→μ mapping and the Kelly size calibrated?

Written 2026-11-21 by the research agent role of the weekly loop. Simulation only. Nothing here reads `live/`.

## Why this question
`atlantis/quant/decide.py` turns a calibrated probability p into an expected h-bar log return
`mu_h = (2p - 1) * sigma_h * sqrt(2/pi)` and sizes positions as `0.5 * mu_h / sigma_h^2` (half Kelly).
That mapping assumes (a) p is calibrated and (b) the size of a move is independent of its direction.
Kelly amplifies any error: if realised returns move less per unit of predicted mu_h than the mapping assumes,
the position is too large. The note `2026-11-09-external-trading-ai-lessons.md` lists this as proposal 7
(section 5, item 7) and nobody has tested it. The previous research loop covered proposal 3 (Hedge
leave-one-out, result FAIL: no ensemble change recommended).

## Hypothesis (to be pre-registered by the planner, not decided here)
H1: regressing the realised h-bar log return (in units of sigma_h) on the predicted mu_h (in units of sigma_h)
over a frozen 2024-2025 holdout gives a slope > 0 whose 95% block-bootstrap CI contains 1.
Interpretation of the slope: slope < 0.5 means Kelly over-sizes (scale KELLY_FRACTION by the slope);
slope <= 0 means the probabilities carry no sizing signal.

## Evidence already in the repo (read only)
- `research/results/hedge-leave-one-out.md` (branch `research/2026-11-14-hedge-leave-one-out`): the full-ensemble holdout
  Brier skill score vs the trailing base rate is 0.0031 with CI [-0.0098, 0.0153], i.e. no demonstrated skill. That makes
  a slope near 0 the likely outcome, and the test is still worth running: it tells us how much to scale sizing.
- The frozen-ledger replay used there (`research/code/hedge_loo_generate.py`, `atlantis.adaptive.run_adaptive` with
  `trade_from` in 2099, empty `llm_root`) reproduces deterministically (identical SHA256 on a second run).
  The same replay gives the p values; realised returns come from the cached pre-2026 daily bid/ask files.

## What would make the result unreliable
- The slope CI will be wide with 20 instruments and about two years of 5-bar rows. The plan must state a minimum number of
  scored rows and call the result INCONCLUSIVE, not PASS, if the CI is too wide to separate 0.5 from 1.
- Overlapping 5-bar windows are autocorrelated, so a block bootstrap by date is required (as in the previous plan).

## Forbidden inputs (same rules as the previous plan)
`live/`, `knowledge/journal.md`, `knowledge/knowhow*.json`, `data/llm/`, any 2026 data, any network fetch.
