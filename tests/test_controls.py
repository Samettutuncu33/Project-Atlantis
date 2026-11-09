"""Control Panel: pause, resume and flatten take effect from the next decision and never rewrite the past."""
import json

import pandas as pd

from atlantis.controls import Controls, sync_from_panel
from atlantis.engine import run_backtest
from atlantis.quant.strategies.library import REGISTRY


def _ev(tmp_path, *events):
    docs = [{"id": f"e{i}", "data": {"mode": m, "pressed_at": t, "by": "u"}} for i, (m, t) in enumerate(events)]
    path = tmp_path / "controls.jsonl"
    sync_from_panel(docs, path)
    return Controls.load(path), path


def test_effective_bar_and_modes(tmp_path):
    c, _ = _ev(tmp_path, ("PAUSED", "2020-06-10T10:00:00Z"), ("RUNNING", "2020-07-01T09:00:00Z"),
               ("FLATTEN", "2020-08-03T23:59:00Z"))
    ts = lambda d: pd.Timestamp(d, tz="UTC")
    assert c.mode_at(ts("2020-06-09")) == ("RUNNING", False)
    assert c.mode_at(ts("2020-06-10")) == ("PAUSED", False)      # pressed during bar 10 Jun -> its decision
    assert c.mode_at(ts("2020-07-01")) == ("RUNNING", False)
    assert c.mode_at(ts("2020-08-03")) == ("PAUSED", True)       # flatten executes once
    assert c.mode_at(ts("2020-08-04")) == ("PAUSED", False)


def test_sync_is_append_only_and_deduplicated(tmp_path):
    _, path = _ev(tmp_path, ("PAUSED", "2020-06-10T10:00:00Z"))
    before = path.read_text()
    new = sync_from_panel([{"id": "e0", "data": {"mode": "RUNNING", "pressed_at": "2021-01-01T00:00:00Z"}},
                           {"id": "bad", "data": {"mode": "BUY_EVERYTHING", "pressed_at": "2021-01-01T00:00:00Z"}}], path)
    assert new == [] and path.read_text() == before


def test_pause_blocks_new_trades_and_flatten_closes_all(fx_data, tmp_path):
    base = run_backtest(fx_data, REGISTRY["donchian_55_20"](), 20_000.0, verify_causality=False)
    fills = [e for e in base.audit.events if e["kind"] == "FILL"]
    t_mid = pd.Timestamp(fills[len(fills) // 2]["fill_ts"])
    c, _ = _ev(tmp_path, ("FLATTEN", (t_mid + pd.Timedelta(hours=3)).isoformat()))
    res = run_backtest(fx_data, REGISTRY["donchian_55_20"](), 20_000.0, verify_causality=False, controls=c)
    eff = c.events[0].effective_bar
    # identical history up to the effective bar: the past is never rewritten
    old = [(e["fill_ts"], e["symbol"], e["qty"]) for e in base.audit.events if e["kind"] == "FILL" and pd.Timestamp(e["fill_ts"]) <= eff]
    new = [(e["fill_ts"], e["symbol"], e["qty"]) for e in res.audit.events if e["kind"] == "FILL" and pd.Timestamp(e["fill_ts"]) <= eff]
    assert old == new
    # after flatten: positions closed, and no fill that opens or adds risk
    assert not res.ledger.lots
    later = [e for e in res.audit.events if e["kind"] == "FILL" and pd.Timestamp(e["fill_ts"]) > eff]
    assert all(e["tag"] in ("flatten", "stop") for e in later)
    assert any(e["kind"] == "CONTROL_FLATTEN" for e in res.audit.events)
