import pytest

from kalshikommander.contracts import parse_contract
from kalshikommander.probability import norm_cdf, p_yes, sensitivity
from tests.conftest import SERIES, market_json


def C(**kw):
    return parse_contract(market_json(**kw), {}, SERIES)


def test_greater_boundary_uses_rounding():
    # greater than 80 => report >= 81 => underlying >= 80.5
    c = C()
    assert p_yes(c, 80.5, 2.0) == pytest.approx(0.5, abs=1e-9)
    assert p_yes(c, 82.0, 2.0) == pytest.approx(1 - norm_cdf((80.5 - 82) / 2), abs=1e-9)


def test_between_inclusive():
    c = C(strike_type="between", floor_strike=79, cap_strike=80)
    expected = norm_cdf((80.5 - 80) / 1.5) - norm_cdf((78.5 - 80) / 1.5)
    assert p_yes(c, 80, 1.5) == pytest.approx(expected, abs=1e-9)


def test_partition_sums_to_one():
    cs = [C(strike_type="less", floor_strike=None, cap_strike=75),
          C(strike_type="between", floor_strike=75, cap_strike=76),
          C(strike_type="between", floor_strike=77, cap_strike=78),
          C(strike_type="greater", floor_strike=78, cap_strike=None)]
    assert sum(p_yes(c, 76.7, 2.3) for c in cs) == pytest.approx(1.0, abs=1e-9)


def test_sigma_sensitivity_moves_toward_half():
    c = C()
    s = dict(sensitivity(c, 84, [1, 2, 4, 8]))
    assert s[1] > s[2] > s[4] > s[8] > 0.5


def test_invalid_sigma():
    with pytest.raises(ValueError):
        p_yes(C(), 80, 0)


def test_celsius_contract():
    c = C(rules_primary="for September 30, 2026 ... greater than 25°C", floor_strike=25)
    assert c.unit == "C"
    # mu 25.5C exactly at boundary => 0.5
    assert p_yes(c, 25.5 * 9 / 5 + 32, 2 * 9 / 5) == pytest.approx(0.5, abs=1e-9)
