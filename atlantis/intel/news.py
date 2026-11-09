"""Daily news and market-intelligence briefs (written by the atlantis-news-analyst agent).

A brief lives at knowledge/intel/<bar-date>.json. This module validates it strictly
(fresh, sourced, well-formed items only) and loads the latest valid brief for the
Atlantis Live page. News never feeds the Python simulation directly. It reaches
decisions only through the forward-only `llm_analyst` predictor, whose
probabilities are scored like every other predictor's. So news has to earn its
weight; it is never trusted by assumption.

CLI: python -m atlantis.intel.news validate <file>
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from atlantis.instruments.spec import universe

MAX_AGE = timedelta(hours=72)
LEVELS = {"high", "medium", "low"}


class BriefError(ValueError):
    pass


def _ts(v, what: str) -> pd.Timestamp:
    try:
        t = pd.Timestamp(v)
    except Exception as e:
        raise BriefError(f"{what}: unreadable timestamp {v!r}") from e
    if pd.isna(t):
        raise BriefError(f"{what}: missing timestamp")
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _url_ok(u) -> bool:
    p = urlparse(str(u))
    return p.scheme in ("http", "https") and bool(p.netloc)


def validate(brief: dict) -> tuple[dict, dict]:
    """Return (clean brief, report). Items that are stale, undated, unsourced or about
    unknown symbols are DROPPED and counted; structural errors raise BriefError."""
    for k in ("date", "made_at", "summary", "items"):
        if k not in brief:
            raise BriefError(f"missing field {k!r}")
    made = _ts(brief["made_at"], "made_at")
    symbols = set(universe()["instruments"]) | {"MACRO"}
    report = {"items_in": len(brief.get("items", [])), "dropped": {}}

    def drop(reason):
        report["dropped"][reason] = report["dropped"].get(reason, 0) + 1

    items = []
    for it in brief.get("items", []):
        if not _url_ok(it.get("source")):
            drop("no valid source url")
            continue
        try:
            pub = _ts(it.get("published_at"), "published_at")
        except BriefError:
            drop("no readable publication time")
            continue
        if pub > made + timedelta(minutes=5):
            drop("published after the brief (impossible)")
            continue
        if made - pub > MAX_AGE:
            drop("older than 72 hours")
            continue
        syms = [s for s in it.get("symbols", []) if s in symbols]
        if not syms:
            drop("no known symbol")
            continue
        tone = float(it.get("tone", 0))
        if not -1 <= tone <= 1:
            drop("tone outside [-1, 1]")
            continue
        items.append({"symbols": syms, "headline": str(it.get("headline", ""))[:300], "source": it["source"],
                      "published_at": pub.isoformat(), "tone": tone,
                      "relevance": it.get("relevance") if it.get("relevance") in LEVELS else "low",
                      "note": str(it.get("note", ""))[:300]})
    cal = []
    for c in brief.get("calendar", []):
        if not _url_ok(c.get("source")):
            drop("calendar event without source")
            continue
        try:
            when = _ts(c.get("when"), "when")
        except BriefError:
            drop("calendar event without date")
            continue
        cal.append({"when": when.isoformat(), "event": str(c.get("event", ""))[:200],
                    "region": str(c.get("region", ""))[:20],
                    "importance": c.get("importance") if c.get("importance") in LEVELS else "low",
                    "symbols": [s for s in c.get("symbols", []) if s in symbols], "source": c["source"]})
    views = {}
    for s, v in (brief.get("views") or {}).items():
        if s in symbols and isinstance(v, dict):
            t = max(-1.0, min(1.0, float(v.get("tone", 0))))
            views[s] = {"tone": t, "event_risk": "high" if v.get("event_risk") == "high" else "normal",
                        "reason": str(v.get("reason", ""))[:300]}
    report["items_kept"] = len(items)
    clean = {"date": str(brief["date"])[:10], "made_at": made.isoformat(), "agent": brief.get("agent", ""),
             "summary": str(brief["summary"])[:1500], "calendar": cal, "items": items, "views": views}
    return clean, report


def latest_brief(root: Path) -> tuple[dict | None, dict | None]:
    files = sorted(Path(root).glob("*.json"))
    for p in reversed(files):
        try:
            return validate(json.loads(p.read_text()))
        except (BriefError, json.JSONDecodeError):
            continue
    return None, None


def bundle_rows(root: Path) -> dict:
    """Rows for live.json: intel_summary (1 row), intel_items, intel_calendar, intel_views."""
    brief, report = latest_brief(root)
    if brief is None:
        return {"intel_summary": [], "intel_items": [], "intel_calendar": [], "intel_views": []}
    names = universe().get("names", {})
    return {
        "intel_summary": [{"date": brief["date"], "made_at": brief["made_at"], "summary": brief["summary"],
                           "items_kept": report["items_kept"], "items_in": report["items_in"],
                           "dropped": "; ".join(f"{k}: {v}" for k, v in report["dropped"].items())}],
        "intel_items": [{**i, "names": ", ".join(names.get(s, s) for s in i["symbols"]),
                         "symbols": ", ".join(i["symbols"])} for i in brief["items"]],
        "intel_calendar": [{**c, "symbols": ", ".join(c["symbols"])} for c in brief["calendar"]],
        "intel_views": [{"symbol": s, "name": names.get(s, s), **v} for s, v in brief["views"].items()],
    }


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "validate":
        raise SystemExit("usage: python -m atlantis.intel.news validate <file>")
    clean, rep = validate(json.loads(Path(sys.argv[2]).read_text()))
    print(json.dumps(rep, indent=1))
    if rep["items_kept"] == 0:
        print("WARNING: no usable news items survived validation")
