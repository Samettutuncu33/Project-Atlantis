"""Fetch yearly daily bid/ask files for the whole universe (cached, resumable)."""
import sys
from datetime import UTC, datetime
from pathlib import Path
from atlantis.instruments.spec import universe
from atlantis.intel.sources.dukascopy_live import Fetcher
f = Fetcher(Path("data/raw/dukascopy_live"), max_attempts=12)
first = int(sys.argv[1]) if len(sys.argv) > 1 else 2016
syms = list(universe()["instruments"])
for y in range(2025, first - 1, -1):
    for s in syms:
        for side in ("BID", "ASK"):
            try:
                p = f.get(f"{s}/{y}/{side}_candles_day_1.bi5", datetime(y + 1, 1, 1, tzinfo=UTC))
                print(s, y, side, "ok" if p else "missing", flush=True)
            except Exception as e:
                print(s, y, side, "FAIL", e, flush=True)
