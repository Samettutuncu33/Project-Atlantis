# External trading-AI lessons: what other systems' track records teach Atlantis

Date: 2026-11-09. Author: research agent (simulation-only project).

## How this was researched, and what could not be verified

- I ran 12 web searches (standard mode). **Direct page fetches failed.** arxiv.org and papers.ssrn.com do not resolve from this cloud session, because they are outside its allowed network domains. I made no further fetch attempts.
- Every external claim below therefore comes from **search-result abstracts and snippets**, not from reading the full papers. Each claim is tagged:
  - **[abstract]**: stated in the paper's own abstract or listing (NBER, RePEc, arXiv, SSRN, official docs). Fairly reliable.
  - **[secondary]**: news, blogs or mirrors. Treat with caution.
  - **[unverified]**: I could not confirm it.
- To read the full texts, allow arxiv.org and papers.ssrn.com in the environment's network settings and rerun the verification.
- Numbers about Atlantis itself come from the repository (`reports/trials.jsonl`, `atlantis/…`). They are tagged **[repo]**.
- Not covered: "A Machine Learning approach to …" replications (there was no search budget left), the nof1.ai leaderboard itself (not fetched), FinRL contest results and StockAgent.

---

## 1. Public LLM / AI-agent trading experiments

### 1.1 nof1 "Alpha Arena" Season 1: live crypto perps, about Oct–Nov 2025
- **What it is:** six frontier LLMs, each given about $10,000 of real money to trade crypto perpetuals autonomously.
- **Evidence (live, real costs, about 17 days) [secondary]:** Qwen 3 Max won with about +22% and DeepSeek V3.1 made about +4.9%. Four of six models lost money; GPT-5 lost about 63% and Gemini 2.5 Pro about 57%.
- **Source disagreements:** news sources disagree on the end date (3 Nov vs 3 Dec 2025) and on the venue. A 2026 ThinkAdvisor article describes "eight models across four competitions", which matches neither. nof1 itself called Season 1 exploratory, without statistical controls.
- **Lessons:**
  - (a) Model rankings over about 17 days of one correlated asset class are close to noise. Leverage plus a few large directional bets dominated the results.
  - (b) Press coverage repeatedly reported over-trading and inconsistent strategy as the failure mode [secondary, Wallstreetcn/Forklog].
  - (c) Real money and real costs quickly expose behaviour that backtests hide.
- **Credibility: low to medium.** The experiment is genuinely live and public, but it is very short, has n=6, and lacks controls. The numbers come from press, not the primary leaderboard.

### 1.2 TradingAgents (Xiao, Sun, Luo, Wang; arXiv 2412.20138, Dec 2024 to Apr 2025)
- **What it is:** a multi-agent LLM "trading firm" with analyst, researcher (bull/bear debate), trader and risk-manager roles.
- **Evidence (backtest/simulation) [abstract]:**
  - Simulated trading ran about Jun–Nov 2024 on a few US mega-caps.
  - It reports better cumulative return, Sharpe and max drawdown than its baselines.
  - The exact numbers are **[unverified]**; a secondary write-up gives about 23–27% on AAPL, GOOGL and AMZN.
- **Caveats:**
  - The test window overlaps the training data of the LLMs used. A Hugging Face commenter raised this look-ahead concern [unverified community remark].
  - The universe is tiny and the window is about 5 months.
- **Lesson:** this is an architecture demo, not evidence of edge. Its useful idea is explicit role separation, especially an independent risk manager. Atlantis already has that as the central risk gate.
- **Credibility: low as performance evidence**, medium as a design reference.

### 1.3 FINSABER: "Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?" (Li, Kim, Cucuringu, Ma; arXiv 2505.07078; listed as accepted to KDD 2026)
- **What it is:** a re-test of published LLM strategies (FinMem, FinAgent and others) over 2004–2024 on a broader universe, with explicit bias mitigation.
- **Evidence (long backtest) [abstract]:**
  - The original evaluations were narrow: FinMem used 6 months and 5 symbols, and FinAgent used 6 months and 6 symbols.
  - Previously reported LLM advantages "deteriorate significantly" over a broader cross-section and a longer period, which the authors attribute to survivorship and data-snooping bias.
  - The LLM strategies were **too conservative in bull markets and too aggressive in bear markets**.
  - Exact table values are **[unverified]**.
- **Lessons:**
  - (a) Short, narrow evaluations overstate edge.
  - (b) Evaluate by market regime, not only in aggregate.
  - (c) Survivorship matters. Atlantis' stock list (US mega-caps chosen today) is a survivorship-biased universe.
