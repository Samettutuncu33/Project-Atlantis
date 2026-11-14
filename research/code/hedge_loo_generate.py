"""Frozen-ledger generation for plan 2026-11-14-hedge-leave-one-out (simulation only, offline).

Reads ONLY cached daily bid/ask files (years <= 2025). Never touches live/, data/llm, or the network.
Usage: python hedge_loo_generate.py <scratch_dir>
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from atlantis.adaptive import run_adaptive  # noqa: E402
from atlantis.instruments.spec import universe  # noqa: E402
from atlantis.intel.sources.dukascopy_live import Fetcher, _candles  # noqa: E402
from atlantis.intel.validate import clean_daily  # noqa: E402

RAW = ROOT / "data" / "raw" / "dukascopy_live"
LAST_YEAR = 2025


class _NoNet:
    def get(self, *a, **k):
        raise RuntimeError("network access forbidden in this research run")


def has(sym: str, y: int) -> bool:
    return all((RAW / sym / str(y) / f"{s}_candles_day_1.bi5").exists()
               and (RAW / sym / str(y) / f"{s}_candles_day_1.bi5").stat().st_size > 0 for s in ("BID", "ASK"))


def load_daily(f: Fetcher, sym: str) -> pd.DataFrame | None:
    if not has(sym, LAST_YEAR):
        return None
    y0 = LAST_YEAR
    while has(sym, y0 - 1):
        y0 -= 1
    sides = {}
    for side in ("BID", "ASK"):
        parts = []
        for y in range(y0, LAST_YEAR + 1):
            payload = f.get(f"{sym}/{y}/{side}_candles_day_1.bi5", datetime(y + 1, 1, 1, tzinfo=UTC))
            d = _candles(payload, datetime(y, 1, 1, tzinfo=UTC), sym)
            parts.append(d[d["volume"] > 0])
        d = pd.concat(parts).sort_index()
        sides[side] = d[~d.index.duplicated(keep="last")].add_prefix(side.lower() + "_")
    df = sides["BID"].join(sides["ASK"], how="inner")
    df.index.name = "ts"
    df = df[df.index <= pd.Timestamp("2025-12-31", tz="UTC")]
    clean, issues = clean_daily(df, sym)
    errs = [i for i in issues if i.severity == "ERROR"]
    if errs:
        raise RuntimeError(f"{sym}: data errors {errs[:3]}")
    return clean


def main(scratch: Path) -> None:
    scratch.mkdir(parents=True, exist_ok=True)
    f = Fetcher(RAW)
    f.s = _NoNet()
    syms = list(universe()["instruments"])
    data = {}
    for s in syms:
        d = load_daily(f, s)
        if d is not None and len(d):
            data[s] = d
    llm = scratch / "empty_llm_root"
    llm.mkdir(exist_ok=True)
    led = scratch / "frozen_ledger.jsonl"
    if led.exists():
        raise SystemExit("ledger exists; freeze rule: run once")
    res = run_adaptive(data, 200.0, start=str(min(d.index[0] for d in data.values()).date()), end="2025-12-31",
                       ledger_path=led, trade_from="2099-01-01", controls=None, context_daily=None,
                       llm_root=llm, horizon=5)
    res.ledger.verify()
    sha = hashlib.sha256(led.read_bytes()).hexdigest()
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    meta = {"ledger": str(led), "sha256": sha, "git_commit": commit, "instruments": sorted(data),
            "instrument_first_bar": {s: str(d.index[0].date()) for s, d in data.items()},
            "n_records": len(res.ledger.records), "hash_chain_verified": True,
            "generated_at": datetime.now(UTC).isoformat()}
    (scratch / "freeze_record.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: meta[k] for k in ("sha256", "git_commit", "n_records")}))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
