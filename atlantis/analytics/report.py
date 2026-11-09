"""Self-contained HTML research report.

Visual convention: anything derived from HISTORICAL MARKET DATA carries a blue
'MARKET DATA' tag; anything produced by the simulator carries an amber
'SIMULATED' tag. No figure in this report is an actual Saxo transaction.
"""

from __future__ import annotations

import html
import math

import pandas as pd

from atlantis.instruments.spec import conditions

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e3e0d8;--mk:#1f5fa8;--sim:#a35f00;--bad:#b3261e;--ok:#2e7d32}
@media (prefers-color-scheme: dark){:root{--bg:#161614;--fg:#ecebe6;--mut:#9d9b94;--line:#33322e;--mk:#7fb0f0;--sim:#f0b25a;--bad:#ff8a80;--ok:#81c784}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;padding:24px 16px;max-width:1100px;margin:auto}
h1{font-size:26px;margin:0 0 4px} h2{font-size:19px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:16px;margin:20px 0 6px}.mut{color:var(--mut)}
.tag{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;padding:1px 6px;border-radius:4px;border:1px solid;vertical-align:middle}
.mk{color:var(--mk);border-color:var(--mk)}.sim{color:var(--sim);border-color:var(--sim)}
.wrap{overflow-x:auto}table{border-collapse:collapse;font-size:13px;width:100%;margin:8px 0}
th,td{padding:4px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
th{color:var(--mut);font-weight:600}.neg{color:var(--bad)}.pos{color:var(--ok)}
.callout{border-left:3px solid var(--sim);padding:8px 12px;margin:12px 0;background:color-mix(in srgb,var(--sim) 8%,transparent)}
svg text{fill:var(--mut);font-size:11px}
"""


def _fmt(v, kind="num"):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    if isinstance(v, bool):
        return "✓" if v else "✗"
    if kind == "pct":
        return f"{v * 100:,.1f}%"
    if kind == "usd":
        return f"${v:,.2f}"
    if isinstance(v, float):
        if math.isinf(v):
            return "∞"
        return f"{v:,.2f}"
    return html.escape(str(v))


def table(df: pd.DataFrame, kinds: dict[str, str] | None = None) -> str:
    kinds = kinds or {}
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    body = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            cls = ""
            if isinstance(v, float) and kinds.get(c) in ("pct", "usd", "num") and v < 0:
                cls = " class='neg'"
            cells.append(f"<td{cls}>{_fmt(v, kinds.get(c, 'num'))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<div class='wrap'><table><tr>{head}</tr>{''.join(body)}</table></div>"


def svg_lines(series: dict[str, pd.Series], height: int = 220, logy: bool = True) -> str:
    palette = ["#1f5fa8", "#a35f00", "#2e7d32", "#7b3fa0", "#b3261e", "#00838f"]
    w, pad = 1000, 40
    allv = pd.concat([s for s in series.values() if len(s)])
    if allv.empty:
        return ""
    f = (lambda x: math.log(max(x, 1e-9))) if logy else (lambda x: x)
    lo, hi = f(allv.min()), f(allv.max())
    hi = hi if hi > lo else lo + 1
    t0, t1 = allv.index.min(), allv.index.max()
    span = max((t1 - t0).total_seconds(), 1)
    out = [f"<svg viewBox='0 0 {w} {height + 24}' width='100%' role='img'>"]
    for i, (name, s) in enumerate(series.items()):
        pts = " ".join(f"{pad + (t - t0).total_seconds() / span * (w - 2 * pad):.1f},"
                       f"{height - (f(v) - lo) / (hi - lo) * (height - 20):.1f}"
                       for t, v in s.items())
        c = palette[i % len(palette)]
        out.append(f"<polyline fill='none' stroke='{c}' stroke-width='1.5' points='{pts}'/>")
        out.append(f"<text x='{pad + i * 220}' y='{height + 18}' style='fill:{c}'>■ {html.escape(name)}</text>")
    out.append(f"<text x='2' y='12'>{allv.max():,.0f}</text><text x='2' y='{height}'>{allv.min():,.0f}</text>")
    out.append("</svg>")
    return "".join(out)


def build(res: dict, manifests: dict, data_issues: dict, equities: dict[str, pd.Series]) -> str:
    rows = pd.DataFrame(res["rows"])
    c = conditions()
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Atlantis Research Report</title><style>{CSS}</style></head><body>"]
    parts.append("<h1>PROJECT ATLANTIS — research report</h1>"
                 "<p class='mut'>Simulation-only. No orders were sent to any broker. "
                 "<span class='tag mk'>MARKET DATA</span> = historical quotes from a public source. "
                 "<span class='tag sim'>SIMULATED</span> = output of the Atlantis execution simulator, "
                 "never an actual Saxo transaction.</p>")
    # Headline
    parts.append("<h2>Key findings</h2><div class='callout'>" + res.get("findings_html", "") + "</div>")
    # Results
    parts.append("<h2>Strategy results <span class='tag sim'>SIMULATED</span></h2>")
    parts.append("<p class='mut'>scale_free = $1,000,000 run measuring each strategy's net edge without "
                 "lot-size distortion. conservative_200 / max_growth_200 = the $200 account. "
                 f"dev = 2012–2019, holdout = 2020–2025 <b>truncated to available data (ends "
                 f"{max(m['end'][:10] for m in manifests.values())}; universe: "
                 f"{', '.join(manifests)})</b>. Parameters fixed from the literature, not fitted.</p>")
    cols = ["strategy", "profile", "period", "leverage", "end_equity", "net_pnl", "cagr", "sharpe",
            "sortino", "max_dd", "ann_vol", "trades", "win_rate", "profit_factor", "expectancy_usd",
            "costs_usd", "costs_pct_capital", "fills", "rejects", "rounded_to_zero", "recon_ok"]
    kinds = {"end_equity": "usd", "net_pnl": "usd", "cagr": "pct", "max_dd": "pct", "ann_vol": "pct",
             "win_rate": "pct", "expectancy_usd": "usd", "costs_usd": "usd", "costs_pct_capital": "pct"}
    parts.append(table(rows[cols], kinds))
    parts.append("<h3>Equity curves, holdout <span class='tag sim'>SIMULATED</span></h3>")
    parts.append(svg_lines({k: v for k, v in equities.items()}))
    # Robustness
    parts.append("<h2>Robustness and overfitting controls <span class='tag sim'>SIMULATED</span></h2>")
    rb = []
    for name, info in res["strategies"].items():
        d = info.get("deflated_sharpe_holdout", {})
        sw = info["cost_sweep_holdout_sharpe"]
        rb.append({"strategy": name, "DSR (prob. true SR>0)": d.get("dsr"),
                   "trials counted": d.get("n_trials"), **{f"Sharpe {k}": v for k, v in sw.items()},
                   "Kelly lev (dev)": info["kelly_dev"]["kelly_leverage"],
                   "Sharpe dev": info["kelly_dev"]["sharpe_ann"],
                   "Sharpe holdout": info["kelly_holdout"]["sharpe_ann"]})
    parts.append(table(pd.DataFrame(rb)))
    # Target
    parts.append("<h2>Your target: 2× per month <span class='tag sim'>SIMULATED</span></h2>"
                 "<p>Required annual Sharpe ratio for 2× every month at full Kelly, before costs: "
                 "<b>≈4.08</b> (g* = SR²/2 = 12·ln 2). Probabilities below come from a stationary "
                 "block bootstrap of each strategy's holdout returns.</p>")
    tg = []
    for name, info in res["strategies"].items():
        for lab, t in (("1× (vol-target)", info["target_at_1x"]),
                       ("full Kelly (from dev)", info["target_at_full_kelly_from_dev"])):
            if t and "error" not in t:
                tg.append({"strategy": name, "leverage": f"{lab} {t['leverage']:.2f}",
                           "P(double in month 1)": t["p_double_in_a_month"],
                           "P(any month doubles, 12m)": t["p_any_month_doubles"],
                           "P(double every month, 12m)": t["p_double_every_month_12m"],
                           "median 12m multiple": t["median_12m_multiple"],
                           "P(lose 50%+ within 12m)": t["p_lose_half_within_12m"]})
    parts.append(table(pd.DataFrame(tg), {k: "pct" for k in ("P(double in month 1)",
                       "P(any month doubles, 12m)", "P(double every month, 12m)",
                       "P(lose 50%+ within 12m)")}))
    # Execution quality
    parts.append("<h2>Execution &amp; cost model <span class='tag sim'>SIMULATED</span></h2>")
    es = c["execution_statistics"]
    parts.append(f"<p>Slippage is calibrated to Saxo's published client execution statistics "
                 f"({html.escape(es['period'])}; <a href='{es['source']}'>source</a>). Fills use the "
                 "real bid/ask of the data source; buys pay the ask, sells receive the bid.</p>")
    # Conditions table
    parts.append("<h2>Saxo conditions used (status of every input)</h2>")
    cond = []
    for k, v in c["fx_spot"].items():
        if isinstance(v, dict):
            cond.append({"field": f"fx_spot.{k}", "value": v.get("value", "–"), "status": v.get("status"),
                         "note / quote": (v.get("quote") or v.get("note") or "")[:160]})
    for k, v in c["currency_conversion"].items():
        cond.append({"field": f"conversion.{k}", "value": v.get("value"), "status": v.get("status"),
                     "note / quote": (v.get("quote") or v.get("note") or "")[:160]})
    cond.append({"field": "margin (ESMA retail)", "value": str(c["margin_retail_esma"]["initial_margin"]),
                 "status": "REGULATION", "note / quote": c["margin_retail_esma"]["source"]})
    parts.append(table(pd.DataFrame(cond)))
    # Data provenance
    parts.append("<h2>Data provenance <span class='tag mk'>MARKET DATA</span></h2>"
                 "<p>Source: Dukascopy Bank public historical feed (bid and ask daily candles). "
                 "<b>Not Saxo quotes.</b> Saxo historical prices require an authenticated API and "
                 "are out of scope until Phase 2.</p>")
    prov = []
    for s, m in manifests.items():
        iss = data_issues.get(s, {})
        prov.append({"symbol": s, "rows": m["rows"], "start": m["start"][:10], "end": m["end"][:10],
                     "raw files": len(m["raw_files"]), "data sha256": m["frame_sha256"][:16] + "…",
                     "INFO": iss.get("INFO", 0), "WARN": iss.get("WARN", 0), "ERROR": iss.get("ERROR", 0)})
    parts.append(table(pd.DataFrame(prov)))
    parts.append("<h2>Assumptions</h2><p>See <code>docs/ASSUMPTIONS.md</code>. Every ASSUMPTION or "
                 "UNAVAILABLE field above is a known limitation of this phase.</p>")
    parts.append("</body></html>")
    return "".join(parts)
