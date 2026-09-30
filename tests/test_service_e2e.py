from datetime import date, timedelta

import pytest

from kalshikommander.evaluation import evaluate

T = "SAMPLE-HIGHTEMP-26SEP30-T74"  # YES if report >= 75; sample YES ask 0.16 x 5 displayed


def setup(app, clock, high=75.5):
    app.refresh()
    app.add_forecast(target_date=date(2026, 9, 30), expected_high=high, unit="F", sigma=2,
                     issued_at=clock() - timedelta(hours=1), source="unit test", source_detail="fixture")
    app.ack_terms(T)


def test_full_paper_cycle(app, clock):
    setup(app, clock)
    did = app.record_decision(T)
    d = app.store.one("SELECT * FROM decisions WHERE id=?", (did,))
    assert d["action"] == "BUY_YES" and d["qty"] == 2  # floor(5 * 0.5)
    r = app.execute_paper(did)
    assert r["status"] == "FILLED" and r["qty"] == 2
    assert r["cost"] == pytest.approx(2 * (0.16 + 0.01) + 0.02)
    with pytest.raises(ValueError):
        app.execute_paper(did)  # never double-executes
    assert app.cash() == pytest.approx(1000 - r["cost"])
    clock.advance(days=2)
    app.record_settlement(T, "yes", "unit test", observed_high=77)
    perf = app.performance()
    assert perf["realized_pnl"] == pytest.approx(2 - r["cost"])
    assert app.cash() == pytest.approx(1000 - r["cost"] + 2)
    eq = app.equity_curve()
    assert eq[0][1] == 1000 and eq[-1][1] == pytest.approx(1000 + 2 - r["cost"])
    ev = evaluate(app.store)
    assert ev["n"] == 1 and any("SAMPLE" in w for w in ev["warnings"])


def test_losing_settlement(app, clock):
    setup(app, clock)
    did = app.record_decision(T)
    r = app.execute_paper(did)
    clock.advance(days=2)
    app.record_settlement(T, "no", "unit test")
    assert app.performance()["realized_pnl"] == pytest.approx(-r["cost"])


def test_execution_rejected_when_decision_quote_goes_stale(app, clock):
    setup(app, clock)
    did = app.record_decision(T)
    clock.advance(minutes=10)
    r = app.execute_paper(did)
    assert r["status"] == "REJECTED" and r["qty"] == 0
    assert app.cash() == 1000


def test_no_trade_without_ack_or_forecast(app, clock):
    app.refresh()
    d = app.analyze(T)["decision"]
    assert d.action == "NO_TRADE"
    with pytest.raises(ValueError):
        app.execute_paper(app.record_decision(T))


def test_ack_is_tied_to_rules_text(app, clock):
    setup(app, clock)
    assert app.is_acked(T, clock())
    assert not app.is_acked("SAMPLE-HIGHTEMP-26SEP30-T69", clock())


def test_daily_loss_limit_blocks_after_exposure(app, clock):
    app.cfg.paper.max_daily_loss = 0.30
    setup(app, clock)
    r = app.execute_paper(app.record_decision(T))
    assert r["cost"] <= 0.30
    d = app.analyze(T)["decision"]
    assert d.action == "NO_TRADE"


def test_same_snapshot_liquidity_not_reused(app, clock):
    setup(app, clock)
    d1 = app.record_decision(T)
    d2 = app.record_decision(T)  # recorded before d1 executed: still BUY on paper
    app.execute_paper(d1)
    with pytest.raises(ValueError):
        app.execute_paper(d2)
    assert app.analyze(T)["decision"].action == "NO_TRADE"
    clock.advance(seconds=5)
    app.refresh()  # new snapshot -> may trade again (within risk limits)
    assert app.analyze(T)["decision"].action == "BUY_YES"
