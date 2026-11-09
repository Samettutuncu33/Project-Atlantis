"""Near-live Dukascopy data for the forward (paper) simulation.

Daily bid/ask bars (00:00 UTC boundaries, identical convention to the yearly
day files used in research) are assembled from:
  * yearly  day candles   {SYM}/{YYYY}/{SIDE}_candles_day_1.bi5         (past years)
  * monthly hour candles  {SYM}/{YYYY}/{MM}/{SIDE}_candles_hour_1.bi5   (completed months)
  * daily   minute candles {SYM}/{YYYY}/{MM}/{DD}/{SIDE}_candles_min_1.bi5 (current month)
and the latest quote from hourly tick files {SYM}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5.
MM is zero-based (January = 00) in Dukascopy URLs.

Files covering a period that ended more than 3 hours ago are cached permanently
with a SHA256; newer files are always re-fetched. SOURCE: Dukascopy, NOT Saxo.
"""

from __future__ import annotations

import hashlib
import json
import lzma
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from atlantis.intel.sources.dukascopy import BASE_URL, PLAUSIBLE_RANGE, POINT, USER_AGENT

CANDLE = np.dtype([("t", ">i4"), ("o", ">i4"), ("c", ">i4"), ("l", ">i4"), ("h", ">i4"), ("v", ">f4")])
TICK = np.dtype([("t", ">i4"), ("ask", ">i4"), ("bid", ">i4"), ("av", ">f4"), ("bv", ">f4")])


class LiveFetchError(RuntimeError):
    pass


class Fetcher:
    def __init__(self, raw_dir: Path, max_attempts: int = 10, now: datetime | None = None):
        self.raw = Path(raw_dir)
        self.max_attempts = max_attempts
        self.now = now or datetime.now(UTC)
        self.s = requests.Session()
        self.provenance: list[dict] = []
        self._mem: dict[str, bytes | None] = {}

    def get(self, rel: str, period_end: datetime) -> bytes | None:
        """Return decompressed payload, b'' for an empty file, None for 404.
        Each file is fetched at most once per run (in-memory cache)."""
        if rel in self._mem:
            return self._mem[rel]
        out = self._get(rel, period_end)
        self._mem[rel] = out
        return out

    def _get(self, rel: str, period_end: datetime) -> bytes | None:
        dest = self.raw / rel
        meta = dest.with_name(dest.name + ".json")
        final = period_end <= self.now - timedelta(hours=3)
        if final and dest.exists() and meta.exists():
            blob = dest.read_bytes()
            m = json.loads(meta.read_text())
            if hashlib.sha256(blob).hexdigest() != m["sha256"]:
                raise LiveFetchError(f"cache corruption in {dest}")
            if m.get("status") == 404:
                return None
            self.provenance.append(m)
            return lzma.decompress(blob) if blob else b""
        url = f"{BASE_URL}/{rel}"
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                r = self.s.get(url, headers={"User-Agent": USER_AGENT}, timeout=40)
                if r.status_code == 404:
                    if final:
                        self._save(dest, meta, b"", url, 404)
                    return None
                if r.status_code == 200:
                    payload = lzma.decompress(r.content) if r.content else b""
                    m = self._save(dest, meta, r.content, url, 200) if final else \
                        {"url": url, "sha256": hashlib.sha256(r.content).hexdigest(),
                         "retrieved_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                         "source": "dukascopy", "final": False}
                    self.provenance.append(m)
                    return payload
                last = LiveFetchError(f"HTTP {r.status_code}")
            except lzma.LZMAError as e:
                last = e
            except Exception as e:      # connection resets are routine on this feed
                last = e
            time.sleep(min(2 ** attempt, 20))
        raise LiveFetchError(f"{url}: {last}")

    def _save(self, dest: Path, meta: Path, blob: bytes, url: str, status: int) -> dict:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        m = {"url": url, "sha256": hashlib.sha256(blob).hexdigest(), "status": status,
             "retrieved_utc": datetime.now(UTC).isoformat(timespec="seconds"),
             "source": "dukascopy", "final": True}
        meta.write_text(json.dumps(m))
        return m


def _candles(payload: bytes, start: datetime, symbol: str) -> pd.DataFrame:
    if not payload:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                            index=pd.DatetimeIndex([], tz="UTC", name="ts"))
    a = np.frombuffer(payload, dtype=CANDLE)
    p = POINT[symbol]
    idx = pd.DatetimeIndex(pd.Timestamp(start) + pd.to_timedelta(a["t"].astype(np.int64), unit="s"),
                           name="ts")
    return pd.DataFrame({"open": a["o"] / p, "high": a["h"] / p, "low": a["l"] / p,
                         "close": a["c"] / p, "volume": a["v"].astype(float)}, index=idx)


