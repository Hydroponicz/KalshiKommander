"""Automatic forecast provider: Open-Meteo (https://open-meteo.com). Free, no API key.

Coverage: worldwide, blending national weather models ("best match"), roughly 1-11 km grids.
Units: requested in °F (`temperature_unit=fahrenheit`); the response's `daily_units` is checked.
Timezone: requested in the CITY's timezone, so each daily maximum covers that city's local
    calendar day (midnight to midnight local clock time, NOT the local-standard-time climate day
    some official reports use).
Cadence: models update every 1-6 hours. The API does not say when the underlying model run
    was produced, so the time we RETRIEVED the forecast is stored as its issue time. That is
    when this app knew it, which is what matters for look-ahead safety, but it can make a
    forecast look fresher than the model run behind it.
Limitations:
  * A grid-cell forecast, not the settlement station's official reading.
  * No uncertainty is provided; the "±" stays your configured assumption.
  * Free tier is for non-commercial use (about 10,000 calls/day); this app makes a few per hour.
  * Availability from your network is not guaranteed; failures are reported, never filled in.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date

BASE_URL = "https://api.open-meteo.com/v1/forecast"


def build_url(lat: float, lon: float, tz_name: str) -> str:
    q = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "daily": "temperature_2m_max",
         "temperature_unit": "fahrenheit", "timezone": tz_name, "forecast_days": 3}
    return BASE_URL + "?" + urllib.parse.urlencode(q)


def extract_daily_highs(payload: dict, tz_name: str) -> dict[date, tuple[float, str]]:
    """Pure parser: {local date: (daily max, unit)}. Raises if units/timezone are not as requested."""
    if payload.get("timezone") != tz_name:
        raise ValueError(f"Open-Meteo answered in timezone {payload.get('timezone')!r}, expected {tz_name!r}")
    unit_raw = ((payload.get("daily_units") or {}).get("temperature_2m_max") or "").replace("°", "").strip().upper()
    if unit_raw not in ("F", "C"):
        raise ValueError(f"unexpected Open-Meteo unit {unit_raw!r}")
    daily = payload.get("daily") or {}
    out = {}
    for d, v in zip(daily.get("time") or [], daily.get("temperature_2m_max") or []):
        if v is None:
            continue  # missing value: never filled in
        out[date.fromisoformat(d)] = (float(v), unit_raw)
    return out


def fetch_open_meteo(lat: float, lon: float, tz_name: str, opener=None) -> tuple[dict, str]:
    url = build_url(lat, lon, tz_name)
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "KalshiKommander-research/0.1"})
    with (opener or urllib.request.urlopen)(req, timeout=15) as r:
        payload = json.loads(r.read().decode("utf-8"))
    return extract_daily_highs(payload, tz_name), url
