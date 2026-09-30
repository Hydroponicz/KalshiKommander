import io
import json
import urllib.error
from datetime import date, timedelta

import pytest

from kalshikommander.config import AppConfig
from kalshikommander.marketdata.kalshi_public import KalshiPublicClient
from kalshikommander.marketdata.sample import SAMPLE_SERIES, SAMPLE_SERIES_2
from kalshikommander.weather.stations import resolve, station_candidates
from kalshikommander.web import Dashboard
from tests.conftest import FIXTURES
from tests.test_cities import RealLikeSource, real_app

KMDW = json.loads((FIXTURES / "nws_station_kmdw.json").read_text())
GEO = json.loads((FIXTURES / "geocode_springfield.json").read_text())
UA = "test"

CHI = {"ticker": "KXHIGHCHI", "title": "Highest temperature in Chicago", "frequency": "daily",
       "settlement_sources": [{"name": "National Weather Service",
                               "url": "https://forecast.weather.gov/product.php?site=LOT&product=CLI&issuedby=MDW"}]}
MIA = {"ticker": "KXHIGHMIA", "title": "Highest temperature in Miami", "frequency": "daily", "settlement_sources": []}
SPR = {"ticker": "KXHIGHSPR", "title": "Highest temperature in Springfield", "frequency": "daily", "settlement_sources": []}
ATL = {"ticker": "KXHIGHATLANTIS", "title": "Highest temperature in Atlantis", "frequency": "daily", "settlement_sources": []}
LOW = {"ticker": "KXLOWCHI", "title": "Lowest temperature in Chicago", "frequency": "daily"}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(calls=None):
    def o(req, timeout):
        if calls is not None:
            calls.append(req.full_url)
        u = req.full_url
        if u.endswith("/stations/KMDW"):
            return Resp(json.dumps(KMDW).encode())
        if "geocoding-api" in u and "Springfield" in u:
            return Resp(json.dumps(GEO).encode())
        if "geocoding-api" in u:
            return Resp(b'{"generationtime_ms": 0.1}')
        raise OSError(f"unexpected {u}")
    return o


def test_station_candidates():
    assert station_candidates(CHI) == ["KMDW"]
    assert station_candidates({"settlement_sources": [{"name": "The Weather Company CLINYC", "url": ""}]}) == ["KNYC"]
    assert station_candidates({}, "recorded at KAUS (Austin-Bergstrom)") == ["KAUS"]
    assert station_candidates({}, "no station here") == []


def test_resolve_prefers_settlement_station():
    r = resolve(CHI, "", UA, opener())
    assert (r["lat"], r["lon"], r["timezone"]) == (41.78611, -87.75222, "America/Chicago")
    assert "KMDW" in r["note"] and "settlement station" in r["note"]


def test_resolve_falls_back_to_known_station_then_geocoding():
    r = resolve(MIA, "", UA, opener())
    assert r["timezone"] == "America/New_York" and "KMIA" in r["note"] and "check" in r["note"]
    r = resolve(SPR, "", UA, opener())
    assert r["timezone"] == "America/Chicago" and r["note"].startswith("approximate: city centre")
    r = resolve(ATL, "", UA, opener())
    assert r["lat"] is None and r["timezone"] is None


class ManySeries(RealLikeSource):
    def list_series(self):
        return [CHI, MIA, SPR, ATL, LOW] + super().list_series()


def follow_app(clock):
    cfg = AppConfig()
    cfg.market.source = "kalshi_public"
    cfg.weather.provider = "manual"
    a = real_app(clock, cfg, follow_all=True)
    a.source = ManySeries(today=date(2026, 9, 30))
    a.http_opener = opener()
    return a


def test_auto_follow_adds_every_high_temperature_city(clock):
    a = follow_app(clock)
    r = a.auto_follow()
    names = {c.series_ticker: c for c in a.cities()}
    assert set(names) == {"KXHIGHCHI", "KXHIGHMIA", "KXHIGHSPR"}
    assert "KXLOWCHI" not in names  # low-temperature series are not daily-high markets
    # no station, no known city, no geocoding match -> not followed, flagged instead of guessed
    flagged = " ".join(r["needs_attention"])
    assert "Atlantis" in flagged and "Sampleville" in flagged and "Testburg" in flagged
    chi = names["KXHIGHCHI"]
    assert chi.timezone == "America/Chicago" and chi.latitude == 41.78611 and chi.origin == "auto"
    assert "KMDW" in chi.location_note
    assert a.auto_follow() == {"added": [], "needs_attention": [], "located": []}  # throttled (6h)


def test_stopped_cities_stay_stopped(clock):
    a = follow_app(clock)
    a.auto_follow()
    a.untrack_city("KXHIGHMIA")
    r = a.auto_follow(force=True)
    assert "Miami" not in r["added"] and a.city("KXHIGHMIA") is None


