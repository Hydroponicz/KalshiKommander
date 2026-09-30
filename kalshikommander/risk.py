"""Risk limits for PAPER trading. Pure functions; no leverage (cost must be covered by cash)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskState:
    cash: float
    open_cost_total: float          # cost (incl. fees) of all unsettled positions
    open_cost_this_market: float
    opened_cost_today: float        # cost of positions opened today (local date), still open or not
    realized_pnl_today: float       # realized P&L from settlements recorded today


@dataclass
class RiskLimits:
    max_stake_per_market: float
    max_total_exposure: float
    max_daily_loss: float


def max_new_cost(state: RiskState, limits: RiskLimits) -> tuple[float, list[str]]:
    """Largest additional virtual $ cost allowed, with binding-limit explanations.

    Daily loss is measured worst-case: every position opened today could lose its full cost,
    plus any realized losses today.
    """
    realized_loss = max(0.0, -state.realized_pnl_today)
    caps = {
        "cash (no leverage)": state.cash,
        "max_stake_per_market": limits.max_stake_per_market - state.open_cost_this_market,
        "max_total_exposure": limits.max_total_exposure - state.open_cost_total,
        "max_daily_loss (worst case)": limits.max_daily_loss - realized_loss - state.opened_cost_today,
    }
    allowed = max(0.0, min(caps.values()))
    notes = [f"{k} leaves ${max(0.0, v):.2f}" for k, v in caps.items()]
    binding = [k for k, v in caps.items() if max(0.0, v) <= allowed + 1e-9]
    if allowed <= 0:
        notes.insert(0, "risk limit exhausted: " + ", ".join(binding))
    return round(allowed, 4), notes
