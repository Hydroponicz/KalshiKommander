"""Probability model: Normal forecast error, discretized to whole-degree reports.

Assumption: the reported daily high H is the forecast expected high mu plus Normal(0, sigma)
error, then rounded to the nearest whole degree (official reports are whole degrees):
    P(report = k) = Phi((k + 0.5 - mu)/sigma) - Phi((k - 0.5 - mu)/sigma)
P(YES) = sum of P(report = k) over integers k the contract's structured strike maps to YES.

This is NOT calibrated. sigma is a user assumption until validated on settled outcomes.
"""

from __future__ import annotations

import math

from .contracts import Contract
from .units import c_to_f

METHOD = "normal-discretized-v1"


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def p_report_equals(k: int, mu: float, sigma: float) -> float:
    return norm_cdf((k + 0.5 - mu) / sigma) - norm_cdf((k - 0.5 - mu) / sigma)


def p_yes(contract: Contract, mu_f: float, sigma_f: float) -> float:
    """mu_f/sigma_f are in °F. If the contract is in °C, reports are whole °C."""
    if sigma_f <= 0:
        raise ValueError("sigma must be > 0")
    if contract.unit == "C":
        mu, sigma = (mu_f - 32) * 5 / 9, sigma_f * 5 / 9
    else:
        mu, sigma = mu_f, sigma_f
    lo, hi = int(math.floor(mu - 10 * sigma)) - 1, int(math.ceil(mu + 10 * sigma)) + 1
    total = 0.0
    for k in range(lo, hi + 1):
        if contract.yes_if(k):
            total += p_report_equals(k, mu, sigma)
    # Account for tails beyond +/-10 sigma (negligible, but keep endpoints consistent).
    if contract.yes_if(hi + 1000):
        total += 1.0 - norm_cdf((hi + 0.5 - mu) / sigma)
    if contract.yes_if(lo - 1000):
        total += norm_cdf((lo - 0.5 - mu) / sigma)
    return min(1.0, max(0.0, total))


def sensitivity(contract: Contract, mu_f: float, sigmas: list[float]) -> list[tuple[float, float]]:
    return [(s, p_yes(contract, mu_f, s)) for s in sigmas]


__all__ = ["METHOD", "p_yes", "sensitivity", "norm_cdf", "p_report_equals", "c_to_f"]
