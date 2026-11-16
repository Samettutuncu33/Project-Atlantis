"""The AI team's files (account G). Each research agent writes a dated, sourced file; "Atlantis",
the lead agent, reads their summaries and approves or refuses every new trade.

  data/agents/<agent>/<YYYY-MM-DDTHH>.json   research agents: news, history, papers, scanner
      {"made_at", "agent", "summary", "probs": {SYMBOL: P(up over the next 24 trading hours)},
       "evidence": [{"symbols": [...], "claim": "...", "source": "https://...", "published_at": "<ISO>"}]}
  data/agents/atlantis/<YYYY-MM-DDTHH>.json  the lead's decisions for that hourly bar
      {"made_at", "agent": "atlantis", "summary", "decisions": {SYMBOL: {"approve": true|false, "reason": "..."}}}

The file key is the hourly bar the file is FOR (the last completed bar when it was written).
Files are forward-only: a file is used for its own bar and later bars, for at most VALID_HOURS,
and the prediction ledger's append-only check rejects any run in which an old bar changed.
SIMULATION ONLY: nothing here can reach a broker.

CLI: python -m atlantis.intel.agents validate <file>
"""
from __future__ import annotations

import bisect
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from atlantis.instruments.spec import universe

ROOT = Path(__file__).resolve().parents[2] / "data" / "agents"
# how long one file stays in force (the agents run at different rhythms)
VALID_HOURS = {"news": 8, "history": 30, "papers": 24 * 8, "scanner": 30}
RESEARCH_AGENTS = tuple(VALID_HOURS)
LEAD = "atlantis"


class AgentFileError(ValueError):
    pass


def _key_ts(key: str) -> pd.Timestamp:
    return pd.Timestamp(key + ":00:00", tz="UTC")


def bar_key(ts) -> str:
    return str(ts).replace(" ", "T")[:13]


def validate(doc: dict, key: str | None = None) -> tuple[dict, dict]:
    """Return (clean file, report). Unsourced or undated evidence and unknown symbols are dropped and
    counted; a research file with probabilities but no surviving evidence is rejected."""
    agent = doc.get("agent")
    if agent not in RESEARCH_AGENTS + (LEAD,):
        raise AgentFileError(f"unknown agent {agent!r}")
    try:
        made = pd.Timestamp(doc["made_at"])
    except Exception as e:
        raise AgentFileError("made_at missing or unreadable") from e
    if pd.isna(made):
        raise AgentFileError("made_at missing")
    made = made.tz_localize("UTC") if made.tzinfo is None else made.tz_convert("UTC")
    if key is not None and not (0 <= (made - _key_ts(key)).total_seconds() <= 3 * 3600):
        raise AgentFileError(f"file key {key} does not match made_at {made.isoformat()} (no back-dating)")
    symbols = set(universe()["instruments"])
    report = {"dropped": {}}

    def drop(why):
        report["dropped"][why] = report["dropped"].get(why, 0) + 1

    clean = {"made_at": made.isoformat(), "agent": agent, "summary": str(doc.get("summary", ""))[:1500]}
    if agent == LEAD:
        decisions = {}
        for s, d in (doc.get("decisions") or {}).items():
            if s not in symbols or not isinstance(d, dict) or not isinstance(d.get("approve"), bool):
                drop("bad decision entry")
                continue
            decisions[s] = {"approve": d["approve"], "reason": str(d.get("reason", ""))[:300]}
        clean["decisions"] = decisions
        report["decisions"] = len(decisions)
        return clean, report
    evidence = []
    for ev in doc.get("evidence") or []:
        u = urlparse(str(ev.get("source", "")))
        if u.scheme not in ("http", "https") or not u.netloc:
            if not (agent == "history" and str(ev.get("source", "")).startswith("atlantis:")):
                drop("evidence without a source url")
                continue
        syms = [s for s in ev.get("symbols", []) if s in symbols]
        if not syms:
            drop("evidence without a known symbol")
            continue
        item = {"symbols": syms, "claim": str(ev.get("claim", ""))[:300], "source": str(ev["source"])}
        if ev.get("published_at"):
            try:
                pub = pd.Timestamp(ev["published_at"])
                pub = pub.tz_localize("UTC") if pub.tzinfo is None else pub.tz_convert("UTC")
            except Exception:
                drop("unreadable publication time")
                continue
            if pub > made + pd.Timedelta(minutes=5):
                drop("published after the file was made (impossible)")
                continue
            item["published_at"] = pub.isoformat()
        elif agent in ("news", "scanner"):
            drop("news evidence without a publication time")
            continue
        evidence.append(item)
    backed = {s for ev in evidence for s in ev["symbols"]}
    probs = {}
    for s, p in (doc.get("probs") or {}).items():
        try:
            p = float(p)
        except (TypeError, ValueError):
            drop("unreadable probability")
            continue
        if s not in symbols or not 0 < p < 1:
            drop("unknown symbol or probability outside (0, 1)")
            continue
        if s not in backed:
            drop("probability without evidence for that symbol")
            continue
        probs[s] = round(min(max(p, 0.35), 0.65), 3)     # one agent alone never claims more than 35-65%
    clean.update(probs=probs, evidence=evidence)
    report.update(probs=len(probs), evidence=len(evidence))
    return clean, report


class AgentFiles:
    """Read side for the simulation: the file in force for a given hourly bar."""

    def __init__(self, agent: str, root: Path | None = None):
        self.agent = agent
        self.dir = Path(root or ROOT) / agent
        self.keys = sorted(p.stem for p in self.dir.glob("*.json")) if self.dir.exists() else []
        self._cache: dict[str, dict] = {}

    def _load(self, key: str) -> dict:
        if key not in self._cache:
            try:
                self._cache[key], _ = validate(json.loads((self.dir / f"{key}.json").read_text()), key)
            except (AgentFileError, json.JSONDecodeError):
                self._cache[key] = {}
        return self._cache[key]

    def in_force(self, ts) -> tuple[str | None, dict]:
        """(key, clean file) of the newest file at or before bar `ts` that is still valid, else (None, {})."""
        k = bar_key(ts)
        i = bisect.bisect_right(self.keys, k)
        if i == 0:
            return None, {}
        key = self.keys[i - 1]
        limit = 0 if self.agent == LEAD else VALID_HOURS[self.agent]       # an approval is for one bar only
        if (_key_ts(k) - _key_ts(key)).total_seconds() > limit * 3600:
            return None, {}
        return key, self._load(key)

    def probs(self, ts) -> dict:
        return self.in_force(ts)[1].get("probs", {})


class Approvals:
    """The lead agent's approval of new or larger positions. No file for a bar = nothing approved."""

    def __init__(self, root: Path | None = None):
        self.files = AgentFiles(LEAD, root)

    def decision(self, ts, symbol: str) -> tuple[bool, str]:
        key, doc = self.files.in_force(ts)
        if key is None:
            return False, "Atlantis has not reviewed this bar"
        d = doc.get("decisions", {}).get(symbol)
        if d is None:
            return False, "not on Atlantis's approved list"
        return d["approve"], ("approved by Atlantis: " if d["approve"] else "refused by Atlantis: ") + d["reason"]


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "validate":
        raise SystemExit("usage: python -m atlantis.intel.agents validate <file>")
    path = Path(sys.argv[2])
    clean, rep = validate(json.loads(path.read_text()), path.stem)
    path.write_text(json.dumps(clean, indent=1))
    print(json.dumps(rep, indent=1))
    if clean["agent"] != LEAD and not clean["probs"]:
        print("WARNING: no probability survived validation; this file changes nothing")
