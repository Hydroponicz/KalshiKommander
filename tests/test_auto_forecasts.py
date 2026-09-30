import io
import json
from datetime import date, timedelta

import pytest

from kalshikommander.config import AppConfig, load_config
from kalshikommander.marketdata.sample import SAMPLE_SERIES, SAMPLE_SERIES_2
from kalshikommander.weather.open_meteo import build_url, extract_daily_highs
from kalshikommander.web import Dashboard
from tests.conftest import FIXTURES
from tests.test_cities import real_app

OM = json.loads((FIXTURES / "open_meteo.json").read_text())
NWS = json.loads((FIXTURES / "nws_forecast.json").read_text())


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(om=OM, nws=NWS, fail=False, calls=None):
    def opener(req, timeout):
        if calls is not None:
            calls.append(req.full_url)
        assert req.get_method() == "GET"
        if fail:
            raise OSError("network unreachable")
        u = req.full_url
        if "open-meteo" in u:
            return Resp(json.dumps(om).encode())
        if "/points/" in u:
            return Resp(json.dumps({"id": u, "properties": {"forecast": "https://api.weather.gov/gridpoints/OKX/33,37/forecast"}}).encode())
        if "gridpoints" in u:
            return Resp(json.dumps(nws).encode())
        raise AssertionError(u)
    return opener


def ny_app(clock, provider="open_meteo", **kw):
    cfg = AppConfig()
    cfg.market.source = "kalshi_public"
    cfg.weather.provider = provider
    a = real_app(clock, cfg)
    a.track_city(SAMPLE_SERIES, "New York", "America/New_York")
    a.set_location(SAMPLE_SERIES, 40.7789, -73.9692)
    a.http_opener = opener_for(**kw)
    return a


def test_open_meteo_parser():
    h = extract_daily_highs(OM, "America/New_York")
    assert h[date(2026, 9, 30)] == (74.3, "F") and h[date(2026, 10, 1)] == (70.1, "F")
    assert date(2026, 10, 2) not in h  # null value is skipped, never filled in
    with pytest.raises(ValueError):
        extract_daily_highs(OM, "America/Chicago")  # answered in a different timezone
    with pytest.raises(ValueError):
        extract_daily_highs({**OM, "daily_units": {"temperature_2m_max": "K"}}, "America/New_York")
    u = build_url(40.7789, -73.9692, "America/New_York")
    assert "temperature_unit=fahrenheit" in u and "timezone=America%2FNew_York" in u


def test_auto_forecasts_open_meteo(clock):
    a = ny_app(clock)
    r = a.auto_forecasts()
    assert r["saved"] == 2 and not r["errors"]
    f = a.forecast_at(SAMPLE_SERIES, date(2026, 9, 30), clock())
    assert f["source"] == "Open-Meteo (automatic)" and f["expected_high"] == 74.3
    assert f["sigma_is_assumption"] == 1 and f["issued_at"] == "2026-09-30T14:00:00Z"
    assert "retrieval time" in f["source_detail"] and "40.7789" in f["source_detail"]
    # within refetch window: nothing fetched
    calls = []
    a.http_opener = opener_for(calls=calls)
    assert a.auto_forecasts()["saved"] == 0 and calls == []
    clock.advance(minutes=61)
    assert a.auto_forecasts()["saved"] == 2 and len(calls) == 1


def test_auto_forecast_feeds_the_model(clock):
    a = ny_app(clock)
    a.update()
    t = f"{SAMPLE_SERIES}-26SEP30-T74"
    an = a.analyze(t)
    assert an["p_yes"] is not None and "no_forecast" not in an["decision"].codes


def test_auto_forecasts_nws_dedupes_same_issuance(clock):
    a = ny_app(clock, provider="nws")
    r = a.auto_forecasts()
    assert r["saved"] == 2  # Sep 30 "Today" 74F and Oct 1 "Thursday" 70F
    f = a.forecast_at(SAMPLE_SERIES, date(2026, 10, 1), clock())
    assert f["expected_high"] == 70 and f["issued_at"] == "2026-09-30T08:12:34Z"
    clock.advance(hours=2)
    assert a.auto_forecasts()["saved"] == 0  # same NWS updateTime: not stored twice


