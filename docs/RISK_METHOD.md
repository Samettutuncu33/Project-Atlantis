# Risk and sizing method: evidence and reasoning

## 1. No hand-picked numbers
Every parameter is one of three things:
- **(a) regulatory:** ESMA retail margin.
- **(b) Saxo-published:** costs and execution statistics.
- **(c) a published default from a cited study.**

No parameter was tuned on our data. Each variant that is run is logged in `reports/trials.jsonl`, so the Deflated Sharpe Ratio can account for multiple testing.

## 2. Position sizing: volatility targeting
- The portfolio target is 10% annualised volatility. We used this figure as a constant rather than estimating it. It is the order of magnitude of diversified managed-futures and trend benchmarks, and the level at which Moskowitz, Ooi & Pedersen (2012) report TSMOM portfolio results (their per-asset scaling is 40%, which combines to roughly 10–12% at portfolio level).
- Each asset gets `σ_target / √N`. This equal-risk rule assumes zero correlation; if the assets are correlated, realised portfolio volatility will be higher than 10%.
- Ex-ante volatility is an EWMA of squared daily log returns with centre of mass 60 days, as in MOP (2012).
- Volatility-managed portfolios have support in Moreira & Muir (2017), "Volatility-Managed Portfolios", *J. Finance* 72(4). Harvey et al. (2018), "The Impact of Volatility Targeting", *JPM* 45(1), find it reduces tail risk in risk assets.

## 3. Lot rounding at $200
- Sizes are rounded to the nearest feasible ticket (0 or ≥ the minimum). That choice minimises tracking error against the vol-targeted size.
- **Consequence:** at $200 and 10% volatility, a major FX pair needs about 100 units against a 1,000-unit minimum, so the position rounds to zero.
- The platform reports this rather than quietly trading a minimum ticket that carries 5–10× the intended risk.

## 4. Trading-cost controls
- Minimum commission is $1 against $200 of capital, so each ticket costs 0.5% of the account. Three controls keep the number of tickets down:
  - Monthly re-sizing.
  - Daily-signal strategies only trade on entry, exit or flip.
  - A 10% position buffer (Carver, *Systematic Trading*, 2015).
- A cost sweep (0×, 1×, 2×, 3× costs, plus 1 and 3 bps of extra spread) shows how much of each strategy's edge survives realistic frictions.

## 5. Stops
- Only the breakout strategy uses a stop: 2× ATR(20), its published rule. TSMOM and reversal are tested without stops, as in their source papers.
- **Not yet built:** walk-forward tests of stops vs. no stops (see the roadmap).

## 6. The `max_growth` profile and the 2× per-month target
- Kelly (1956) and Thorp (2006) give the growth-optimal leverage `f* = μ/σ²`, and the resulting log-growth `g* = SR²/2`. Doubling every month means `g = 12·ln2 ≈ 8.32` per year, which requires **SR ≈ 4.08**. That assumes full Kelly, no estimation error and no costs.
- Even at exactly full Kelly with known parameters, P(wealth ever falls to x of its peak) = x. So there is a 50% chance of halving and a 10% chance of losing 90%.
- `max_growth` uses **½ Kelly**, a standard concession to estimation error (MacLean, Thorp & Ziemba 2011).
  - Kelly is estimated on the **development period only** and then applied to the holdout.
  - The ESMA margin cap still binds.
- The target is never used as an objective. It is only reported, as bootstrap probabilities computed from holdout returns.

## 7. Overfitting controls
- Pre-registered parameters; development period 2012–2019; holdout 2020–2025.
- Look-ahead detector: every backtest recomputes signals on truncated data and fails if any past signal changes.
- Deflated Sharpe Ratio (Bailey & López de Prado 2014), using the number of trials actually run.
- Universe: FX majors and metals only. These are continuously traded with no delistings, so there is no survivorship bias.
