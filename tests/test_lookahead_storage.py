import sqlite3
from datetime import date, timedelta

import pytest

from kalshikommander.evaluation import evaluate
from kalshikommander.storage import Store


def test_append_only_tables_reject_update_and_delete(app):
    app.refresh()
    with pytest.raises(sqlite3.DatabaseError):
        app.store.conn.execute("UPDATE market_snapshots SET market_json='{}'")
    with pytest.raises(sqlite3.DatabaseError):
        app.store.conn.execute("DELETE FROM orderbook_snapshots")
    with pytest.raises(sqlite3.DatabaseError):
        app.store.conn.execute("DELETE FROM cash_ledger")


def test_forecast_recorded_later_is_invisible_to_earlier_decision(app, clock):
    app.refresh()
    t0 = clock()
    clock.advance(minutes=5)
    # issued earlier but only RECORDED after t0 -> must not be visible as of t0
    app.add_forecast(target_date=date(2026, 9, 30), expected_high=75, unit="F", sigma=2,
                     issued_at=t0 - timedelta(hours=1), source="late entry")
    assert app.forecast_at(date(2026, 9, 30), t0) is None
    assert app.forecast_at(date(2026, 9, 30), clock()) is not None
    a = app.analyze("SAMPLE-HIGHTEMP-26SEP30-T74", as_of=t0)
    assert a["p_yes"] is None and a["decision"].action == "NO_TRADE"


def test_future_issue_time_rejected(app, clock):
    with pytest.raises(ValueError):
        app.add_forecast(target_date=date(2026, 9, 30), expected_high=75, unit="F", sigma=2,
                         issued_at=clock() + timedelta(minutes=1), source="x")


def test_snapshots_after_as_of_are_invisible(app, clock):
    t0 = clock()
    clock.advance(seconds=10)
    app.refresh()
    c, _ = app.contract_at("SAMPLE-HIGHTEMP-26SEP30-T74", t0)
    b, _ = app.book_at("SAMPLE-HIGHTEMP-26SEP30-T74", t0)
    assert c is None and b is None


def test_settlement_before_close_rejected(app, clock):
    app.refresh()
    with pytest.raises(ValueError):
        app.record_settlement("SAMPLE-HIGHTEMP-26SEP30-T74", "yes", "test")


def test_settlement_cannot_be_rewritten(app, clock):
    app.refresh()
    clock.advance(days=2)
    app.record_settlement("SAMPLE-HIGHTEMP-26SEP30-T74", "yes", "test")
    with pytest.raises(sqlite3.IntegrityError):
        app.record_settlement("SAMPLE-HIGHTEMP-26SEP30-T74", "no", "test")


def test_evaluation_ignores_post_close_decisions(app, clock):
    app.refresh()
    app.add_forecast(target_date=date(2026, 9, 30), expected_high=75.5, unit="F", sigma=2,
                     issued_at=clock() - timedelta(hours=1), source="t")
    t = "SAMPLE-HIGHTEMP-26SEP30-T74"
    app.record_decision(t)                       # pre-close: counts
    clock.advance(days=2)
    app.record_settlement(t, "yes", "test")
    app.store.insert("decisions", {              # a post-close "prediction" must be ignored
        "created_at": clock(), "ticker": t, "is_sample": 1,
        "market_snapshot_id": app.store.latest_market_snapshot(t, clock())["id"],
        "action": "NO_TRADE", "qty": 0, "p_yes": 0.999, "reasons_json": [], "detail_json": {}, "config_json": {}})
    r = evaluate(app.store)
    assert r["n"] == 1
    assert r["predictions"][0]["p_yes"] != 0.999
    assert any("backtest not possible" in w for w in r["warnings"])


def test_memory_store_isolated():
    s = Store(":memory:")
    assert s.one("SELECT COUNT(*) n FROM decisions")["n"] == 0
