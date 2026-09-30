"""Append-only SQLite store.

Every snapshot/decision table is INSERT-only: SQLite triggers abort any UPDATE or DELETE, so
data recorded later cannot rewrite what was known at decision time. Settlement results live
in their own table and are linked to decisions only at evaluation time.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .timeutil import to_iso

APPEND_ONLY_TABLES = [
    "market_snapshots", "orderbook_snapshots", "forecasts", "estimates", "decisions",
    "paper_orders", "paper_fills", "cash_ledger", "settlements", "terms_acks",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_snapshots (
  id INTEGER PRIMARY KEY, captured_at TEXT NOT NULL, source TEXT NOT NULL, is_sample INTEGER NOT NULL,
  ticker TEXT NOT NULL, event_ticker TEXT, series_ticker TEXT,
  market_json TEXT NOT NULL, event_json TEXT, series_json TEXT);
CREATE INDEX IF NOT EXISTS ix_ms ON market_snapshots(ticker, captured_at);
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
  id INTEGER PRIMARY KEY, captured_at TEXT NOT NULL, source TEXT NOT NULL, is_sample INTEGER NOT NULL,
  ticker TEXT NOT NULL, orderbook_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_ob ON orderbook_snapshots(ticker, captured_at);
CREATE TABLE IF NOT EXISTS forecasts (
  id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, issued_at TEXT NOT NULL, target_date TEXT NOT NULL,
  location TEXT NOT NULL, source TEXT NOT NULL, source_detail TEXT,
  expected_high REAL NOT NULL, unit TEXT NOT NULL, expected_high_f REAL NOT NULL,
  sigma REAL NOT NULL, sigma_f REAL NOT NULL, sigma_is_assumption INTEGER NOT NULL,
  notes TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS estimates (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, ticker TEXT NOT NULL,
  market_snapshot_id INTEGER NOT NULL REFERENCES market_snapshots(id),
  forecast_id INTEGER NOT NULL REFERENCES forecasts(id),
  method TEXT NOT NULL, mu_f REAL NOT NULL, sigma_f REAL NOT NULL, p_yes REAL NOT NULL,
  sensitivity_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, ticker TEXT NOT NULL, is_sample INTEGER NOT NULL,
  market_snapshot_id INTEGER REFERENCES market_snapshots(id),
  orderbook_snapshot_id INTEGER REFERENCES orderbook_snapshots(id),
  forecast_id INTEGER REFERENCES forecasts(id), estimate_id INTEGER REFERENCES estimates(id),
  action TEXT NOT NULL, side TEXT, qty INTEGER NOT NULL, limit_price REAL, max_cost REAL,
  p_yes REAL, market_mid_yes REAL, reasons_json TEXT NOT NULL, detail_json TEXT NOT NULL,
  config_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_orders (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, decision_id INTEGER NOT NULL UNIQUE REFERENCES decisions(id),
  ticker TEXT NOT NULL, side TEXT NOT NULL, requested_qty INTEGER NOT NULL, limit_price REAL NOT NULL,
  status TEXT NOT NULL, notes_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_fills (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, order_id INTEGER NOT NULL REFERENCES paper_orders(id),
  ticker TEXT NOT NULL, side TEXT NOT NULL, qty INTEGER NOT NULL, price REAL NOT NULL,
  slippage REAL NOT NULL, fee REAL NOT NULL, cost REAL NOT NULL);
CREATE TABLE IF NOT EXISTS cash_ledger (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL, amount REAL NOT NULL,
  ticker TEXT, ref TEXT);
CREATE TABLE IF NOT EXISTS settlements (
  id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, ticker TEXT NOT NULL UNIQUE,
  result TEXT NOT NULL CHECK (result IN ('yes','no')), source TEXT NOT NULL,
  observed_high REAL, notes TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS terms_acks (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, ticker TEXT NOT NULL,
  market_snapshot_id INTEGER NOT NULL REFERENCES market_snapshots(id), rules_sha TEXT NOT NULL);
"""


def _triggers() -> str:
    out = []
    for t in APPEND_ONLY_TABLES:
        for op in ("UPDATE", "DELETE"):
            out.append(
                f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;")
    return "\n".join(out)


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA + _triggers())
        self.conn.commit()

    # -- generic -------------------------------------------------------------------------
    def insert(self, table: str, row: dict) -> int:
        if table not in APPEND_ONLY_TABLES:
            raise ValueError(table)
        clean = {k: (to_iso(v) if isinstance(v, datetime) else
                     json.dumps(v, default=str, sort_keys=True) if isinstance(v, (dict, list)) else v)
                 for k, v in row.items()}
        cols = ", ".join(clean)
        qs = ", ".join("?" for _ in clean)
        cur = self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(clean.values()))
        self.conn.commit()
        return int(cur.lastrowid)

    def one(self, sql: str, args=()) -> sqlite3.Row | None:
        return self.conn.execute(sql, args).fetchone()

    def all(self, sql: str, args=()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, args).fetchall()

    # -- point-in-time reads (never return rows recorded after `as_of`) ------------------
    def latest_market_snapshot(self, ticker: str, as_of: datetime):
        return self.one("SELECT * FROM market_snapshots WHERE ticker=? AND captured_at<=? "
                        "ORDER BY captured_at DESC, id DESC LIMIT 1", (ticker, to_iso(as_of)))

    def latest_orderbook_snapshot(self, ticker: str, as_of: datetime):
        return self.one("SELECT * FROM orderbook_snapshots WHERE ticker=? AND captured_at<=? "
                        "ORDER BY captured_at DESC, id DESC LIMIT 1", (ticker, to_iso(as_of)))

    def latest_forecast(self, target_date: str, as_of: datetime):
        """Most recently ISSUED forecast for the date that was both issued and recorded by as_of."""
        return self.one("SELECT * FROM forecasts WHERE target_date=? AND issued_at<=? AND recorded_at<=? "
                        "ORDER BY issued_at DESC, id DESC LIMIT 1",
                        (target_date, to_iso(as_of), to_iso(as_of)))

    def terms_acked(self, ticker: str, rules_sha: str, as_of: datetime) -> bool:
        return self.one("SELECT 1 FROM terms_acks WHERE ticker=? AND rules_sha=? AND created_at<=?",
                        (ticker, rules_sha, to_iso(as_of))) is not None
