"""Work out WHERE to forecast for a Kalshi weather series, and the city's timezone, automatically.

Order of preference (each result records where it came from, and is shown on the Cities page):
  1. The settlement station named in the series' settlement sources / rules text
     (e.g. an NWS climate-report link "...issuedby=MDW" or "CLIMDW" -> station KMDW), looked up
     on the NWS stations API for exact coordinates and timezone (US stations only).
  2. A small built-in table of stations public guides say Kalshi uses (see cities.py).
  3. The city centre from Open-Meteo's free geocoding API (flagged as approximate).
If none works, the city is reported as needing a location; nothing is guessed silently.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from ..cities import guess_label, guess_timezone, suggest_station

_ISSUEDBY = re.compile(r"issuedby=([A-Za-z]{3})\b")
_CLI = re.compile(r"\bCLI([A-Z]{3})\b")
_ICAO = re.compile(r"\b(K[A-Z]{3})\b")


def station_candidates(series: dict, rules_text: str = "") -> list[str]:
    """ICAO station ids mentioned by the series' settlement sources or the rules text, best first."""
    out: list[str] = []
    texts = []
    for src in series.get("settlement_sources") or []:
        texts.append(str(src.get("url", "")))
        texts.append(str(src.get("name", "")))
    texts.append(rules_text or "")
    for t in texts:
        for m in _ISSUEDBY.findall(t):
            out.append("K" + m.upper())
        for m in _CLI.findall(t):
            out.append("K" + m)
        for m in _ICAO.findall(t):
            out.append(m)
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _get_json(url: str, user_agent: str, opener=None) -> dict:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": user_agent, "Accept": "application/geo+json"})
    with (opener or urllib.request.urlopen)(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def nws_station(icao: str, user_agent: str, opener=None) -> dict | None:
    """{'lat','lon','timezone','name'} for a US station from api.weather.gov, or None."""
    if not re.fullmatch(r"K[A-Z]{3}", icao):
        return None
    d = _get_json(f"https://api.weather.gov/stations/{icao}", user_agent, opener)
    coords = (d.get("geometry") or {}).get("coordinates") or []
    props = d.get("properties") or {}
    if len(coords) < 2 or not props.get("timeZone"):
        return None
    return {"lat": float(coords[1]), "lon": float(coords[0]), "timezone": props["timeZone"],
            "name": props.get("name") or icao}


def geocode(name: str, opener=None) -> dict | None:
    """City centre from Open-Meteo geocoding: {'lat','lon','timezone','name'} or None."""
    if not name.strip():
        return None
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": name, "count": 1, "language": "en", "format": "json"})
    d = _get_json(url, "KalshiKommander-research/0.1", opener)
    res = (d.get("results") or [])
    if not res or res[0].get("latitude") is None or not res[0].get("timezone"):
        return None
    r = res[0]
    label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country_code")) if x)
    return {"lat": float(r["latitude"]), "lon": float(r["longitude"]), "timezone": r["timezone"], "name": label}


def _clean_city(label: str) -> str:
    """'NYC' -> 'New York'; 'Chicago Midway' -> 'Chicago'. Best-effort text for geocoding."""
    aliases = {"NYC": "New York", "LA": "Los Angeles", "DC": "Washington", "SF": "San Francisco"}
    label = re.sub(r"\(.*?\)", "", label).strip()
    return aliases.get(label.upper(), label)


def resolve(series: dict, rules_text: str, user_agent: str, opener=None) -> dict:
    """Returns {'label','lat','lon','timezone','note','errors'}; lat/lon/timezone may be None."""
    ticker = series.get("ticker", "")
    label = guess_label(series.get("title") or "", ticker)
    out = {"label": label, "lat": None, "lon": None, "timezone": None, "note": "", "errors": []}
    for icao in station_candidates(series, rules_text):
        try:
            st = nws_station(icao, user_agent, opener)
        except Exception as e:
            out["errors"].append(f"NWS station {icao}: {e}")
            continue
        if st:
            out.update(lat=st["lat"], lon=st["lon"], timezone=st["timezone"],
                       note=f"settlement station {icao} ({st['name']}) from the contract's source")
            return out
    hint = suggest_station(f"{label} {series.get('title', '')}", ticker)
    if hint:
        tz = guess_timezone(f"{label} {series.get('title', '')}") or guess_timezone(hint[0])
        out.update(lat=hint[1], lon=hint[2], timezone=tz, note=f"suggested: {hint[0]} — check against the contract rules")
        if out["timezone"]:
            return out
    try:
        g = geocode(_clean_city(label), opener)
    except Exception as e:
        g = None
        out["errors"].append(f"geocoding {label!r}: {e}")
    if g:
        out.update(lat=g["lat"], lon=g["lon"], timezone=g["timezone"],
                   note=f"approximate: city centre of {g['name']} (set the station on the Cities page)")
    else:
        out["timezone"] = out["timezone"] or guess_timezone(f"{label} {series.get('title', '')}")
    return out

