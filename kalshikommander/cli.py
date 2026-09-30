"""Command-line entry point. Every trading action is PAPER / SIMULATED."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import PAPER_LABEL
from .config import load_config
from .evaluation import evaluate
from .marketdata.base import looks_like_daily_high_series
from .marketdata.kalshi_public import KalshiPublicClient
from .service import App
from .timeutil import parse_local_input


def cmd_discover(args, cfg):
    """List currently available daily-high-temperature series from Kalshi public data."""
    client = KalshiPublicClient()
    try:
        series = client.list_series()
    except Exception as e:
        print(f"Could not reach Kalshi public API: {e}\nUse market.source = \"sample\" until it is reachable.")
        return 2
    cands = [s for s in series if looks_like_daily_high_series(s)]
    if not cands:
        print("No daily-high-temperature series found in the public series list.")
        return 1
    for s in cands:
        n_open = "?"
        if args.check_open:
            try:
                n_open = len(client.list_events(s["ticker"]))
            except Exception as e:
                n_open = f"error: {e}"
        srcs = ", ".join(x.get("name", "") for x in s.get("settlement_sources") or [])
        print(f"{s.get('ticker'):<16} open events: {n_open!s:<4} {s.get('title')}  [settles: {srcs or 'n/a'}]")
    print("\nSet [market] series_ticker (and timezone, city_label) in config.toml, with source = \"kalshi_public\".")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kalshikommander", description=f"Kalshi weather research — {PAPER_LABEL} only")
    ap.add_argument("--config", default=None, help="path to config.toml (default ./config.toml if present)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover", help="list available daily-high-temperature series (public data)")
    d.add_argument("--check-open", action="store_true", help="also count open events per series")
    sub.add_parser("refresh", help="snapshot today's/tomorrow's markets and order books")
    s = sub.add_parser("serve", help="run the local dashboard")
    s.add_argument("--port", type=int)
    f = sub.add_parser("add-forecast", help="record a manually sourced forecast")
    f.add_argument("--date", required=True)
    f.add_argument("--high", type=float, required=True)
    f.add_argument("--unit", default="F")
    f.add_argument("--sigma", type=float, help="uncertainty in the same unit (default: configured assumption)")
    f.add_argument("--issued", required=True, help="issue time, e.g. 2026-09-30T06:00 (city local) or with offset")
    f.add_argument("--source", required=True)
    f.add_argument("--detail", default="")
    n = sub.add_parser("nws", help="fetch an NWS forecast (optional provider)")
    n.add_argument("--date", required=True)
    dc = sub.add_parser("decide", help="record timestamped decision snapshots")
    dc.add_argument("--ticker", action="append", help="default: all of today's/tomorrow's contracts")
    ex = sub.add_parser("paper-execute", help="simulate a stored BUY decision")
    ex.add_argument("decision_id", type=int)
    st = sub.add_parser("settle", help="record a settlement result manually")
    st.add_argument("ticker")
    st.add_argument("result", choices=["yes", "no"])
    st.add_argument("--source", required=True)
    st.add_argument("--observed-high", type=float)
    sub.add_parser("fetch-settlements", help="record results the market data reports as settled")
    sub.add_parser("evaluate", help="score stored predictions against settlements")
    sub.add_parser("status", help="print paper ledger summary")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)

    if args.cmd == "discover":
        return cmd_discover(args, cfg)
    app = App(cfg)
    try:
        return _run(args, app, cfg)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _run(args, app, cfg) -> int:
    if args.cmd == "refresh":
        print(json.dumps(app.refresh(), indent=2))
    elif args.cmd == "serve":
        from .web import serve
        serve(app, cfg.host, args.port or cfg.port)
    elif args.cmd == "add-forecast":
        fid = app.add_forecast(target_date=date.fromisoformat(args.date), expected_high=args.high, unit=args.unit,
                               sigma=args.sigma, issued_at=parse_local_input(args.issued, app.tz),
                               source=args.source, source_detail=args.detail)
        print(f"forecast #{fid} saved")
    elif args.cmd == "nws":
        print(f"forecast #{app.fetch_nws(date.fromisoformat(args.date))} saved")
    elif args.cmd == "decide":
        for t in args.ticker or app.todays_tickers():
            did = app.record_decision(t)
            r = app.store.one("SELECT action, qty, reasons_json FROM decisions WHERE id=?", (did,))
            print(f"[{PAPER_LABEL}] #{did} {t}: {r['action']} qty={r['qty']} — {'; '.join(json.loads(r['reasons_json']))}")
    elif args.cmd == "paper-execute":
        print(PAPER_LABEL, json.dumps(app.execute_paper(args.decision_id), indent=2))
    elif args.cmd == "settle":
        print(f"settlement #{app.record_settlement(args.ticker, args.result, args.source, args.observed_high)}")
    elif args.cmd == "fetch-settlements":
        print(app.fetch_settlements())
    elif args.cmd == "evaluate":
        r = evaluate(app.store)
        r.pop("predictions")
        print(json.dumps(r, indent=2, default=str))
    elif args.cmd == "status":
        print(json.dumps(app.performance(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
