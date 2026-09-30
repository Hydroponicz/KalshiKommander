from datetime import date, timedelta

import pytest

from kalshikommander.config import AppConfig, ReadinessConfig
from kalshikommander.evaluation import bootstrap_beats_market, paper_trade_results, readiness, sigma_check
from kalshikommander.marketdata.sample import SAMPLE_SERIES, SAMPLE_SERIES_2
from kalshikommander.service import rules_template, template_sha
from kalshikommander.web import Dashboard
from tests.test_cities import real_app

T = f"{SAMPLE_SERIES}-26SEP30-T74"


def rules(text):
    return {"rules_primary": text, "rules_secondary": ""}


def test_template_blanks_only_dates_and_numbers():
    a = rules("If the highest temperature recorded in Central Park, New York for September 30, 2026 is greater than 74°, then Yes.")
    b = rules("If the highest temperature recorded in Central Park, New York for Oct 1, 2026 is greater than 81.5°, then Yes.")
    moved = rules("If the highest temperature recorded at LaGuardia, New York for September 30, 2026 is greater than 74°, then Yes.")
    worded = rules("If the highest temperature recorded in Central Park, New York for September 30, 2026 is at least 74°, then Yes.")
    assert template_sha(a) == template_sha(b)
    assert "<DATE>" in rules_template(a) and "<N>" in rules_template(a)
    assert template_sha(a) != template_sha(moved)   # different station -> ask again
    assert template_sha(a) != template_sha(worded)  # different comparison wording -> ask again


def test_accept_city_rules_covers_all_same_wording(app, clock):
    app.refresh()
    assert app.city_rules_status(SAMPLE_SERIES) == "needs_review"
    ts = app.rules_templates(SAMPLE_SERIES)
    assert len(ts) == 3  # "less than", "between", "greater than" wordings
    t0 = clock()
    clock.advance(seconds=5)
    assert app.accept_city_rules(SAMPLE_SERIES) == 3
    assert app.city_rules_status(SAMPLE_SERIES) == "accepted"
    for t in app.todays_tickers(SAMPLE_SERIES):  # today's and tomorrow's contracts
        assert app.is_acked(t, clock())
    assert not app.is_acked(T, t0)  # point-in-time: not accepted before the click
    assert app.city_rules_status(SAMPLE_SERIES_2) == "needs_review"  # other city unaffected
    assert app.accept_city_rules(SAMPLE_SERIES) == 0  # idempotent


def test_changed_wording_is_not_covered(clock):
    a = real_app(clock, _real_cfg())
    a.track_city(SAMPLE_SERIES, "NY", "America/New_York")
    a.refresh()
    a.accept_city_rules(SAMPLE_SERIES)
    assert a.is_acked(T, clock())
    orig = a.source._markets

    def moved(d, series=SAMPLE_SERIES):
        ms = orig(d, series)
        for m in ms:
            m["rules_primary"] = m["rules_primary"].replace("fictional", "relocated fictional")
        return ms
    a.source._markets = moved
    clock.advance(seconds=10)
    a.refresh()
    assert not a.is_acked(T, clock())
    assert a.city_rules_status(SAMPLE_SERIES) == "needs_review"


def test_accept_refuses_wording_that_fails_checks(clock):
    a = real_app(clock, _real_cfg())
    a.track_city(SAMPLE_SERIES, "NY", "America/New_York")
    orig = a.source._markets

    def broken(d, series=SAMPLE_SERIES):
        ms = orig(d, series)
        for m in ms:
            m["rules_primary"] = "Resolves per the source."  # no date, no strike
        return ms
    a.source._markets = broken
    a.refresh()
    with pytest.raises(ValueError):
        a.accept_city_rules(SAMPLE_SERIES)


def test_city_acceptance_enables_trading(app, clock):
    app.refresh()
    app.add_forecast(target_date=date(2026, 9, 30), expected_high=75.5, unit="F", sigma=2,
                     issued_at=clock() - timedelta(hours=1), source="t", series_ticker=SAMPLE_SERIES)
    assert "no_ack" in app.analyze(T)["decision"].codes
    app.accept_city_rules(SAMPLE_SERIES)
    assert app.analyze(T)["decision"].action == "BUY_YES"


def _real_cfg():
    cfg = AppConfig()
    cfg.market.source = "kalshi_public"
    cfg.weather.provider = "manual"
    return cfg


def test_update_records_settlements_automatically(clock):
    a = real_app(clock, _real_cfg())
    a.track_city(SAMPLE_SERIES, "NY", "America/New_York")
    a.refresh()
    real_get = a.source.get_market

    def settled(ticker):
        m = real_get(ticker)
        m.update(status="finalized", result="yes" if ticker == T else "no", expiration_value="76")
        return m
    a.source.get_market = settled
    clock.advance(days=1, hours=12)  # after close
    r = a.update()
    assert len(r["settled"]) == 5 and not r["settle_error"]
    s = a.store.one("SELECT * FROM settlements WHERE ticker=?", (T,))
    assert s["result"] == "yes" and s["observed_high"] == 76
    clock.advance(days=30)  # old markets are no longer polled
    calls = []
    a.source.get_market = lambda t: calls.append(t) or real_get(t)
    a.fetch_settlements()
    assert calls == []


