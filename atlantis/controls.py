"""Trading controls from the user's Control Panel: RUNNING / PAUSED / FLATTEN.

Events come from the Control Panel artifact's database. The scheduled run copies
them into live/controls.jsonl, which is append-only and committed. An event pressed at
time T takes effect at the first daily decision made AFTER T: the decision for
bar D happens when bar D closes (D+1 00:00 UTC), so the event applies from the
bar whose close is later than T. Past decisions are never changed, so the
deterministic replay stays identical for every bar before the event.

  PAUSED   - no new risk: the gate rejects every risk-increasing intent;
             open positions are kept and can still be reduced.
  FLATTEN  - close every open position at the next open, cancel working
             orders, then stay PAUSED.
  RUNNING  - normal trading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

MODES = ("RUNNING", "PAUSED", "FLATTEN")


@dataclass(frozen=True)
class ControlEvent:
    id: str
    mode: str
    pressed_at: pd.Timestamp
    effective_bar: pd.Timestamp     # first bar whose decision obeys this event
    by: str = ""


def effective_bar_for(pressed_at: pd.Timestamp) -> pd.Timestamp:
    """Bar D's decision is taken at D+1 00:00 UTC, so a press at T applies to bar floor(T)."""
    return pressed_at.tz_convert("UTC").normalize()


class Controls:
    def __init__(self, events: list[ControlEvent] | None = None):
        self.events = sorted(events or [], key=lambda e: (e.effective_bar, e.pressed_at))

    @classmethod
    def load(cls, path: Path) -> Controls:
        p = Path(path)
        if not p.exists():
            return cls([])
        evs = []
        for line in p.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                evs.append(ControlEvent(d["id"], d["mode"], pd.Timestamp(d["pressed_at"]),
                                        pd.Timestamp(d["effective_bar"]), d.get("by", "")))
        return cls(evs)

    def mode_at(self, t: pd.Timestamp) -> tuple[str, bool]:
        """(mode for decisions at bar t, whether a FLATTEN must be executed at this bar)."""
        mode, flatten_now = "RUNNING", False
        for e in self.events:
            if e.effective_bar <= t:
                mode = e.mode
                flatten_now = e.mode == "FLATTEN" and e.effective_bar == t
        return ("PAUSED" if mode == "FLATTEN" else mode), flatten_now

    def current(self) -> dict:
        if not self.events:
            return {"mode": "RUNNING", "since": None, "event_id": None}
        e = self.events[-1]
        return {"mode": "PAUSED" if e.mode == "FLATTEN" else e.mode, "last_action": e.mode,
                "since": e.pressed_at.isoformat(), "effective_bar": str(e.effective_bar.date()),
                "event_id": e.id}


def sync_from_panel(panel_docs: list[dict], path: Path) -> list[dict]:
    """Append Control Panel events (from an ArtifactData list of collection `events`)
    that are not yet in controls.jsonl. Existing lines are never modified."""
    p = Path(path)
    known = set()
    if p.exists():
        known = {json.loads(x)["id"] for x in p.read_text().splitlines() if x.strip()}
    new = []
    for doc in sorted(panel_docs, key=lambda d: d.get("data", d).get("pressed_at", "")):
        d = doc.get("data", doc)
        did = doc.get("id") or d.get("id")
        if did in known or d.get("mode") not in MODES:
            continue
        t = pd.Timestamp(d["pressed_at"])
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        rec = {"id": did, "mode": d["mode"], "pressed_at": t.isoformat(),
               "effective_bar": effective_bar_for(t).isoformat(), "by": d.get("by", "")}
        new.append(rec)
        known.add(did)
    if new:
        with p.open("a") as f:
            for r in new:
                f.write(json.dumps(r) + "\n")
    return new
