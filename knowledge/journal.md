# Atlantis memory journal

Every scheduled run reads the end of this file first and appends a dated entry at the end.
Facts only: what happened, what was predicted, what turned out right or wrong, and anything odd in the data.
No edits to past entries.

## 2026-11-09 setup (session that built the system)
- Live start is 9 Nov 2026; the first fills land at the 10 Nov 00:00 UTC open.
- NVDA gapped about -7% at the 9 Nov open (IBKR: Friday close 186.64, about 173 at the open). Watch how stocks behave this week.
- Baseline signals at start. Trend: short EURUSD; long GBPUSD, USDJPY and AUDUSD. Breakout: short EURUSD, USDJPY and AUDUSD.
- Known limits:
  - BTC is unreachable at $200, because 0.01 BTC needs $400 of ESMA margin.
  - The conservative FX accounts (A, C) round every position to zero.

## 2026-11-09 external research
- 2026-11-09: Short live LLM contests prove little. In Alpha Arena S1 (about 17 days, 6 models), 4 of 6 lost money (GPT-5 about -63%), and press reports cited over-trading. Atlantis' first weeks are noise in the same way. Details: research/notes/2026-11-09-external-trading-ai-lessons.md
- 2026-11-09: FINSABER (2004-2024 re-test) found that FinMem/FinAgent-style LLM edges fade over long periods and broad universes. Judge E by regime (bull/bear/sideways), not only in aggregate.
- 2026-11-09: LLMs memorise pre-cutoff financial data, so an LLM backtest is invalid. Keep llm_analyst strictly forward-only, as it is now.
- 2026-11-09: Our own holdout (2020-2025) annualised Sharpe is negative for all three rules: tsmom -0.04, donchian -0.29, reversal -0.85. No predictor has demonstrated edge yet.
- 2026-11-09: trials.jsonl holds only 8 rule trials. ML, feature, Hedge and calibrator choices are unlogged, so the Deflated Sharpe is too optimistic (Harvey-Liu-Zhu bar: t > 3).
- 2026-11-09: Qlib LightGBM on Alpha158 shows only IC about 0.04-0.05 across about 300 stocks. With 20 instruments, expect AUC barely above 0.5 and months of data before any significance.
- 2026-11-09: Numerai pays for orthogonal (marginal) contribution. Trend and breakout probably double-count in Hedge, so test leave-one-out ensemble Brier.
- 2026-11-09: Pre-registered live test proposed: after 26 weeks, E's Brier skill score vs the trailing base rate must have a block-bootstrap 95% CI above 0; otherwise cut sizing.
