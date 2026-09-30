import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from kalshikommander.cities import guess_label, guess_timezone
from kalshikommander.config import AppConfig, load_config
from kalshikommander.marketdata.sample import SAMPLE_SERIES, SAMPLE_SERIES_2, SampleSource
from kalshikommander.service import App
from kalshikommander.storage import Store


class RealLikeSource(SampleSource):
    """Sample markets presented as a non-sample source, to exercise dashboard-tracked cities."""
    name = "fake_public"
    is_sample = False


def real_app(clock, cfg=None, follow_all=False):
    cfg = cfg or AppConfig()
    cfg.market.follow_all = follow_all  # tests stay offline unless they opt in with a fake opener
    return App(cfg, source=RealLikeSource(today=date(2026, 9, 30)), store=Store(":memory:"), clock=clock)


def test_timezone_guess():
    assert guess_timezone("Highest temperature in NYC") == "America/New_York"
    assert guess_timezone("Highest temperature in Chicago") == "America/Chicago"
    assert guess_timezone("Highest temperature in Los Angeles") == "America/Los_Angeles"
    assert guess_timezone("Highest temperature in Denver") == "America/Denver"
    assert guess_timezone("Highest temperature in Atlantis") is None
    assert guess_timezone("Highest temperature in Dallas") == "America/Chicago"
    assert guess_timezone("Plateau") is None  # 'LA' must match as a whole word only
    assert guess_label("Highest temperature in Austin", "KXHIGHAUS") == "Austin"


def test_sample_mode_shows_two_cities_and_refreshes_both(app):
    assert [c.series_ticker for c in app.cities()] == [SAMPLE_SERIES, SAMPLE_SERIES_2]
    r = app.refresh()
    assert r["markets"] == 20 and not r["errors"]
    assert len(app.todays_tickers(SAMPLE_SERIES_2)) == 10


def test_forecasts_are_per_city(app, clock):
    app.refresh()
    app.add_forecast(target_date=date(2026, 9, 30), expected_high=75, unit="F", sigma=2,
                     issued_at=clock() - timedelta(hours=1), source="x", series_ticker=SAMPLE_SERIES)
    assert app.forecast_at(SAMPLE_SERIES, date(2026, 9, 30), clock()) is not None
    assert app.forecast_at(SAMPLE_SERIES_2, date(2026, 9, 30), clock()) is None
    assert app.analyze(f"{SAMPLE_SERIES_2}-26SEP30-T66")["decision"].codes.count("no_forecast") == 1
    with pytest.raises(ValueError):
        app.add_forecast(target_date=date(2026, 9, 30), expected_high=75, unit="F", sigma=2,
                         issued_at=clock(), source="x", series_ticker="NOT-TRACKED")


def test_city_local_dates_differ_by_timezone(clock):
    # 03:30 UTC Oct 1 = Sep 30 23:30 in New York, but already Oct 1 in London
    clock.t = datetime(2026, 10, 1, 3, 30, tzinfo=timezone.utc)
    cfg = AppConfig()
    a = real_app(clock, cfg)
    a.track_city(SAMPLE_SERIES, "East", "America/New_York")
    a.track_city(SAMPLE_SERIES_2, "Far east", "Europe/London")
    assert a.city_dates(a.city(SAMPLE_SERIES))[0] == date(2026, 9, 30)
    assert a.city_dates(a.city(SAMPLE_SERIES_2))[0] == date(2026, 10, 1)


def test_track_and_untrack_via_dashboard(clock):
    a = real_app(clock)
    assert a.cities() == []
    with pytest.raises(RuntimeError):
        a.refresh()
    a.track_city("sample-hightemp2", "Testburg", "America/Chicago")
    assert [c.series_ticker for c in a.cities()] == [SAMPLE_SERIES_2]
    found = {x["ticker"]: x for x in a.discover_cities()}
    assert found[SAMPLE_SERIES_2]["tracked"] and not found[SAMPLE_SERIES]["tracked"]
    assert a.refresh()["markets"] == 10
    a.untrack_city(SAMPLE_SERIES_2)
    assert a.cities() == []
    assert a.store.one("SELECT COUNT(*) n FROM market_snapshots")["n"] == 10  # history kept
    with pytest.raises(ValueError):
        a.track_city("BAD TICKER!", "x", "America/Chicago")
    with pytest.raises(Exception):
        a.track_city("OK", "x", "Mars/Olympus")


def test_config_cities_and_legacy_series(tmp_path, clock):
    f = tmp_path / "c.toml"
    f.write_text('[market]\nsource = "kalshi_public"\nseries_ticker = "SAMPLE-HIGHTEMP"\ncity_label = "Legacy"\n'
                 '[[cities]]\nseries_ticker = "SAMPLE-HIGHTEMP2"\nlabel = "Testburg"\ntimezone = "America/Chicago"\n')
    cfg = load_config(f)
    a = real_app(clock, cfg)
    assert [(c.name, c.origin) for c in a.cities()] == [("Legacy", "config"), ("Testburg", "config")]
    with pytest.raises(ValueError):
        a.untrack_city("SAMPLE-HIGHTEMP2")  # config cities are edited in config.toml
    f.write_text('[[cities]]\nseries_ticker = "X"\ntimezone = "Nowhere/Nope"\n')
    with pytest.raises(ValueError):
        load_config(f)


def test_legacy_forecasts_without_city_still_apply(tmp_path, clock):
    """A database from before multi-city support keeps working (forecasts gain a NULL city)."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE forecasts (id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, issued_at TEXT NOT NULL, "
                "target_date TEXT NOT NULL, location TEXT NOT NULL, source TEXT NOT NULL, source_detail TEXT, "
                "expected_high REAL NOT NULL, unit TEXT NOT NULL, expected_high_f REAL NOT NULL, sigma REAL NOT NULL, "
                "sigma_f REAL NOT NULL, sigma_is_assumption INTEGER NOT NULL, notes TEXT, raw_json TEXT)")
    con.execute("INSERT INTO forecasts VALUES (1,'2026-09-30T12:00:00Z','2026-09-30T11:00:00Z','2026-09-30','old','src',"
                "'',75,'F',75,2,2,0,'','{}')")
    con.commit()
    con.close()
    cfg = AppConfig()
    cfg.market.source = "kalshi_public"
    cfg.market.series_ticker = SAMPLE_SERIES
    a = App(cfg, source=RealLikeSource(today=date(2026, 9, 30)), store=Store(db), clock=clock)
    assert a.forecast_at(SAMPLE_SERIES, date(2026, 9, 30), clock())["id"] == 1
    a.track_city(SAMPLE_SERIES_2, "Testburg", "America/Chicago")
    assert a.forecast_at(SAMPLE_SERIES_2, date(2026, 9, 30), clock()) is None
    with pytest.raises(sqlite3.DatabaseError):
        a.store.conn.execute("UPDATE forecasts SET expected_high=1")
