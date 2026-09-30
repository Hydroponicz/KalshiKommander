"""Parse Kalshi market/event/series JSON into a Contract and verify its terms.

Settlement semantics come from STRUCTURED fields (strike_type, floor_strike, cap_strike) and
are cross-checked against the verbatim rules text. The title is never used to infer rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from .timeutil import parse_ts

TRADABLE_STATUSES = ("active", "open")
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December"]
_EVENT_DATE_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})(?:$|-)")


def parse_price(obj: dict, name: str) -> float | None:
    """Read a price in dollars. Supports new `<name>_dollars` strings and legacy integer cents."""
    v = obj.get(f"{name}_dollars")
    if v not in (None, ""):
        try:
            return round(float(v), 4)
        except (TypeError, ValueError):
            return None
    v = obj.get(name)
    if v is None or v == "":
        return None
    try:
        return round(float(v) / 100.0, 4)
    except (TypeError, ValueError):
        return None


def parse_count(obj: dict, name: str) -> float | None:
    v = obj.get(f"{name}_fp", obj.get(name))
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def date_from_event_ticker(event_ticker: str) -> date | None:
    """Kalshi event tickers encode the event date as YYMONDD, e.g. KXHIGHNY-26SEP30."""
    m = _EVENT_DATE_RE.search((event_ticker or "").upper())
    if not m or m.group(2) not in _MONTHS:
        return None
    try:
        return date(2000 + int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)))
    except ValueError:
        return None


def _fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def date_mentions(d: date) -> list[str]:
    """Strings we accept as a mention of date d inside rules text."""
    mn = _MONTH_NAMES[d.month - 1]
    return [f"{mn} {d.day}, {d.year}", f"{mn[:3]} {d.day}, {d.year}", f"{mn} {d.day:02d}, {d.year}",
            d.isoformat(), f"{d.month}/{d.day}/{d.year}", f"{mn} {d.day}"]


@dataclass
class Contract:
    ticker: str
    event_ticker: str
    series_ticker: str
    title: str
    yes_sub_title: str
    status: str
    open_time: datetime | None
    close_time: datetime | None
    expiration_time: datetime | None
    rules_primary: str
    rules_secondary: str
    strike_type: str
    floor_strike: float | None
    cap_strike: float | None
    unit: str
    target_date: date | None
    settlement_sources: list = field(default_factory=list)
    contract_url: str = ""
    contract_terms_url: str = ""
    market_url: str = ""
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None
    last_price: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    result: str = ""
    is_sample: bool = False
    fee_type: str = ""
    fee_multiplier: float | None = None

    # ---- settlement semantics ------------------------------------------------------------
    def yes_if(self, observed: int | float) -> bool:
        """Would the contract resolve YES if the reported value were `observed`?

        Mapping (documented in README): greater: v > floor; greater_or_equal: v >= floor;
        less: v < cap; less_or_equal: v <= cap; between: floor <= v <= cap (inclusive).
        """
        st, lo, hi = self.strike_type, self.floor_strike, self.cap_strike
        if st == "greater" and lo is not None:
            return observed > lo
        if st == "greater_or_equal" and lo is not None:
            return observed >= lo
        if st == "less" and hi is not None:
            return observed < hi
        if st == "less_or_equal" and hi is not None:
            return observed <= hi
        if st == "between" and lo is not None and hi is not None:
            return lo <= observed <= hi
        raise ValueError(f"unsupported/incomplete strike: {st} floor={lo} cap={hi}")

    def describe_yes_set(self, lo: int = -60, hi: int = 140) -> str:
        """Human-readable YES set over integer reported values (reports are whole degrees)."""
        try:
            ks = [k for k in range(lo, hi + 1) if self.yes_if(k)]
        except ValueError as e:
            return f"cannot interpret: {e}"
        if not ks:
            return "no integer value resolves YES (check terms)"
        u = f"°{self.unit}"
        if ks[0] == lo and ks[-1] == hi:
            return "every value (check terms)"
        if ks[0] == lo:
            return f"reported high ≤ {ks[-1]}{u}"
        if ks[-1] == hi:
            return f"reported high ≥ {ks[0]}{u}"
        return f"reported high from {ks[0]}{u} to {ks[-1]}{u} (inclusive)"

    def threshold_text(self) -> str:
        lo, hi = self.floor_strike, self.cap_strike
        return f"strike_type={self.strike_type}, floor_strike={lo}, cap_strike={hi} (°{self.unit})"

    # ---- verification ---------------------------------------------------------------------
    def verification_problems(self) -> list[str]:
        """Reasons the terms cannot be machine-verified. Empty list = passes automated checks."""
        p: list[str] = []
        if not self.rules_primary.strip():
            p.append("rules_primary text missing")
        if self.strike_type not in ("greater", "greater_or_equal", "less", "less_or_equal", "between"):
            p.append(f"unsupported strike_type {self.strike_type!r}")
        else:
            try:
                self.yes_if(0)
            except ValueError as e:
                p.append(str(e))
        rules = self.rules_primary
        for s in (self.floor_strike, self.cap_strike):
            if s is not None and _fmt_num(s) not in rules:
                p.append(f"strike {_fmt_num(s)} not found in rules text")
        if self.target_date is None:
            p.append("target date could not be determined from event ticker / event data")
        elif not any(m in rules for m in date_mentions(self.target_date)):
            p.append(f"target date {self.target_date} not found in rules text")
        if not self.settlement_sources:
            p.append("series has no settlement source listed")
        if self.close_time is None:
            p.append("close_time missing")
        return p


def detect_unit(rules: str) -> str:
    r = rules or ""
    if "°C" in r or "Celsius" in r or "celsius" in r:
        return "C"
    return "F"


def parse_contract(market: dict, event: dict | None = None, series: dict | None = None,
                   is_sample: bool = False) -> Contract:
    event = event or {}
    series = series or {}
    event_ticker = market.get("event_ticker") or event.get("event_ticker") or ""
    target = date_from_event_ticker(event_ticker)
    if target is None and event.get("strike_date"):
        sd = parse_ts(event["strike_date"])
        target = sd.date() if sd else None
    rules = market.get("rules_primary") or ""
    series_ticker = series.get("ticker") or event.get("series_ticker") or event_ticker.split("-")[0]
    sources = series.get("settlement_sources") or []
    return Contract(
        ticker=market.get("ticker", ""),
        event_ticker=event_ticker,
        series_ticker=series_ticker,
        title=market.get("title") or event.get("title") or "",
        yes_sub_title=market.get("yes_sub_title") or market.get("subtitle") or "",
        status=(market.get("status") or "").lower(),
        open_time=parse_ts(market.get("open_time")),
        close_time=parse_ts(market.get("close_time")),
        expiration_time=parse_ts(market.get("expiration_time") or market.get("latest_expiration_time")),
        rules_primary=rules,
        rules_secondary=market.get("rules_secondary") or "",
        strike_type=(market.get("strike_type") or "").lower(),
        floor_strike=_f(market.get("floor_strike")),
        cap_strike=_f(market.get("cap_strike")),
        unit=detect_unit(rules),
        target_date=target,
        settlement_sources=[s for s in sources if isinstance(s, dict)],
        contract_url=series.get("contract_url") or "",
        contract_terms_url=series.get("contract_terms_url") or "",
        market_url=(f"https://kalshi.com/markets/{series_ticker.lower()}" if series_ticker and not is_sample else ""),
        yes_bid=parse_price(market, "yes_bid"),
        yes_ask=parse_price(market, "yes_ask"),
        no_bid=parse_price(market, "no_bid"),
        no_ask=parse_price(market, "no_ask"),
        last_price=parse_price(market, "last_price"),
        volume=parse_count(market, "volume"),
        open_interest=parse_count(market, "open_interest"),
        result=(market.get("result") or "").lower(),
        is_sample=is_sample,
        fee_type=series.get("fee_type") or "",
        fee_multiplier=_f(series.get("fee_multiplier")),
    )


def _f(v) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None
