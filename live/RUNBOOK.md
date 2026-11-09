# Scheduled live-simulation run (every 6 hours)

Atlantis Live page (monitoring + start/stop): https://claude.ai/artifact/SG2VmB7APqkgiKyShrSHTD
(The older dashboard AWBpwhmciFEZQZuu8Tp1TY is retired and is no longer updated.)
Repository: https://github.com/WildSideMelbourne/project-atlantis (branch `main`)

SIMULATION ONLY. No real orders, ever. From the IBKR connector, use only `search_contracts`,
`get_price_history` and `get_price_snapshot`. Never call order, order-instruction, alert, watchlist,
screener-write, account, balance, position or trade tools.

0. **Memory:** read the last 60 lines of `knowledge/journal.md` before anything else.
1. Clone the repo, then `pip install -q -e .` and `pip install -q lightgbm scikit-learn`.
2. **IBKR market data (optional; skip if IBKR is unavailable):** for each symbol in
   `atlantis/intel/sources/ibkr_files.py::CONTRACTS`, call `get_price_history(contract_id, security_type,
   step=ONE_DAY, period=ONE_MONTH, outside_rth=false)`. Save the JSON answer verbatim, plus
   `symbol`, `contract_id`, `security_type`, `retrieved_utc` and `tool`, to `data/ibkr/<SYMBOL>_<conid>_<YYYY-MM-DD>.json`.
   Call IBKR one request at a time; it refuses parallel calls.
2a. **Control Panel (start/stop):** ArtifactData `list` collection `events` on
   https://claude.ai/artifact/SG2VmB7APqkgiKyShrSHTD with `out_dir` /tmp/panel, then
   `python scripts/sync_controls.py /tmp/panel`. This appends new presses to `live/controls.jsonl`.
   Never edit that file by hand; the simulation obeys it (PAUSED = no new risk, FLATTEN = close all, then paused).
2b. **AI analyst (forward-only predictor `llm_analyst`):** run `python scripts/analyst_brief.py`. It prints the
   latest completed bar's indicators per instrument and the file to write, `data/llm/<bar-date>.json`.
   If that file already exists, do NOT change it: predictions are append-only. Otherwise study the briefing and
   write `{"made_at": "<UTC now>", "analyst": "claude", "probs": {"<SYMBOL>": <P(up in 5 trading days)>, ...}}`.
   Use well-calibrated probabilities: most should sit between 0.45 and 0.55, and go further only with a reason.
   Omit any instrument you have no view on. You will be scored by Brier score against the other predictors.
3. `python -m atlantis.live step`. Exit code 2 means a check failed. Continue anyway, so the dashboard shows the failure.
   If it crashes, retry once. If it crashes again, stop and report. Never publish stale data as new.
4. Upload `live/out/live.json` to https://claude.ai/artifact/SG2VmB7APqkgiKyShrSHTD as an asset (Artifact tool, `asset: true`).
   Note the returned `/_blob/<id>`.
5. **Publish to the page:** ArtifactData `get` doc `latest` in collection `status` on that page (note its version). Then `set` it,
   pinned with `if_version`, to `{run_utc, last_completed_bar, trading_mode, live_json: "/_blob/<id>",
   accounts: [{account, equity}, ...]}`, taken from `live/out/live.json`. The page reloads its data from `live_json`.
   Delete the previous run's asset only if nothing references it.
6. **Journal:** append one dated entry to the END of `knowledge/journal.md` with 3–6 factual lines:
   notable moves, which predictors were right or wrong, gate rejections, data problems. Never edit earlier entries.
7. Commit `live/`, `knowledge/`, `data/llm/`, `data/ibkr/` and `data/raw/dukascopy_live/` with the message `live run <run_utc>`,
   then `git pull --rebase origin main` and `git push origin main`.
8. Report the five account equities, new fills, how many predictions were newly scored and the hit rate,
   any know-how weight that changed by more than 5 points, and any check that is not OK.
