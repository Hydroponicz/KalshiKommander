"""Tracked cities (one Kalshi daily-high series each) and a timezone GUESS helper.

The timezone guess only pre-fills the Cities form; you confirm or change it. Settlement
details always come from each market's own rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

US_TIMEZONES = [
    "America/New_York", "America/Detroit", "America/Chicago", "America/Denver", "America/Phoenix",
    "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
]

# keyword (matched as a whole word, case-insensitive) -> IANA zone
_TZ_HINTS = [
    (("NYC", "New York", "Philadelphia", "Boston", "Miami", "Atlanta", "Washington", "DC",
      "Orlando", "Tampa", "Charlotte", "Baltimore", "Pittsburgh"), "America/New_York"),
    (("Detroit",), "America/Detroit"),
    (("Chicago", "Austin", "Houston", "Dallas", "San Antonio", "New Orleans", "Minneapolis",
      "Nashville", "Kansas City", "St. Louis", "Oklahoma City"), "America/Chicago"),
    (("Denver", "Salt Lake"), "America/Denver"),
    (("Phoenix",), "America/Phoenix"),
    (("Los Angeles", "LA", "LAX", "San Francisco", "Seattle", "Las Vegas", "Portland", "San Diego"),
     "America/Los_Angeles"),
]


def guess_timezone(text: str) -> str | None:
    for words, tz in _TZ_HINTS:
        for w in words:
            if re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", text or ""):
                return tz
    return None


# SUGGESTED forecast points: the weather station each city's Kalshi market is reported to settle
# on (per public guides, not verified here). Always compare with the station named in the rules.
# keywords (whole word) -> (station description, latitude, longitude)
_STATION_HINTS = [
    (("NYC", "New York"), ("Central Park, NY (KNYC)", 40.7789, -73.9692)),
    (("Chicago",), ("Chicago Midway Airport (KMDW)", 41.7861, -87.7522)),
    (("Austin",), ("Austin-Bergstrom Airport (KAUS)", 30.1831, -97.6799)),
    (("Miami",), ("Miami International Airport (KMIA)", 25.7881, -80.3169)),
    (("Los Angeles", "LA", "LAX"), ("Los Angeles International Airport (KLAX)", 33.9382, -118.3870)),
    (("Philadelphia",), ("Philadelphia International Airport (KPHL)", 39.8683, -75.2311)),
    (("Denver",), ("Denver International Airport (KDEN)", 39.8466, -104.6562)),
]


_TICKER_HINTS = {"KXHIGHNY": "New York", "KXHIGHCHI": "Chicago", "KXHIGHAUS": "Austin", "KXHIGHMIA": "Miami",
                 "KXHIGHLAX": "Los Angeles", "KXHIGHPHIL": "Philadelphia", "KXHIGHDEN": "Denver"}


def suggest_station(text: str, series_ticker: str = "") -> tuple[str, float, float] | None:
    text = f"{text or ''} {_TICKER_HINTS.get((series_ticker or '').upper(), '')}"
    for words, station in _STATION_HINTS:
        for w in words:
            if re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", text or ""):
                return station
    return None


def guess_label(title: str, ticker: str) -> str:
    m = re.search(r"\bin\s+(.+?)\??$", title or "")
    return (m.group(1).strip() if m else "") or ticker


@dataclass
class City:
    series_ticker: str
    label: str
    timezone: str
    latitude: float | None = None
    longitude: float | None = None
    origin: str = "config"   # "config" | "dashboard" | "sample"
    location_note: str = ""  # where latitude/longitude came from

    @property
    def name(self) -> str:
        return self.label or self.series_ticker
