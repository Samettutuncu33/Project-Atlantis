"""Dukascopy public historical data feed (bid and ask candles).

Provenance: this is REAL two-sided market quote data from Dukascopy Bank SA.
It is NOT Saxo Bank data. Every frame produced here is tagged with
``source="dukascopy"`` so reports never confuse it with Saxo quotes.

File format (verified empirically 2026-11-09 against known EURUSD closes):
  - URL: https://datafeed.dukascopy.com/datafeed/{SYM}/{YYYY}/{SIDE}_candles_day_1.bi5
  - LZMA-compressed, big-endian records of 24 bytes:
      int32 seconds-since-period-start, int32 open, int32 close, int32 low,
      int32 high, float32 volume
  - Prices are integers scaled by ``point`` (1e5 for most FX, 1e3 for JPY
    quotes and metals).  NB: the order is O, C, L, H — not OHLC.
"""

from __future__ import annotations

import hashlib
import json
import lzma
import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
RECORD = struct.Struct(">5if")
USER_AGENT = "Mozilla/5.0 (compatible; atlantis-research/0.1)"

# Price scaling. Verified for EURUSD (1e5). JPY pairs and XAU/XAG use 1e3 —
# validated at parse time by a plausibility range check (see PLAUSIBLE_RANGE).
POINT: dict[str, float] = {
    "EURUSD": 1e5, "GBPUSD": 1e5, "AUDUSD": 1e5, "NZDUSD": 1e5,
    "USDCAD": 1e5, "USDCHF": 1e5, "EURGBP": 1e5,
    "USDJPY": 1e3, "EURJPY": 1e3, "GBPJPY": 1e3,
    "XAUUSD": 1e3, "XAGUSD": 1e3,
}
# Very wide sanity bands; a scaling error would be off by 100x and fail these.
PLAUSIBLE_RANGE: dict[str, tuple[float, float]] = {
    "EURUSD": (0.7, 1.8), "GBPUSD": (0.9, 2.2), "AUDUSD": (0.4, 1.2),
    "NZDUSD": (0.3, 1.0), "USDCAD": (0.8, 1.7), "USDCHF": (0.6, 1.4),
    "EURGBP": (0.6, 1.1), "USDJPY": (70, 200), "EURJPY": (80, 200),
    "GBPJPY": (100, 260), "XAUUSD": (900, 6000), "XAGUSD": (10, 120),
}


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchResult:
    path: Path
    sha256: str
    url: str
    retrieved_utc: str
    from_cache: bool


def _url(symbol: str, year: int, side: str) -> str:
    if side not in ("BID", "ASK"):
        raise ValueError(f"side must be BID or ASK, got {side!r}")
    return f"{BASE_URL}/{symbol}/{year}/{side}_candles_day_1.bi5"


def fetch_year(symbol: str, year: int, side: str, raw_dir: Path,
               max_attempts: int = 8, session: requests.Session | None = None,
               offline: bool = False) -> FetchResult:
    """Download one yearly daily-candle file, caching it on disk.

    The feed resets connections frequently, so we retry with exponential
    backoff. A cached file is reused only if its sidecar hash still matches.
    """
    url = _url(symbol, year, side)
    dest = raw_dir / symbol / f"{year}_{side}_day.bi5"
    meta = dest.with_suffix(".json")
    if dest.exists() and meta.exists():
        m = json.loads(meta.read_text())
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest == m["sha256"]:
            return FetchResult(dest, digest, url, m["retrieved_utc"], True)
        raise FetchError(f"cache corruption: {dest} hash {digest} != {m['sha256']}")

    if offline:
        raise FetchError(f"offline mode: {dest} not cached")
    s = session or requests.Session()
    last: Exception | None = None
    for attempt in range(max_attempts):
        try:
            r = s.get(url, headers={"User-Agent": USER_AGENT}, timeout=40)
            if r.status_code == 404:
                raise FetchError(f"404 (no data published) for {url}")
            if r.status_code == 200 and r.content:
                lzma.decompress(r.content)  # integrity check before caching
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                digest = hashlib.sha256(r.content).hexdigest()
                now = datetime.now(UTC).isoformat(timespec="seconds")
                meta.write_text(json.dumps({"url": url, "sha256": digest,
                                            "retrieved_utc": now, "source": "dukascopy"}))
                return FetchResult(dest, digest, url, now, False)
            last = FetchError(f"HTTP {r.status_code} for {url}")
        except FetchError:
            raise
        except Exception as e:  # network resets are common on this feed
            last = e
        time.sleep(min(2 ** attempt, 30))
    raise FetchError(f"giving up on {url} after {max_attempts} attempts: {last}")


def parse_day_candles(blob: bytes, symbol: str, year: int) -> pd.DataFrame:
    raw = lzma.decompress(blob)
    if len(raw) % RECORD.size:
        raise FetchError(f"{symbol} {year}: payload length {len(raw)} not a multiple of 24")
    arr = np.frombuffer(raw, dtype=np.dtype([("t", ">i4"), ("o", ">i4"), ("c", ">i4"),
                                             ("l", ">i4"), ("h", ">i4"), ("v", ">f4")]))
    point = POINT[symbol]
    start = datetime(year, 1, 1, tzinfo=UTC)
    idx = pd.DatetimeIndex([start + timedelta(seconds=int(t)) for t in arr["t"]], name="ts")
    df = pd.DataFrame({
        "open": arr["o"].astype(float) / point, "high": arr["h"].astype(float) / point,
        "low": arr["l"].astype(float) / point, "close": arr["c"].astype(float) / point,
        "volume": arr["v"].astype(float),
    }, index=idx)
    lo, hi = PLAUSIBLE_RANGE[symbol]
    med = float(df["close"].median()) if len(df) else lo
    if not (lo <= med <= hi):
        raise FetchError(f"{symbol} {year}: median close {med} outside plausible "
                         f"range {lo}-{hi}; price scaling is probably wrong")
    return df


def cached_years(symbol: str, raw_dir: Path) -> list[int]:
    """Longest run of consecutive years with BOTH sides cached (no holes)."""
    d = raw_dir / symbol
    have = {int(p.name[:4]) for p in d.glob("*_BID_day.bi5")} & \
        {int(p.name[:4]) for p in d.glob("*_ASK_day.bi5")}
    best: list[int] = []
    for y in sorted(have):
        run = [y]
        while run[-1] + 1 in have:
            run.append(run[-1] + 1)
        if len(run) > len(best):
            best = run
    return best


def load_bid_ask(symbol: str, years: list[int], raw_dir: Path,
                 offline: bool = False) -> tuple[pd.DataFrame, list[dict]]:
    """Return a daily frame with bid_* and ask_* columns plus provenance records."""
    frames, prov = [], []
    for y in years:
        sides = {}
        for side in ("BID", "ASK"):
            res = fetch_year(symbol, y, side, raw_dir, offline=offline)
            sides[side] = parse_day_candles(res.path.read_bytes(), symbol, y)
            prov.append({"symbol": symbol, "year": y, "side": side, "url": res.url,
                         "sha256": res.sha256, "retrieved_utc": res.retrieved_utc,
                         "source": "dukascopy"})
        b = sides["BID"].add_prefix("bid_")
        a = sides["ASK"].add_prefix("ask_")
        frames.append(b.join(a, how="outer"))
    df = pd.concat(frames).sort_index()
    df.attrs["source"] = "dukascopy"
    df.attrs["symbol"] = symbol
    return df, prov
