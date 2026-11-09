"""Hourly chart + context briefing for the AI analyst (account F). Run BEFORE `python -m atlantis.live step`.

Prints, per instrument, the last completed HOUR's indicators plus its daily/weekly context, and the
file to write: data/llm/hourly/<YYYY-MM-DDTHH>.json =
  {"made_at": "<UTC now>", "analyst": "claude", "probs": {"EURUSD": 0.52, ...}}
with P(mid price higher 4 hours after that bar). Omit an instrument to abstain. Read the latest
news brief and flash files in knowledge/intel/ first."""
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from atlantis.engine import build_panels
from atlantis.instruments.spec import universe
from atlantis.intel.sources.dukascopy_live import Fetcher, LiveFetchError, daily_bid_ask, hourly_bid_ask
from atlantis.intel.validate import clean_daily
from atlantis.quant.predict.features import add_context, build_features

now = datetime.now(UTC)
f = Fetcher(Path("data/raw/dukascopy_live"))
hourly, daily = {}, {}
for s in universe()["instruments"]:
    try:
        h = hourly_bid_ask(f, s, date(2026, 9, 1), now)
        hourly[s] = h[h.index.dayofweek < 5]
        daily[s] = clean_daily(daily_bid_ask(f, s, 2025, (now - timedelta(days=1)).date()), s)[0]
    except LiveFetchError:
        pass
feats = add_context(build_features(build_panels(hourly)), build_panels(daily))
last = feats.index.get_level_values("ts").max()
key = last.strftime("%Y-%m-%dT%H")
target = Path(f"data/llm/hourly/{key}.json")
ledger = Path("live/predictions_intraday.jsonl")
if target.exists() or (ledger.exists() and any(f'"made_at": "{last.isoformat()}' in x for x in ledger.open())):
    print(f"SKIP: hour {key} already predicted or has an analyst file. Do not write one now.")
    raise SystemExit(0)
print(f"Hourly briefing for bar {last} -> write {target}\n")
for s, r in feats.xs(last, level="ts").iterrows():
    print(f"{s:14s} {r['mid']:.6g} | 1h-trend 5/20/60 bars {r['ret_5']:+.2f}/{r['ret_20']:+.2f}/{r['ret_60']:+.2f}σ "
          f"| RSI {50 + 50 * r['rsi_14']:.0f} | week {r['d_ret_5']:+.2f}σ month {r['d_ret_20']:+.2f}σ "
          f"year {r['d_ret_250']:+.2f}σ | daily RSI {50 + 50 * r['d_rsi_14']:.0f} | 55d channel {r['d_donchian_pos_55']:.2f}")
for p in sorted(Path("knowledge/intel").glob("*.json"))[-1:] + sorted(Path("knowledge/intel/flash").glob("*.json"))[-3:]:
    print(f"\n--- {p} ---\n{p.read_text()[:3000]}")
