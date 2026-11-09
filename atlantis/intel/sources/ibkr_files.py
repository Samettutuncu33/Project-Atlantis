"""IBKR market data, READ-ONLY, ingested from saved tool outputs.

Interactive Brokers data reaches Atlantis only through the user's IBKR
connector, which Claude calls (get_price_history / get_price_snapshot). Each
call's JSON answer is saved verbatim to data/ibkr/<SYMBOL>_<conid>_<date>.json
with retrieval metadata. This module only reads those files. It never calls
IBKR and has no access to orders, accounts, balances or positions.

The user approved IBKR for market data only (2026-11-09). IBKR bars are
exchange LAST-trade prices for the regular session. Atlantis keeps executing
on Dukascopy bid/ask and uses IBKR as an independent cross-check, plus a
second source for US stocks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

# Atlantis symbol -> (IBKR contract id, security type), resolved with search_contracts
CONTRACTS: dict[str, tuple[int, str]] = {
    "NVDAUSUSD": (4815747, "STK"),     # NVIDIA CORP, NASDAQ (verified 2026-11-09)
    "MSFTUSUSD": (272093, "STK"),      # MICROSOFT CORP, NASDAQ (verified 2026-11-09)
    # AAPL, AMZN, GOOGL: lookup pending (IBKR service unavailable at the time)
}


def load_bars(symbol: str, root: Path) -> pd.DataFrame:
    """Merge all saved IBKR daily-bar files for a symbol (latest retrieval wins per date)."""
    frames = []
    for p in sorted(Path(root).glob(f"{symbol}_*.json")):
        d = json.loads(p.read_text())
        idx = pd.DatetimeIndex(pd.to_datetime(d["time"], utc=True)).normalize()
        frames.append(pd.DataFrame({k: d[k] for k in ("open", "high", "low", "close", "volume")}, index=idx)
                      .assign(retrieved_utc=d.get("retrieved_utc"), file=p.name))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index.name = "session_date"
    df.attrs["source"] = "IBKR (exchange last trade, regular session)"
    return df


def cross_check(symbol: str, ibkr: pd.DataFrame, duka: pd.DataFrame, tolerance: float = 0.01) -> list[dict]:
    """Compare IBKR session closes with Dukascopy CFD bars.

    Dukascopy's daily bar for session date D closes at 00:00 UTC on D+1, which
    is after the US close (20:00/21:00 UTC), so its *open* for D+1 sits close
    to IBKR's close for D. A gap above `tolerance` (1%) is flagged for review.
    Some gap is normal: after-hours trading moves the CFD."""
    if ibkr.empty or duka.empty:
        return [{"check": f"ibkr_crosscheck:{symbol}", "status": "WARN", "detail": "no overlapping data"}]
    mid_open = (duka["bid_open"] + duka["ask_open"]) / 2
    rows = []
    for d, r in ibkr.iterrows():
        nxt = mid_open[mid_open.index > d]
        if nxt.empty:
            continue
        cfd = float(nxt.iloc[0])
        rows.append((d, r["close"], cfd, cfd / r["close"] - 1))
    if not rows:
        return [{"check": f"ibkr_crosscheck:{symbol}", "status": "WARN", "detail": "no overlapping dates"}]
    worst = max(rows, key=lambda x: abs(x[3]))
    med = float(pd.Series([abs(x[3]) for x in rows]).median())
    status = "OK" if med <= tolerance else "WARN"
    return [{"check": f"ibkr_crosscheck:{symbol}", "status": status,
             "detail": f"{len(rows)} sessions; median |CFD - exchange| {med:.2%}; largest "
                       f"{worst[3]:+.2%} on {worst[0].date()} (exchange {worst[1]}, CFD {worst[2]:.2f})"}]