def _to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate intraday candles to 00:00-UTC daily bars, dropping empty (flat,
    zero-volume) sub-candles first so they cannot distort open/close."""
    live = df[df["volume"] > 0]
    if live.empty:
        return live
    g = live.groupby(live.index.floor("D"))
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "volume": g["volume"].sum()})


def _side_daily(f: Fetcher, symbol: str, side: str, first_year: int, until: date) -> pd.DataFrame:
    parts = []
    for y in range(first_year, until.year):
        payload = f.get(f"{symbol}/{y}/{side}_candles_day_1.bi5", datetime(y + 1, 1, 1, tzinfo=UTC))
        if payload is None:
            raise LiveFetchError(f"{symbol} {y} day file missing")
        d = _candles(payload, datetime(y, 1, 1, tzinfo=UTC), symbol)
        parts.append(d[d["volume"] > 0])
    y = until.year
    for m in range(1, until.month):
        start = datetime(y, m, 1, tzinfo=UTC)
        end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=UTC)
        payload = f.get(f"{symbol}/{y}/{m - 1:02d}/{side}_candles_hour_1.bi5", end)
        if payload is None:
            raise LiveFetchError(f"{symbol} {y}-{m:02d} hour file missing")
        parts.append(_to_daily(_candles(payload, start, symbol)))
    d0 = date(y, until.month, 1)
    while d0 <= until:
        start = datetime(d0.year, d0.month, d0.day, tzinfo=UTC)
        payload = f.get(f"{symbol}/{d0.year}/{d0.month - 1:02d}/{d0.day:02d}/{side}_candles_min_1.bi5",
                        start + timedelta(days=1))
        if payload is not None:
            parts.append(_to_daily(_candles(payload, start, symbol)))
        d0 += timedelta(days=1)
    out = pd.concat([p for p in parts if len(p)]).sort_index()
    return out[~out.index.duplicated(keep="last")]


def daily_bid_ask(f: Fetcher, symbol: str, first_year: int, until: date) -> pd.DataFrame:
    """Completed daily bars through `until` (inclusive), bid_* and ask_* columns."""
    b = _side_daily(f, symbol, "BID", first_year, until).add_prefix("bid_")
    a = _side_daily(f, symbol, "ASK", first_year, until).add_prefix("ask_")
    df = b.join(a, how="inner")
    df.index.name = "ts"
    lo, hi = PLAUSIBLE_RANGE[symbol]
    if len(df) and not (lo <= df["bid_close"].median() <= hi):
        raise LiveFetchError(f"{symbol}: implausible price scale")
    df.attrs["source"] = "dukascopy"
    return df


def latest_quote(f: Fetcher, symbol: str, lookback_hours: int = 72) -> dict | None:
    """Last tick (bid/ask) from the most recent completed hour that has ticks."""
    h = f.now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    for _ in range(lookback_hours):
        rel = f"{symbol}/{h.year}/{h.month - 1:02d}/{h.day:02d}/{h.hour:02d}h_ticks.bi5"
        try:
            payload = f.get(rel, h + timedelta(hours=1))
        except LiveFetchError:
            payload = None
        if payload:
            a = np.frombuffer(payload, dtype=TICK)
            p = POINT[symbol]
            ts = h + timedelta(milliseconds=int(a["t"][-1]))
            return {"symbol": symbol, "ts": ts.isoformat(), "bid": a["bid"][-1] / p,
                    "ask": a["ask"][-1] / p, "source_url": f"{BASE_URL}/{rel}"}
        h -= timedelta(hours=1)
    return None


def _to_hourly(df: pd.DataFrame) -> pd.DataFrame:
    live = df[df["volume"] > 0]
    if live.empty:
        return live
    g = live.groupby(live.index.floor("h"))
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "volume": g["volume"].sum()})


def _ticks_hour(payload: bytes, hour_start: datetime, symbol: str, side: str) -> pd.DataFrame:
    if not payload:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    a = np.frombuffer(payload, dtype=TICK)
    px = (a["bid"] if side == "BID" else a["ask"]) / POINT[symbol]
    vol = (a["bv"] if side == "BID" else a["av"]).astype(float)
    idx = pd.DatetimeIndex([pd.Timestamp(hour_start)], name="ts")
    return pd.DataFrame({"open": [px[0]], "high": [px.max()], "low": [px.min()], "close": [px[-1]],
                         "volume": [vol.sum()]}, index=idx)


def _side_hourly(f: Fetcher, symbol: str, side: str, start: date, now: datetime) -> pd.DataFrame:
    parts = []
    y, m = start.year, start.month
    while (y, m) < (now.year, now.month):
        ms = datetime(y, m, 1, tzinfo=UTC)
        me = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=UTC)
        payload = f.get(f"{symbol}/{y}/{m - 1:02d}/{side}_candles_hour_1.bi5", me)
        if payload is None:
            raise LiveFetchError(f"{symbol} {y}-{m:02d} hour file missing")
        parts.append(_candles(payload, ms, symbol))
        y, m = (y + (m == 12), m % 12 + 1)
    d0 = date(now.year, now.month, 1)
    today = now.date()
    while d0 < today:
        ds = datetime(d0.year, d0.month, d0.day, tzinfo=UTC)
        payload = f.get(f"{symbol}/{d0.year}/{d0.month - 1:02d}/{d0.day:02d}/{side}_candles_min_1.bi5",
                        ds + timedelta(days=1))
        if payload is not None:
            parts.append(_to_hourly(_candles(payload, ds, symbol)))
        d0 += timedelta(days=1)
    h = datetime(today.year, today.month, today.day, tzinfo=UTC)
    last_complete = now.replace(minute=0, second=0, microsecond=0)
    while h < last_complete:
        rel = f"{symbol}/{h.year}/{h.month - 1:02d}/{h.day:02d}/{h.hour:02d}h_ticks.bi5"
        # A download failure must not silently drop an hour: that would change history between runs.
        # LiveFetchError propagates; the run stops and the next scheduled run retries.
        payload = f.get(rel, h + timedelta(hours=1))
        if payload:
            parts.append(_ticks_hour(payload, h, symbol, side))
        h += timedelta(hours=1)
    out = pd.concat([p for p in parts if len(p)]).sort_index()
    out = out[out["volume"] > 0]
    return out[~out.index.duplicated(keep="last")]


def hourly_bid_ask(f: Fetcher, symbol: str, start: date, now: datetime | None = None) -> pd.DataFrame:
    """Completed hourly bid/ask bars from `start` up to the last completed hour."""
    now = now or f.now
    b = _side_hourly(f, symbol, "BID", start, now).add_prefix("bid_")
    a = _side_hourly(f, symbol, "ASK", start, now).add_prefix("ask_")
    df = b.join(a, how="inner")
    df.index.name = "ts"
    bad = (df["ask_close"] < df["bid_close"]) | (df["ask_open"] < df["bid_open"])
    df = df[~bad]
    df.attrs["source"] = "dukascopy"
    return df
