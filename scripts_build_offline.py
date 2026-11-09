"""Build the clean store from cached raw files only (no network)."""
from pathlib import Path
from atlantis.data.sources.dukascopy import load_bid_ask, cached_years
from atlantis.data.validate import clean_daily
from atlantis.data.store import DataStore
raw = Path("data/raw/dukascopy"); store = DataStore(Path("data"))
for d in sorted(raw.iterdir()):
    yrs = cached_years(d.name, raw)
    if len(yrs) < 6:
        print("skip", d.name, yrs); continue
    df, prov = load_bid_ask(d.name, yrs, raw, offline=True)
    clean, issues = clean_daily(df, d.name)
    m = store.write(d.name, clean, prov, issues)
    sev = {k: sum(i.severity == k for i in issues) for k in ("INFO","WARN","ERROR")}
    print(d.name, yrs[0], yrs[-1], m["rows"], sev)
    for i in issues:
        if i.severity != "INFO": print("   ", i.severity, i.check, i.ts[:10], i.detail)