def test_future_issue_time_is_rejected_not_stored(clock):
    future = json.loads(json.dumps(NWS))
    future["properties"]["updateTime"] = "2026-09-30T23:00:00+00:00"
    a = ny_app(clock, provider="nws", nws=future)
    r = a.auto_forecasts()
    assert r["saved"] == 0 and r["errors"]
    assert a.store.one("SELECT COUNT(*) n FROM forecasts")["n"] == 0


def test_network_failure_reported_nothing_invented(clock):
    a = ny_app(clock, fail=True)
    r = a.auto_forecasts()
    assert r["saved"] == 0 and "network unreachable" in r["errors"][0]
    assert a.store.one("SELECT COUNT(*) n FROM forecasts")["n"] == 0


def test_city_without_location_is_skipped(clock):
    cfg = AppConfig()
    cfg.market.source = "kalshi_public"
    a = real_app(clock, cfg)
    a.track_city(SAMPLE_SERIES_2, "Testburg", "America/Chicago")
    a.http_opener = opener_for()
    r = a.auto_forecasts()
    assert r["saved"] == 0 and any("no location" in x for x in r["skipped"])


def test_suggested_station_and_override(clock):
    cfg = AppConfig()
    cfg.market.source = "kalshi_public"
    a = real_app(clock, cfg)
    a.track_city("KXHIGHCHI", "Chicago", "America/Chicago")
    c = a.city("KXHIGHCHI")
    assert (c.latitude, c.longitude) == (41.7861, -87.7522) and "Midway" in c.location_note
    assert "check against the contract rules" in c.location_note
    a.set_location("KXHIGHCHI", 41.9742, -87.9073)
    c = a.city("KXHIGHCHI")
    assert c.latitude == 41.9742 and c.location_note == "set by you"
    with pytest.raises(ValueError):
        a.set_location("KXHIGHCHI", 123, 0)


def test_sample_mode_never_fetches(app):
    calls = []
    app.http_opener = opener_for(calls=calls)
    r = app.auto_forecasts()
    assert r["saved"] == 0 and calls == [] and "sample mode" in r["skipped"][0]


def test_manual_provider_is_off(clock):
    a = ny_app(clock, provider="manual")
    assert not a.auto_forecasts_enabled()
    assert a.auto_forecasts()["saved"] == 0


def test_update_records_decisions(clock):
    a = ny_app(clock)
    r = a.update(record_decisions=True)
    assert r["prices"]["markets"] == 10 and r["forecasts"]["saved"] == 2 and r["decisions"] == 10
    assert a.store.one("SELECT COUNT(*) n FROM decisions WHERE p_yes IS NOT NULL")["n"] == 10  # both days have forecasts
    assert a.store.one("SELECT COUNT(*) n FROM decisions")["n"] == 10


def test_newer_manual_forecast_wins(clock):
    a = ny_app(clock)
    a.auto_forecasts()
    clock.advance(minutes=5)
    a.add_forecast(target_date=date(2026, 9, 30), expected_high=80, unit="F", sigma=2,
                   issued_at=clock() - timedelta(minutes=1), source="my own", series_ticker=SAMPLE_SERIES)
    assert a.forecast_at(SAMPLE_SERIES, date(2026, 9, 30), clock())["source"] == "my own"


def test_dashboard_auto_flow(clock):
    a = ny_app(clock)
    d = Dashboard(a)
    page = d.index({})
    assert "Update prices &amp; forecasts" in page and "Forecasts arrive automatically from <b>Open-Meteo</b>" in page
    msg = d.post("/update", {})
    assert "2 new forecasts" in msg
    page = d.index({})
    assert "Automatic forecast:" in page and "fetch forecast now" in page
    assert "Change location" in d.cities_page({})
    assert "Location saved" in d.post("/set_location", {"series": SAMPLE_SERIES, "lat": "40.7", "lon": "-74.0"})


def test_config_validation(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[weather]\nprovider = "accuweather"\n')
    with pytest.raises(ValueError):
        load_config(f)
    f.write_text('[auto]\nupdate_every_minutes = 1\n')
    with pytest.raises(ValueError):
        load_config(f)
    f.write_text('[auto]\nupdate_every_minutes = 15\nrecord_decisions = false\n')
    cfg = load_config(f)
    assert cfg.auto.update_every_minutes == 15 and not cfg.auto.record_decisions
