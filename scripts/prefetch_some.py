import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from atlantis.intel.sources.dukascopy_live import Fetcher, daily_bid_ask
until = (datetime.now(UTC) - timedelta(days=1)).date()
for s in sys.argv[1:]:
    try:
        df = daily_bid_ask(Fetcher(Path("data/raw/dukascopy_live"), max_attempts=15), s, 2025, until)
        print(s, "OK", len(df), df.index[-1].date(), flush=True)
    except Exception as e:
        print(s, "FAIL", e, flush=True)
