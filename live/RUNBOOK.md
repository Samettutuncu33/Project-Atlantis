# Atlantis runs: who does what (Claude API mode, from 9 Nov 2026)

- **GitHub Actions, every hour at :25, Mon–Fri** (no Saxo trading hours at weekends) (`.github/workflows/hourly-simulation.yml`), no Claude plan needed:
  1. AI agents through the Claude API (repo secret `ANTHROPIC_API_KEY`, `scripts/ai_api_runner.py`):
     news brief with web search + daily AI analyst (account E) at 00 UTC; hourly AI analyst (account F) at 00/06/12/18 UTC.
     Every call's real cost goes to `live/api_spend.jsonl`; calls stop when the month would pass $18.
  2. `python -m atlantis.live step` (accounts A–F), then `live/STATUS.md` (readable on GitHub), then commit.
- **AI runner session on the Claude plan: PAUSED.** If re-enabled, it only syncs the Control Panel and uploads
  `live/out/live.json` to the page (steps 2 and 6 below); it writes no news or forecast files (the API runner does).

# Scheduled live-simulation run

Page (monitoring + start/stop): https://claude.ai/artifact/SG2VmB7APqkgiKyShrSHTD ("Atlantis Live")
Repository: https://github.com/Samettutuncu33/Project-Atlantis (branch `main`)

SIMULATION ONLY. No real orders, ever. From the IBKR connector, if present, use only `search_contracts`,
`get_price_history` and `get_price_snapshot`. Never call order, order-instruction, alert, watchlist,
screener-write, account, balance, position or trade tools.

Accounts: A–D are fixed-rule daily baselines; E is daily adaptive (5-day predictions);
F is hourly adaptive (4-hour predictions, with daily/weekly context, news and the hourly AI analyst).

## Live reporting to the command view (do this throughout the run)
The page's command view shows the agents live. Report on the page above with ArtifactData:
- **At the very start:** `set` doc `run` in collection `pipeline` to
  `{run_id: "<YYYYMMDDTHH>", state: "running", started_at: "<UTC now>", stages: {controls: "running", news: "idle",
  analyst: "idle", simulation: "idle", publish: "idle", commit: "idle"}, details: {}}`.
- **After each stage** (controls, news, analyst, simulation, publish, commit): send ONE ArtifactData `batch` with
  (a) `update` of `pipeline/run`: the finished stage becomes "done" (or "error"), the next stage "running", and
  `details.<stage>` gets a short result, e.g. "3 news items", "20 probs", "2 fills, 1 rejected", "page updated";
  (b) `set` of a new doc in collection `activity`, id `<YYYYMMDDTHHMMSS>-<agent>`, with
  `{at: "<UTC now>", agent: "<executor|news|analyst|gate|learning>", msg: "<one factual line>", level: "info|warn|error"}`.
  Good messages: new trades and gate rejections (from live/out/live.json fills and checks), news found or none, predictions
  written, and newly scored predictions with their hit rate.
- **At the end:** `update` `pipeline/run` to `state: "done"` (or "error") with `finished_at`.
Pin every update with `if_version` from your previous write's result. These writes are status only; nothing reads them back into the simulation.

## Every run (AI runner)
0. **Memory:** read the last 60 lines of `knowledge/journal.md`.
1. Clone the repo, then `pip install -q -e . lightgbm scikit-learn`.
2. **Control Panel:** ArtifactData `list` collection `events` on the page above with `out_dir` /tmp/panel, then
   `python scripts/sync_controls.py /tmp/panel`. Never edit `live/controls.jsonl` by hand.
3. **Breaking-news flash (FULL run only) (agent `atlantis-news-analyst`, quick mode, at most 3 searches):** look only for
   market-moving news from the last 2 hours: central banks, data surprises, company or crypto shocks, oil and geopolitics.
   If there is any, write `knowledge/intel/flash/<YYYY-MM-DDTHH>.json` in the brief format and validate it with
   `python -m atlantis.intel.news validate <file>`. If there's nothing, write nothing.
4. **Hourly AI analyst file (FULL run only; predictor `llm_analyst` for account F):** run `python scripts/analyst_brief_hourly.py`.
   Unless it prints SKIP, study the hourly charts, the daily and weekly context, the latest news brief and the flashes, then write
   `data/llm/hourly/<YYYY-MM-DDTHH>.json` = `{"made_at", "analyst": "claude", "probs": {SYMBOL: P(up in 4 hours)}}`.
   Keep probabilities calibrated (mostly 0.45–0.55; go further only with a concrete reason) and omit what you have no view on.
5. Do NOT run the simulation (GitHub Actions does it hourly). Commit and push anything this run wrote
   (`live/controls.jsonl`, `knowledge/intel/`, `data/llm/`, `knowledge/journal.md`) BEFORE :25 with `git pull --rebase` + push.
6. `git pull origin main` again (to get the latest Actions output), then upload `live/out/live.json` to the page as an asset (Artifact tool, `asset: true`). Then ArtifactData `get` doc
   `latest` in collection `status` (note its version) and `set` it, pinned with `if_version`, to `{run_utc, last_completed_bar,
   trading_mode, live_json: "/_blob/<id>", accounts: [{account, equity}]}`. Delete the previous asset if nothing references it.
7. Commit `live/`, `knowledge/`, `data/llm/`, `data/ibkr/` and `data/raw/dukascopy_live/` with the message `live run <run_utc>`,
   then `git pull --rebase origin main` and `git push origin main`.
8. Report the trading mode, the equity of accounts A–F, new fills, newly scored predictions with their hit rate, and every check that is not OK.

## Additionally, in the 00:02 run (daily)
- **Daily news and market-intelligence brief** (agent `atlantis-news-analyst`, full mode): write `knowledge/intel/<bar-date>.json`
  (the bar date printed by `scripts/analyst_brief.py`) and validate it. Use only dated, sourced items from the last 72 hours.
- **Daily AI analyst (account E):** run `python scripts/analyst_brief.py`. Unless it prints SKIP, read today's brief and write
  `data/llm/<bar-date>.json` with P(up in 5 trading days).
- **Journal:** append one dated entry to the END of `knowledge/journal.md` (3–6 factual lines). Never edit earlier entries.
