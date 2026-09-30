"""Optional provider: US National Weather Service API (api.weather.gov). Free, no key.

Coverage: United States and territories only (NWS gridpoints ~2.5 km).
Units: the /forecast endpoint reports `temperature` with `temperatureUnit` (normally "F").
Timezone: period start/end times carry the local UTC offset; we take the DAYTIME period whose
    start falls on the target local date as the forecast daily high.
Cadence: forecasts are typically refreshed about hourly; `updateTime`/`generationTime` is stored
    as the issue time.
Limitations:
  * A gridpoint forecast is NOT the settlement station's official reading; the settlement
    station and source are defined by each market's rules (and may not be NWS).
  * No uncertainty is provided; sigma remains YOUR assumption and is labeled as such.
  * The API requires a User-Agent identifying you; set weather.nws_user_agent in config.toml.
  * Availability from your network is not guaranteed; failures are reported, never filled in.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime

from ..timeutil import parse_ts


def _get(url: str, user_agent: str, opener=None) -> dict:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": user_agent,
                                                             "Accept": "application/geo+json"})
    with (opener or urllib.request.urlopen)(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def extract_daily_high(forecast_json: dict, target: date) -> dict | None:
    """Pure parser: return {'expected_high','unit','issued_at','period_name'} or None."""
    props = forecast_json.get("properties") or {}
    issued = props.get("updateTime") or props.get("generatedAt") or props.get("updated")
    if not issued:
        return None
    for p in props.get("periods") or []:
        if not p.get("isDaytime"):
            continue
        start = datetime.fromisoformat(p["startTime"])  # keeps local offset
        if start.date() == target and p.get("temperature") is not None:
            return {"expected_high": float(p["temperature"]), "unit": p.get("temperatureUnit", "F"),
                    "issued_at": parse_ts(issued), "period_name": p.get("name", ""),
                    "detail": p.get("shortForecast", "")}
    return None


def fetch_nws_forecast(lat: float, lon: float, target: date, user_agent: str, opener=None) -> tuple[dict | None, dict]:
    point = _get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", user_agent, opener)
    url = (point.get("properties") or {}).get("forecast")
    if not url or not url.startswith("https://api.weather.gov/"):
        raise RuntimeError("NWS points response had no forecast URL")
    fc = _get(url, user_agent, opener)
    return extract_daily_high(fc, target), {"points_url": point.get("id"), "forecast_url": url, "forecast": fc}
