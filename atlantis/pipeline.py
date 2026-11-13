"""What a live run really did, stage by stage, for the dashboard's command view.

Nothing here is simulated activity: every time is the wall clock of the run, and every
line is read from the run's own outputs (fills, gate rejections, checks, agent files)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

STAGES = ("controls", "market", "news", "analyst", "simulation", "gate", "broker", "checks", "commit")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StageLog:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def start(self, stage: str) -> None:
        self.rows[stage] = {"stage": stage, "started_at": _now(), "finished_at": None, "status": "running", "detail": ""}

    def end(self, stage: str, detail: str, status: str = "done") -> None:
        r = self.rows.setdefault(stage, {"stage": stage, "started_at": _now()})
        r.update(finished_at=_now(), status=status, detail=str(detail)[:160])

    def mirror(self, stage: str, of: str, detail: str, status: str = "done") -> None:
        """A stage that runs inside another one (gate and broker work inside the simulation loop)."""
        src = self.rows[of]
        self.rows[stage] = {"stage": stage, "started_at": src["started_at"], "finished_at": src["finished_at"],
                            "status": status, "detail": str(detail)[:160]}

    def merge_ai(self, path: Path, run_started: str, max_age_min: float = 45) -> None:
        """News and analyst stages are written by scripts/ai_api_runner.py just before the simulation step."""
        ai = {}
        if path.exists():
            try:
                ai = json.loads(path.read_text())
            except json.JSONDecodeError:
                ai = {}
        t0 = datetime.fromisoformat(run_started)
        for stage in ("news", "analyst"):
            r = ai.get(stage)
            fresh = r and r.get("finished_at") and \
                0 <= (t0 - datetime.fromisoformat(r["finished_at"])).total_seconds() <= max_age_min * 60
            self.rows[stage] = {"stage": stage, **r} if fresh else {
                "stage": stage, "started_at": run_started, "finished_at": run_started, "status": "idle",
                "detail": "not run this time"}

    def table(self) -> list[dict]:
        return [self.rows[s] for s in STAGES if s in self.rows]


def activity_rows(rows: dict, checks: list[dict], rejects: list[dict], run_utc: str, names: dict,
                  keep: int = 60) -> list[dict]:
    """Real events, newest first: fills, gate/broker rejections, news, analyst output, failed checks."""
    out = []
    for f in rows.get("fills", []):
        out.append({"at": f["ts"], "agent": "broker", "level": "info",
                    "msg": f"Account {f['account']} {'bought' if f['side'] == 'BUY' else 'sold'} {f['qty']:g} "
                           f"{names.get(f['symbol'], f['symbol'])} at {f['price']:,.6g} (simulated)"})
    for r in rejects:
        out.append({"at": r["ts"], "agent": "gate", "level": "warn",
                    "msg": f"Account {r['account']} order rejected: {names.get(r.get('symbol'), r.get('symbol') or '')} "
                           f"{r.get('check') or ''} {r.get('reason') or ''}".strip()})
    for s in rows.get("intel_summary", []):
        out.append({"at": s["made_at"], "agent": "news", "level": "info",
                    "msg": f"News brief for {s['date']}: {s['items_kept']} dated, sourced items kept of {s['items_in']}"})
    for a in rows.get("agents", []):
        if a.get("last") and "analyst" in a["agent"].lower():
            out.append({"at": a["last"], "agent": "analyst", "level": "info", "msg": f"{a['agent']}: {a['did']}"})
    for c in rows.get("calibration", []):
        out.append({"at": run_utc, "agent": "learning", "level": "info",
                    "msg": f"Account {c['account']}: {c['resolved_total']:,} predictions scored so far"
                           + (f", recent hit rate {c['recent_hit_rate']:.0%}" if c.get("recent_hit_rate") is not None else "")})
    bad = [c for c in checks if c["status"] not in ("OK", "INFO")]
    for c in bad:
        out.append({"at": run_utc, "agent": "checks", "level": "error", "msg": f"{c['check']}: {c['detail']}"[:220]})
    out.append({"at": run_utc, "agent": "checks", "level": "info" if not bad else "error",
                "msg": f"Run finished: {len(checks) - len(bad)} of {len(checks)} checks passed"})
    out.sort(key=lambda r: str(r["at"]), reverse=True)
    return out[:keep]
