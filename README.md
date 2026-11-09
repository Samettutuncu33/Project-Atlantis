# PROJECT ATLANTIS

A quantitative trading research and **simulation-only** platform. It starts with $200 of virtual capital, uses Saxo Bank's published trading conditions, and runs on real historical bid/ask data.

> **This platform never connects to a live broker.** It cannot place orders and never handles your credentials. Every fill is labelled `SIMULATED`. Market data is labelled with its source; current price data is **Dukascopy, not Saxo**.

## Quick start
```bash
pip install -e ".[dev]"
python -m pytest -q                     # 40+ tests: golden trades, property tests, safety
python scripts_prefetch.py              # download raw bid/ask files (slow, cached, resumable)
python scripts_build_offline.py         # validate + store from cache
python -m atlantis.cli research         # run the pre-registered research protocol -> reports/report.html
python -m atlantis.cli audit            # verify data hashes and list validation issues
```

## Layout
- `atlantis/data`: Dukascopy source, validation, hashed Parquet store, Saxo SIM adapter (disabled, read-only).
- `atlantis/config/saxo_conditions.yaml`: every Saxo input, with a status (published, regulation, assumption, unavailable) and its citation.
- `atlantis/sim`: orders, bid/ask fill model, Saxo cost model, simulated broker.
- `atlantis/portfolio/ledger.py`: double-entry multi-currency ledger with Saxo FIFO netting.
- `atlantis/risk/sizing.py`: vol targeting, min-ticket rounding, ESMA margin cap.
- `atlantis/strategies`: TSMOM, Donchian, short-term reversal, benchmark.
- `atlantis/engine.py`: event-driven daily backtester with an automatic look-ahead detector.
- `atlantis/checks/reconcile.py`: independent FIFO recomputation of every run.
- `atlantis/research`: protocol runner, Deflated Sharpe, Kelly, block-bootstrap target analysis.
- `docs/`: assumptions, risk method, data sources, roadmap.
