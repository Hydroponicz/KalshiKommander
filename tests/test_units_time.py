from datetime import date, datetime, timezone

import pytest

from kalshikommander.timeutil import (climate_day_window_utc, local_date, parse_local_input, parse_ts, to_iso)
from kalshikommander.units import c_to_f, f_to_c, normalize_unit, spread_to_f, to_f


def test_c_f_conversion():
    assert c_to_f(0) == 32
    assert c_to_f(100) == 212
    assert c_to_f(-40) == -40
    assert f_to_c(212) == pytest.approx(100)
    assert f_to_c(c_to_f(23.7)) == pytest.approx(23.7)
    assert to_f(30, "C") == pytest.approx(86)
    assert to_f(86, "°F") == 86


def test_spread_conversion_has_no_offset():
    assert spread_to_f(2, "C") == pytest.approx(3.6)
    assert spread_to_f(3, "F") == 3


def test_bad_unit():
    with pytest.raises(ValueError):
        normalize_unit("K")


def test_local_date_across_utc_midnight():
    # 02:30 UTC Oct 1 is still Sep 30 evening in New York (EDT, UTC-4)
    t = datetime(2026, 10, 1, 2, 30, tzinfo=timezone.utc)
    assert local_date(t, "America/New_York") == date(2026, 9, 30)
    assert local_date(t, "Europe/London") == date(2026, 10, 1)
    # Los Angeles
    assert local_date(datetime(2026, 10, 1, 6, 59, tzinfo=timezone.utc), "America/Los_Angeles") == date(2026, 9, 30)


def test_climate_day_uses_standard_time_during_dst():
    # Summer: EST is UTC-5 so the climate day starts 05:00 UTC (01:00 EDT local clock)
    s, e = climate_day_window_utc(date(2026, 7, 4), "America/New_York")
    assert s == datetime(2026, 7, 4, 5, 0, tzinfo=timezone.utc)
    assert e == datetime(2026, 7, 5, 5, 0, tzinfo=timezone.utc)
    # Winter: same 05:00 UTC
    s, _ = climate_day_window_utc(date(2026, 1, 15), "America/New_York")
    assert s == datetime(2026, 1, 15, 5, 0, tzinfo=timezone.utc)
    # Phoenix has no DST
    s, _ = climate_day_window_utc(date(2026, 7, 4), "America/Phoenix")
    assert s == datetime(2026, 7, 4, 7, 0, tzinfo=timezone.utc)


def test_dst_transition_day_local_input():
    # 2026-11-01 01:30 in New York is ambiguous; zoneinfo picks fold=0 (EDT)
    t = parse_local_input("2026-11-01T01:30", "America/New_York")
    assert t == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    t2 = parse_local_input("2026-03-08T12:00", "America/New_York")  # after spring-forward: EDT
    assert t2 == datetime(2026, 3, 8, 16, 0, tzinfo=timezone.utc)


def test_parse_ts_rejects_naive_and_roundtrips():
    with pytest.raises(ValueError):
        parse_ts("2026-09-30T10:00:00")
    t = parse_ts("2026-09-30T10:00:00-04:00")
    assert to_iso(t) == "2026-09-30T14:00:00Z"
    assert parse_local_input("2026-09-30T14:00:00Z", "America/New_York") == t
