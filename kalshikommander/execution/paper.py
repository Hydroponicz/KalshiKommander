"""Local simulated (PAPER) execution. No network access, no exchange connectivity.

Conservative fill assumptions (see README):
  * Immediate-or-cancel only; no resting orders, no queue position, no maker rebates.
  * Fills only against levels VISIBLE in the stored order-book snapshot, walking from the best
    price, and only up to `fill_fraction_of_displayed` of each level's displayed quantity.
  * Every fill pays the taker fee (rounded up to the cent per level) plus a fixed slippage.
  * The snapshot must be younger than `max_quote_age_seconds`, otherwise the order is rejected.
  * Whole contracts only.
A displayed price alone never produces a fill: quantity must be visible at that price.
"""

from __future__ import annotations

import math
from datetime import datetime

from ..fees import trading_fee
from ..orderbook import OrderBook
from .base import ExecutionAdapter, ExecutionReport, Fill, OrderRequest


class PaperExecutionAdapter(ExecutionAdapter):
    is_simulated = True

    def __init__(self, fee_rate: float, slippage: float, fill_fraction: float, max_quote_age_seconds: float):
        if not 0 < fill_fraction <= 1:
            raise ValueError("fill_fraction must be in (0, 1]")
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.fill_fraction = fill_fraction
        self.max_quote_age_seconds = max_quote_age_seconds

    def submit(self, order: OrderRequest, book: OrderBook, book_captured_at: datetime,
               now: datetime) -> ExecutionReport:
        age = (now - book_captured_at).total_seconds()
        if age < 0:
            return ExecutionReport("REJECTED", notes=["order book snapshot is from the future (look-ahead guard)"])
        if age > self.max_quote_age_seconds:
            return ExecutionReport("REJECTED", notes=[f"order book snapshot is stale ({age:.0f}s old)"])
        if order.side not in ("yes", "no") or order.max_qty <= 0:
            return ExecutionReport("REJECTED", notes=["invalid order"])

        fills: list[Fill] = []
        remaining_qty, budget = order.max_qty, order.max_cost
        for level in book.asks(order.side):
            if remaining_qty <= 0 or level.price > order.limit_price + 1e-9:
                break
            eff = level.price + self.slippage
            if eff >= 1.0:
                break
            q = min(remaining_qty, int(math.floor(level.qty * self.fill_fraction)))
            while q > 0 and q * eff + trading_fee(q, level.price, self.fee_rate) > budget + 1e-9:
                q -= 1
            if q <= 0:
                if int(math.floor(level.qty * self.fill_fraction)) == 0:
                    continue  # level too small after haircut; try next level
                break      # budget exhausted
            f = Fill(q, level.price, self.slippage, trading_fee(q, level.price, self.fee_rate))
            fills.append(f)
            remaining_qty -= q
            budget -= f.cost
        if not fills:
            return ExecutionReport("UNFILLED", notes=["no visible quantity at or below limit within budget"])
        status = "FILLED" if remaining_qty == 0 else "PARTIAL"
        return ExecutionReport(status, fills=fills, notes=[f"simulated IOC against snapshot {age:.0f}s old"])
