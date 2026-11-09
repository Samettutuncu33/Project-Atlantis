# Scheduled live-simulation run (every 6 hours)

Dashboard: https://claude.ai/artifact/AWBpwhmciFEZQZuu8Tp1TY
Repository: https://github.com/WildSideMelbourne/project-atlantis (branch `main`)

SIMULATION ONLY. No real orders, ever. From the IBKR connector, use only `search_contracts`,
`get_price_history` and `get_price_snapshot`. Never call order, order-instruction, alert, watchlist,
screener-write, account, balance, position or trade tools.

1. Clone the repo, then `pip install -q -e .` and `pip install -q lightgbm scikit-learn`.
2. **IBKR market data (optional; skip if IBKR is unavailable):** for each symbol in
   `atlantis/intel/sources/ibkr_files.py::CONTRACTS`, call `get_price_history(contract_id, security_type,
   step=ONE_DAY, period=ONE_MONTH, outside_rth=false)`. Save the JSON answer verbatim, plus
   `symbol`, `contract_id`, `security_type`, `retrieved_utc` and `tool`, to `data/ibkr/<SYMBOL>_<conid>_<YYYY-MM-DD>.json`.
   Call IBKR one request at a time; it refuses parallel calls.
3. `python -m atlantis.live step`. Exit code 2 means a check failed. Continue anyway, so the dashboard shows the failure.
   If it crashes, retry once. If it crashes again, stop and report. Never publish stale data as new.
4. Upload `live/out/live.json` to the dashboard as an asset (Artifact tool, `asset: true`, dashboard url). Note the `/_blob/<id>`.
5. `python scripts/dashboard_updates.py /_blob/<id> /tmp/dash` writes one update per dataset.
   Read each `datasets/<id>` document for its version. Then send one ArtifactData `batch` of `update` writes,
   pinned with `if_version`, each using `file_path` /tmp/dash/<id>.json. A dataset that does not exist yet is created with `set`.
6. Commit `live/`, `knowledge/`, `data/ibkr/` and `data/raw/dukascopy_live/` with the message `live run <run_utc>`,
   then `git pull --rebase origin main` and `git push origin main`.
7. Report the five account equities, new fills, how many predictions were newly scored and the hit rate,
   any know-how weight that changed by more than 5 points, and any check that is not OK.
