import pytest

from kalshikommander.fees import trading_fee
from kalshikommander.orderbook import parse_orderbook


def test_parse_fp_orderbook_and_derive_asks():
    b = parse_orderbook({"orderbook_fp": {"yes_dollars": [["0.3800", "10.00"], ["0.4000", "5.00"]],
                                          "no_dollars": [["0.5500", "7.00"], ["0.5700", "3.00"]]}})
    assert b.best_bid("yes").price == 0.40
    a = b.asks("yes")
    assert [(l.price, l.qty) for l in a] == [(0.43, 3.0), (0.45, 7.0)]
    assert b.best_ask("no").price == 0.60 and b.best_ask("no").qty == 5.0


def test_parse_legacy_orderbook_cents():
    b = parse_orderbook({"orderbook": {"yes": [[40, 5]], "no": [[55, 7]]}})
    assert b.best_ask("yes").price == 0.45
    assert b.best_ask("no").price == 0.60


def test_empty_and_null_book():
    b = parse_orderbook({"orderbook": {"yes": None, "no": None}})
    assert b.is_empty() and b.best_ask("yes") is None


def test_fees():
    assert trading_fee(1, 0.50, 0.07) == 0.02   # 0.0175 rounded up
    assert trading_fee(100, 0.50, 0.07) == 1.75
    assert trading_fee(10, 0.10, 0.07) == 0.07  # 0.063 -> 0.07
    assert trading_fee(0, 0.5, 0.07) == 0
    assert trading_fee(100, 0.5, 0.0175) == pytest.approx(0.44)
    with pytest.raises(ValueError):
        trading_fee(1, 42, 0.07)  # cents passed by mistake
