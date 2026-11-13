"""The Claude API runner: budget guard, parsing, no-key skip. No network calls."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("ai_api_runner", Path(__file__).parents[1] / "scripts" / "ai_api_runner.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def test_budget_guard_skips_near_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "SPEND", tmp_path / "spend.jsonl")
    monkeypatch.setattr(r, "BUDGET", 18.0)
    assert r.allowed("hourly_analyst")
    r.SPEND.write_text(json.dumps({"at": r.now_iso(), "usd": 17.8}) + "\n"
                       + json.dumps({"at": "2000-01-01T00:00:00+00:00", "usd": 99}) + "\n")
    assert abs(r.month_spend() - 17.8) < 1e-9          # other months don't count
    assert not r.allowed("hourly_analyst")


def test_cost_record_uses_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "SPEND", tmp_path / "spend.jsonl")
    u = SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000, cache_read_input_tokens=0,
                        cache_creation_input_tokens=0, server_tool_use=SimpleNamespace(web_search_requests=3))
    usd = r.record("news", u)
    assert abs(usd - (4.0 + 2.0 + 0.03)) < 1e-9
    assert json.loads(r.SPEND.read_text())["web_searches"] == 3


def test_parse_and_clean_probs():
    text = 'reasoning...\n```json\n{"probs": {"EURUSD": 0.53, "NVDAUSUSD": 1.2, "FAKE": 0.6, "XAUUSD": "0.47", "BTCUSD": 0.999}}\n```'
    probs = r.clean_probs(r.last_json(text))
    assert probs == {"EURUSD": 0.53, "XAUUSD": 0.47, "BTCUSD": 0.98}


def test_no_key_skips(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(r, "STAGE_FILE", tmp_path / "ai_stage.json")
    r.main("hourly")
    assert "SKIP" in capsys.readouterr().out
    assert json.loads(r.STAGE_FILE.read_text())["analyst"]["status"] == "idle"     # recorded honestly, not as work done


def test_stage_keeps_a_real_result_over_a_later_not_due(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "STAGE_FILE", tmp_path / "ai_stage.json")
    r.stage("analyst", r.now_iso(), "done", "20 forecasts")
    r.stage("analyst", r.now_iso(), "idle", "not due")
    assert json.loads(r.STAGE_FILE.read_text())["analyst"]["detail"] == "20 forecasts"
