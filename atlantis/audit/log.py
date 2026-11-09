"""Append-only audit log and reproducible run manifests."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path


class AuditLog:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def event(self, ts: str, kind: str, severity: str = "INFO", **data) -> None:
        self.events.append({"seq": len(self.events), "ts": ts, "kind": kind,
                            "severity": severity, **data})

    def by_severity(self, *levels: str) -> list[dict]:
        return [e for e in self.events if e["severity"] in levels]

    def write(self, path: Path) -> str:
        lines = [json.dumps(e, sort_keys=True, default=str) for e in self.events]
        blob = "\n".join(lines).encode()
        path.write_bytes(blob)
        return hashlib.sha256(blob).hexdigest()


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True, cwd=Path(__file__).parent).stdout.strip()
    except Exception:
        return "uncommitted"


def run_manifest(config: dict, data_hashes: dict[str, str]) -> dict:
    return {"config": config, "data_sha256": data_hashes, "code_git_sha": git_sha(),
            "python": platform.python_version(),
            "label": "SIMULATED EXECUTION on historical market data"}