- **Credibility: medium to high.** It is a peer-reviewed venue (per the listing), its design directly targets the biases, and its conclusion goes against what the authors' own field would prefer to find.

### 1.4 LLM look-ahead / memorisation bias
- **"A Test of Lookahead Bias in LLM Forecasts"** (Gao, Jiang, Yan; arXiv 2512.23847) [abstract]: a statistical test for look-ahead bias, applied to news headlines that predict returns and to earnings calls that predict capex. Memorisation inflates the apparent predictive power.
- **"The Memorization Problem"** (arXiv 2504.14765; authors not confirmed) [abstract]:
  - LLMs recall exact economic and financial values from before their knowledge cutoff.
  - Their counterfactual forecasting ability is *not identified* on data the model has seen.
- **Related work [abstract-level, not read]:**
  - MemGuard-Alpha (arXiv 2603.26797): membership-inference filtering. Its title stresses the *limits* of that approach.
  - Look-Ahead-Bench (Benhenda; arXiv 2601.13770).
  - FinCAD (arXiv 2605.24564).
- **Lesson:** any backtest of an LLM predictor on dates before its training cutoff is invalid. Only forward-recorded predictions count.
- **Credibility: medium to high.** Several independent groups reach the same conclusion. These are recent preprints, not all peer-reviewed.

## 2. Open-source projects that publish benchmarks or lessons

### 2.1 Microsoft Qlib benchmarks (`examples/benchmarks/README.md`)
- **What it is:** a public leaderboard of ML models on China A-shares (CSI300) using the Alpha158 / Alpha360 technical feature sets.
- **Evidence (backtest, as reported in the README):** LightGBM on Alpha158 shows IC about 0.04–0.05, ICIR about 0.37–0.40 and an annualised excess return of about 9–11% [secondary mirrors of the README; varies by commit and data version].
- **Data caveat:** the README itself warns that results differ between dataset versions because the data comes from an unstable Yahoo source.
- **Lessons:**
  - (a) Even well-engineered technical-feature GBMs reach only a *tiny* per-prediction signal (IC about 0.05). They make money through **breadth**, about 300 names cross-sectionally.
  - (b) Results depend on the data vintage, so pin data versions.
  - Atlantis has 20 time-series predictions per day, so its breadth is about 15x smaller. Realistic skill is an AUC barely above 0.5.
- **Credibility: medium to high** as a calibration of what is realistic. It is reproducible and open, but it is a backtest on one market.

### 2.2 Freqtrade / FreqAI (official docs; JOSS paper "FreqAI: generalizing adaptive modeling for chaotic time-series market forecasts")
- **What it is:** an open-source crypto bot framework with self-adaptive periodic retraining. Its backtester emulates the same retraining schedule.
- **Evidence [abstract/docs]:** the docs ship `lookahead-analysis` and `recursive-analysis` commands. These exist because user strategies routinely leaked future candles, for example through a negative `shift`.
- **Not verified:** details of the Dissimilarity-Index outlier filter and of `live_retrain_hours`, because the docs were not fetched.
- **Lessons:**
  - (a) Backtest the *retraining schedule itself*, not one fitted model.
  - (b) Build automated look-ahead tests: recompute features on truncated data and require identical values.
  - (c) Abstain when the inputs are out of distribution.
- **Credibility: medium.** These are engineering practices, not performance claims.

### 2.3 Numerai: Meta Model Contribution (MMC) / True Contribution (official docs)
- **What it is:** a hedge fund that pays crowd models by their *orthogonal* contribution.
- **Evidence [docs]:**
  - MMC is the covariance with the target after the submission is neutralised against the stake-weighted meta model.
  - The docs warn that a linear combination of well-known signals has "little to no orthogonal component".
  - Feature neutralisation is used to cap a model's exposure to any single feature.
- **Lessons:**
  - (a) Score each predictor by its *marginal* contribution to the ensemble, not its standalone accuracy.
  - (b) Highly correlated predictors add little. Atlantis' trend and breakout rules are likely highly correlated.
  - (c) Limit concentration on one feature or regime.
- **Credibility: high as practice**, from years of a live tournament with real stakes. Numerai's own performance numbers were not checked.

## 3. Evidence on why ML / backtested trading strategies fail out of sample

### 3.1 Bailey, Borwein, López de Prado, Zhu: "The Probability of Backtest Overfitting" (SSRN 2326253; J. Computational Finance)
- **What it says [abstract]:**
  - PBO is the probability that the in-sample-best configuration underperforms the median configuration out of sample. It is estimated with combinatorially symmetric cross-validation (CSCV).
  - It requires the out-of-sample results of **all** tried configurations.
  - The more configurations tried, the higher the PBO.
  - There is no universal threshold.
