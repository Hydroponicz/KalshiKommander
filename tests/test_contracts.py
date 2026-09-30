from datetime import date

import pytest

from kalshikommander.contracts import date_from_event_ticker, parse_contract, parse_price
from tests.conftest import SERIES, market_json


def test_parse_legacy_cents_and_dollar_strings():
    c = parse_contract(market_json(), {}, SERIES)
    assert c.yes_bid == 0.40 and c.yes_ask == 0.45 and c.no_bid == 0.55
    m = market_json(yes_bid=None, yes_bid_dollars="0.4150")
    assert parse_price(m, "yes_bid") == 0.415


def test_parse_core_fields():
    c = parse_contract(market_json(), {}, SERIES)
    assert c.ticker == "KXTEST-26SEP30-T80"
    assert c.series_ticker == "KXTEST"
    assert c.target_date == date(2026, 9, 30)
    assert c.unit == "F"
    assert c.close_time.isoformat() == "2026-10-01T04:59:00+00:00"
    assert c.verification_problems() == []
    assert c.describe_yes_set() == "reported high ≥ 81°F"


def test_date_from_event_ticker():
    assert date_from_event_ticker("KXHIGHNY-26JAN05") == date(2026, 1, 5)
    assert date_from_event_ticker("KXHIGHNY-26FEB30") is None
    assert date_from_event_ticker("garbage") is None


def test_title_is_not_used_for_rules():
    # Title claims 90, structured strike and rules say 80: semantics follow structured fields.
    c = parse_contract(market_json(title="Will it be above 90° today?"), {}, SERIES)
    assert c.yes_if(81) and not c.yes_if(80)


def test_mismatched_rules_fail_verification():
    c = parse_contract(market_json(floor_strike=85), {}, SERIES)  # rules text says 80
    assert any("85" in p for p in c.verification_problems())


def test_missing_rules_or_source_or_strike_fail():
    assert parse_contract(market_json(rules_primary=""), {}, SERIES).verification_problems()
    assert parse_contract(market_json(), {}, {}).verification_problems()  # no settlement source
    assert parse_contract(market_json(strike_type="custom"), {}, SERIES).verification_problems()
    assert parse_contract(market_json(floor_strike=None), {}, SERIES).verification_problems()


def test_date_not_in_rules_fails():
    c = parse_contract(market_json(rules_primary="If the high is greater than 80° then Yes."), {}, SERIES)
    assert any("target date" in p for p in c.verification_problems())


@pytest.mark.parametrize("st,lo,hi,val,expected", [
    ("greater", 80, None, 80, False), ("greater", 80, None, 81, True), ("greater", 80, None, 80.5, True),
    ("greater_or_equal", 80, None, 80, True), ("greater_or_equal", 80, None, 79, False),
    ("less", None, 70, 70, False), ("less", None, 70, 69, True),
    ("less_or_equal", None, 70, 70, True), ("less_or_equal", None, 70, 71, False),
    ("between", 71, 72, 70, False), ("between", 71, 72, 71, True), ("between", 71, 72, 72, True),
    ("between", 71, 72, 73, False),
])
def test_threshold_boundaries(st, lo, hi, val, expected):
    c = parse_contract(market_json(strike_type=st, floor_strike=lo, cap_strike=hi), {}, SERIES)
    assert c.yes_if(val) is expected


def test_celsius_detection():
    c = parse_contract(market_json(rules_primary="... September 30, 2026 ... greater than 25°C ..."), {}, SERIES)
    assert c.unit == "C"
