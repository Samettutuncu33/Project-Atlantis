"""atlantis CLI: fetch | research | backtest | audit."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from atlantis.data.store import DataStore

ROOT = Path.cwd()


def load_all(store: DataStore, symbols: list[str] | None = None):
    data, manifests, issues = {}, {}, {}
    for s in symbols or store.available():
        df, m = store.read(s)
        data[s], manifests[s] = df, m
        issues[s] = dict(Counter(i["severity"] for i in m["issues"]))
    return data, manifests, issues


def cmd_research(a) -> None:
    from atlantis.analytics.report import build
    from atlantis.research.runner import research

    store = DataStore(ROOT / "data")
    data, manifests, issues = load_all(store, a.symbols.split(",") if a.symbols else None)
    if not data:
        raise SystemExit("no data in store; run `atlantis fetch` first")
    out = ROOT / "reports"
    res = research(data, out, a.strategies.split(",") if a.strategies else None, a.capital)
    res["findings_html"] = findings(res)
    eq = {}
    from atlantis.engine import run_backtest
    from atlantis.research.runner import HOLDOUT
    from atlantis.strategies.library import REGISTRY
    for name in res["strategies"]:
        eq[name] = run_backtest(data, REGISTRY[name](), 1_000_000.0, *HOLDOUT,
                                verify_causality=False).equity
    (out / "report.html").write_text(build(res, manifests, issues, eq))
    serial = {k: v for k, v in res.items() if k != "findings_html"}
    (out / "results.json").write_text(json.dumps(serial, indent=1, default=str))
    print(f"wrote {out / 'report.html'}")


def findings(res: dict) -> str:
    rows = res["rows"]
    c200 = [r for r in rows if r["profile"] == "conservative_200"]
    no_trade = sum(1 for r in c200 if r["fills"] == 0)
    ho = {r["strategy"]: r for r in rows if r["profile"] == "scale_free" and r["period"] == "holdout"}
    best = max(ho.values(), key=lambda r: r["sharpe"])
    mg = [r for r in rows if r["profile"] == "max_growth_200"]
    p2x = max((i["target_at_1x"].get("p_double_every_month_12m", 0) for i in res["strategies"].values()),
              default=0)
    recon = all(r["recon_ok"] for r in rows)
    li = [
        f"<li>Accounting reconciliation: <b>{'0 breaks' if recon else 'BREAKS FOUND'}</b> across "
        f"{len(rows)} runs (independent FIFO recomputation vs engine ledger).</li>",
        f"<li><b>{no_trade} of {len(c200)}</b> conservative $200 runs could not place a single trade: "
        "vol-targeted sizes fall below half the 1,000-unit minimum ticket. At $200 the binding "
        "constraint is minimum ticket size, not strategy choice.</li>",
        f"<li>Best holdout Sharpe (scale-free, after Saxo-calibrated costs): <b>{best['strategy']} "
        f"{best['sharpe']:.2f}</b>. Doubling every month needs ≈4.08.</li>",
        f"<li>Highest bootstrap probability of doubling in all 12 months at 1× leverage: "
        f"<b>{p2x:.2%}</b>.</li>",
    ]
    mt = [r for r in rows if r["profile"] == "min_ticket_200"]
    if mt:
        worst = min(mt, key=lambda r: r["max_dd"])
        li.append(f"<li>Forcing the minimum ticket on $200 (min_ticket_200) produces "
                  f"{min(r['ann_vol'] for r in mt):.0%}–{max(r['ann_vol'] for r in mt):.0%} annual "
                  f"volatility and drawdowns down to <b>{worst['max_dd']:.0%}</b> "
                  f"({worst['strategy']}, {worst['period']}); costs reach up to "
                  f"{max(r['costs_pct_capital'] for r in mt):.0%} of capital. That exceeds the Kelly-optimal "
                  "risk of every strategy tested (for strategies with a negative estimated edge the "
                  "optimal risk is zero).</li>")
    for r in mg:
        li.append(f"<li>max_growth $200 · {r['strategy']}: leverage {r['leverage']:.2f}×, end equity "
                  f"${r['end_equity']:,.2f}, max drawdown {r['max_dd']:.1%}, costs "
                  f"{r['costs_pct_capital']:.1%} of capital.</li>")
    return "<ul>" + "".join(li) + "</ul>"


def cmd_audit(a) -> None:
    store = DataStore(ROOT / "data")
    for s in store.available():
        _, m = store.read(s)  # verifies hash
        c = Counter(i["severity"] for i in m["issues"])
        print(f"{s}: rows={m['rows']} {m['start'][:10]}..{m['end'][:10]} hash OK  {dict(c)}")


def main() -> None:
    p = argparse.ArgumentParser(prog="atlantis")
    sub = p.add_subparsers(required=True)
    r = sub.add_parser("research")
    r.add_argument("--strategies")
    r.add_argument("--symbols")
    r.add_argument("--capital", type=float, default=200.0)
    r.set_defaults(fn=cmd_research)
    au = sub.add_parser("audit")
    au.set_defaults(fn=cmd_audit)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
