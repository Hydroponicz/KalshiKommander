"""Time helpers. All stored timestamps are timezone-aware UTC ISO-8601 strings."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime not allowed; attach a timezone")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp. Naive timestamps are rejected (ambiguous)."""
    if not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return dt.astimezone(timezone.utc)


def parse_local_input(value: str, tz_name: str) -> datetime:
    """Parse a user-entered time. If it has no offset, interpret it in the city's timezone."""
    s = value.strip().replace(" ", "T", 1) if "T" not in value else value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(timezone.utc)


def local_date(dt: datetime, tz_name: str) -> date:
    return dt.astimezone(ZoneInfo(tz_name)).date()


def standard_time_offset(tz_name: str, d: date) -> timedelta:
    """UTC offset of *standard* (non-DST) time for the zone around date d."""
    tz = ZoneInfo(tz_name)
    for probe in (datetime(d.year, 1, 15, 12, tzinfo=tz), datetime(d.year, 7, 15, 12, tzinfo=tz)):
        if not probe.dst():
            return probe.utcoffset()
    return datetime(d.year, 1, 15, 12, tzinfo=tz).utcoffset()  # pragma: no cover


def climate_day_window_utc(d: date, tz_name: str) -> tuple[datetime, datetime]:
    """Window for an NWS-style climate day: midnight-to-midnight LOCAL STANDARD TIME.

    NWS Daily Climate Reports (CLI) use local standard time year-round, so during daylight
    saving time the "day" runs 01:00-01:00 local clock time. This is informational: the
    authoritative definition is whatever the specific market's rules say.
    """
    off = standard_time_offset(tz_name, d)
    start = datetime(d.year, d.month, d.day, tzinfo=timezone(off))
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def age_seconds(ts: datetime, now: datetime) -> float:
    return (now - ts).total_seconds()
