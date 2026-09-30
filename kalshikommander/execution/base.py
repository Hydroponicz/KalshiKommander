"""Execution adapter interface.

A future live adapter would implement this interface in a SEPARATE milestone after explicit
review. Nothing in this codebase selects an adapter from configuration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from ..orderbook import OrderBook


@dataclass
class OrderRequest:
    ticker: str
    side: str            # "yes" | "no"   (buy only; positions are held to settlement)
    max_qty: int
    limit_price: float   # max exchange price per contract, dollars
    max_cost: float      # max total cost incl. fees and slippage, dollars


@dataclass
class Fill:
    qty: int
    price: float         # exchange price level
    slippage: float      # extra $/contract assumed
    fee: float           # $ for this fill

    @property
    def cost(self) -> float:
        return round(self.qty * (self.price + self.slippage) + self.fee, 4)


@dataclass
class ExecutionReport:
    status: str                      # FILLED | PARTIAL | UNFILLED | REJECTED
    fills: list[Fill] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    simulated: bool = True

    @property
    def qty(self) -> int:
        return sum(f.qty for f in self.fills)

    @property
    def cost(self) -> float:
        return round(sum(f.cost for f in self.fills), 4)

    @property
    def fees(self) -> float:
        return round(sum(f.fee for f in self.fills), 4)


class ExecutionAdapter(ABC):
    is_simulated: bool = True

    @abstractmethod
    def submit(self, order: OrderRequest, book: OrderBook, book_captured_at: datetime,
               now: datetime) -> ExecutionReport: ...
