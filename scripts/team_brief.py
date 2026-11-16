"""Briefing for the AI team (account G). Run it BEFORE `python -m atlantis.live step`.

Prints: the hourly bar the team is deciding for, which agents are due, each instrument's indicators,
measured history statistics for agent "history" (computed here, never invented), the summaries of the
files in force, and account G's positions. SIMULATION ONLY."""
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from atlantis.engine import build_panels
from atlantis.instruments.spec import universe
from atlantis.intel.agents import LEAD, RESEARCH_AGENTS, ROOT, VALID_HOURS, AgentFiles, bar_key
from atlantis.intel.sources.dukascopy_live import Fetcher, LiveFetchError, daily_bid_ask, hourly_bid_ask
from atlantis.intel.validate import clean_daily
from atlantis.quant.predict.features import add_context, build_features

H = 24                                     # the team's horizon in trading hours (TEAM_HORIZON)
DUE_AFTER_H = {"news": 6, "history": 24, "papers": 24 * 7, "scanner": 24}
now = datetime.now(UTC)
f = Fetcher(Path("data/raw/dukascopy_live"))
names = universe().get("names", {})
hourly, daily = {}, {}
for s in universe()["instruments"]:
    try:
        h = hourly_bid_ask(f, s, date(2026, 1, 1), now)
        hourly[s] = h[h.index.dayofweek < 5]
        daily[s] = clean_daily(daily_bid_ask(f, s, 2025, (now - timedelta(days=1)).date()), s)[0]
    except LiveFetchError as e:
        print(f"SKIP: market data incomplete ({s}: {str(e)[:80]}). Write no files this hour.")
        raise SystemExit(0)
panels = build_panels(hourly)
feats = add_context(build_features(panels), build_panels(daily))
last = feats.index.get_level_values("ts").max()
key = bar_key(last.isoformat())
ledger = Path("live/predictions_team.jsonl")
if ledger.exists() and any(f'"made_at": "{last.isoformat()}' in x for x in ledger.open()):
    print(f"SKIP: bar {key} is already decided. Write no team files now (they would change history).")
    raise SystemExit(0)
print(f"TEAM BAR {key} (hourly bar starting {last}); horizon: the next {H} trading hours.")
print(f"Write files as data/agents/<agent>/{key}.json, then: python -m atlantis.intel.agents validate <file>\n")
print("WHO IS DUE THIS HOUR")
for a in RESEARCH_AGENTS:
    fl = AgentFiles(a)
    age = (last - datetime.fromisoformat(fl.keys[-1] + ":00:00+00:00")).total_seconds() / 3600 if fl.keys else None
    due = age is None or age >= DUE_AFTER_H[a]
    print(f"  {a:8s} {'DUE' if due else 'not due'}  (last file {fl.keys[-1] if fl.keys else 'none'}, "
          f"valid {VALID_HOURS[a]} h, refresh every {DUE_AFTER_H[a]} h)")
print(f"  {LEAD:8s} DUE every hour: decisions for bar {key}\n")

mid = panels["mid_close"]
ret_h = np.log(mid.shift(-H) / mid)                 # forward H-hour log return, known only for past bars
today = feats.xs(last, level="ts")
print("INSTRUMENTS (indicators at this bar) and MEASURED HISTORY for agent 'history'")
print("history = of past hourly bars since 2026-01 whose 24h trend and RSI were in the same bucket as now, "
      "the share that were higher 24 trading hours later (n = how many such bars). Cite it as source \"atlantis:history\".")
for s, r in today.iterrows():
    fs = feats.xs(s, level="symbol") if "symbol" in feats.index.names else None
    line = (f"{s:14s} {names.get(s, s)[:26]:26s} {r['mid']:.6g} | 5h {r['ret_5']:+.2f}σ 20h {r['ret_20']:+.2f}σ "
            f"| RSI {50 + 50 * r['rsi_14']:.0f} | week {r['d_ret_5']:+.2f}σ month {r['d_ret_20']:+.2f}σ")
    if fs is not None:
        same = fs[(np.sign(fs["ret_20"]) == np.sign(r["ret_20"])) & ((fs["rsi_14"] > 0) == (r["rsi_14"] > 0))]
        fwd = ret_h[s].reindex(same.index).dropna()
        base = ret_h[s].dropna()
        if len(fwd) >= 30:
            line += f" | history: up {np.mean(fwd > 0):.0%} of n={len(fwd)} (all bars: {np.mean(base > 0):.0%})"
        else:
            line += f" | history: too few similar bars (n={len(fwd)})"
    print(line)

print("\nFILES IN FORCE (summaries the lead must read)")
for a in RESEARCH_AGENTS:
    k, doc = AgentFiles(a).in_force(last.isoformat())
    print(f"--- {a}: {k or 'none in force'} ---")
    if doc:
        print(doc.get("summary", ""))
        print("probs:", json.dumps(doc.get("probs", {})))
out = Path("live/out/live.json")
if out.exists():
    b = json.loads(out.read_text())
    pos = [p for p in b.get("positions", []) if p.get("account") == "G"]
    acc = [a for a in b.get("accounts", []) if a.get("account") == "G"]
    print("\nACCOUNT G:", json.dumps(acc[0]) if acc else "not started yet")
    print("OPEN POSITIONS G:", json.dumps(pos) if pos else "none")
