"""Kalshi-style trading fee model.

General taker fee (per Kalshi's published fee schedule at time of writing):
    fee = ceil_to_cent(rate * C * P * (1 - P)),  rate = 0.07 for taker orders
where C = contracts, P = price in dollars. Some series use different multipliers; the rate is
configurable and should be checked against Kalshi's current fee schedule.
The paper simulator only models aggressive (taker) orders, so taker fees always apply.
"""

from __future__ import annotations

import math


def ceil_cent(x: float) -> float:
    return math.ceil(round(x * 100, 6)) / 100.0


def trading_fee(contracts: float, price: float, rate: float) -> float:
    if contracts <= 0:
        return 0.0
    if not 0 <= price <= 1:
        raise ValueError("price must be in dollars between 0 and 1")
    return ceil_cent(rate * contracts * price * (1 - price))


def fee_per_contract_upper_bound(price: float, rate: float) -> float:
    """Per-contract fee assuming a 1-contract fill (worst case for cent rounding)."""
    return trading_fee(1, price, rate)
