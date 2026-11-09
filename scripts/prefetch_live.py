"""Pre-download 2025-2026 daily bid/ask for the whole universe into the live cache."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from atlantis.instruments.spec import universe
from atlantis.intel.sources.dukascopy_live import Fetcher, daily_bid_ask
until = (datetime.now(UTC) - timedelta(days=1)).date()
for s in universe()["instruments"]:
    f = Fetcher(Path("data/raw/dukascopy_live"), max_attempts=15)
    try:
        df = daily_bid_ask(f, s, 2025, until)
        print(s, "OK", len(df), df.index[-1].date(), flush=True)
    except Exception as e:
        print(s, "FAIL", e, flush=True)
