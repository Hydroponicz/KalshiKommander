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

    @property
    def name(self) -> str:
        return self.label or self.series_ticker
