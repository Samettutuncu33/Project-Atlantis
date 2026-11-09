"""Saxo OpenAPI SIMULATION-gateway adapter — READ-ONLY, DISABLED by default.

Phase 2 only. Hard safety rules enforced in code (and in tests):
  * Only host gateway.saxobank.com with path prefix /sim/openapi/ is allowed.
    The LIVE gateway (/openapi/ without /sim, or any other host) is refused.
  * Only HTTP GET. Only reference-data and chart services are allowed.
    Every /trade/, /port/ (account), and order/position path is refused.
  * Disabled unless ATLANTIS_SAXO_SIM_ENABLED=1.
  * No credentials are read, stored or logged here: the cloud environment's
    proxy injects the token for the SIM host (configured by the user).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import requests

SIM_HOST = "gateway.saxobank.com"
SIM_PREFIX = "/sim/openapi/"
ALLOWED_SERVICES = ("ref/", "chart/")
FORBIDDEN_FRAGMENTS = ("/trade/", "/port/", "/orders", "/positions", "/closepositions",
                       "/netpositions", "/cs/", "/hist/", "/root/")


class SafetyViolation(RuntimeError):
    pass


def assert_safe(method: str, url: str) -> None:
    u = urlparse(url)
    if method.upper() != "GET":
        raise SafetyViolation(f"method {method} refused: adapter is read-only")
    if u.scheme != "https" or u.hostname != SIM_HOST:
        raise SafetyViolation(f"host {u.hostname} refused: only the SIM gateway is allowed")
    if not u.path.startswith(SIM_PREFIX):
        raise SafetyViolation(f"path {u.path} refused: LIVE endpoints are never allowed")
    low = u.path.lower()
    if any(f in low for f in FORBIDDEN_FRAGMENTS):
        raise SafetyViolation(f"path {u.path} refused: trading/account services are blocked")
    service = u.path[len(SIM_PREFIX):]
    if not service.startswith(ALLOWED_SERVICES):
        raise SafetyViolation(f"service {service} refused: only {ALLOWED_SERVICES} allowed")


class SaxoSimAdapter:
    def __init__(self, session: requests.Session | None = None):
        if os.environ.get("ATLANTIS_SAXO_SIM_ENABLED") != "1":
            raise SafetyViolation("Saxo SIM adapter is disabled (set ATLANTIS_SAXO_SIM_ENABLED=1 "
                                  "after configuring SIM access)")
        self.s = session or requests.Session()

    def get(self, service_path: str, params: dict | None = None) -> dict:
        url = f"https://{SIM_HOST}{SIM_PREFIX}{service_path.lstrip('/')}"
        assert_safe("GET", url)
        r = self.s.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # Read-only conveniences (documented OpenAPI services)
    def instrument_details(self, uic: int, asset_type: str = "FxSpot") -> dict:
        return self.get(f"ref/v1/instruments/details/{uic}/{asset_type}")

    def chart(self, uic: int, asset_type: str = "FxSpot", horizon: int = 1440, count: int = 1200) -> dict:
        return self.get("chart/v3/charts", {"Uic": uic, "AssetType": asset_type,
                                            "Horizon": horizon, "Count": count})
