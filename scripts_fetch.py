"""Fetch + validate + store all universe data (run: python scripts_fetch.py)."""
import sys, json
from pathlib import Path
from atlantis.data.sources.dukascopy import load_bid_ask, FetchError
from atlantis.data.validate import clean_daily
from atlantis.data.store import DataStore
SYMS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","USDCHF","NZDUSD","EURGBP","EURJPY","GBPJPY","XAUUSD","XAGUSD"]
YEARS = list(range(2010, 2026))
store = DataStore(Path("data"))
for s in SYMS:
    try:
        df, prov = load_bid_ask(s, YEARS, Path("data/raw/dukascopy"))
        clean, issues = clean_daily(df, s)
        m = store.write(s, clean, prov, issues)
        sev = {k: sum(i.severity == k for i in issues) for k in ("INFO","WARN","ERROR")}
        print(s, m["rows"], m["start"], m["end"], sev, flush=True)
    except FetchError as e:
        print("FAILED", s, e, flush=True)
