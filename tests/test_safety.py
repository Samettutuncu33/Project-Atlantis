"""Safety tests: the platform must never be able to reach a live broker endpoint."""

import re
from pathlib import Path

import pytest

from atlantis.intel.sources.saxo_sim import SafetyViolation, SaxoSimAdapter, assert_safe

PKG = Path(__file__).resolve().parent.parent / "atlantis"


@pytest.mark.parametrize("method,url", [
    ("GET", "https://gateway.saxobank.com/openapi/ref/v1/instruments"),          # LIVE
    ("GET", "https://gateway.saxobank.com/sim/openapi/trade/v2/orders"),         # trading
    ("POST", "https://gateway.saxobank.com/sim/openapi/trade/v2/orders"),
    ("GET", "https://gateway.saxobank.com/sim/openapi/port/v1/accounts/me"),     # account
    ("GET", "https://gateway.saxobank.com/sim/openapi/port/v1/positions"),
    ("GET", "https://evil.example.com/sim/openapi/ref/v1/instruments"),
    ("GET", "http://gateway.saxobank.com/sim/openapi/ref/v1/instruments"),
    ("DELETE", "https://gateway.saxobank.com/sim/openapi/ref/v1/instruments"),
    ("GET", "https://gateway.saxobank.com/sim/openapi/root/v1/user"),
])
def test_unsafe_requests_refused(method, url):
    with pytest.raises(SafetyViolation):
        assert_safe(method, url)


def test_reference_and_chart_reads_allowed():
    assert_safe("GET", "https://gateway.saxobank.com/sim/openapi/ref/v1/instruments/details/21/FxSpot")
    assert_safe("GET", "https://gateway.saxobank.com/sim/openapi/chart/v3/charts")


def test_adapter_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ATLANTIS_SAXO_SIM_ENABLED", raising=False)
    with pytest.raises(SafetyViolation):
        SaxoSimAdapter()


def test_no_live_endpoints_or_secrets_in_code():
    live = re.compile(r"gateway\.saxobank\.com/openapi|live\.logonvalidation|saxotrader\.com/oapi")
    secret = re.compile(r"(?i)(access_token|client_secret|password)\s*=\s*['\"][^'\"]{8,}")
    for p in PKG.rglob("*.py"):
        text = p.read_text()
        assert not live.search(text), f"live endpoint referenced in {p}"
        assert not secret.search(text), f"possible hard-coded secret in {p}"
