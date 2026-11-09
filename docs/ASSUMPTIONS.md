# Assumptions and unavailable data

Every number the simulator uses is labelled in `atlantis/config/saxo_conditions.yaml` with one of four statuses:

- `SAXO_PUBLISHED`: taken from a public Saxo page.
- `REGULATION`: set by regulation.
- `ASSUMPTION`: a documented choice of ours.
- `UNAVAILABLE`: not public, so the engine will not use it.

This file explains each `ASSUMPTION` and `UNAVAILABLE` item. Where something is uncertain, the assumption is chosen to be **conservative**, meaning it costs the simulated account more rather than less.

| ID | Item | What we do | Why / effect |
|----|------|-----------|--------------|
| A1 | FX $1 minimum commission threshold | Charge $1 on **every** FX ticket | Saxo says the $1 minimum applies to "small notional trade sizes"; the threshold is only shown in a JS table. Every trade from a $200 account is small. |
| A2 | FX commission rate (per notional) | 0 (spread-only) | Classic-tier FX is advertised as priced through spreads; the per-pair rates are only shown in JS. |
| A3 | Saxo FX spreads | Execute at **Dukascopy** real bid/ask; `extra_spread_bps` sweep of +1 and +3 bps | Saxo's spreads are not public. Dukascopy spreads are real market quotes but come from a different venue. Daily candle opens are at 00:00 UTC, shortly after the 22:00 UTC rollover, when spreads can be wider than usual. That is conservative. |
| A4 | Minimum trade size | 1,000 base units, step 1 | Saxo shows this behind an "info" button on the trade ticket. **This is the most important assumption for a $200 account.** |
| A5 | Overnight interest-rate differential | Set to 0. We charge only Saxo's published mark-ups: 0.75% p.a. Tom/Next on notional and 2% p.a. on unrealised P&L | Needs daily SOFR/€STR/SONIA/TONAR history, which is not yet sourced. Real carry would help some positions and hurt others. |
| A5b | Tom/Next mark-up application | 0.75% p.a. applied once per position on notional | Saxo applies the mark-up to each currency's derived interest rate. If both legs are marked up, the effective cost can reach about 1.5% p.a. For TSMOM this is the single largest cost item, so the published figure is a **lower bound**. |
| A13 | Sunday re-open bars | Removed from the trading calendar | Measured EURUSD median spread: Sunday open 2.3 pips vs 0.4 pips on weekdays. Orders fill at Monday's 00:00 UTC open instead. |
| A6 | Currency conversion fee on FX P&L | 0.25% on every non-USD realised P&L | Saxo's wording is ambiguous for FX spot; we pick the costlier reading. |
| A7 | Pip size for metals | XAU 0.01, XAG 0.001 | Used only to convert Saxo's slippage statistics, which are quoted in pips. |
| A8 | Slippage | Deterministic expected value: Saxo's published *average net* slippage per pair and order type (Aug 2026) | These are aggregate statistics across all Saxo clients. Our individual fills are not real executions. |
| A9 | Limit orders | A fill needs the bar to trade **through** the limit by at least 1 pip | Queue position is unknown, so touching the limit is not counted as a fill. |
| A10 | Same-bar stop vs. target | Not applicable yet (no take-profit orders); stops fill at the trigger or at the gapped open | |
| A11 | Margin close-out | Checked against each bar's worst prices; liquidated at those worst prices | Daily bars cannot show the intraday path, so we assume the worst case. |
| A12 | Daily bar boundary | 00:00 UTC (Dukascopy), not 17:00 New York (Saxo's rollover) | Financing is charged per calendar day elapsed. |

## Unavailable (not used)
- **Saxo historical prices and bid/ask.** They require an authenticated OpenAPI. Phase 2 will add them once you provide SIM access.
- **Saxo per-instrument spreads, minimum sizes and commission tables.** Saxo's pages load these via an internal pricing service. We do not script calls to that service.
- **Equity, ETF and CFD conditions** (commissions, exchange fees, borrow costs). Those asset classes are deferred until the data can be sourced.
- **Our own real executions.** None exist, and all fills are simulated.
