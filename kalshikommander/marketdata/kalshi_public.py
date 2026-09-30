"""Read-only client for Kalshi's PUBLIC market-data REST endpoints (no auth, no keys).

Safety properties:
  * Only HTTP GET is ever issued.
  * Only an allowlist of market-data paths can be requested (series, events, markets, orderbook).
  * No authentication headers, keys, or signing are implemented.
Order endpoints are not referenced anywhere in this codebase.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import MarketDataSource

PUBLIC_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
_ALLOWED_PATHS = [
    re.compile(r"^/series$"),
    re.compile(r"^/series/[A-Za-z0-9_.-]+$"),
    re.compile(r"^/events$"),
    re.compile(r"^/events/[A-Za-z0-9_.-]+$"),
    re.compile(r"^/markets$"),
    re.compile(r"^/markets/[A-Za-z0-9_.-]+$"),
    re.compile(r"^/markets/[A-Za-z0-9_.-]+/orderbook$"),
]


class NotAllowedError(RuntimeError):
    pass


class KalshiPublicClient(MarketDataSource):
    name = "kalshi_public"
    is_sample = False

    # Gentle pacing: following many cities means hundreds of reads per update.
    MIN_INTERVAL_S = 0.08

    def __init__(self, timeout: float = 15.0, opener=None, min_interval: float | None = None):
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self._min_interval = self.MIN_INTERVAL_S if min_interval is None else min_interval
        self._last = 0.0

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not any(p.match(path) for p in _ALLOWED_PATHS):
            raise NotAllowedError(f"path not on read-only allowlist: {path}")
        url = PUBLIC_BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        req = urllib.request.Request(url, method="GET", headers={
            "Accept": "application/json", "User-Agent": "KalshiKommander-research/0.1 (read-only)"})
        assert req.get_method() == "GET"
        for attempt in range(3):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                with self._open(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:  # rate limited: back off and retry
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("unreachable")

    def list_series(self) -> list[dict]:
        out, last_err = [], None
        for params in ({"category": "Climate and Weather"}, {}):
            try:
                data = self._get("/series", params)
            except Exception as e:
                last_err = e
                continue
            out = data.get("series") or []
            if out:
                return out
        if last_err is not None:
            raise last_err
        return out

    def get_series(self, series_ticker: str) -> dict:
        return self._get(f"/series/{series_ticker}").get("series") or {}

    def list_events(self, series_ticker: str) -> list[dict]:
        events, cursor = [], None
        for _ in range(5):
            data = self._get("/events", {"series_ticker": series_ticker, "status": "open",
                                         "with_nested_markets": "true", "limit": 50, "cursor": cursor})
            events += data.get("events") or []
            cursor = data.get("cursor")
            if not cursor:
                break
        return events

    def get_market(self, ticker: str) -> dict:
        return self._get(f"/markets/{ticker}").get("market") or {}

    def get_orderbook(self, ticker: str) -> dict:
        return self._get(f"/markets/{ticker}/orderbook")
