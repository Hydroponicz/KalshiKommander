"""CLEARLY LABELED SAMPLE DATA. Not real markets, not real prices, not a real city.

Used when Kalshi's public API is unreachable or no series is configured, so the app can be
exercised end-to-end. Sample data writes to a separate database (data/sample.db).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .base import MarketDataSource

SAMPLE_SERIES = "SAMPLE-HIGHTEMP"
SAMPLE_SERIES_2 = "SAMPLE-HIGHTEMP2"
# series -> (fictional city, timezone, base temperature)
SAMPLE_CITIES = {
    SAMPLE_SERIES: ("Sampleville", "America/New_York", 72),
    SAMPLE_SERIES_2: ("Testburg", "America/Chicago", 64),
}
SAMPLE_NOTE = "SAMPLE DATA - fictional market for testing the app; not from Kalshi"
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _code(d: date) -> str:
    return f"{d.year % 100:02d}{_MONTHS[d.month - 1]}{d.day:02d}"


class SampleSource(MarketDataSource):
    name = "sample"
    is_sample = True

    def __init__(self, tz_name: str = "America/New_York", today: date | None = None):
        self.today = today or datetime.now(ZoneInfo(tz_name)).date()

    def list_series(self) -> list[dict]:
        return [self.get_series(t) for t in SAMPLE_CITIES]

    def get_series(self, series_ticker: str) -> dict:
        city = SAMPLE_CITIES[series_ticker][0]
        return {"ticker": series_ticker, "title": f"SAMPLE: Highest temperature in {city}",
                "frequency": "daily", "category": "SAMPLE",
                "settlement_sources": [{"name": "SAMPLE Weather Service (fictional)", "url": ""}],
                "contract_url": "", "fee_type": "quadratic", "fee_multiplier": 1, "_sample": SAMPLE_NOTE}

    def _markets(self, d: date, series: str = SAMPLE_SERIES) -> list[dict]:
        city, tz_name, base = SAMPLE_CITIES[series]
        tz = ZoneInfo(tz_name)
        et = f"{series}-{_code(d)}"
        close = datetime.combine(d + timedelta(days=1), time(0, 59), tz).isoformat()
        opened = datetime.combine(d - timedelta(days=1), time(10, 0), tz).isoformat()
        datestr = f"{d.strftime('%B')} {d.day}, {d.year}"
        specs = [("less", None, base - 3), ("between", base - 3, base - 2), ("between", base - 1, base),
                 ("between", base + 1, base + 2), ("greater", base + 2, None)]
        # fictional bids: [yes_bids], [no_bids] in dollars
        books = [([(0.08, 40)], [(0.88, 30)]), ([(0.18, 25), (0.15, 60)], [(0.76, 20)]),
                 ([(0.30, 15), (0.28, 50)], [(0.64, 10), (0.60, 40)]),
                 ([(0.22, 20)], [(0.72, 25), (0.70, 30)]), ([(0.12, 30)], [(0.84, 5)])]
        out = []
        for i, ((st, lo, hi), (yb, nb)) in enumerate(zip(specs, books)):
            if st == "less":
                cond, sub = f"less than {hi}°", f"{hi - 1}° or below"
            elif st == "greater":
                cond, sub = f"greater than {lo}°", f"{lo + 1}° or above"
            else:
                cond, sub = f"between {lo}° and {hi}°, inclusive", f"{lo}° to {hi}°"
            tick = f"{et}-{'T' if st != 'between' else 'B'}{lo if lo is not None else hi}"
            out.append({
                "ticker": tick, "event_ticker": et, "status": "active",
                "title": f"SAMPLE: Highest temperature in {city} on {datestr}?",
                "yes_sub_title": sub, "open_time": opened, "close_time": close,
                "expiration_time": close, "strike_type": st, "floor_strike": lo, "cap_strike": hi,
                "rules_primary": (f"[SAMPLE DATA] If the highest temperature recorded at the fictional "
                                  f"{city} station for {datestr} as reported by the SAMPLE Weather "
                                  f"Service is {cond}, then the market resolves to Yes."),
                "rules_secondary": "[SAMPLE DATA] Fictional. Not a Kalshi contract.",
                "yes_bid_dollars": f"{yb[0][0]:.4f}", "yes_ask_dollars": f"{1 - nb[0][0]:.4f}",
                "no_bid_dollars": f"{nb[0][0]:.4f}", "no_ask_dollars": f"{1 - yb[0][0]:.4f}",
                "last_price_dollars": f"{yb[0][0] + 0.01:.4f}", "volume_fp": "100.00",
                "open_interest_fp": "50.00", "result": "",
                "_book": {"orderbook_fp": {
                    "yes_dollars": [[f"{p:.4f}", f"{q:.2f}"] for p, q in sorted(yb)],
                    "no_dollars": [[f"{p:.4f}", f"{q:.2f}"] for p, q in sorted(nb)]}},
            })
        return out

    def list_events(self, series_ticker: str) -> list[dict]:
        evs = []
        for d in (self.today, self.today + timedelta(days=1)):
            ms = self._markets(d, series_ticker)
            evs.append({"event_ticker": ms[0]["event_ticker"], "series_ticker": series_ticker,
                        "title": ms[0]["title"], "markets": [{k: v for k, v in m.items() if k != "_book"} for m in ms]})
        return evs

    def _find(self, ticker: str) -> dict:
        for series in SAMPLE_CITIES:
            for d in (self.today, self.today + timedelta(days=1)):
                for m in self._markets(d, series):
                    if m["ticker"] == ticker:
                        return m
        raise KeyError(ticker)

    def get_market(self, ticker: str) -> dict:
        return {k: v for k, v in self._find(ticker).items() if k != "_book"}

    def get_orderbook(self, ticker: str) -> dict:
        return self._find(ticker)["_book"]
