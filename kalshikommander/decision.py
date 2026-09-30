"""Decision logic: compare model probability with EXECUTABLE prices (asks), after fees,
slippage, and a safety margin. Pure function - no I/O. Returns NO_TRADE with reasons whenever
required data is missing, stale, thin, or unverifiable."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from .config import PaperConfig
from .contracts import TRADABLE_STATUSES, Contract
from .fees import fee_per_contract_upper_bound
from .orderbook import OrderBook
from .risk import RiskLimits, RiskState, max_new_cost


@dataclass
class ForecastInput:
    id: int | None
    expected_high_f: float
    sigma_f: float
    issued_at: datetime
    recorded_at: datetime
    target_date: object  # date
    source: str


@dataclass
class SideAnalysis:
    side: str
    model_prob: float
    best_ask: float | None
    best_ask_qty: float
    all_in_cost_per_contract: float | None  # ask + worst-case fee + slippage
    edge: float | None                       # model_prob - all_in_cost
    fillable_qty: int                        # sum of qty passing the margin, after haircut


@dataclass
class Decision:
    action: str                 # BUY_YES | BUY_NO | NO_TRADE
    side: str | None
    qty: int
    limit_price: float | None
    max_cost: float
    reasons: list[str] = field(default_factory=list)
    sides: list[SideAnalysis] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)


def analyze_side(side: str, prob: float, book: OrderBook, cfg: PaperConfig) -> tuple[SideAnalysis, float | None]:
    asks = book.asks(side)
    best = asks[0] if asks else None
    fillable, limit = 0, None
    for lv in asks:
        cost = lv.price + cfg.slippage_per_contract + fee_per_contract_upper_bound(lv.price, cfg.taker_fee_rate)
        if prob - cost < cfg.safety_margin:
            break
        fillable += int(math.floor(lv.qty * cfg.fill_fraction_of_displayed))
        limit = lv.price
    if best is None:
        return SideAnalysis(side, prob, None, 0, None, None, 0), None
    c = best.price + cfg.slippage_per_contract + fee_per_contract_upper_bound(best.price, cfg.taker_fee_rate)
    return SideAnalysis(side, prob, best.price, best.qty, round(c, 4), round(prob - c, 4), fillable), limit


def decide(*, contract: Contract | None, book: OrderBook | None, book_captured_at: datetime | None,
           forecast: ForecastInput | None, p_yes: float | None, now: datetime, cfg: PaperConfig,
           risk: RiskState, terms_acked: bool, snapshot_already_traded: bool = False) -> Decision:
    reasons: list[str] = []
    if snapshot_already_traded:
        # the simulator never consumes the same displayed liquidity twice
        reasons.append("a paper order already used this order-book snapshot; refresh for new quotes")
    if contract is None:
        return Decision("NO_TRADE", None, 0, None, 0.0, ["no market data"])
    if contract.status not in TRADABLE_STATUSES:
        reasons.append(f"market status is {contract.status!r}, not open")
    if contract.close_time is not None and now >= contract.close_time:
        reasons.append("market close time has passed")
    problems = contract.verification_problems()
    if problems:
        reasons.append("contract terms cannot be verified: " + "; ".join(problems))
    if cfg.require_terms_ack and not terms_acked:
        reasons.append("you have not confirmed reading this market's rules text")
    if forecast is None or p_yes is None:
        reasons.append("no forecast available for this market's date (none is ever invented)")
    else:
        if forecast.issued_at > now or forecast.recorded_at > now:
            reasons.append("forecast is timestamped after decision time (look-ahead guard)")
        age_h = (now - forecast.issued_at).total_seconds() / 3600
        if age_h > cfg.max_forecast_age_hours:
            reasons.append(f"forecast is stale ({age_h:.1f}h old > {cfg.max_forecast_age_hours}h)")
        if contract.target_date and forecast.target_date != contract.target_date:
            reasons.append(f"forecast target date {forecast.target_date} != market date {contract.target_date}")
    if book is None or book_captured_at is None:
        reasons.append("no order book snapshot")
    else:
        age = (now - book_captured_at).total_seconds()
        if age < 0:
            reasons.append("order book snapshot is from the future (look-ahead guard)")
        elif age > cfg.max_quote_age_seconds:
            reasons.append(f"quote is stale ({age:.0f}s old > {cfg.max_quote_age_seconds}s)")
        if book.is_empty():
            reasons.append("order book is empty")

    sides: list[SideAnalysis] = []
    limits: dict[str, float | None] = {}
    if book is not None and p_yes is not None:
        for side, prob in (("yes", p_yes), ("no", 1 - p_yes)):
            sa, lim = analyze_side(side, prob, book, cfg)
            sides.append(sa)
            limits[side] = lim

    allowed, risk_notes = max_new_cost(risk, RiskLimits(cfg.max_stake_per_market, cfg.max_total_exposure,
                                                         cfg.max_daily_loss))
    best = max((s for s in sides if s.edge is not None), key=lambda s: s.edge, default=None)
    if best is None and not reasons:
        reasons.append("no executable ask on either side")
    elif best is not None and best.edge < cfg.safety_margin:
        reasons.append(f"best edge {best.edge:+.3f} on {best.side.upper()} is below safety margin {cfg.safety_margin:.3f}")
    elif best is not None and best.fillable_qty < cfg.min_contracts:
        reasons.append(f"book too thin: {best.fillable_qty} fillable contracts < minimum {cfg.min_contracts}")
    if allowed <= 0:
        reasons.append(risk_notes[0] if risk_notes else "risk limits exhausted")
    elif best is not None and best.all_in_cost_per_contract and allowed < best.all_in_cost_per_contract * cfg.min_contracts:
        reasons.append(f"risk limits allow only ${allowed:.2f}, less than one contract")

    if reasons or best is None:
        return Decision("NO_TRADE", None, 0, None, 0.0, reasons, sides, risk_notes)
    qty = min(best.fillable_qty, int(allowed // best.all_in_cost_per_contract))
    return Decision("BUY_" + best.side.upper(), best.side, qty, limits[best.side], round(allowed, 4),
                    [f"edge {best.edge:+.3f} on {best.side.upper()} >= margin {cfg.safety_margin:.3f}"],
                    sides, risk_notes)
