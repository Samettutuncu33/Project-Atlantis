"""News briefs: stale, undated, unsourced or impossible items are dropped, never used."""
import json

import pytest

from atlantis.intel.news import BriefError, bundle_rows, validate

MADE = "2026-11-10T00:45:00Z"


def item(**kw):
    base = {"symbols": ["NVDAUSUSD"], "headline": "h", "source": "https://example.com/a",
            "published_at": "2026-11-09T15:00:00Z", "tone": -0.4, "relevance": "high", "note": "n"}
    base.update(kw)
    return base


def brief(items, **kw):
    b = {"date": "2026-11-09", "made_at": MADE, "agent": "atlantis-news-analyst", "summary": "s",
         "items": items, "calendar": [], "views": {}}
    b.update(kw)
    return b


def test_filters_bad_items():
    clean, rep = validate(brief([
        item(),                                                    # kept
        item(published_at="2024-05-01T10:00:00Z"),                 # stale (old search result)
        item(published_at="2026-11-11T00:00:00Z"),                 # from the future
        item(source="not a url"),                                  # unsourced
        item(published_at=None),                                   # undated
        item(symbols=["TSLA"]),                                    # not in the universe
        item(tone=3),                                              # out of range
    ]))
    assert rep["items_kept"] == 1 and len(clean["items"]) == 1
    assert rep["dropped"] == {"older than 72 hours": 1, "published after the brief (impossible)": 1,
                              "no valid source url": 1, "no readable publication time": 1,
                              "no known symbol": 1, "tone outside [-1, 1]": 1}


def test_structural_errors_raise():
    with pytest.raises(BriefError):
        validate({"date": "2026-11-09", "items": []})


def test_bundle_rows_uses_latest_valid_brief(tmp_path):
    (tmp_path / "2026-11-06.json").write_text(json.dumps(brief([item(published_at="2026-11-06T10:00:00Z")],
                                                               made_at="2026-11-07T00:40:00Z", date="2026-11-06")))
    (tmp_path / "2026-11-09.json").write_text(json.dumps(brief([item()],
        views={"NVDAUSUSD": {"tone": -0.3, "event_risk": "high", "reason": "earnings next week"}})))
    rows = bundle_rows(tmp_path)
    assert rows["intel_summary"][0]["date"] == "2026-11-09"
    assert rows["intel_items"][0]["names"] == "NVIDIA"
    assert rows["intel_views"][0]["event_risk"] == "high"
