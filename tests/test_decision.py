from datetime import date, datetime, timedelta, timezone

from kalshikommander.config import PaperConfig
from kalshikommander.contracts import parse_contract
from kalshikommander.decision import ForecastInput, decide
from kalshikommander.orderbook import Level, OrderBook
from kalshikommander.risk import RiskState
from tests.conftest import SERIES, market_json

NOW = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
C = parse_contract(market_json(), {}, SERIES)
BOOK = OrderBook(yes_bids=[Level(0.40, 50)], no_bids=[Level(0.60, 50)])  # YES ask 0.40, NO ask 0.60
FC = ForecastInput(1, 83.0, 2.0, NOW - timedelta(hours=1), NOW - timedelta(minutes=30), date(2026, 9, 30), "t")
RISK = RiskState(1000, 0, 0, 0, 0)


def run(**kw):
    args = dict(contract=C, book=BOOK, book_captured_at=NOW - timedelta(seconds=10), forecast=FC, p_yes=0.80,
                now=NOW, cfg=PaperConfig(), risk=RISK, terms_acked=True)
    args.update(kw)
    return decide(**args)


def test_buy_yes_when_edge_exceeds_margin():
    d = run()
    assert d.action == "BUY_YES" and d.qty > 0 and d.limit_price == 0.40
    yes = [s for s in d.sides if s.side == "yes"][0]
    # all-in = 0.40 + fee(1@0.40)=0.02 + slippage 0.01
    assert yes.all_in_cost_per_contract == 0.43 and yes.edge == 0.37


def test_uses_ask_not_mid_or_last():
    d = run(p_yes=0.44)  # above 0.40 ask but edge after costs 0.01 < 0.05 margin
    assert d.action == "NO_TRADE" and any("safety margin" in r for r in d.reasons)


def test_buy_no_side():
    d = run(p_yes=0.10)
    assert d.action == "BUY_NO"


def test_stale_quote():
    d = run(book_captured_at=NOW - timedelta(seconds=301))
    assert d.action == "NO_TRADE" and any("stale" in r for r in d.reasons)


def test_stale_forecast():
    old = ForecastInput(1, 83, 2, NOW - timedelta(hours=13), NOW - timedelta(hours=13), date(2026, 9, 30), "t")
    assert any("forecast is stale" in r for r in run(forecast=old).reasons)


def test_missing_forecast_or_book_means_no_trade():
    assert run(forecast=None, p_yes=None).action == "NO_TRADE"
    assert run(book=None, book_captured_at=None).action == "NO_TRADE"
    assert run(contract=None).action == "NO_TRADE"


def test_thin_book():
    thin = OrderBook(yes_bids=[Level(0.40, 50)], no_bids=[Level(0.60, 1)])  # 1*0.5 -> 0 fillable
    d = run(book=thin)
    assert d.action == "NO_TRADE" and any("thin" in r for r in d.reasons)


def test_unverified_terms_or_no_ack():
    bad = parse_contract(market_json(floor_strike=85), {}, SERIES)
    assert any("cannot be verified" in r for r in run(contract=bad).reasons)
    assert any("confirmed" in r for r in run(terms_acked=False).reasons)


def test_closed_market():
    closed = parse_contract(market_json(status="closed"), {}, SERIES)
    assert run(contract=closed).action == "NO_TRADE"
    assert run(now=C.close_time + timedelta(seconds=1),
               book_captured_at=C.close_time).action == "NO_TRADE"


def test_forecast_date_mismatch():
    f = ForecastInput(1, 83, 2, NOW - timedelta(hours=1), NOW, date(2026, 10, 1), "t")
    assert any("!=" in r for r in run(forecast=f).reasons)


def test_risk_exhausted():
    d = run(risk=RiskState(1000, 100, 0, 0, 0))
    assert d.action == "NO_TRADE" and any("risk" in r for r in d.reasons)


def test_size_respects_stake_limit():
    d = run()
    assert d.qty * 0.43 <= PaperConfig().max_stake_per_market + 1e-9