- **Credibility: high** (peer-reviewed, widely used, CRAN `pbo` implementation).

### 3.2 Bailey & López de Prado: "The Deflated Sharpe Ratio" (J. Portfolio Management 40(5), 2014; as cited in `atlantis/quant/research/robustness.py`)
- **What it does:** corrects the Sharpe ratio for the number of trials and for non-normal returns.
- **Citation status:** the original paper did not appear in my search results. The citation is the repository's, and I did not re-verify it.
- **Credibility: high** (standard reference).

### 3.3 Harvey, Liu & Zhu: "…and the Cross-Section of Expected Returns" (RFS 29(1):5–68, 2016; NBER w20592)
- **What it says [abstract]:**
  - Hundreds of factors have been tested, so t=2 is not a valid bar. A new factor needs **t > 3.0**.
  - "Most claimed research findings in financial economics are likely false."
- **Credibility: high.**

### 3.4 Gu, Kelly & Xiu: "Empirical Asset Pricing via Machine Learning" (RFS 33(5):2223–2273, 2020; NBER w25398)
- **What it says [abstract]:**
  - Trees and neural networks predict best, because they capture nonlinear interactions.
  - The dominant signals are momentum, liquidity and volatility variants.
  - The economic gains are large, in some cases double the regression benchmark.
- **Not verified:** transaction-cost treatment and the out-of-sample R² values.
- **What the abstract implies:** out-of-sample R² values in monthly return prediction are small, so the edge per bet is small, and the gain comes from breadth and from many thousands of stocks.
- **Credibility: high.** It supports nonlinear models in principle but on a very different scale: a monthly cross-section of about 30k stocks, versus 20 instruments over 5 days.

### 3.5 Moskowitz, Ooi & Pedersen: "Time Series Momentum" (JFE 104(2):228–250, 2012)
- **What it says [abstract]:**
  - Significant TSMOM appears across 58 liquid futures (equity indices, currencies, commodities, bonds).
  - Returns persist for 1–12 months and partially reverse later.
  - The strategy does best in extreme markets.
- **Replication critique [secondary/unverified]:** Kim, Tse & Wald report that much of the alpha comes from **volatility scaling**: monthly alpha falls from 1.27% to 0.41% without it.
- **Credibility: high** for the original. The critique is medium, as I only saw a secondary summary.
- **Atlantis' own evidence [repo]:** 12-month TSMOM had an annualised Sharpe of about **+0.21 in development (2012–2019) and −0.04 in holdout (2020–2025)**. The published edge has largely not shown up in this universe recently.

---

## 4. What Atlantis already does: supported vs contradicted by the evidence

