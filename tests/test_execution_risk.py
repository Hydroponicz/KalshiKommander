from datetime import datetime, timedelta, timezone

from kalshikommander.execution.base import OrderRequest
from kalshikommander.execution.paper import PaperExecutionAdapter
from kalshikommander.fees import trading_fee
from kalshikommander.orderbook import Level, OrderBook
from kalshikommander.risk import RiskLimits, RiskState, max_new_cost

T = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
BOOK = OrderBook(yes_bids=[Level(0.40, 10)], no_bids=[Level(0.60, 10), Level(0.55, 20)])  # YES asks .40x10, .45x20


def ex(**kw):
    d = dict(fee_rate=0.07, slippage=0.0, fill_fraction=0.5, max_quote_age_seconds=300)
    d.update(kw)
    return PaperExecutionAdapter(**d)


def test_fill_limited_to_haircut_of_visible_qty():
    r = ex().submit(OrderRequest("X", "yes", 100, 0.45, 1000), BOOK, T, T)
    assert r.status == "PARTIAL"
    assert [(f.qty, f.price) for f in r.fills] == [(5, 0.40), (10, 0.45)]
    assert r.fees == trading_fee(5, 0.40, 0.07) + trading_fee(10, 0.45, 0.07)


def test_limit_price_respected():
    r = ex().submit(OrderRequest("X", "yes", 100, 0.40, 1000), BOOK, T, T)
    assert r.qty == 5 and all(f.price <= 0.40 for f in r.fills)


def test_full_fill_status():
    r = ex().submit(OrderRequest("X", "yes", 3, 0.45, 1000), BOOK, T, T)
    assert r.status == "FILLED" and r.qty == 3


def test_budget_caps_cost_including_fees():
    r = ex(slippage=0.01).submit(OrderRequest("X", "yes", 100, 0.45, 2.0), BOOK, T, T)
    assert r.cost <= 2.0 and r.qty == 4  # 4*0.41 + fee(4@0.40)=0.07 -> 1.71; 5 would be 2.05+0.09


def test_stale_quote_rejected():
    r = ex().submit(OrderRequest("X", "yes", 1, 0.45, 10), BOOK, T, T + timedelta(seconds=301))
    assert r.status == "REJECTED" and not r.fills


def test_future_snapshot_rejected():
    r = ex().submit(OrderRequest("X", "yes", 1, 0.45, 10), BOOK, T + timedelta(seconds=1), T)
    assert r.status == "REJECTED"


def test_displayed_price_without_quantity_never_fills():
    thin = OrderBook(yes_bids=[], no_bids=[Level(0.60, 1)])  # 1 displayed * 50% haircut -> 0
    r = ex().submit(OrderRequest("X", "yes", 1, 0.99, 10), thin, T, T)
    assert r.status == "UNFILLED" and r.qty == 0
    r2 = ex().submit(OrderRequest("X", "no", 1, 0.99, 10), thin, T, T)  # no YES bids => no NO asks
    assert r2.status == "UNFILLED"


def test_risk_limits():
    lim = RiskLimits(25, 100, 50)
    a, _ = max_new_cost(RiskState(1000, 0, 0, 0, 0), lim)
    assert a == 25
    a, _ = max_new_cost(RiskState(1000, 90, 0, 0, 0), lim)
    assert a == 10
    a, _ = max_new_cost(RiskState(1000, 20, 20, 0, 0), lim)
    assert a == 5
    a, _ = max_new_cost(RiskState(1000, 0, 0, 30, -15), lim)  # 50-15-30
    assert a == 5
    a, notes = max_new_cost(RiskState(3, 0, 0, 0, 0), lim)  # no leverage
    assert a == 3
    a, notes = max_new_cost(RiskState(1000, 0, 0, 0, -60), lim)
    assert a == 0 and "exhausted" in notes[0]
