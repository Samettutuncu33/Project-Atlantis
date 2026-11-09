from pathlib import Path

import pandas as pd

from atlantis.intel.sources.ibkr_files import cross_check, load_bars

ROOT = Path(__file__).resolve().parent.parent / "data" / "ibkr"


def test_saved_ibkr_file_loads_as_daily_bars():
    df = load_bars("NVDAUSUSD", ROOT)
    assert len(df) == 21 and df.attrs["source"].startswith("IBKR")
    assert df.loc["2026-11-06", "close"].item() == 186.64
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()


def test_cross_check_flags_large_gaps():
    days = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"], utc=True)
    ib = pd.DataFrame({"close": [100.0, 100.0, 100.0]}, index=days[:3])
    du = pd.DataFrame({"bid_open": [100.0, 100.0, 100.0, 105.0], "ask_open": [100.0, 100.0, 100.0, 105.0]},
                      index=days)
    c = cross_check("X", ib, du)[0]
    assert c["status"] == "OK" and "+5.00%" in c["detail"]     # median small, largest gap reported
    du2 = du * 1.03
    assert cross_check("X", ib, du2)[0]["status"] == "WARN"
