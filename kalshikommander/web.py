"""Local dashboard (stdlib http.server). Binds to localhost only. Every trade/metric is PAPER."""

from __future__ import annotations

import html
import json
import traceback
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

from . import PAPER_LABEL
from .evaluation import evaluate
from .service import App
from .timeutil import local_date, parse_local_input, parse_ts

E = html.escape

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f6f7f9;color:#1b1f24}
header{background:#1b1f24;color:#fff;padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header a{color:#cfe3ff;text-decoration:none;margin-right:12px}
.paper{background:#ffcc00;color:#000;font-weight:700;padding:2px 8px;border-radius:4px}
.sample{background:#d9480f;color:#fff;font-weight:700;padding:2px 8px;border-radius:4px}
main{padding:16px;max-width:1300px;margin:auto}
section{background:#fff;border:1px solid #dde1e6;border-radius:8px;padding:12px 16px;margin-bottom:16px;overflow-x:auto}
h2{font-size:1.1rem;margin:4px 0 10px}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{border-bottom:1px solid #eceef1;padding:4px 6px;text-align:left;vertical-align:top}
th{background:#f1f3f5}
.no{color:#a61e4d;font-weight:600}.yes{color:#2b8a3e;font-weight:600}
.muted{color:#68707a;font-size:.85rem}
.flash{background:#e7f5ff;border:1px solid #74c0fc;padding:8px;border-radius:6px;margin-bottom:12px}
.err{background:#fff5f5;border-color:#ff8787}
form.inline{display:inline}
input,select,button{font-size:.9rem;padding:3px 6px;margin:2px}
button{cursor:pointer}
pre{white-space:pre-wrap;background:#f8f9fa;padding:8px;border-radius:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}
.kpi{background:#f8f9fa;border-radius:6px;padding:8px}.kpi b{display:block;font-size:1.15rem}
"""


def money(x) -> str:
    if x is None:
        return "—"
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


class Dashboard:
    def __init__(self, app: App):
        self.app = app

    # ------------------------------------------------------------ helpers
    def lt(self, ts) -> str:
        if ts is None:
            return "—"
        dt = parse_ts(ts) if isinstance(ts, str) else ts
        return dt.astimezone(ZoneInfo(self.app.tz)).strftime("%Y-%m-%d %H:%M:%S %Z")

    def page(self, title: str, body: str, flash: str = "", err: bool = False) -> str:
        src = self.app.source
        tag = ('<span class="sample">SAMPLE DATA — FICTIONAL</span>' if src.is_sample
               else '<span class="muted" style="color:#ddd">Kalshi public market data (read-only)</span>')
        fl = f'<div class="flash{" err" if err else ""}">{E(flash)}</div>' if flash else ""
        return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                f"<title>{E(title)} · KalshiKommander</title><style>{CSS}</style></head><body><header>"
                f"<b>KalshiKommander</b><span class='paper'>{PAPER_LABEL}</span>{tag}"
                f"<nav><a href='/'>Dashboard</a><a href='/evaluate'>Evaluation</a></nav>"
                f"<span class='muted' style='color:#aaa'>No real orders are ever placed. Series: {E(self.app.series_ticker or 'not set')}"
                f" · tz {E(self.app.tz)}</span></header><main>{fl}{body}</main></body></html>")

    # ------------------------------------------------------------ pages
    def index(self, q: dict) -> str:
        app = self.app
        now = app.clock()
        tickers = app.todays_tickers()
        rows = []
        for t in tickers:
            a = app.analyze(t)
            c, b, d = a["contract"], a["book"], a["decision"]
            ya, na = (b.best_ask("yes") if b else None), (b.best_ask("no") if b else None)
            age = f"{(now - parse_ts(a['book_row']['captured_at'])).total_seconds():.0f}s" if a["book_row"] else "—"
            dcls = "no" if d.action == "NO_TRADE" else "yes"
            rows.append(
                f"<tr><td><a href='/market?t={urllib.parse.quote(t)}'>{E(t)}</a></td><td>{c.target_date}</td>"
                f"<td>{E(c.describe_yes_set())}</td><td>{E(c.status)}</td><td>{self.lt(c.close_time)}</td>"
                f"<td>{money(ya.price) + ' ×' + format(ya.qty, 'g') if ya else '—'}</td>"
                f"<td>{money(na.price) + ' ×' + format(na.qty, 'g') if na else '—'}</td>"
                f"<td>{pct(a['p_yes'])}</td><td class='{dcls}'>{E(d.action)}</td><td>{age}</td></tr>")
        mk = ("<table><tr><th>Contract</th><th>Date</th><th>YES if (structured strike)</th><th>Status</th><th>Close</th>"
              "<th>Buy YES @ (qty)</th><th>Buy NO @ (qty)</th><th>Model P(YES)</th><th>Live check</th><th>Book age</th></tr>"
              + "".join(rows) + "</table>") if rows else (
              "<p>No market snapshots for today/tomorrow yet. Click <b>Refresh market data</b>.</p>")
        today = local_date(now, app.tz)
        nws_btn = ""
        if app.cfg.weather.provider == "nws":
            nws_btn = (f"<form class='inline' method='post' action='/nws'><input type='date' name='target_date' value='{today}'>"
                       "<button>Fetch NWS forecast (optional provider)</button></form>")
        forecasts = app.store.all("SELECT * FROM forecasts ORDER BY id DESC LIMIT 15")
        frows = "".join(
            f"<tr><td>{f['id']}</td><td>{f['target_date']}</td><td>{f['expected_high']:g}°{f['unit']} "
            f"({f['expected_high_f']:.1f}°F)</td><td>±{f['sigma_f']:.1f}°F{' (assumed)' if f['sigma_is_assumption'] else ''}</td>"
            f"<td>{E(f['source'])}<div class='muted'>{E(f['source_detail'] or '')}</div></td><td>{self.lt(f['issued_at'])}</td>"
            f"<td>{self.lt(f['recorded_at'])}</td><td>{E(f['notes'] or '')}</td></tr>" for f in forecasts)
        decisions = app.store.all("SELECT * FROM decisions ORDER BY id DESC LIMIT 20")
        drows = "".join(
            f"<tr><td>{d['id']}</td><td>{self.lt(d['created_at'])}</td><td><a href='/market?t={urllib.parse.quote(d['ticker'])}'>{E(d['ticker'])}</a></td>"
            f"<td class='{'no' if d['action'] == 'NO_TRADE' else 'yes'}'>{E(d['action'])}</td><td>{d['qty']}</td>"
            f"<td>{pct(d['p_yes'])}</td><td>{E('; '.join(json.loads(d['reasons_json'])))}</td>"
            f"<td>{self._exec_button(d)}</td></tr>" for d in decisions)
        perf = app.performance()
        body = f"""
<section><h2>Market data</h2>
<form class='inline' method='post' action='/refresh'><button>Refresh market data (snapshot now)</button></form>
<span class='muted'>Every refresh stores an immutable timestamped snapshot of each market and its order book.</span>
{mk}
<p class='muted'>“Buy YES @” is the executable ask derived from the best resting NO bid (1 − NO bid), with displayed quantity; not a midpoint or last trade.
“Live check” recomputes the decision now without saving; open a contract to record a timestamped decision.</p></section>

<section><h2>Enter a forecast (never invented — you supply the source)</h2>
<form method='post' action='/forecast'>
Target date <input type='date' name='target_date' value='{today}' required>
Expected high <input name='expected_high' size='5' required>
<select name='unit'><option>F</option><option>C</option></select>
Uncertainty σ <input name='sigma' size='4' placeholder='{app.cfg.model.default_sigma_f} (°F default)'>
Issued at (local, {E(app.tz)}) <input type='datetime-local' name='issued_at' required>
<br>Source <input name='source' size='22' placeholder='e.g. NWS point forecast' required>
Source URL / detail <input name='source_detail' size='40'>
Notes <input name='notes' size='30'> <button>Save forecast</button></form> {nws_btn}
<p class='muted'>Leave σ blank to use the configured default; it is then stored and labeled as an assumption.</p>
<table><tr><th>#</th><th>Date</th><th>Expected high</th><th>σ</th><th>Source</th><th>Issued</th><th>Recorded</th><th>Notes</th></tr>{frows}</table></section>

<section><h2>Recorded decisions ({PAPER_LABEL})</h2>
<table><tr><th>#</th><th>At</th><th>Contract</th><th>Action</th><th>Qty</th><th>P(YES)</th><th>Rationale</th><th></th></tr>{drows}</table></section>

{self._ledger_html(perf)}
{self._settle_html()}
"""
        return self.page("Dashboard", body, q.get("msg", ""), q.get("err") == "1")

    def _exec_button(self, d) -> str:
        if d["action"] not in ("BUY_YES", "BUY_NO"):
            return ""
        o = self.app.store.one("SELECT status FROM paper_orders WHERE decision_id=?", (d["id"],))
        if o:
            return f"<span class='muted'>paper order: {E(o['status'])}</span>"
        return (f"<form class='inline' method='post' action='/execute'><input type='hidden' name='decision_id' value='{d['id']}'>"
                f"<button>Simulate paper order</button></form>")

    def _ledger_html(self, perf: dict) -> str:
        app = self.app
        prow = "".join(
            f"<tr><td>{E(p['ticker'])}</td><td>{p['side'].upper()}</td><td>{p['qty']}</td><td>{money(p['cost'])}</td>"
            f"<td>{money(p['fees'])}</td><td>{self.lt(p['opened_at'])}</td><td>{E(p['result'] or 'open')}</td>"
            f"<td>{money(p['pnl'])}</td></tr>" for p in app.positions())
        led = "".join(f"<tr><td>{self.lt(r['created_at'])}</td><td>{E(r['kind'])}</td><td>{E(r['ticker'] or '')}</td>"
                      f"<td>{money(r['amount'])}</td></tr>"
                      for r in app.store.all("SELECT * FROM cash_ledger ORDER BY id DESC LIMIT 30"))
        kp = "".join(f"<div class='kpi'>{E(k)}<b>{v}</b></div>" for k, v in [
            ("Virtual cash", money(perf["cash"])), ("Open cost", money(perf["open_cost"])),
            ("Realized P&L", money(perf["realized_pnl"])), ("Fees paid", money(perf["fees_paid"])),
            ("Settled / wins", f"{perf['settled_positions']} / {perf['wins']}"), ("Open positions", perf["open_positions"])])
        return f"""<section><h2>Paper ledger &amp; performance — {PAPER_LABEL}</h2>
<div class='grid'>{kp}</div>
<h3>Equity curve (virtual $, open positions at cost)</h3>{self._svg(app.equity_curve())}
<h3>Positions</h3><table><tr><th>Contract</th><th>Side</th><th>Qty</th><th>Cost incl. fees</th><th>Fees</th><th>Opened</th><th>Result</th><th>P&L</th></tr>{prow}</table>
<h3>Cash ledger (latest 30)</h3><table><tr><th>At</th><th>Kind</th><th>Contract</th><th>Amount</th></tr>{led}</table>
<p class='muted'>Small samples of paper P&amp;L are dominated by luck. See the Evaluation page before drawing conclusions.</p></section>"""

    def _svg(self, pts) -> str:
        if len(pts) < 2:
            return "<p class='muted'>Not enough events yet.</p>"
        w, h, pad = 900, 180, 30
        ys = [p[1] for p in pts]
        lo, hi = min(ys), max(ys)
        if hi - lo < 1e-9:
            lo, hi = lo - 1, hi + 1
        xy = [(pad + i * (w - 2 * pad) / (len(pts) - 1), h - pad - (y - lo) * (h - 2 * pad) / (hi - lo)) for i, y in enumerate(ys)]
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in xy)
        return (f"<svg viewBox='0 0 {w} {h}' style='width:100%;max-width:{w}px' role='img' aria-label='paper equity curve'>"
                f"<polyline fill='none' stroke='#1971c2' stroke-width='2' points='{path}'/>"
                f"<text x='4' y='{pad}' font-size='11'>{money(hi)}</text><text x='4' y='{h - pad}' font-size='11'>{money(lo)}</text>"
                f"<text x='{w - 170}' y='14' font-size='11' fill='#d9480f'>{PAPER_LABEL}</text></svg>")

    def _settle_html(self) -> str:
        opts = "".join(f"<option>{E(t)}</option>" for t in self.app.known_tickers())
        s = self.app.store.all("SELECT * FROM settlements ORDER BY id DESC LIMIT 20")
        srows = "".join(f"<tr><td>{E(r['ticker'])}</td><td>{E(r['result'].upper())}</td><td>{E(r['source'])}</td>"
                        f"<td>{'' if r['observed_high'] is None else r['observed_high']}</td><td>{self.lt(r['recorded_at'])}</td></tr>" for r in s)
        return f"""<section><h2>Settlements (stored separately from predictions)</h2>
<form class='inline' method='post' action='/fetch_settlements'><button>Fetch settled results from market data</button></form>
<form method='post' action='/settle'>Contract <select name='ticker'>{opts}</select>
Result <select name='result'><option>yes</option><option>no</option></select>
Source <input name='source' placeholder='e.g. Kalshi market page result' required>
Observed high <input name='observed_high' size='5'> <button>Record settlement</button></form>
<p class='muted'>A settlement can only be recorded after the market's close time, once per contract; it cannot be edited later.</p>
<table><tr><th>Contract</th><th>Result</th><th>Source</th><th>Observed</th><th>Recorded</th></tr>{srows}</table></section>"""

    def market(self, q: dict) -> str:
        app = self.app
        t = q.get("t", "")
        sigma = float(q["sigma"]) if q.get("sigma") else None
        a = app.analyze(t, sigma_f=sigma)
        c = a["contract"]
        if c is None:
            return self.page("Not found", "<p>No snapshot for that ticker.</p>")
        d, b = a["decision"], a["book"]
        probs = c.verification_problems()
        src = "".join(f"<li>{E(s.get('name', ''))} {self._link(s.get('url'))}</li>" for s in c.settlement_sources) or "<li>none listed</li>"
        links = " · ".join(x for x in [
            self._link(c.market_url, "Kalshi series page (URL pattern assumed — verify)") if c.market_url else "",
            self._link(c.contract_url, "Contract terms (series contract_url)") if c.contract_url else "",
            self._link(c.contract_terms_url, "Contract terms URL") if c.contract_terms_url else ""] if x) or "—"
        ob = "<p>No order book snapshot.</p>"
        if b:
            def side_tbl(levels, label):
                return (f"<td><b>{label}</b><table><tr><th>Price</th><th>Qty</th></tr>" +
                        "".join(f"<tr><td>{money(l.price)}</td><td>{l.qty:g}</td></tr>" for l in levels[:10]) + "</table></td>")
            ob = ("<table><tr>" + side_tbl(b.yes_bids, "YES bids") + side_tbl(b.no_bids, "NO bids") +
                  side_tbl(b.asks("yes"), "Buy YES asks (=1−NO bid)") + side_tbl(b.asks("no"), "Buy NO asks (=1−YES bid)") +
                  f"</tr></table><p class='muted'>Snapshot captured {self.lt(a['book_row']['captured_at'])} (id {a['book_row']['id']}).</p>")
        f = a["forecast_row"]
        fc = ("<p class='no'>No forecast recorded for this date (as of now). No estimate is made without one.</p>" if f is None else
              f"<p>Forecast #{f['id']}: expected high <b>{f['expected_high']:g}°{f['unit']}</b> ({f['expected_high_f']:.1f}°F), "
              f"σ {f['sigma_f']:.1f}°F{' (<i>assumed default</i>)' if f['sigma_is_assumption'] else ''}; source {E(f['source'])} "
              f"{E(f['source_detail'] or '')}; issued {self.lt(f['issued_at'])}; recorded {self.lt(f['recorded_at'])}.</p>")
        sens = "".join(f"<tr><td>{s:.1f}°F{' ←' if a['sigma_f'] and abs(s - a['sigma_f']) < 1e-9 else ''}</td><td>{pct(p)}</td></tr>"
                       for s, p in a["sensitivity"])
        sides = "".join(
            f"<tr><td>{s.side.upper()}</td><td>{pct(s.model_prob)}</td><td>{money(s.best_ask)}</td><td>{s.best_ask_qty:g}</td>"
            f"<td>{money(s.all_in_cost_per_contract)}</td><td>{'—' if s.edge is None else f'{s.edge:+.3f}'}</td><td>{s.fillable_qty}</td></tr>"
            for s in d.sides)
        p = app.cfg.paper
        ack = ("<span class='yes'>You confirmed reading these rules.</span>" if a["acked"] else
               f"<form class='inline' method='post' action='/ack'><input type='hidden' name='ticker' value='{E(t)}'>"
               "<button>I have read the rules text above and the YES interpretation matches it</button></form>")
        body = f"""
<section><h2>{E(c.title)} {'<span class="sample">SAMPLE</span>' if c.is_sample else ''}</h2>
<table>
<tr><th>Ticker</th><td>{E(c.ticker)} (event {E(c.event_ticker)}, series {E(c.series_ticker)})</td></tr>
<tr><th>YES sub-title</th><td>{E(c.yes_sub_title)}</td></tr>
<tr><th>Date (from event ticker)</th><td>{c.target_date}</td></tr>
<tr><th>Structured strike</th><td>{E(c.threshold_text())}</td></tr>
<tr><th>Interpreted YES set</th><td><b>{E(c.describe_yes_set())}</b></td></tr>
<tr><th>Status</th><td>{E(c.status)}</td></tr>
<tr><th>Open / Close / Expiration</th><td>{self.lt(c.open_time)} / <b>{self.lt(c.close_time)}</b> / {self.lt(c.expiration_time)}</td></tr>
<tr><th>Market summary prices</th><td>YES bid {money(c.yes_bid)} · YES ask {money(c.yes_ask)} · NO bid {money(c.no_bid)} · NO ask {money(c.no_ask)} · last {money(c.last_price)} · volume {c.volume} · OI {c.open_interest}</td></tr>
<tr><th>Market snapshot</th><td>captured {self.lt(a['market_row']['captured_at'])} (id {a['market_row']['id']}, source {E(a['market_row']['source'])})</td></tr>
<tr><th>Settlement source(s)</th><td><ul>{src}</ul></td></tr>
<tr><th>Links</th><td>{links}</td></tr>
<tr><th>Fee info (series)</th><td>fee_type={E(c.fee_type or '—')} multiplier={c.fee_multiplier}; simulator uses taker rate {p.taker_fee_rate}</td></tr>
</table>
<h3>Rules (verbatim from market data)</h3><pre>{E(c.rules_primary)}</pre><pre>{E(c.rules_secondary)}</pre>
<p>Automated terms checks: {'<span class="yes">pass</span>' if not probs else '<span class="no">FAIL: ' + E('; '.join(probs)) + '</span>'}</p>
<p>{ack}</p>
<p class='muted'>NWS-style climate days run midnight–midnight local <i>standard</i> time; the market's own rules above are authoritative.</p></section>

<section><h2>Order book depth</h2>{ob}</section>

<section><h2>Forecast &amp; probability estimate (not calibrated)</h2>{fc}
<p>Model P(YES) = <b>{pct(a['p_yes'])}</b> using σ = {a['sigma_f'] or '—'}°F. Method: Normal(expected high, σ) discretized to whole-degree reports, summed over the YES set.</p>
<form method='get' action='/market'><input type='hidden' name='t' value='{E(t)}'>Try σ (°F): <input name='sigma' size='4' value='{q.get('sigma', '')}'><button>Recompute (view only)</button></form>
<table style='max-width:300px'><tr><th>σ (°F)</th><th>P(YES)</th></tr>{sens}</table></section>

<section><h2>Decision — {PAPER_LABEL}</h2>
<p>Current check: <b class='{'no' if d.action == 'NO_TRADE' else 'yes'}'>{E(d.action)}</b>{f' {d.qty} contracts, limit {money(d.limit_price)}' if d.qty else ''}</p>
<ul>{''.join(f'<li>{E(r)}</li>' for r in d.reasons)}</ul>
<table><tr><th>Side</th><th>Model prob</th><th>Best ask</th><th>Displayed qty</th><th>All-in cost/contract</th><th>Edge</th><th>Fillable (after haircut, passing margin)</th></tr>{sides}</table>
<p class='muted'>All-in cost = ask + worst-case taker fee per contract + slippage ${p.slippage_per_contract}. Trade requires edge ≥ safety margin {p.safety_margin}. Fill haircut: {p.fill_fraction_of_displayed:.0%} of displayed quantity.</p>
<p class='muted'>Risk: {E('; '.join(d.risk_notes))}</p>
<form method='post' action='/decide'><input type='hidden' name='ticker' value='{E(t)}'>
<button>Record timestamped decision snapshot (uses configured σ)</button></form></section>"""
        return self.page(t, body, q.get("msg", ""), q.get("err") == "1")

    def evaluate_page(self, q: dict) -> str:
        r = evaluate(self.app.store)
        f = lambda x: "—" if x is None else f"{x:.4f}"
        cal = "".join(f"<tr><td>{b['range']}</td><td>{b['n']}</td><td>{pct(b['mean_pred'])}</td><td>{pct(b['observed'])}</td></tr>" for b in r["calibration"])
        preds = "".join(f"<tr><td>{E(p['ticker'])}</td><td>{self.lt(p['created_at'])}</td><td>{pct(p['p_yes'])}</td>"
                        f"<td>{pct(p['market_mid_yes'])}</td><td>{'YES' if p['y'] else 'NO'}</td><td>{E(p['action'])}</td></tr>" for p in r["predictions"])
        perf = self.app.performance()
        body = f"""<section><h2>Forward-test evaluation — {PAPER_LABEL}</h2>
<ul>{''.join(f'<li class="no">{E(w)}</li>' for w in r['warnings'])}</ul>
<table style='max-width:600px'><tr><th>Settled predictions scored</th><td>{r['n']}</td></tr>
<tr><th>Model Brier score (lower is better)</th><td>{f(r['model_brier'])}</td></tr>
<tr><th>Model log loss</th><td>{f(r['model_log_loss'])}</td></tr>
<tr><th>Model Brier vs market-mid Brier (same {r['n_with_market_mid']} contracts)</th><td>{f(r['model_brier_on_mid_subset'])} vs {f(r['market_mid_brier'])}</td></tr>
<tr><th>Paper realized P&L / fees</th><td>{money(perf['realized_pnl'])} / {money(perf['fees_paid'])}</td></tr></table>
<h3>Calibration bins</h3><table style='max-width:600px'><tr><th>Predicted</th><th>n</th><th>Mean predicted</th><th>Observed YES rate</th></tr>{cal}</table>
<h3>Scored predictions (last pre-close decision per contract)</h3>
<table><tr><th>Contract</th><th>Decided at</th><th>Model P(YES)</th><th>Market mid</th><th>Outcome</th><th>Action</th></tr>{preds}</table></section>"""
        return self.page("Evaluation", body)

    @staticmethod
    def _link(url, label=None) -> str:
        if not url or not str(url).startswith(("https://", "http://")):
            return ""
        return f"<a href='{E(url)}' target='_blank' rel='noopener noreferrer'>{E(label or url)}</a>"

    # ------------------------------------------------------------ actions
    def post(self, path: str, form: dict) -> str:
        app = self.app
        g = lambda k: (form.get(k) or "").strip()
        if path == "/refresh":
            r = app.refresh()
            return f"Snapshotted {r['markets']} markets, {r['orderbooks']} order books." + (f" Errors: {r['errors']}" if r["errors"] else "")
        if path == "/forecast":
            fid = app.add_forecast(target_date=date.fromisoformat(g("target_date")), expected_high=float(g("expected_high")),
                                   unit=g("unit") or "F", sigma=float(g("sigma")) if g("sigma") else None,
                                   issued_at=parse_local_input(g("issued_at"), app.tz), source=g("source"),
                                   source_detail=g("source_detail"), notes=g("notes"))
            return f"Saved forecast #{fid}."
        if path == "/nws":
            return f"Saved NWS forecast #{app.fetch_nws(date.fromisoformat(g('target_date')))}."
        if path == "/ack":
            app.ack_terms(g("ticker"))
            return "Rules acknowledgment recorded (tied to this exact rules text)."
        if path == "/decide":
            did = app.record_decision(g("ticker"))
            d = app.store.one("SELECT action FROM decisions WHERE id=?", (did,))
            return f"Recorded decision #{did}: {d['action']} ({PAPER_LABEL})."
        if path == "/execute":
            r = app.execute_paper(int(g("decision_id")))
            return (f"{PAPER_LABEL} order #{r['order_id']}: {r['status']}, {r['qty']} contracts, cost {money(r['cost'])} "
                    f"incl. fees {money(r['fees'])}. {' '.join(r['notes'])}")
        if path == "/settle":
            oh = float(g("observed_high")) if g("observed_high") else None
            app.record_settlement(g("ticker"), g("result"), g("source"), oh)
            return "Settlement recorded."
        if path == "/fetch_settlements":
            got = app.fetch_settlements()
            return f"Recorded {len(got)} settlements: {', '.join(got) or 'none settled yet'}."
        raise ValueError("unknown action")


def make_handler(dash: Dashboard, allowed_hosts: set[str]):
    class Handler(BaseHTTPRequestHandler):
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in allowed_hosts

        def _send(self, code: int, body: str, ctype="text/html; charset=utf-8", headers=None):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, "forbidden host")
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                if u.path == "/":
                    return self._send(200, dash.index(q))
                if u.path == "/market":
                    return self._send(200, dash.market(q))
                if u.path == "/evaluate":
                    return self._send(200, dash.evaluate_page(q))
                return self._send(404, "not found")
            except Exception as e:
                traceback.print_exc()
                return self._send(500, dash.page("Error", f"<pre>{E(repr(e))}</pre>"))

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, "forbidden host")
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlparse(origin).hostname not in allowed_hosts:
                return self._send(403, "cross-origin request refused")
            n = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8")).items()}
            back = self.headers.get("Referer") or "/"
            bu = urllib.parse.urlparse(back)
            base = bu.path if bu.path in ("/", "/market", "/evaluate") else "/"
            keep = {k: v for k, v in urllib.parse.parse_qs(bu.query).items() if k in ("t",)}
            try:
                msg, err = dash.post(urllib.parse.urlparse(self.path).path, form), "0"
            except Exception as e:
                msg, err = f"Error: {e}", "1"
            qs = urllib.parse.urlencode({**{k: v[0] for k, v in keep.items()}, "msg": msg, "err": err})
            self._send(303, "", headers={"Location": f"{base}?{qs}"})

        def log_message(self, fmt, *args):
            pass

    return Handler


def serve(app: App, host: str, port: int):
    httpd = HTTPServer((host, port), make_handler(Dashboard(app), {"127.0.0.1", "localhost", "::1"}))
    print(f"{PAPER_LABEL} dashboard: http://{host}:{port}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