def test_bootstrap_and_sigma_check():
    good = [{"p_yes": 0.9, "y": 1, "market_mid_yes": 0.5, "series": "S", "target_date": date(2026, 9, d)} for d in range(1, 21)]
    assert bootstrap_beats_market(good) == 1.0
    bad = [{**p, "p_yes": 0.1} for p in good]
    assert bootstrap_beats_market(bad) == 0.0
    assert bootstrap_beats_market(good[:1]) is None
    s = sigma_check([{"observed_high": 75, "mu_f": 73, "unit": "F"}, {"observed_high": 70, "mu_f": 71, "unit": "F"},
                     {"observed_high": None, "mu_f": 70, "unit": "F"}])
    assert s["n"] == 2 and s["bias_f"] == 0.5


def test_stress_test_is_never_better_than_actual(app, clock):
    app.refresh()
    app.add_forecast(target_date=date(2026, 9, 30), expected_high=75.5, unit="F", sigma=2,
                     issued_at=clock() - timedelta(hours=1), source="t", series_ticker=SAMPLE_SERIES)
    app.accept_city_rules(SAMPLE_SERIES)
    r = app.execute_paper(app.record_decision(T))
    assert r["qty"] == 2
    clock.advance(days=2)
    app.record_settlement(T, "yes", "test")
    res = paper_trade_results(app.store, 0.25, 0.01)
    assert len(res) == 1 and res[0]["actual_pnl"] == pytest.approx(2 - r["cost"])
    # 25% of 5 shown -> 1 contract, +1c slippage: smaller profit
    assert res[0]["stress_pnl"] < res[0]["actual_pnl"]


def test_readiness_excludes_sample_and_starts_not_ready(app, clock):
    app.refresh()
    app.add_forecast(target_date=date(2026, 9, 30), expected_high=75.5, unit="F", sigma=2,
                     issued_at=clock() - timedelta(hours=1), source="t", series_ticker=SAMPLE_SERIES)
    app.record_decision(T)
    clock.advance(days=2)
    app.record_settlement(T, "yes", "test")
    r = readiness(app.store, ReadinessConfig())
    assert r["n_preds"] == 0 and not r["all_ok"]  # sample data never counts
    assert [c["name"] for c in r["checks"]][0] == "Enough settled predictions"


def test_readiness_can_pass_with_enough_real_evidence(clock):
    """Synthetic but real-mode data: many days where the model beats the market and paper trades profit."""
    a = real_app(clock, _real_cfg())
    a.track_city(SAMPLE_SERIES, "NY", "America/New_York")
    rc = ReadinessConfig(min_predictions=3, min_settled_days=3, min_paper_trades=1, confidence=0.5)
    start = clock()
    for day in range(3):
        a.source.today = date(2026, 9, 30) + timedelta(days=day)
        clock.t = start + timedelta(days=day)
        a.refresh()
        a.accept_city_rules(SAMPLE_SERIES)
        d = a.source.today
        a.add_forecast(target_date=d, expected_high=76.5, unit="F", sigma=1.5,
                       issued_at=clock() - timedelta(hours=1), source="t", series_ticker=SAMPLE_SERIES)
        tick = f"{SAMPLE_SERIES}-{d.strftime('%y%b%d').upper()}-T74"
        did = a.record_decision(tick)
        if day == 0:
            a.execute_paper(did)
        clock.advance(days=1, hours=2)
        a.record_settlement(tick, "yes", "test", observed_high=77)
    clock.t = start + timedelta(days=5)
    r = readiness(a.store, rc)
    got = {c["name"]: c["ok"] for c in r["checks"]}
    assert got["Enough settled predictions"] and got["Enough different days"] and got["Model beats the market's own prices"]
    assert got["Profitable after fees"] and got["Settings unchanged during the test"]
    assert r["sigma"]["n"] == 3


def test_web_rules_and_results(app, clock):
    d = Dashboard(app)
    app.refresh()
    assert "Rules need a one-time review" in d.index({})
    page = d.rules_page({"s": SAMPLE_SERIES})
    assert "Wording 1 of 3" in page and "accept them for all" in page
    assert "Accepted 3" in d.post("/accept_city_rules", {"series": SAMPLE_SERIES})
    assert "All current wordings accepted" in d.rules_page({"s": SAMPLE_SERIES})
    assert "Rules accepted" in d.index({"city": SAMPLE_SERIES})
    res = d.evaluate_page({})
    assert "Readiness scorecard" in res and "When could real money make sense?" in res