**Supported:**
- A forward-only LLM predictor: `LLMAnalyst` abstains on any date without a pre-written file, and predictions are hash-chained in the ledger before their outcome exists. This is exactly what the memorisation literature (1.4) requires.
- A trial registry plus Deflated Sharpe (`robustness.py`), with pre-registered parameters, a 2012–2019 dev / 2020–2025 holdout split, and Kelly estimated on dev only (3.1–3.3).
- Training with purge and embargo (`training_set`: outcome known at or before asof − 5 days) (López de Prado; FreqAI's look-ahead focus).
- Full cost model (Saxo commissions, spread, financing), an edge-greater-than-cost gate, and half Kelly. These answer the over-trading failure seen in Alpha Arena (1.1).
- An independent central risk gate, matching the TradingAgents risk-manager role (1.2).
- Volatility-scaled sizing, which the TSMOM critique suggests is where much of trend's edge comes from (3.5).
- A small-capacity LightGBM (`num_leaves=8`, 200 trees) and logistic regression with C=0.1, which fits the tiny-IC reality (2.1).

**Contradicted, or in tension:**
- **The trial count is understated.** Only 8 trials are registered [repo], all rule strategies. The ML hyperparameters, 14-feature set, Hedge η, calibrator, horizon, edge threshold and the ensemble itself were also choices. The DSR and any future PBO will be too optimistic until these are logged (3.1, 3.3).
- **The holdout evidence is currently negative** for all three rules [repo]: TSMOM −0.04, Donchian −0.29, reversal −0.85 (annualised Sharpe). Hedge-weighting predictors with no holdout edge cannot create edge. At best it learns to shrink toward 0.5.
- **The universe has survivorship bias.** US mega-caps chosen in 2026 makes historical stock results optimistic (1.3).
- **Breadth is low** (20 instruments, highly correlated within classes). The expected skill per prediction is tiny, so statistical significance will take many months of live data (2.1, 3.4). Any early live result is noise, as in Alpha Arena (1.1).
- **There is a sizing assumption to test.** `decide.propose` maps p to μ via `mu_h = (2p−1)·σ_h·√(2/π)`, which assumes the move size is independent of direction. Kelly amplifies any miscalibration in p or μ.
- **Hedge scores standalone Brier per predictor.** Numerai's evidence says marginal contribution is what matters, and correlated rules (trend and breakout) can double-count (2.3).

---

## 5. Testable proposals (each with a falsifiable success criterion)

1. **Pre-registered live skill test for account E (top priority).**
   - Freeze a base-rate forecaster: the trailing 252-day frequency of 5-day up-moves for each instrument.
   - Score E's calibrated probabilities against it with the Brier skill score (BSS), using a block bootstrap with a block of at least 5 days and one block per date across instruments.
   - **Success:** after 26 weeks, BSS > 0 with the 95% CI excluding 0, overall and in at least 3 of 6 asset classes.
   - **Fail:** the CI includes or sits below 0, in which case position sizing is cut to the floor (for example quarter Kelly or no trading) until the criterion is met.
   - Write the criterion into the journal *before* the data arrives.
2. **Log every degree of freedom as a trial, then run PBO (CSCV) before promoting anything.**
   - Register the ML hyperparameters, feature-set versions, Hedge η, calibrator, horizon and edge multiplier in `trials.jsonl`.
   - Run CSCV over all configurations (Roadmap item 9).
   - **Success:** a configuration is promoted only if PBO < 0.2 *and* holdout DSR > 0.95. Any new signal must have t > 3 (HLZ).
   - **Fail:** PBO ≥ 0.5 means configuration selection is no better than chance, so revert to the simplest pre-registered set.
3. **Marginal-contribution scoring of predictors (Numerai-style).**
   - Each month, compute the leave-one-out ensemble Brier for each predictor and the pairwise correlation of predictor outputs.
   - **Success:** each kept predictor improves the out-of-sample ensemble Brier (Δ < 0) over a rolling 6 months.
   - **Fail:** a predictor whose removal improves the ensemble Brier for 6 consecutive months is dropped, or its Hedge weight is capped.
   - **Second test:** whether Hedge on residualised predictions beats the current Hedge on out-of-sample Brier.
4. **Vol-scaling vs signal attribution.**
   - Compare the TSMOM and breakout rules with 1000 sign-randomised but identically vol-scaled baselines over the holdout.
   - **Success:** a rule's holdout Sharpe exceeds the 95th percentile of the random-sign baselines.
   - **Fail:** below that, the rule's "edge" is vol targeting or beta, and its prior weight should go to 0.5.
5. **Regime-sliced evaluation (FINSABER).**
   - Report Brier and net P&L of E separately for up, down and sideways regimes. One way to label regimes is the sign of an instrument's 6-month return, with a band in which |return| < 0.5σ counts as sideways.
   - **Success:** no regime has a BSS significantly below 0 (95% CI).
   - **Fail:** a significantly negative regime means sizing in that regime is cut or a regime feature is added, and the change is logged as a trial.
6. **Cost-robustness and turnover check (Alpha Arena over-trading).**
   - Re-run the holdout with `cost_multiplier` ∈ {1, 2, 3} and edge thresholds `edge > k·cost` for k ∈ {1, 1.5, 2}. Pre-register the choice rule as "smallest k with holdout net Sharpe ≥ 0 at 2x costs".
   - **Success:** holdout net Sharpe at 2x costs ≥ 0.
   - **Fail:** below 0, the strategy only exists at optimistic costs. Also track live turnover and live costs as a share of gross P&L, with an alarm above 50%.
7. **Check that the p→μ mapping and Kelly are calibrated.**
   - Regress the realised 5-day return (in σ units) on the predicted `mu_h` (in σ units) using live and holdout predictions.
   - **Success:** the slope is > 0 and its 95% CI contains 1.
   - **Fail:** a slope < 0.5 means Kelly over-sizes, so scale `KELLY_FRACTION` by the slope. A slope ≤ 0 means no sizing signal at all.
8. **Look-ahead audit for features and the LLM.**
   - (a) A FreqAI-style automated test: recompute all 14 features on data truncated at t and require them to equal the full-history features at t.
   - (b) An LLM memorisation probe: ask the LLM analyst for P(up 5d) on dates before and after its training cutoff.
   - **Interpretation of (b):** much higher hit rates before the cutoff (two-proportion test, p < 0.05) confirm memorisation and keep the LLM strictly forward-only, as it is now. A rejected test should *not* be read as permission to backtest it.
9. **Survivorship-bias check for stocks.**
   - Re-run the stock-class holdout with an index-membership-at-date universe, if such data can be obtained, or else with a randomly drawn set of non-mega-cap large caps.
   - **Success:** the stock-class holdout Sharpe stays within 0.2 of the current result.
   - **Fail:** a larger gap means today's stock results are survivorship-inflated, and that is documented in `docs/ASSUMPTIONS.md`.

---

## Sources

**LLM / agent trading**
- [Forklog: four out of six AI models suffer losses in trading tournament](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/) (secondary)
- [GNcrypto: Qwen wins Alpha Arena Season 1 with 22% returns](https://www.gncrypto.news/news/qwen-wins-alpha-arena-season-1-with-22-percent-returns/) (secondary)
- [Wallstreetcn on Alpha Arena failure modes (Chinese)](https://wallstreetcn.com/articles/3771681) (secondary)
- [ThinkAdvisor 2026: why AI bots aren't ready to replace your fund manager](https://www.thinkadvisor.com/amp/2026/05/06/why-ai-bots-arent-ready-to-replace-your-fund-manager/) (secondary; not read)
- [TradingAgents, arXiv 2412.20138](https://arxiv.org/abs/2412.20138v1); [project site](https://tradingagents-ai.github.io); [Hugging Face page](https://huggingface.co/papers/2412.20138)
- [FINSABER: Can LLM-based Financial Investing Strategies Outperform the Market in Long Run? arXiv 2505.07078](https://arxiv.org/pdf/2505.07078)

**Look-ahead / memorisation**
- [A Test of Lookahead Bias in LLM Forecasts, arXiv 2512.23847](https://arxiv.org/html/2512.23847v1)
- [The Memorization Problem, arXiv 2504.14765](https://arxiv.org/html/2504.14765v2)
- [MemGuard-Alpha, arXiv 2603.26797](https://arxiv.org/pdf/2603.26797)
- [Look-Ahead-Bench (RePEc listing of arXiv 2601.13770)](https://econpapers.repec.org/paper/arxpapers/2601.13770.htm)

**Open-source projects**
- [Microsoft Qlib benchmarks](https://github.com/microsoft/qlib/blob/main/examples/benchmarks)
- [Freqtrade FreqAI docs (CodeClimate mirror)](https://codeclimate.com/github/freqtrade/freqtrade/docs/freqai.md/source); [FreqAI paper, JOSS](https://joss.theoj.org/papers/10.21105/joss.04864.pdf)
- [Numerai: Meta Model Contribution](https://docs.numer.ai/numerai-tournament/scoring/meta-model-contribution-mmc); [True Contribution](https://docs.numer.ai/numerai-tournament/scoring/true-contribution-tc); [Signals scoring definitions](https://docs.numer.ai/numerai-signals/scoring/definitions); [office-hours recap on feature neutralisation](https://docs.numer.ai/community/community-built-products/numerai-community-office-hours/office-hours-recaps-season-3/ohwa-s03e04)

**Overfitting and out-of-sample evidence**
- [Bailey, Borwein, López de Prado, Zhu: The Probability of Backtest Overfitting (SSRN)](https://papers.ssrn.com/abstract=2326253); [full text (eScholarship)](https://escholarship.org/content/qt4w1110bb/qt4w1110bb.pdf); [CRAN pbo package](https://packages.oit.ncsu.edu/cran/web/packages/pbo/readme/README.html)
- [Harvey, Liu & Zhu, NBER w20592](https://nber.org/papers/w20592); [RFS listing](https://econpapers.repec.org/RePEc:oup:rfinst:v:29:y:2016:i:1:p:5-68.)
- [Gu, Kelly & Xiu, NBER w25398](https://nber.org/papers/w25398); [RFS listing](https://econpapers.repec.org/RePEc:oup:rfinst:v:33:y:2020:i:5:p:2223-2273.)
- [Moskowitz, Ooi & Pedersen, Time Series Momentum (SSRN)](https://papers.ssrn.com/abstract=2089463); [JFE listing](https://econpapers.repec.org/RePEc:eee:jfinec:v:104:y:2012:i:2:p:228-250); [Quantpedia: Deconstructing the Time-Series Momentum Strategy (Kim, Tse & Wald summary)](https://quantpedia.com/deconstructing-the-time-series-momentum-strategy/) (secondary)
- Deflated Sharpe Ratio: Bailey & López de Prado (2014), J. Portfolio Management 40(5). This is the repository's citation; I found no URL for it.
