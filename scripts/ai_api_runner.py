"""AI agents through the Claude API (runs inside GitHub Actions, no Claude plan needed).

  python scripts/ai_api_runner.py daily    news brief (web search) + daily AI analyst (account E)
  python scripts/ai_api_runner.py hourly   hourly AI analyst (account F)

SIMULATION ONLY. The model only writes forecast files; it has no tools except web search
and cannot trade. Every file it writes goes through the same validators as before.

Budget: every call's real cost (from the API's usage numbers) is appended to
live/api_spend.jsonl. A call is skipped when this month's spend plus the call's worst
case would pass ATLANTIS_API_BUDGET_USD (default 18, leaving room under a $20 top-up).
Without ANTHROPIC_API_KEY the script prints SKIP and exits 0, so the simulation still runs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

MODEL = "claude-opus-5-5"
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ = 4.0 / 1e6, 20.0 / 1e6, 0.2 / 1e6   # USD per token
PRICE_SEARCH = 10.0 / 1000                                               # USD per web search
SPEND = Path("live/api_spend.jsonl")
BUDGET = float(os.environ.get("ATLANTIS_API_BUDGET_USD", "18"))
HOURLY_EVERY_H = 5.0     # at most one hourly-analyst call per 5 hours (budget: about 4 per day)
WORST_CASE = {"news": 1.00, "daily_analyst": 0.40, "hourly_analyst": 0.40}
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD", "BTCUSD", "ETHUSD", "AAPLUSUSD",
           "MSFTUSUSD", "NVDAUSUSD", "AMZNUSUSD", "GOOGLUSUSD", "USA500IDXUSD", "USATECHIDXUSD", "DEUIDXEUR",
           "GBRIDXGBP", "JPNIDXJPY", "LIGHTCMDUSD", "XAUUSD"]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def month_spend() -> float:
    if not SPEND.exists():
        return 0.0
    ym = datetime.now(UTC).strftime("%Y-%m")
    return sum(r["usd"] for r in map(json.loads, SPEND.read_text().splitlines()) if r["at"].startswith(ym))


def record(task: str, usage) -> float:
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    usd = (usage.input_tokens * PRICE_IN + cache_write * PRICE_IN * 1.25 + cache_read * PRICE_CACHE_READ
           + usage.output_tokens * PRICE_OUT + searches * PRICE_SEARCH)
    SPEND.parent.mkdir(parents=True, exist_ok=True)
    with SPEND.open("a") as f:
        f.write(json.dumps({"at": now_iso(), "task": task, "model": MODEL, "input_tokens": usage.input_tokens,
                            "cache_read": cache_read, "output_tokens": usage.output_tokens,
                            "web_searches": searches, "usd": round(usd, 4)}) + "\n")
    return usd


def allowed(task: str) -> bool:
    spent = month_spend()
    if spent + WORST_CASE[task] > BUDGET:
        print(f"SKIP {task}: month spend ${spent:.2f} + worst case ${WORST_CASE[task]:.2f} > budget ${BUDGET:.2f}")
        return False
    return True


def ask(task: str, system: str, prompt: str, web_search: bool = False) -> str:
    """One model call (continues after pause_turn). Returns all text; records the cost."""
    import anthropic
    client = anthropic.Anthropic()
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}] if web_search else []
    messages = [{"role": "user", "content": prompt}]
    texts = []
    for _ in range(4):
        resp = client.messages.create(model=MODEL, max_tokens=16000, system=system, messages=messages,
                                      output_config={"effort": "low"}, **({"tools": tools} if tools else {}))
        spent = record(task, resp.usage)
        print(f"{task}: stop={resp.stop_reason} in={resp.usage.input_tokens} out={resp.usage.output_tokens} ${spent:.3f}")
        texts += [b.text for b in resp.content if b.type == "text"]
        if resp.stop_reason != "pause_turn":
            if resp.stop_reason == "refusal":
                raise SystemExit(f"{task}: the model declined; nothing written")
            break
        messages = [*messages, {"role": "assistant", "content": resp.content}]
    return "\n".join(texts)


def last_json(text: str) -> dict:
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    raw = blocks[-1] if blocks else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def briefing(script: str) -> tuple[str | None, str]:
    out = subprocess.run([sys.executable, script], capture_output=True, text=True, check=True).stdout
    if out.startswith("SKIP"):
        print(out.strip())
        return None, out
    m = re.search(r"(data/llm/\S+?\.json)", out)
    return (m.group(1) if m else None), out


def clean_probs(d: dict) -> dict:
    out = {}
    for s, v in (d.get("probs") or {}).items():
        try:
            p = float(v)
        except (TypeError, ValueError):
            continue
        if s in SYMBOLS and 0.0 < p < 1.0:
            out[s] = round(min(max(p, 0.02), 0.98), 3)
    return out


ANALYST_SYSTEM = (
    "You are the ATLANTIS AI analyst in a paper-trading SIMULATION (no real money, no orders). You read chart "
    "indicators and dated news and give calibrated probabilities that each instrument's mid price will be higher "
    "at the stated horizon. Your forecasts are scored with the Brier score against no-view (0.50) and other models; "
    "overconfidence is punished. Keep most probabilities between 0.45 and 0.55; go further only with a concrete "
    "reason from the data or a dated news item. Omit instruments you have no view on. Never invent facts. "
    "Answer with one short reasoning paragraph, then a single ```json block: {\"probs\": {\"SYMBOL\": p, ...}}.")


def analyst(task: str, script: str, horizon: str) -> None:
    target, text = briefing(script)
    if target is None or not allowed(task):
        return
    target = Path(target)
    if target.exists():
        print(f"SKIP {task}: {target} exists")
        return
    reply = ask(task, ANALYST_SYSTEM, f"Horizon: {horizon}. Symbols: {', '.join(SYMBOLS)}.\n\n{text[:60000]}")
    probs = clean_probs(last_json(reply))
    if not probs:
        print(f"{task}: no usable probabilities; nothing written")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"made_at": now_iso(), "analyst": f"claude-api:{MODEL}", "probs": probs}, indent=1))
    print(f"{task}: wrote {target} ({len(probs)} instruments)")


NEWS_SYSTEM = (
    "You are the ATLANTIS market-intelligence agent for a paper-trading SIMULATION. Use web search to collect "
    "market-moving news from the LAST 72 HOURS only, plus the economic calendar for the next 5 trading days. "
    "Rules: every item needs a real source URL you saw in the search results and a verifiable publication time "
    "(ISO 8601, UTC); leave out anything you cannot date. Never invent headlines, numbers, dates or URLs. "
    "tone is -1..+1 for the instrument's price (0 if unclear); be conservative. Write facts, not trading advice.")


def news(bar_date: str) -> None:
    target = Path(f"knowledge/intel/{bar_date}.json")
    if target.exists() or not allowed("news"):
        return
    fmt = ('{"date": "%s", "made_at": "<UTC ISO now>", "agent": "atlantis-news-analyst (api)", '
           '"summary": "3-6 sentences", "calendar": [{"when": "YYYY-MM-DD[THH:MMZ]", "event": "...", '
           '"region": "US", "importance": "high|medium|low", "symbols": ["EURUSD"], "source": "https://..."}], '
           '"items": [{"symbols": ["NVDAUSUSD"], "headline": "...", "source": "https://...", '
           '"published_at": "<ISO>", "tone": 0.0, "relevance": "high|medium|low", "note": "why it matters"}], '
           '"views": {"NVDAUSUSD": {"tone": 0.0, "event_risk": "high|normal", "reason": "..."}}}') % bar_date
    prompt = (f"Now (UTC): {now_iso()}. Cover: central banks and macro data (USD, EUR, GBP, JPY, AUD, CHF, CAD); "
              "Apple, Microsoft, NVIDIA, Amazon, Alphabet; Bitcoin and Ether; oil (OPEC, inventories); gold; "
              "S&P 500, Nasdaq 100, DAX, FTSE, Nikkei. Use at most 6 searches.\n"
              f"Allowed symbols: {', '.join(SYMBOLS)}, MACRO.\nEnd with one ```json block in exactly this format:\n{fmt}")
    from atlantis.intel.news import BriefError, validate
    brief = last_json(ask("news", NEWS_SYSTEM, prompt, web_search=True))
    brief["date"], brief["made_at"] = bar_date, now_iso()
    try:
        clean, report = validate(brief)
    except BriefError as e:
        print(f"news: brief rejected ({e}); nothing written")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(clean, indent=1))
    print(f"news: wrote {target}: {json.dumps(report)}")


def main(mode: str) -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("SKIP: no ANTHROPIC_API_KEY secret; AI agents not run (the simulation still runs)")
        return
    print(f"month spend so far ${month_spend():.2f} of ${BUDGET:.2f}")
    if mode == "daily":
        _, text = briefing("scripts/analyst_brief.py")
        m = re.search(r"bar (\d{4}-\d{2}-\d{2})", text)
        if m:                       # the news brief runs even when the analyst file for that bar exists
            news(m.group(1))
        analyst("daily_analyst", "scripts/analyst_brief.py", "5 trading days after the briefing bar")
    elif mode == "hourly":
        # GitHub starts scheduled runs late, so "due" is decided by elapsed time, not by the clock hour.
        files = sorted(Path("data/llm/hourly").glob("*.json"))
        if files:
            last = datetime.fromisoformat(json.loads(files[-1].read_text())["made_at"])
            age_h = (datetime.now(UTC) - last).total_seconds() / 3600
            if age_h < HOURLY_EVERY_H:
                print(f"SKIP hourly_analyst: last forecast {age_h:.1f} h ago (< {HOURLY_EVERY_H} h)")
                return
        analyst("hourly_analyst", "scripts/analyst_brief_hourly.py", "4 hours after the briefing bar")
    else:
        raise SystemExit("usage: ai_api_runner.py daily|hourly")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
