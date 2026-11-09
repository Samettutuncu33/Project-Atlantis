# Roadmap

| # | Step | Status |
|---|------|--------|
| 1 | Skeleton, docs, tooling, safety tests | ✅ done |
| 2 | Data layer: Dukascopy bid/ask fetcher, Parquet store, validation, provenance manifest | ✅ done. Full universe download is in progress; the feed throttles this cloud IP heavily. |
| 3 | Saxo public conditions transcribed with citations; execution statistics | ✅ done (FX/metals) |
| 4 | Orders (market/limit/stop, DAY/GTC), fills, costs, FIFO multi-currency ledger, ESMA margin close-out, negative balance protection | ✅ done; property-tested |
| 5 | Vol-target sizing, min-ticket rounding, margin cap, Carver buffer | ✅ done |
| 6 | Analytics, HTML report, quantstats cross-check, independent reconciliation | ✅ done |
| 7 | TSMOM, Donchian breakout, short-term reversal, benchmark; look-ahead detector | ✅ done |
| 8 | Pairs / stat-arb (cointegration), multi-asset risk parity, ML-assisted research (purged CV) | ⏳ needs the multi-symbol universe |
| 9 | Walk-forward stop vs. no-stop study, PBO (CSCV), parameter-stability maps | ⏳ |
| 10 | Benchmark overnight rates for real carry (A5) | ⏳ needs a rates source (e.g. FRED, after host approval) |
| 11 | **Phase 2:** Saxo SIM read-only adapter: Saxo charts, instrument details, real min sizes and spreads, replacing A3/A4 | 🔒 adapter built and disabled; waiting for your SIM access |
| 12 | Equities/ETFs (Saxo $1 minimum commissions) | ⏳ needs a price source reachable from this environment |
