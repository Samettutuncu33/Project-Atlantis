"""Write live/STATUS.md from live/out/live.json: a plain summary readable on GitHub (no Claude plan needed).
SIMULATION ONLY: every number here is simulated paper trading, not a real account."""
import json
from datetime import UTC, datetime
from pathlib import Path

d = json.loads(Path("live/out/live.json").read_text())
run = (d.get("run") or [{}])[0]
spend_file = Path("live/api_spend.jsonl")
ym = datetime.now(UTC).strftime("%Y-%m")
spend = sum(r["usd"] for r in map(json.loads, spend_file.read_text().splitlines()) if r["at"].startswith(ym)) \
    if spend_file.exists() else 0.0

L = [f"# Atlantis status (SIMULATION ONLY)", "",
     f"Last run: {run.get('run_utc', '?')} · last bar: {run.get('last_completed_bar', '?')} · "
     f"mode: **{run.get('trading_mode', '?')}** · Claude API spend this month: **${spend:.2f}**", "",
     "| Account | Strategy | Equity $ | Return % | Fills | Open positions | Max drawdown % |", "|---|---|---|---|---|---|---|"]
for a in d.get("accounts", []):
    L.append(f"| {a['account']} | {a.get('name', '')} | {a['equity']:.2f} | {a['return_pct']:+.2f} | {a['fills']} | "
             f"{a['open_positions']} | {a['max_drawdown_pct']:.1f} |")
pos = d.get("positions", [])
L += ["", "## Open positions", ""]
if pos:
    L += ["| Account | Name | Qty | Value $ | P&L $ |", "|---|---|---|---|---|"]
    L += [f"| {p.get('account')} | {p.get('name', p.get('symbol'))} | {p.get('qty', p.get('quantity', ''))} | "
          f"{p.get('value_usd', '')} | {p.get('pnl_usd', '')} |" for p in pos]
else:
    L.append("None.")
fills = d.get("fills", [])[-10:]
L += ["", "## Last fills", ""]
if fills:
    L += ["| Time | Account | Symbol | Side | Qty | Price |", "|---|---|---|---|---|---|"]
    L += [f"| {f.get('ts', '')} | {f.get('account', '')} | {f.get('symbol', '')} | "
          f"{f.get('side', '')} | {f.get('qty', '')} | {f.get('price', '')} |" for f in fills]
else:
    L.append("None yet.")
bad = [c for c in d.get("checks", []) if c.get("status") != "OK"]
L += ["", "## Checks", "", "All OK." if not bad else "\n".join(f"- **{c['status']}** {c['check']}: {c['detail']}" for c in bad)]
Path("live/STATUS.md").write_text("\n".join(L) + "\n")
print("wrote live/STATUS.md")
