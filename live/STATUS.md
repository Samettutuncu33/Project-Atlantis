# Atlantis status (SIMULATION ONLY)

Last run: 2026-11-11T22:54:06+00:00 · last bar: 2026-11-10 · mode: **RUNNING** · Claude API spend this month: **$0.46**

| Account | Strategy | Equity $ | Return % | Fills | Open positions | Max drawdown % |
|---|---|---|---|---|---|---|
| A | Trend 12m · conservative | 200.00 | +0.00 | 0 | 0 | 0.0 |
| B | Trend 12m · min ticket | 196.04 | -1.98 | 4 | 4 | -4.4 |
| C | Breakout 55/20 · conservative | 200.00 | +0.00 | 0 | 0 | 0.0 |
| D | Breakout 55/20 · min ticket | 205.98 | +2.99 | 3 | 3 | 0.0 |
| E | Atlantis Adaptive · multi-asset, self-learning | 198.99 | -0.51 | 2 | 2 | -0.5 |
| F | Atlantis Intraday · hourly, news + daily/weekly context | 199.85 | -0.08 | 8 | 0 | -3.2 |

## Open positions

| Account | Name | Qty | Value $ | P&L $ |
|---|---|---|---|---|
| B | Euro / US dollar | -1000.0 | 1135.35 | 13.16 |
| B | British pound / US dollar | 1000.0 | 1327.31 | -16.8 |
| B | US dollar / Japanese yen | 1000.0 | 999.89 | 11.19 |
| B | Australian dollar / US dollar | 1000.0 | 684.63 | -7.51 |
| D | Euro / US dollar | -1000.0 | 1135.35 | 13.16 |
| D | US dollar / Japanese yen | -1000.0 | 977.25 | -11.43 |
| D | Australian dollar / US dollar | -1000.0 | 699.3 | 7.25 |
| E | Nikkei 225 index (Japan) | 0.3 | 113.14 | -0.72 |
| E | WTI crude oil | 1.0 | 86.17 | -0.3 |

## Last fills

| Time | Account | Symbol | Side | Qty | Price |
|---|---|---|---|---|---|
| 2026-11-10T00:00:00+00:00 | E | JPNIDXJPY | BUY | 0.3 | 60645.481 |
| 2026-11-10T00:00:00+00:00 | E | LIGHTCMDUSD | BUY | 1.0 | 86.47 |
| 2026-11-09T18:00:00+00:00 | F | JPNIDXJPY | BUY | 0.4 | 60527.634 |
| 2026-11-10T12:00:00+00:00 | F | JPNIDXJPY | BUY | 0.3 | 60121.583 |
| 2026-11-10T15:00:00+00:00 | F | JPNIDXJPY | SELL | 0.2 | 60458.417 |
| 2026-11-10T15:00:00+00:00 | F | USA500IDXUSD | BUY | 0.1 | 7529.332 |
| 2026-11-10T16:00:00+00:00 | F | USA500IDXUSD | SELL | 0.1 | 7489.603 |
| 2026-11-11T13:00:00+00:00 | F | JPNIDXJPY | SELL | 0.5 | 61785.417 |
| 2026-11-11T16:00:00+00:00 | F | JPNIDXJPY | BUY | 0.7 | 62117.634 |
| 2026-11-11T21:00:00+00:00 | F | JPNIDXJPY | SELL | 0.7 | 61942.519 |

## Checks

- **CRITICAL** prediction_ledger_append_only:E: earlier predictions changed: first difference at record 66 of 96940 (resolution 2017-01-18T00:00:00+00:00:DEUIDXEUR); stored ledger kept
- **CRITICAL** prediction_ledger_append_only:F: earlier predictions changed: first difference at record 0 of 1223 (checkpoint ); stored ledger kept
- **CRITICAL** journal_append_only: 5 earlier fills changed (first at line 1)
