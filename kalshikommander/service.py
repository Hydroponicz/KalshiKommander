"""Application service: wires market data, storage, model, decision, risk and PAPER execution.

Each component is independently testable; this module only orchestrates and persists.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Callable

from . import PAPER_LABEL
from .cities import City, guess_label, guess_timezone, suggest_station
from .config import AppConfig
from .contracts import Contract, parse_contract
from .decision import ForecastInput, decide
from .execution.base import OrderRequest
from .execution.paper import PaperExecutionAdapter
from .marketdata.base import MarketDataSource, looks_like_daily_high_series
from .marketdata.kalshi_public import KalshiPublicClient
from .marketdata.sample import SAMPLE_CITIES, SampleSource
from .orderbook import OrderBook, parse_orderbook
from .probability import METHOD, p_yes, sensitivity
from .risk import RiskState
from .storage import Store
from .timeutil import local_date, parse_ts, to_iso, utcnow
from .units import normalize_unit, spread_to_f, to_f

SETTLED_STATUSES = ("settled", "finalized", "determined")


def rules_sha(market: dict) -> str:
    text = (market.get("rules_primary") or "") + "\n" + (market.get("rules_secondary") or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_source(cfg: AppConfig) -> MarketDataSource:
    if cfg.market.source == "sample":
        return SampleSource(cfg.market.timezone)
    return KalshiPublicClient()


class App:
    def __init__(self, cfg: AppConfig, source: MarketDataSource | None = None, store: Store | None = None,
                 clock: Callable[[], datetime] = utcnow):
        self.cfg = cfg
        self.source = source or make_source(cfg)
        self.store = store or Store(cfg.db_path)
        self.clock = clock
        self.http_opener = None  # injectable for tests; weather providers use urllib by default
        self.last_update = None  # (time, summary) of the most recent update()
        p = cfg.paper
        self.executor = PaperExecutionAdapter(p.taker_fee_rate, p.slippage_per_contract,
                                              p.fill_fraction_of_displayed, p.max_quote_age_seconds)
        if self.store.one("SELECT 1 FROM cash_ledger LIMIT 1") is None:
            self.store.insert("cash_ledger", {"created_at": self.clock(), "kind": "DEPOSIT (virtual)",
                                              "amount": p.starting_cash, "ref": PAPER_LABEL})

    @property
    def tz(self) -> str:
        """YOUR timezone (display and the daily-loss day boundary)."""
        return self.cfg.market.timezone

    # ---------------------------------------------------------------- cities
    @property
    def legacy_series(self) -> str:
        """The single series from the pre-multi-city `[market] series_ticker` setting (if any)."""
        return self.cfg.market.series_ticker or ("SAMPLE-HIGHTEMP" if self.source.is_sample else "")

    def cities(self) -> list[City]:
        """Tracked cities: config `[[cities]]`, the legacy `[market]` series, then dashboard choices."""
        out: dict[str, City] = {}
        if self.source.is_sample:
            for t, (label, tz, _) in SAMPLE_CITIES.items():
                out[t] = City(t, f"{label} (SAMPLE)", tz, origin="sample")
        elif self.cfg.market.series_ticker:
            m = self.cfg.market
            out[m.series_ticker] = City(m.series_ticker, m.city_label, m.timezone,
                                        self.cfg.weather.latitude, self.cfg.weather.longitude)
        for c in self.cfg.cities:
            out[c.series_ticker] = City(c.series_ticker, c.label, c.timezone, c.latitude, c.longitude)
        if not self.source.is_sample:
            for r in self.store.all("SELECT * FROM tracked_series ORDER BY id"):
                if r["action"] == "track":
                    out[r["series_ticker"]] = City(r["series_ticker"], r["label"] or "", r["timezone"],
                                                   r["latitude"], r["longitude"], origin="dashboard")
                elif out.get(r["series_ticker"]) and out[r["series_ticker"]].origin == "dashboard":
                    out.pop(r["series_ticker"])
        return [self._with_location(c) for c in out.values()]

    def _with_location(self, c: City) -> City:
        """Forecast location: your saved location > config/track coordinates > suggested station."""
        row = self.store.one("SELECT * FROM city_locations WHERE series_ticker=? ORDER BY id DESC LIMIT 1",
                             (c.series_ticker,))
        if row is not None:
            c.latitude, c.longitude, c.location_note = row["latitude"], row["longitude"], row["note"] or "set by you"
        elif c.latitude is not None and c.longitude is not None:
            c.location_note = "from config.toml" if c.origin == "config" else "set when followed"
        elif c.origin != "sample":
            hint = suggest_station(c.label, c.series_ticker)
            if hint:
                c.location_note = f"suggested: {hint[0]} — check against the contract rules"
                c.latitude, c.longitude = hint[1], hint[2]
        return c

    def set_location(self, series_ticker: str, latitude: float, longitude: float, note: str = "set by you") -> int:
        if self.city(series_ticker) is None:
            raise ValueError("unknown city")
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("latitude must be -90..90 and longitude -180..180")
        return self.store.insert("city_locations", {"created_at": self.clock(), "series_ticker": series_ticker,
                                                    "latitude": latitude, "longitude": longitude, "note": note})

    def city(self, series_ticker: str) -> City | None:
        return next((c for c in self.cities() if c.series_ticker == series_ticker), None)

    def track_city(self, series_ticker: str, label: str, timezone: str,
                   latitude: float | None = None, longitude: float | None = None) -> int:
        from zoneinfo import ZoneInfo
        series_ticker = series_ticker.strip().upper()
        if not re.fullmatch(r"[A-Z0-9_.-]+", series_ticker or ""):
            raise ValueError("invalid series ticker")
        ZoneInfo(timezone)  # raises for unknown zones
        return self.store.insert("tracked_series", {
            "created_at": self.clock(), "action": "track", "series_ticker": series_ticker,
            "label": label.strip(), "timezone": timezone, "latitude": latitude, "longitude": longitude})

    def untrack_city(self, series_ticker: str) -> int:
        c = self.city(series_ticker)
        if c is None or c.origin != "dashboard":
            raise ValueError("only cities added on the Cities page can be removed there; "
                             "edit config.toml for the others")
        return self.store.insert("tracked_series", {"created_at": self.clock(), "action": "untrack",
                                                    "series_ticker": series_ticker})

    def discover_cities(self) -> list[dict]:
        """Daily-high series currently listed by the market-data source, with a timezone GUESS."""
        tracked = {c.series_ticker for c in self.cities()}
        out = []
        for s in self.source.list_series():
            if not looks_like_daily_high_series(s):
                continue
            title = s.get("title") or ""
            out.append({"ticker": s.get("ticker", ""), "title": title,
                        "label": guess_label(title, s.get("ticker", "")),
                        "tz_guess": guess_timezone(title + " " + s.get("ticker", "")),
                        "sources": ", ".join(x.get("name", "") for x in s.get("settlement_sources") or []),
                        "tracked": s.get("ticker") in tracked})
        return sorted(out, key=lambda x: x["label"].lower())

    def city_dates(self, city: City) -> list[date]:
        today = local_date(self.clock(), city.timezone)
        return [today, today + timedelta(days=1)]

    # ---------------------------------------------------------------- market data snapshots
    def refresh(self, series_ticker: str | None = None) -> dict:
        """Snapshot every open market (and its book) for today/tomorrow in each city's own timezone."""
        cities = self.cities() if series_ticker is None else [c for c in self.cities() if c.series_ticker == series_ticker]
        if not cities:
            raise RuntimeError("No cities tracked. Open the Cities page (or run `python -m kalshikommander discover`) "
                               "and add one.")
        total = {"markets": 0, "orderbooks": 0, "errors": []}
        for city in cities:
            try:
                r = self._refresh_city(city)
            except Exception as e:
                total["errors"].append(f"{city.name}: {e}")
                continue
            total["markets"] += r["markets"]
            total["orderbooks"] += r["orderbooks"]
            total["errors"] += r["errors"]
        return total

    def _refresh_city(self, city: City) -> dict:
        series = self.source.get_series(city.series_ticker)
        events = self.source.list_events(city.series_ticker)
        wanted = set(self.city_dates(city))
        n_m = n_b = 0
        errors = []
        for ev in events:
            ev_meta = {k: v for k, v in ev.items() if k != "markets"}
            for m in ev.get("markets") or []:
                c = parse_contract(m, ev_meta, series, self.source.is_sample)
                if c.target_date not in wanted:
                    continue
                try:
                    full = self.source.get_market(c.ticker) or m
                except Exception as e:  # keep list data but note it
                    full, _ = m, errors.append(f"{c.ticker}: market detail failed: {e}")
                self.store.insert("market_snapshots", {
                    "captured_at": self.clock(), "source": self.source.name, "is_sample": int(self.source.is_sample),
                    "ticker": c.ticker, "event_ticker": c.event_ticker, "series_ticker": city.series_ticker,
                    "market_json": full, "event_json": ev_meta, "series_json": series})
                n_m += 1
                try:
                    ob = self.source.get_orderbook(c.ticker)
                    self.store.insert("orderbook_snapshots", {
                        "captured_at": self.clock(), "source": self.source.name,
                        "is_sample": int(self.source.is_sample), "ticker": c.ticker, "orderbook_json": ob})
                    n_b += 1
                except Exception as e:
                    errors.append(f"{c.ticker}: orderbook failed: {e}")
        return {"markets": n_m, "orderbooks": n_b, "errors": errors}

    def contract_at(self, ticker: str, as_of: datetime) -> tuple[Contract | None, object]:
        row = self.store.latest_market_snapshot(ticker, as_of)
        if row is None:
            return None, None
        c = parse_contract(json.loads(row["market_json"]), json.loads(row["event_json"] or "{}"),
                           json.loads(row["series_json"] or "{}"), bool(row["is_sample"]))
        if row["series_ticker"]:
            c.series_ticker = row["series_ticker"]
        return c, row

    def book_at(self, ticker: str, as_of: datetime) -> tuple[OrderBook | None, object]:
        row = self.store.latest_orderbook_snapshot(ticker, as_of)
        if row is None:
            return None, None
        return parse_orderbook(json.loads(row["orderbook_json"])), row

    def known_tickers(self, as_of: datetime | None = None, dates: set[date] | None = None,
                      series_ticker: str | None = None) -> list[str]:
        as_of = as_of or self.clock()
        if series_ticker:
            rows = self.store.all("SELECT DISTINCT ticker FROM market_snapshots WHERE captured_at<=? AND series_ticker=?",
                                  (to_iso(as_of), series_ticker))
        else:
            rows = self.store.all("SELECT DISTINCT ticker FROM market_snapshots WHERE captured_at<=?", (to_iso(as_of),))
        out = []
        for r in rows:
            c, _ = self.contract_at(r["ticker"], as_of)
            if c and (dates is None or c.target_date in dates):
                lo = c.floor_strike if c.floor_strike is not None else (c.cap_strike or 0) - 1e6
                out.append((c.target_date or date.min, lo, r["ticker"]))
        return [t for *_, t in sorted(out)]

    def todays_tickers(self, series_ticker: str | None = None) -> list[str]:
        """Contracts for today/tomorrow, where 'today' is each city's own local date."""
        out = []
        for city in self.cities():
            if series_ticker and city.series_ticker != series_ticker:
                continue
            out += self.known_tickers(dates=set(self.city_dates(city)), series_ticker=city.series_ticker)
        return out

    # ---------------------------------------------------------------- forecasts
    def add_forecast(self, *, target_date: date, expected_high: float, unit: str, sigma: float | None,
                     issued_at: datetime, source: str, series_ticker: str | None = None, source_detail: str = "",
                     location: str = "", notes: str = "", raw: dict | None = None) -> int:
        now = self.clock()
        unit = normalize_unit(unit)
        series_ticker = series_ticker or self.legacy_series
        city = self.city(series_ticker) if series_ticker else None
        if city is None:
            raise ValueError("choose which tracked city this forecast is for")
        if not source.strip():
            raise ValueError("forecast source is required")
        if issued_at > now:
            raise ValueError("forecast issue time cannot be in the future")
        sigma_is_assumption = sigma is None
        if sigma is None:
            sigma, unit_sigma = self.cfg.model.default_sigma_f, "F"
        else:
            unit_sigma = unit
        if sigma <= 0:
            raise ValueError("uncertainty (sigma) must be > 0")
        return self.store.insert("forecasts", {
            "recorded_at": now, "issued_at": issued_at, "target_date": target_date.isoformat(),
            "series_ticker": city.series_ticker, "location": location or city.name, "source": source.strip(),
            "source_detail": source_detail, "expected_high": expected_high, "unit": unit,
            "expected_high_f": round(to_f(expected_high, unit), 3), "sigma": sigma,
            "sigma_f": round(spread_to_f(sigma, unit_sigma), 3), "sigma_is_assumption": int(sigma_is_assumption),
            "notes": notes, "raw_json": raw or {}})

    def fetch_nws(self, target: date, series_ticker: str | None = None) -> int:
        from .weather.nws import fetch_nws_forecast
        series_ticker = series_ticker or self.legacy_series
        city = self.city(series_ticker)
        if city is None:
            raise ValueError("unknown city")
        w = self.cfg.weather
        lat = city.latitude if city.latitude is not None else w.latitude
        lon = city.longitude if city.longitude is not None else w.longitude
        if lat is None or lon is None:
            raise RuntimeError(f"Set a latitude/longitude for {city.name} (Cities page or config.toml) to use NWS")
        parsed, raw = fetch_nws_forecast(lat, lon, target, w.nws_user_agent)
        if parsed is None:
            raise RuntimeError(f"NWS forecast had no daytime period for {target}; nothing recorded")
        return self.add_forecast(target_date=target, expected_high=parsed["expected_high"], unit=parsed["unit"],
                                 sigma=None, issued_at=parsed["issued_at"], source="NWS api.weather.gov",
                                 series_ticker=city.series_ticker,
                                 source_detail=f"{raw['forecast_url']} period={parsed['period_name']}",
                                 notes=parsed["detail"], raw={"forecast_url": raw["forecast_url"]})

    def forecast_at(self, series_ticker: str, target: date, as_of: datetime):
        return self.store.latest_forecast(series_ticker, target.isoformat(), as_of, self.legacy_series)

    # ---------------------------------------------------------------- automatic forecasts
    AUTO_SOURCES = {"open_meteo": "Open-Meteo (automatic)", "nws": "NWS api.weather.gov (automatic)"}

    def auto_forecasts_enabled(self) -> bool:
        return self.cfg.weather.provider in self.AUTO_SOURCES and not self.source.is_sample

    def auto_forecasts(self, force: bool = False) -> dict:
        """Fetch and store forecasts for every city's today/tomorrow from the configured provider.

        Only real fetched values are stored (never interpolated or invented). Each city is fetched at
        most every `refetch_minutes` unless `force`. The "±" uses the configured default assumption."""
        res = {"saved": 0, "skipped": [], "errors": []}
        if self.source.is_sample:
            res["skipped"].append("sample mode: automatic forecasts only run for real cities")
            return res
        provider = self.cfg.weather.provider
        if provider not in self.AUTO_SOURCES:
            res["skipped"].append("automatic forecasts are off (weather.provider = \"manual\")")
            return res
        source = self.AUTO_SOURCES[provider]
        now = self.clock()
        for city in self.cities():
            if city.latitude is None or city.longitude is None:
                res["skipped"].append(f"{city.name}: no location set")
                continue
            last = self.store.one("SELECT MAX(recorded_at) t FROM forecasts WHERE series_ticker=? AND source=?",
                                  (city.series_ticker, source))["t"]
            if not force and last and (now - parse_ts(last)).total_seconds() < self.cfg.weather.refetch_minutes * 60:
                continue
            try:
                res["saved"] += self._fetch_city_forecast(city, provider, source, now)
            except Exception as e:  # network/format problems are reported, never papered over
                res["errors"].append(f"{city.name}: {e}")
        return res

    def _fetch_city_forecast(self, city: City, provider: str, source: str, now: datetime) -> int:
        where = f"lat {city.latitude:.4f}, lon {city.longitude:.4f} ({city.location_note or 'location'})"
        rows = []  # (date, value, unit, issued_at, detail)
        if provider == "open_meteo":
            from .weather.open_meteo import fetch_open_meteo
            highs, url = fetch_open_meteo(city.latitude, city.longitude, city.timezone, self.http_opener)
            for d in self.city_dates(city):
                if d in highs:
                    rows.append((d, highs[d][0], highs[d][1], now,
                                 f"{url} · {where} · issue time = retrieval time (model run time not provided)"))
        else:
            from .weather.nws import extract_daily_high, fetch_nws_raw
            fc, url = fetch_nws_raw(city.latitude, city.longitude, self.cfg.weather.nws_user_agent, self.http_opener)
            for d in self.city_dates(city):
                p = extract_daily_high(fc, d)
                if p:
                    rows.append((d, p["expected_high"], p["unit"], p["issued_at"], f"{url} period={p['period_name']} · {where}"))
        saved = 0
        for d, value, unit, issued, detail in rows:
            dup = self.store.one("SELECT 1 FROM forecasts WHERE series_ticker=? AND target_date=? AND source=? "
                                 "AND issued_at=? AND expected_high=?",
                                 (city.series_ticker, d.isoformat(), source, to_iso(issued), value))
            if dup:
                continue  # same NWS issuance already stored
            self.add_forecast(target_date=d, expected_high=value, unit=unit, sigma=None, issued_at=issued,
                              source=source, series_ticker=city.series_ticker, source_detail=detail)
            saved += 1
        return saved

    def update(self, record_decisions: bool = False, force_forecasts: bool = False) -> dict:
        """One-stop update: snapshot prices, fetch automatic forecasts, optionally record decisions."""
        r = {"prices": self.refresh(), "forecasts": self.auto_forecasts(force_forecasts), "decisions": 0}
        if record_decisions:
            for t in self.todays_tickers():
                self.record_decision(t)
                r["decisions"] += 1
        self.last_update = (self.clock(), r)
        return r

    # ---------------------------------------------------------------- terms acknowledgment
    def ack_terms(self, ticker: str) -> int:
        now = self.clock()
        c, row = self.contract_at(ticker, now)
        if row is None:
            raise ValueError("no snapshot for ticker")
        return self.store.insert("terms_acks", {"created_at": now, "ticker": ticker, "market_snapshot_id": row["id"],
                                                "rules_sha": rules_sha(json.loads(row["market_json"]))})

    def is_acked(self, ticker: str, as_of: datetime) -> bool:
        _, row = self.contract_at(ticker, as_of)
        return row is not None and self.store.terms_acked(ticker, rules_sha(json.loads(row["market_json"])), as_of)

    # ---------------------------------------------------------------- positions / risk
    def positions(self) -> list[dict]:
        rows = self.store.all(
            "SELECT f.ticker, f.side, SUM(f.qty) qty, SUM(f.cost) cost, SUM(f.fee) fees, MIN(f.created_at) opened_at, "
            "s.result, s.recorded_at settled_at FROM paper_fills f LEFT JOIN settlements s ON s.ticker=f.ticker "
            "GROUP BY f.ticker, f.side ORDER BY opened_at")
        out = []
        for r in rows:
            d = dict(r)
            if d["result"]:
                d["payout"] = float(d["qty"]) if d["result"] == d["side"] else 0.0
                d["pnl"] = round(d["payout"] - d["cost"], 4)
            else:
                d["payout"] = d["pnl"] = None
            out.append(d)
        return out

    def cash(self) -> float:
        return round(self.store.one("SELECT COALESCE(SUM(amount),0) s FROM cash_ledger")["s"], 4)

    def risk_state(self, ticker: str, now: datetime) -> RiskState:
        today = local_date(now, self.tz)
        open_total = open_mkt = opened_today = realized_today = 0.0
        for p in self.positions():
            opened_local = local_date(parse_ts(p["opened_at"]), self.tz)
            if p["result"] is None:
                open_total += p["cost"]
                if p["ticker"] == ticker:
                    open_mkt += p["cost"]
            else:
                if local_date(parse_ts(p["settled_at"]), self.tz) == today:
                    realized_today += p["pnl"]
            if opened_local == today and p["result"] is None:
                opened_today += p["cost"]
        return RiskState(self.cash(), round(open_total, 4), round(open_mkt, 4), round(opened_today, 4),
                         round(realized_today, 4))

    # ---------------------------------------------------------------- analysis & decisions
    def analyze(self, ticker: str, as_of: datetime | None = None, sigma_f: float | None = None) -> dict:
        """Point-in-time view: uses ONLY rows recorded at or before `as_of`. Does not persist."""
        now = as_of or self.clock()
        c, mrow = self.contract_at(ticker, now)
        book, brow = self.book_at(ticker, now)
        frow = self.forecast_at(c.series_ticker, c.target_date, now) if c and c.target_date else None
        fin = None
        prob = sens = None
        sig = None
        if frow is not None and c is not None:
            sig = sigma_f or frow["sigma_f"]
            fin = ForecastInput(frow["id"], frow["expected_high_f"], sig, parse_ts(frow["issued_at"]),
                                parse_ts(frow["recorded_at"]), date.fromisoformat(frow["target_date"]), frow["source"])
            try:
                prob = p_yes(c, fin.expected_high_f, sig)
                sens = sensitivity(c, fin.expected_high_f, sorted(set(self.cfg.model.sensitivity_sigmas_f + [sig])))
            except ValueError:
                prob = None
        acked = self.is_acked(ticker, now)
        dec = decide(contract=c, book=book, book_captured_at=parse_ts(brow["captured_at"]) if brow else None,
                     forecast=fin, p_yes=prob, now=now, cfg=self.cfg.paper,
                     risk=self.risk_state(ticker, now), terms_acked=acked,
                     snapshot_already_traded=bool(brow) and self._snapshot_traded(brow["id"]))
        return {"now": now, "contract": c, "market_row": mrow, "book": book, "book_row": brow,
                "forecast_row": frow, "sigma_f": sig, "p_yes": prob, "sensitivity": sens or [],
                "decision": dec, "acked": acked}

    def _snapshot_traded(self, orderbook_snapshot_id: int) -> bool:
        return self.store.one("SELECT 1 FROM paper_orders o JOIN decisions d ON d.id=o.decision_id "
                              "WHERE d.orderbook_snapshot_id=?", (orderbook_snapshot_id,)) is not None

    @staticmethod
    def _mid(book: OrderBook | None) -> float | None:
        if not book:
            return None
        b, a = book.best_bid("yes"), book.best_ask("yes")
        return round((b.price + a.price) / 2, 4) if b and a else None

    def record_decision(self, ticker: str) -> int:
        """Persist an immutable estimate + decision snapshot for `ticker` as of now."""
        a = self.analyze(ticker)
        c, dec = a["contract"], a["decision"]
        est_id = None
        if a["p_yes"] is not None:
            est_id = self.store.insert("estimates", {
                "created_at": a["now"], "ticker": ticker, "market_snapshot_id": a["market_row"]["id"],
                "forecast_id": a["forecast_row"]["id"], "method": METHOD, "mu_f": a["forecast_row"]["expected_high_f"],
                "sigma_f": a["sigma_f"], "p_yes": a["p_yes"], "sensitivity_json": a["sensitivity"]})
        return self.store.insert("decisions", {
            "created_at": a["now"], "ticker": ticker, "is_sample": int(bool(c and c.is_sample)),
            "market_snapshot_id": a["market_row"]["id"] if a["market_row"] else None,
            "orderbook_snapshot_id": a["book_row"]["id"] if a["book_row"] else None,
            "forecast_id": a["forecast_row"]["id"] if a["forecast_row"] else None, "estimate_id": est_id,
            "action": dec.action, "side": dec.side, "qty": dec.qty, "limit_price": dec.limit_price,
            "max_cost": dec.max_cost, "p_yes": a["p_yes"], "market_mid_yes": self._mid(a["book"]),
            "reasons_json": dec.reasons,
            "detail_json": {"sides": [asdict(s) for s in dec.sides], "risk_notes": dec.risk_notes, "codes": dec.codes,
                            "terms_acked": a["acked"], "label": PAPER_LABEL},
            "config_json": asdict(self.cfg.paper)})

    def execute_paper(self, decision_id: int) -> dict:
        """Simulate an IOC buy for a stored BUY_* decision against ITS OWN order-book snapshot."""
        now = self.clock()
        d = self.store.one("SELECT * FROM decisions WHERE id=?", (decision_id,))
        if d is None or d["action"] not in ("BUY_YES", "BUY_NO"):
            raise ValueError("decision is not a BUY decision")
        if self.store.one("SELECT 1 FROM paper_orders WHERE decision_id=?", (decision_id,)):
            raise ValueError("decision already executed")
        if self._snapshot_traded(d["orderbook_snapshot_id"]):
            raise ValueError("another paper order already used this order-book snapshot; refresh and decide again")
        brow = self.store.one("SELECT * FROM orderbook_snapshots WHERE id=?", (d["orderbook_snapshot_id"],))
        book = parse_orderbook(json.loads(brow["orderbook_json"]))
        # risk may have changed since the decision (other paper trades): re-check
        from .risk import RiskLimits, max_new_cost
        p = self.cfg.paper
        allowed, _ = max_new_cost(self.risk_state(d["ticker"], now),
                                  RiskLimits(p.max_stake_per_market, p.max_total_exposure, p.max_daily_loss))
        order = OrderRequest(d["ticker"], d["side"], int(d["qty"]), float(d["limit_price"]),
                             min(float(d["max_cost"]), allowed))
        rep = self.executor.submit(order, book, parse_ts(brow["captured_at"]), now)
        oid = self.store.insert("paper_orders", {
            "created_at": now, "decision_id": decision_id, "ticker": d["ticker"], "side": d["side"],
            "requested_qty": order.max_qty, "limit_price": order.limit_price, "status": rep.status,
            "notes_json": rep.notes + [PAPER_LABEL]})
        for f in rep.fills:
            self.store.insert("paper_fills", {"created_at": now, "order_id": oid, "ticker": d["ticker"],
                                              "side": d["side"], "qty": f.qty, "price": f.price,
                                              "slippage": f.slippage, "fee": f.fee, "cost": f.cost})
            self.store.insert("cash_ledger", {"created_at": now, "kind": "PAPER BUY (incl. fee)",
                                              "amount": -f.cost, "ticker": d["ticker"], "ref": f"order {oid}"})
        return {"order_id": oid, "status": rep.status, "qty": rep.qty, "cost": rep.cost, "fees": rep.fees,
                "notes": rep.notes}

    # ---------------------------------------------------------------- settlement
    def record_settlement(self, ticker: str, result: str, source: str, observed_high: float | None = None,
                          notes: str = "", raw: dict | None = None) -> int:
        now = self.clock()
        result = result.strip().lower()
        if result not in ("yes", "no"):
            raise ValueError("result must be 'yes' or 'no'")
        if not source.strip():
            raise ValueError("settlement source is required")
        c, _ = self.contract_at(ticker, now)
        if c is not None and c.close_time is not None and now < c.close_time:
            raise ValueError("cannot record a settlement before the market's close time")
        sid = self.store.insert("settlements", {"recorded_at": now, "ticker": ticker, "result": result,
                                                "source": source, "observed_high": observed_high,
                                                "notes": notes, "raw_json": raw or {}})
        for p in self.positions():
            if p["ticker"] == ticker and p["side"] == result and p["qty"]:
                self.store.insert("cash_ledger", {"created_at": now, "kind": "PAPER SETTLEMENT PAYOUT",
                                                  "amount": float(p["qty"]), "ticker": ticker, "ref": f"settlement {sid}"})
        return sid

    def fetch_settlements(self) -> list[str]:
        """Record results for known tickers that Kalshi's public data reports as settled."""
        done = {r["ticker"] for r in self.store.all("SELECT ticker FROM settlements")}
        recorded = []
        for t in self.known_tickers():
            if t in done:
                continue
            m = self.source.get_market(t)
            if (m.get("status") or "").lower() in SETTLED_STATUSES and (m.get("result") or "").lower() in ("yes", "no"):
                self.record_settlement(t, m["result"], f"{self.source.name} market.result (status={m.get('status')})",
                                       raw={"status": m.get("status"), "result": m.get("result"),
                                            "settlement_value": m.get("settlement_value")})
                recorded.append(t)
        return recorded

    # ---------------------------------------------------------------- reporting
    def equity_curve(self) -> list[tuple[str, float]]:
        """Equity = cash + open positions valued at COST, so only settlements move it."""
        events = []
        for r in self.store.all("SELECT created_at t, id, amount, kind, ticker FROM cash_ledger"):
            events.append((r["t"], 0, r["id"], dict(r)))
        for s in self.store.all("SELECT recorded_at t, id, ticker FROM settlements"):
            events.append((s["t"], 1, s["id"], {"k": "S", "ticker": s["ticker"]}))
        events.sort(key=lambda e: (e[0], e[1], e[2]))
        cash = 0.0
        open_cost: dict[str, float] = {}
        out = []
        for t, _, _, e in events:
            if e.get("k") == "S":
                open_cost.pop(e["ticker"], None)
            else:
                cash += e["amount"]
                if e["kind"].startswith("PAPER BUY"):
                    open_cost[e["ticker"]] = open_cost.get(e["ticker"], 0.0) - e["amount"]
            point = (t, round(cash + sum(open_cost.values()), 4))
            if out and out[-1][0] == t:
                out[-1] = point  # collapse same-timestamp events (e.g. settlement + payout)
            else:
                out.append(point)
        return out

    def performance(self) -> dict:
        pos = self.positions()
        settled = [p for p in pos if p["result"]]
        return {
            "label": PAPER_LABEL,
            "starting_cash": self.cfg.paper.starting_cash,
            "cash": self.cash(),
            "open_positions": sum(1 for p in pos if not p["result"]),
            "open_cost": round(sum(p["cost"] for p in pos if not p["result"]), 4),
            "settled_positions": len(settled),
            "realized_pnl": round(sum(p["pnl"] for p in settled), 4),
            "fees_paid": round(sum(p["fees"] for p in pos), 4),
            "wins": sum(1 for p in settled if p["pnl"] > 0),
        }
