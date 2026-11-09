"""Chart briefing for the LLM analyst (run BEFORE `python -m atlantis.live step`).

Prints, per instrument, the latest completed daily bar's indicators in plain terms,
and the path of the file the analyst must write:
  data/llm/<last-bar-date>.json = {"made_at": "<UTC now>", "analyst": "claude",
                                   "probs": {"EURUSD": 0.53, ...}}
Probabilities are P(mid price higher 5 trading days after that bar). Write them
before seeing any later price. Omit an instrument to abstain on it.
"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from atlantis.engine import build_panels
from atlantis.instruments.spec import universe
from atlantis.intel.sources.dukascopy_live import Fetcher, LiveFetchError, daily_bid_ask
from atlantis.intel.validate import clean_daily
from atlantis.quant.predict.features import build_features

until = (datetime.now(UTC) - timedelta(days=1)).date()
f = Fetcher(Path("data/raw/dukascopy_live"))
data = {}
for s in universe()["instruments"]:
    try:
        data[s] = clean_daily(daily_bid_ask(f, s, 2025, until), s)[0]
    except LiveFetchError:
        pass
feats = build_features(build_panels(data))
last = feats.index.get_level_values("ts").max()
today = feats.xs(last, level="ts")
print(f"Briefing for bar {last.date()} (write data/llm/{last.date()}.json)\n")
for s, r in today.iterrows():
    print(f"{s:14s} price {r['mid']:.5g} | 5d {r['ret_5']:+.2f}σ 20d {r['ret_20']:+.2f}σ 60d {r['ret_60']:+.2f}σ "
          f"12m {r['ret_250']:+.2f}σ | RSI {50 + 50 * r['rsi_14']:.0f} | Bollinger pos {r['boll_pos_20']:.2f} | "
          f"55d channel pos {r['donchian_pos_55']:.2f} | vol ratio {r['vol_ratio_20_120']:.2f} | "
          f"{r['dist_high_250']:+.1%} from 12m high")
journal = Path("knowledge/journal.md")
if journal.exists():
    print("\n--- last journal entries ---\n" + "\n".join(journal.read_text().splitlines()[-40:]))
