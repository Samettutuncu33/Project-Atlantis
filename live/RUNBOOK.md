# Scheduled live-simulation run (every 6 hours)

Dashboard: https://claude.ai/artifact/AWBpwhmciFEZQZuu8Tp1TY
Simulation only. No broker connection, credentials or real orders exist anywhere in this project.

1. `pip install -q -e .` (from the repository root).
2. `python -m atlantis.live step`. Exit code 2 means a check failed. Continue anyway, so the dashboard shows the failure.
   If it crashes (for example, Dukascopy stays unreachable for about 10 minutes), retry once. If it crashes again, stop and report the error. Do not publish stale data as new.
3. Upload `live/out/live.json` to the dashboard as an asset (Artifact tool, `asset: true`, url above). Note the `/_blob/<id>`.
4. `python scripts/dashboard_updates.py /_blob/<id> /tmp/dash` writes one update per dataset.
   Read each `datasets/<id>` document to get its version. Then send one ArtifactData `batch` of `update` writes, one per dataset, pinned with `if_version`, each using `file_path` /tmp/dash/<id>.json.
5. Delete the previous run's asset only if no dataset still names it.
6. Commit `live/` and `data/raw/dukascopy_live/` with the message `live run <run_utc>`, then push to `main`.
7. Report the four account equities, any new fills, and any check that is not OK.
