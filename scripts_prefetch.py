"""Pre-download raw Dukascopy files with a small worker pool (cached)."""
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from atlantis.intel.sources.dukascopy import fetch_year
SYMS = ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","USDCHF","NZDUSD","EURGBP","EURJPY","GBPJPY","XAUUSD","XAGUSD"]
jobs = [(s, y, side) for y in range(2025, 2009, -1) for s in SYMS for side in ("BID", "ASK")]
ok = fail = 0
with ThreadPoolExecutor(3) as ex:
    futs = {ex.submit(fetch_year, s, y, side, Path("data/raw/dukascopy"), 10): (s, y, side) for s, y, side in jobs}
    for f in as_completed(futs):
        try: f.result(); ok += 1
        except Exception as e: fail += 1; print("FAIL", futs[f], e, flush=True)
        if (ok + fail) % 20 == 0: print(f"{ok+fail}/{len(jobs)} ok={ok} fail={fail}", flush=True)
print("DONE", ok, fail, flush=True)
