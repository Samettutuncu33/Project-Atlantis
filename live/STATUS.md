# Atlantis status (SIMULATION ONLY)

Last run: 2026-11-12T03:59:19+00:00 · last bar: 2026-11-11 · mode: **RUNNING** · Claude API spend this month: **$0.46**

| Account | Strategy | Equity $ | Return % | Fills | Open positions | Max drawdown % |
|---|---|---|---|---|---|---|
| A | Trend 12m · conservative | 200.00 | +0.00 | 0 | 0 | 0.0 |
| B | Trend 12m · min ticket | 195.58 | -2.21 | 4 | 4 | -4.4 |
| C | Breakout 55/20 · conservative | 200.00 | +0.00 | 0 | 0 | 0.0 |
| D | Breakout 55/20 · min ticket | 214.18 | +7.09 | 4 | 2 | 0.0 |
| E | Atlantis Adaptive · multi-asset, self-learning | 201.11 | +0.55 | 2 | 2 | -0.5 |
| F | Atlantis Intraday · hourly, news + daily/weekly context | 201.03 | +0.52 | 9 | 1 | -3.2 |

## Open positions

| Account | Name | Qty | Value $ | P&L $ |
|---|---|---|---|---|
| B | Euro / US dollar | -1000.0 | 1137.16 | 14.97 |
| B | British pound / US dollar | 1000.0 | 1325.52 | -18.59 |
| B | US dollar / Japanese yen | 1000.0 | 999.99 | 11.37 |
| B | Australian dollar / US dollar | 1000.0 | 684.06 | -8.08 |
| D | Euro / US dollar | -1000.0 | 1137.16 | 14.97 |
| D | Australian dollar / US dollar | -1000.0 | 699.93 | 7.88 |
| E | Nikkei 225 index (Japan) | 0.3 | 115.23 | 1.38 |
| E | WTI crude oil | 1.0 | 86.21 | -0.26 |
| F | Nikkei 225 index (Japan) | 0.7 | 270.14 | 1.19 |

## Last fills

| Time | Account | Symbol | Side | Qty | Price |
|---|---|---|---|---|---|
| 2026-11-10T00:00:00+00:00 | E | LIGHTCMDUSD | BUY | 1.0 | 86.47 |
| 2026-11-09T18:00:00+00:00 | F | JPNIDXJPY | BUY | 0.4 | 60527.634 |
| 2026-11-10T12:00:00+00:00 | F | JPNIDXJPY | BUY | 0.3 | 60121.583 |
| 2026-11-10T15:00:00+00:00 | F | JPNIDXJPY | SELL | 0.2 | 60458.417 |
| 2026-11-10T15:00:00+00:00 | F | USA500IDXUSD | BUY | 0.1 | 7529.332 |
| 2026-11-10T16:00:00+00:00 | F | USA500IDXUSD | SELL | 0.1 | 7489.603 |
| 2026-11-11T13:00:00+00:00 | F | JPNIDXJPY | SELL | 0.5 | 61785.417 |
| 2026-11-11T16:00:00+00:00 | F | JPNIDXJPY | BUY | 0.7 | 62117.634 |
| 2026-11-11T21:00:00+00:00 | F | JPNIDXJPY | SELL | 0.7 | 61942.519 |
| 2026-11-12T00:00:00+00:00 | F | JPNIDXJPY | BUY | 0.7 | 61400.532 |

## Checks

- **CRITICAL** prediction_ledger_append_only:E: earlier predictions changed: first difference at record 66 of 96940 (resolution 2017-01-18T00:00:00+00:00:DEUIDXEUR); stored ledger kept
- **CRITICAL** prediction_ledger_append_only:F: earlier predictions changed: first difference at record 0 of 1223 (checkpoint ); stored ledger kept
- **CRITICAL** journal_append_only: 5 earlier fills changed (first at line 1)