def test_follow_all_off_unless_forced(clock):
    a = follow_app(clock)
    a.cfg.market.follow_all = False
    assert a.auto_follow()["added"] == []
    assert a.auto_follow(force=True)["added"]


def _ready_app(clock):
    cfg = AppConfig()
    cfg.market.source = "kalshi_public"
    cfg.weather.provider = "manual"
    cfg.paper.max_total_exposure = cfg.paper.max_daily_loss = 1000.0
    a = real_app(clock, cfg)
    for s, tz in ((SAMPLE_SERIES, "America/New_York"), (SAMPLE_SERIES_2, "America/Chicago")):
        a.track_city(s, s, tz)
    a.refresh()
    assert a.accept_all_rules()["accepted"] == 6
    for s, hi in ((SAMPLE_SERIES, 75.5), (SAMPLE_SERIES_2, 67.5)):
        a.add_forecast(target_date=date(2026, 9, 30), expected_high=hi, unit="F", sigma=2,
                       issued_at=clock() - timedelta(hours=1), source="t", series_ticker=s)
    return a


def test_signals_and_batch_approval(clock):
    a = _ready_app(clock)
    sig = a.paper_buy_signals()
    assert len(sig) >= 2 and {s["city"] for s in sig} == {SAMPLE_SERIES, SAMPLE_SERIES_2}
    clock.advance(minutes=10)  # prices now stale -> approval re-snapshots first
    res = a.approve_paper_buys([s["ticker"] for s in sig])
    assert all(r["status"] in ("FILLED", "PARTIAL") for r in res)
    assert a.store.one("SELECT COUNT(*) n FROM orderbook_snapshots")["n"] == 40  # 20 original + 20 refreshed
    again = a.approve_paper_buys([sig[0]["ticker"]])  # same prices already used -> skipped, nothing double-filled
    assert again[0]["status"] == "SKIPPED"


def test_update_can_paper_trade_automatically(clock):
    a = _ready_app(clock)
    r = a.update(record_decisions=True, paper_trade=True)
    assert r["paper_trades"] and all(t["status"] in ("FILLED", "PARTIAL") for t in r["paper_trades"])
    r2 = a.update(record_decisions=True, paper_trade=False)
    assert r2["paper_trades"] == []


def test_review_page_and_batch_post(clock):
    a = _ready_app(clock)
    d = Dashboard(a)
    page = d.review_page({})
    assert "Paper-buy signals" in page and "Approve selected paper buys" in page and "All followed cities accepted" in page
    ts = [s["ticker"] for s in a.paper_buy_signals()]
    msg = d.post("/approve", {"t": ts})
    assert f"{len(ts)} of {len(ts)} paper buys simulated" in msg
    with pytest.raises(ValueError):
        d.post("/approve", {})


def test_rules_all_page(clock):
    cfg = AppConfig()
    cfg.market.source = "kalshi_public"
    a = real_app(clock, cfg)
    a.track_city(SAMPLE_SERIES, "A", "America/New_York")
    a.track_city(SAMPLE_SERIES_2, "B", "America/Chicago")
    a.refresh()
    d = Dashboard(a)
    assert "2 of 2 cities need a one-time rules review" in d.review_page({})
    page = d.rules_all_page({})
    assert "6 wordings across 2 cities" in page
    assert "Accepted 6" in d.post("/accept_all_rules", {})
    assert "Nothing to review" in d.rules_all_page({})


def test_today_folds_cities_when_many(clock):
    a = follow_app(clock)
    a.auto_follow()
    a.track_city(SAMPLE_SERIES, "Sampleville", "America/New_York")  # 4 cities -> folded
    page = Dashboard(a).index({})
    assert "each is folded" in page and "<details class='card'><summary><b style" in page


def test_kalshi_client_retries_on_429():
    calls = []

    def o(req, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        return Resp(b'{"market": {"ticker": "X"}}')
    c = KalshiPublicClient(opener=o, min_interval=0)
    import kalshikommander.marketdata.kalshi_public as kp
    orig, kp.time.sleep = kp.time.sleep, lambda s: None
    try:
        assert c.get_market("X")["ticker"] == "X" and len(calls) == 2
    finally:
        kp.time.sleep = orig


def test_batch_approval_respects_risk_limits(clock):
    a = _ready_app(clock)
    a.cfg.paper.max_daily_loss = 30.0
    res = a.approve_paper_buys([s["ticker"] for s in a.paper_buy_signals()])
    spent = sum(r.get("cost", 0) for r in res)
    assert spent <= 30.0 + 1e-9 and any(r["status"] == "SKIPPED" for r in res)
