# Data sources (researched 2026-11-09)

| Source | What | Access | Status |
|---|---|---|---|
| Dukascopy `datafeed.dukascopy.com` | Daily bid **and** ask OHLC candles for FX and metals, 2010 onwards | Public, no login | **Used.** Real two-sided quotes, **not Saxo**. Its servers often reset connections from this cloud environment, so the fetcher retries with backoff and caches every file with a SHA256. |
| Saxo public site `www.home.saxo` | Commissions, financing mark-ups, conversion fee, trading hours, FIFO rule, **monthly FX execution statistics** | Public | **Used.** Text snapshots and hashes are in `data/saxo_public_snapshots/`; values are transcribed into `saxo_conditions.yaml` with quotes. |
| Saxo developer portal `www.developer.saxo` | OpenAPI reference (endpoint shapes for Phase 2) | Public docs | Reachable. Used to design the SIM adapter. |
| Saxo internal pricing service (behind the site's JS tables) | Per-pair spreads, minimum sizes | Undocumented internal service | **Not used.** Scripting calls to it was judged inappropriate. These values are UNAVAILABLE until Phase 2. |
| Saxo OpenAPI SIM `gateway.saxobank.com/sim/openapi` | Historical charts, instrument details | Needs an OAuth token | **Phase 2**, once you provide access. Read-only, SIM-only adapter is built and disabled. |
| Stooq | Daily ETF and index bars | Public | Unreachable from this environment (connections reset). |

## Labelling
- Every stored dataset has a manifest. It records the source, raw-file URLs and hashes, retrieval time, validation issues, and the label "HISTORICAL MARKET DATA (non-Saxo source)".
- Every simulated fill carries `label: SIMULATED`.
- The report tags each section MARKET DATA or SIMULATED.
