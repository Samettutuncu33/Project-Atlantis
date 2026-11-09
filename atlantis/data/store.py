"""Parquet market-data store with a provenance manifest.

Every dataset written here records: source, symbol, raw-file URLs and SHA256
hashes, retrieval time, and validation issues. A content hash of the final
frame goes into every backtest run manifest so results are reproducible.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from atlantis.data.validate import Issue


def frame_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df, index=True).to_numpy().tobytes())
    h.update(",".join(map(str, df.columns)).encode())
    return h.hexdigest()


class DataStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "clean").mkdir(parents=True, exist_ok=True)

    def path(self, symbol: str) -> Path:
        return self.root / "clean" / f"{symbol}_daily.parquet"

    def write(self, symbol: str, df: pd.DataFrame, provenance: list[dict],
              issues: list[Issue]) -> dict:
        p = self.path(symbol)
        df.to_parquet(p)
        manifest = {
            "symbol": symbol, "source": df.attrs.get("source", "unknown"),
            "rows": len(df), "start": str(df.index.min()), "end": str(df.index.max()),
            "frame_sha256": frame_hash(df), "raw_files": provenance,
            "issues": [i.as_dict() for i in issues],
            "label": "HISTORICAL MARKET DATA (non-Saxo source)",
        }
        p.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=1))
        return manifest

    def read(self, symbol: str) -> tuple[pd.DataFrame, dict]:
        p = self.path(symbol)
        df = pd.read_parquet(p)
        manifest = json.loads(p.with_suffix(".manifest.json").read_text())
        if frame_hash(df) != manifest["frame_sha256"]:
            raise RuntimeError(f"{symbol}: stored data does not match manifest hash")
        df.attrs["source"] = manifest["source"]
        df.attrs["symbol"] = symbol
        return df, manifest

    def available(self) -> list[str]:
        return sorted(p.name.split("_daily")[0] for p in (self.root / "clean").glob("*_daily.parquet"))
