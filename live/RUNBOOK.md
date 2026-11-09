# Scheduled live-simulation run (every hour)

Page (monitoring + start/stop): https://claude.ai/artifact/SG2VmB7APqkgiKyShrSHTD ("Atlantis Live")
Repository: https://github.com/WildSideMelbourne/project-atlantis (branch `main`)

SIMULATION ONLY. No real orders, ever. From the IBKR connector, if present, use only `search_contracts`,
`get_price_history` and `get_price_snapshot`. Never call order, order-instruction, alert, watchlist,
screener-write, account, balance, position or trade tools.

Accounts: A–D are fixed-rule daily baselines; E is daily adaptive (5-day predictions);
F is hourly adaptive (4-hour predictions, with daily/weekly context, news and the hourly AI analyst).

## Every hour
0. **Memory:** read the last 60 lines of `knowledge/journal.md`.
1. Clone the repo, then `pip install -q -e . lightgbm scikit-learn`.
2. **Control Panel:** ArtifactData `list` collection `events` on the page above with `out_dir` /tmp/panel, then
   `python scripts/sync_controls.py /tmp/panel`. Never edit `live/controls.jsonl` by hand.
3. **Breaking-news flash (agent `atlantis-news-analyst`, quick mode, at most 3 searches):** look only for
   market-moving news from the last 2 hours: central banks, data surprises, company or crypto shocks, oil and geopolitics.
   If there is any, write `knowledge/intel/flash/<YYYY-MM-DDTHH>.json` in the brief format and validate it with
   `python -m atlantis.intel.news validate <file>`. If there's nothing, write nothing.
4. **Hourly AI analyst (predictor `llm_analyst` for account F):** run `python scripts/analyst_brief_hourly.py`.
   Unless it prints SKIP, study the hourly charts, the daily and weekly context, the latest news brief and the flashes, then write
   `data/llm/hourly/<YYYY-MM-DDTHH>.json` = `{"made_at", "analyst": "claude", "probs": {SYMBOL: P(up in 4 hours)}}`.
   Keep probabilities calibrated (mostly 0.45–0.55; go further only with a concrete reason) and omit what you have no view on.
5. `python -m atlantis.live step`. Exit code 2 means a check failed: continue, so the page shows it.
   If it crashes, retry once. If it crashes again, stop and report. Never publish stale data as new.
6. Upload `live/out/live.json` to the page as an asset (Artifact tool, `asset: true`). Then ArtifactData `get` doc
   `latest` in collection `status` (note its version) and `set` it, pinned with `if_version`, to `{run_utc, last_completed_bar,
   trading_mode, live_json: "/_blob/<id>", accounts: [{account, equity}]}`. Delete the previous asset if nothing references it.
7. Commit `live/`, `knowledge/`, `data/llm/`, `data/ibkr/` and `data/raw/dukascopy_live/` with the message `live run <run_utc>`,
   then `git pull --rebase origin main` and `git push origin main`.
8. Report the trading mode, the equity of accounts A–F, new fills, newly scored predictions with their hit rate, and every check that is not OK.

## Additionally, in the first run after 00:00 UTC (daily)
- **Daily news and market-intelligence brief** (agent `atlantis-news-analyst`, full mode): write `knowledge/intel/<bar-date>.json`
  (the bar date printed by `scripts/analyst_brief.py`) and validate it. Use only dated, sourced items from the last 72 hours.
- **Daily AI analyst (account E):** run `python scripts/analyst_brief.py`. Unless it prints SKIP, read today's brief and write
  `data/llm/<bar-date>.json` with P(up in 5 trading days).
- **Journal:** append one dated entry to the END of `knowledge/journal.md` (3–6 factual lines). Never edit earlier entries.
