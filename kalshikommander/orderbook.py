"""Order book parsing and executable-price derivation.

Kalshi's order book lists BIDS only, for YES and for NO. A YES contract can be BOUGHT by
matching a resting NO bid: YES ask price = 1 - NO bid price, and vice versa.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    price: float  # dollars per contract
    qty: float    # contracts displayed


@dataclass
class OrderBook:
    yes_bids: list[Level]  # best (highest) first
    no_bids: list[Level]   # best (highest) first

    def asks(self, side: str) -> list[Level]:
        """Executable BUY levels for `side` ('yes'|'no'), cheapest first."""
        opposite = self.no_bids if side == "yes" else self.yes_bids
        return [Level(round(1.0 - l.price, 4), l.qty) for l in opposite]

    def best_ask(self, side: str) -> Level | None:
        a = self.asks(side)
        return a[0] if a else None

    def best_bid(self, side: str) -> Level | None:
        b = self.yes_bids if side == "yes" else self.no_bids
        return b[0] if b else None

    def is_empty(self) -> bool:
        return not self.yes_bids and not self.no_bids


def _levels(raw, in_cents: bool) -> list[Level]:
    out = []
    for item in raw or []:
        try:
            price, qty = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if in_cents:
            price /= 100.0
        if 0 < price < 1 and qty > 0:
            out.append(Level(round(price, 4), qty))
    return sorted(out, key=lambda l: -l.price)


def parse_orderbook(payload: dict) -> OrderBook:
    """Accepts {'orderbook_fp': {'yes_dollars': [[\"0.42\", \"13.00\"], ...], 'no_dollars': ...}}
    or legacy {'orderbook': {'yes': [[42, 13], ...], 'no': ...}} (cents)."""
    fp = payload.get("orderbook_fp")
    if isinstance(fp, dict):
        return OrderBook(_levels(fp.get("yes_dollars"), False), _levels(fp.get("no_dollars"), False))
    ob = payload.get("orderbook") or {}
    if "yes_dollars" in ob or "no_dollars" in ob:
        return OrderBook(_levels(ob.get("yes_dollars"), False), _levels(ob.get("no_dollars"), False))
    return OrderBook(_levels(ob.get("yes"), True), _levels(ob.get("no"), True))
