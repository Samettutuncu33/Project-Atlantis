# Atlantis status (SIMULATION ONLY)

Last run: 2026-11-13T09:49:24+00:00 · last bar: 2026-11-12 · mode: **RUNNING** · Claude API spend this month: **$0.46**

| Account | Strategy | Equity $ | Return % | Fills | Open positions | Max drawdown % |
|---|---|---|---|---|---|---|
| A | Trend 12m · conservative | 200.00 | +0.00 | 0 | 0 | 0.0 |
| B | Trend 12m · min ticket | 190.79 | -4.60 | 4 | 4 | -4.6 |
| C | Breakout 55/20 · conservative | 200.00 | +0.00 | 0 | 0 | 0.0 |
| D | Breakout 55/20 · min ticket | 219.99 | +10.00 | 4 | 2 | 0.0 |
| E | Atlantis Adaptive · multi-asset, self-learning | 203.83 | +1.92 | 2 | 2 | -0.5 |
| F | Atlantis Intraday · hourly, news + daily/weekly context | 200.50 | +0.25 | 11 | 1 | -3.2 |

## Open positions

| Account | Name | Qty | Value $ | P&L $ |
|---|---|---|---|---|
| B | Euro / US dollar | -1000.0 | 1138.43 | 16.24 |
| B | British pound / US dollar | 1000.0 | 1323.49 | -20.62 |
| B | US dollar / Japanese yen | 1000.0 | 999.99 | 12.0 |
| B | Australian dollar / US dollar | 1000.0 | 679.49 | -12.65 |
| D | Euro / US dollar | -1000.0 | 1138.43 | 16.24 |
| D | Australian dollar / US dollar | -1000.0 | 704.51 | 12.46 |
| E | Nikkei 225 index (Japan) | 0.3 | 115.39 | 1.62 |
| E | WTI crude oil | 1.0 | 88.7 | 2.23 |
| F | Nikkei 225 index (Japan) | 0.7 | 267.23 | -0.83 |

## Last fills

| Time | Account | Symbol | Side | Qty | Price |
|---|---|---|---|---|---|
| 2026-11-10T12:00:00+00:00 | F | JPNIDXJPY | BUY | 0.3 | 60121.583 |
| 2026-11-10T15:00:00+00:00 | F | JPNIDXJPY | SELL | 0.2 | 60458.417 |
| 2026-11-10T15:00:00+00:00 | F | USA500IDXUSD | BUY | 0.1 | 7529.332 |
| 2026-11-10T16:00:00+00:00 | F | USA500IDXUSD | SELL | 0.1 | 7489.603 |
| 2026-11-11T13:00:00+00:00 | F | JPNIDXJPY | SELL | 0.5 | 61785.417 |
| 2026-11-11T16:00:00+00:00 | F | JPNIDXJPY | BUY | 0.7 | 62117.634 |
| 2026-11-11T21:00:00+00:00 | F | JPNIDXJPY | SELL | 0.7 | 61942.519 |
| 2026-11-12T00:00:00+00:00 | F | JPNIDXJPY | BUY | 0.7 | 61400.532 |
| 2026-11-13T03:00:00+00:00 | F | JPNIDXJPY | SELL | 0.7 | 61747.315 |
| 2026-11-13T04:00:00+00:00 | F | JPNIDXJPY | BUY | 0.7 | 61237.583 |

## Checks

- **CRITICAL** prediction_ledger_append_only:E: earlier predictions changed: first difference at record 66 of 97020 (resolution 2017-01-18T00:00:00+00:00:DEUIDXEUR); stored ledger kept
- **CRITICAL** prediction_ledger_append_only:F: earlier predictions changed: first difference at record 0 of 2625 (checkpoint ); stored ledger kept
- **CRITICAL** journal_append_only: 5 earlier fills changed (first at line 1)
