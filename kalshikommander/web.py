"""Local dashboard (stdlib http.server). Binds to localhost only. Every trade/metric is PAPER.

Pages: Today (all cities), Contract detail, Cities, Paper account, Results, How it works.
"""

from __future__ import annotations

import html
import json
import traceback
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

from . import PAPER_LABEL
from .cities import US_TIMEZONES, City
from .evaluation import MIN_MEANINGFUL_N, evaluate
from .service import App
from .timeutil import parse_local_input, parse_ts

E = html.escape

CSS = """
:root{
  --bg:#f4f4f1;--surface:#fcfcfb;--surface-2:#f0efec;--border:#dddcd6;
  --ink:#0b0b0b;--ink-2:#52514e;--ink-3:#77766f;
  --accent:#2a78d6;--accent-ink:#1c5cab;--track:#e4e3de;
  --good:#0ca30c;--good-ink:#006300;--good-bg:#e7f6e7;
  --warn:#fab219;--warn-ink:#7a5200;--warn-bg:#fff4db;
  --bad:#d03b3b;--bad-ink:#a02828;--bad-bg:#fdeaea;
  --neutral-bg:#ecebe7;--paper:#ffcc00;--sample:#d9480f;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#121211;--surface:#1a1a19;--surface-2:#242422;--border:#383835;
    --ink:#ffffff;--ink-2:#c3c2b7;--ink-3:#9a998f;
    --accent:#3987e5;--accent-ink:#86b6ef;--track:#383835;
    --good-ink:#6fd46f;--good-bg:#173017;--warn-ink:#fab219;--warn-bg:#3a2d0c;
    --bad-ink:#f08a8a;--bad-bg:#3a1a1a;--neutral-bg:#2c2c2a;
  }
}
:root[data-theme="dark"]{
  --bg:#121211;--surface:#1a1a19;--surface-2:#242422;--border:#383835;
  --ink:#ffffff;--ink-2:#c3c2b7;--ink-3:#9a998f;
  --accent:#3987e5;--accent-ink:#86b6ef;--track:#383835;
  --good-ink:#6fd46f;--good-bg:#173017;--warn-ink:#fab219;--warn-bg:#3a2d0c;
  --bad-ink:#f08a8a;--bad-bg:#3a1a1a;--neutral-bg:#2c2c2a;
}
*{box-sizing:border-box}
body{font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:0;background:var(--bg);color:var(--ink)}
a{color:var(--accent-ink)}
header{background:#1b1f24;color:#fff;padding:10px 16px}
header .row{max-width:1180px;margin:auto;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header nav a{color:#dbe8fb;text-decoration:none;padding:6px 10px;border-radius:6px;white-space:nowrap;display:inline-block}
header nav a.on,header nav a:hover{background:#2f3640;color:#fff}
.brand{font-weight:700;font-size:1.05rem;margin-right:6px}
.badge{font-weight:700;font-size:.78rem;padding:2px 8px;border-radius:4px;letter-spacing:.02em}
.badge.paper{background:var(--paper);color:#000}.badge.sample{background:var(--sample);color:#fff}
main{max-width:1180px;margin:auto;padding:20px 16px 48px}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.2rem;margin:0 0 8px}h3{font-size:1rem;margin:18px 0 6px}
.sub{color:var(--ink-2);margin:0 0 16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin-bottom:18px}
.muted{color:var(--ink-3);font-size:.88rem}
.small{font-size:.88rem}
.flash{padding:10px 14px;border-radius:8px;margin-bottom:16px;background:var(--good-bg);border:1px solid var(--good)}
.flash.err{background:var(--bad-bg);border-color:var(--bad)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:0;padding:0;list-style:none;counter-reset:s}
.steps li{background:var(--surface-2);border-radius:8px;padding:10px 12px;font-size:.92rem;counter-increment:s}
.steps li::before{content:counter(s);display:inline-block;width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;text-align:center;font-weight:700;font-size:.8rem;line-height:22px;margin-right:6px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{background:var(--surface-2);border-radius:8px;padding:10px 12px}
.kpi .l{color:var(--ink-2);font-size:.85rem}.kpi .v{font-size:1.35rem;font-weight:650;font-variant-numeric:tabular-nums}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.chips a{display:inline-block;padding:4px 12px;border-radius:999px;border:1px solid var(--border);text-decoration:none;color:var(--ink);margin:0 4px 4px 0;background:var(--surface)}
.chips a.on{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.city-h{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px}
.day{border-top:1px solid var(--border);margin-top:14px;padding-top:12px}
.fc{background:var(--surface-2);border-radius:8px;padding:10px 12px;margin:6px 0 10px}
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.93rem}
th,td{padding:8px 8px;text-align:left;vertical-align:middle;border-bottom:1px solid var(--border)}
th{font-weight:600;color:var(--ink-2);font-size:.82rem;background:transparent}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
.pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-weight:600;font-size:.85rem;white-space:nowrap}
.pill .i{display:inline-block;width:18px;height:18px;border-radius:50%;text-align:center;line-height:18px;font-size:.75rem;color:#fff}
.pill.good{background:var(--good-bg);color:var(--good-ink)}.pill.good .i{background:var(--good)}
.pill.warn{background:var(--warn-bg);color:var(--warn-ink)}.pill.warn .i{background:var(--warn);color:#000}
.pill.bad{background:var(--bad-bg);color:var(--bad-ink)}.pill.bad .i{background:var(--bad)}
.pill.neutral{background:var(--neutral-bg);color:var(--ink-2)}.pill.neutral .i{background:var(--ink-3)}
.why{color:var(--ink-2);font-size:.85rem;margin-top:2px}
.bar{position:relative;width:150px;height:18px}
.bar .t{position:absolute;left:0;right:0;top:8px;height:3px;border-radius:2px;background:var(--track)}
.bar .p{position:absolute;top:1px;width:3px;height:16px;margin-left:-1px;border-radius:1px;background:var(--ink-2)}
.bar .m{position:absolute;top:3px;width:12px;height:12px;margin-left:-6px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 2px var(--surface)}
.legend{display:flex;gap:14px;align-items:center;font-size:.82rem;color:var(--ink-2);flex-wrap:wrap}
.legend .sw-m{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--accent);margin-right:4px}
.legend .sw-p{display:inline-block;width:3px;height:12px;background:var(--ink-2);margin-right:4px;vertical-align:-1px}
form.inline{display:inline}
input,select,button{font:inherit;font-size:.92rem;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--ink)}
input[type=number]{width:100px}
button{cursor:pointer;background:var(--surface-2)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
button.link{background:none;border:none;color:var(--accent-ink);text-decoration:underline;padding:0}
label{font-size:.85rem;color:var(--ink-2);display:inline-flex;flex-direction:column;gap:2px;margin:0 8px 8px 0}
.formrow{display:flex;flex-wrap:wrap;align-items:flex-end}
pre{white-space:pre-wrap;background:var(--surface-2);padding:12px;border-radius:8px;font-size:.9rem;margin:6px 0}
details summary{cursor:pointer;color:var(--accent-ink);margin:8px 0}
.receipt td{padding:4px 8px}.receipt tr.total td{border-top:2px solid var(--ink-3);font-weight:650}
.big{font-size:2.2rem;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.box{background:var(--surface-2);border-radius:8px;padding:12px 14px}
.verdict{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap}
ul.plain{margin:6px 0;padding-left:20px}
.hbar{display:flex;align-items:center;gap:8px}
.hbar .f{height:12px;border-radius:0 4px 4px 0;background:var(--accent)}
#eqtip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:4px 8px;font-size:.82rem;display:none;white-space:nowrap}
.nowrap{white-space:nowrap}
@media (max-width:720px){
  table.ladder thead{display:none}
  table.ladder,table.ladder tbody,table.ladder tr,table.ladder td{display:block;width:100%}
  table.ladder tr{border:1px solid var(--border);border-radius:8px;padding:8px 10px;margin-bottom:10px}
  table.ladder td{border:none;padding:3px 0;text-align:left}
  table.ladder td[data-l]::before{content:attr(data-l);display:inline-block;min-width:170px;color:var(--ink-2);font-size:.82rem}
  table.ladder td.num div{display:inline;margin-left:6px}
  h1{font-size:1.3rem}
}
footer{max-width:1180px;margin:auto;padding:0 16px 30px;color:var(--ink-3);font-size:.82rem}
"""

EQUITY_JS = """
(function(){
  var svg=document.getElementById('eq'); if(!svg) return;
  var pts=JSON.parse(svg.getAttribute('data-pts')); var tip=document.getElementById('eqtip');
  var line=document.getElementById('eqx'), dot=document.getElementById('eqd'), wrap=svg.parentNode;
  svg.addEventListener('mousemove',function(ev){
    var r=svg.getBoundingClientRect(), vb=svg.viewBox.baseVal, x=(ev.clientX-r.left)*vb.width/r.width;
    var best=0; for(var i=1;i<pts.length;i++){ if(Math.abs(pts[i].x-x)<Math.abs(pts[best].x-x)) best=i; }
    var p=pts[best]; line.setAttribute('x1',p.x); line.setAttribute('x2',p.x); line.style.display='';
    dot.setAttribute('cx',p.x); dot.setAttribute('cy',p.y); dot.style.display='';
    tip.innerHTML='<b>'+p.v+'</b><br>'+p.t+'<br>'+p.k; tip.style.display='block';
    var px=p.x*r.width/vb.width; tip.style.left=Math.min(px+12, r.width-180)+'px'; tip.style.top='8px';
  });
  svg.addEventListener('mouseleave',function(){tip.style.display='none';line.style.display='none';dot.style.display='none';});
})();
"""

# reason code -> (pill kind, headline, what to do). Order = priority for the one-line verdict.
REASONS = {
    "no_market": ("warn", "No price data yet", "Click “Refresh prices”."),
    "closed": ("neutral", "Trading has closed", "Wait for the result, then record it on the Paper account page."),
    "not_open": ("neutral", "Market isn't open", ""),
    "no_book": ("warn", "No prices yet", "Click “Refresh prices”."),
    "book_future": ("bad", "Price data is timestamped in the future", "Check your computer's clock."),
    "quote_stale": ("warn", "Prices are out of date", "Click “Refresh prices” to get current ones."),
    "no_forecast": ("warn", "Needs your forecast", "Enter a forecast for this city and date."),
    "forecast_future": ("bad", "Forecast is timestamped after now", "Check the issue time you entered."),
    "forecast_stale": ("warn", "Forecast is too old", "Enter a newer forecast."),
    "forecast_date": ("warn", "Forecast is for a different day", "Enter a forecast for this date."),
    "terms_unverified": ("bad", "Rules couldn't be checked", "Open details to see which check failed. The app won't trade it."),
    "no_ack": ("warn", "Read the rules first", "Open details and confirm you've read the official rules."),
    "snapshot_used": ("neutral", "Already paper-traded at these prices", "Refresh prices before another paper trade."),
    "book_empty": ("neutral", "Nobody is selling right now", ""),
    "no_ask": ("neutral", "Nobody is selling right now", ""),
    "small_edge": ("neutral", "No trade — price isn't cheap enough", ""),
    "thin": ("neutral", "No trade — too few contracts for sale", ""),
    "risk": ("neutral", "No trade — paper risk limit reached", "See the limits in config.toml."),
    "risk_small": ("neutral", "No trade — paper risk limit reached", "See the limits in config.toml."),
}
PRIORITY = list(REASONS)
CHOOSE_OPT = "<option value=''>choose…</option>"


def money(x) -> str:
    if x is None:
        return "—"
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def cents(x) -> str:
    if x is None:
        return "—"
    c = x * 100
    return f"{c:.0f}¢" if abs(c - round(c)) < 1e-6 else f"{c:.1f}¢"


def pct(x) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def pill(kind: str, text: str) -> str:
    icon = {"good": "✓", "warn": "!", "bad": "✕", "neutral": "–"}[kind]
    return f"<span class='pill {kind}'><span class='i' aria-hidden='true'>{icon}</span>{E(text)}</span>"


def verdict(dec, sigma_note: bool = False) -> tuple[str, str, str]:
    """(pill kind, headline, one-line explanation) for a Decision."""
    if dec.action != "NO_TRADE":
        s = next((x for x in dec.sides if x.side == dec.side), None)
        side = dec.side.upper()
        why = (f"Model gives {side} a {pct(s.model_prob)} chance; buying costs about {cents(s.all_in_cost_per_contract)} "
               f"all-in. Up to {dec.qty} paper contracts." if s else "")
        return "good", f"Paper-buy {side}", why
    codes = dec.codes or []
    top = min(codes, key=lambda c: PRIORITY.index(c) if c in PRIORITY else 99) if codes else None
    if top is None:
        return "neutral", "No trade", "; ".join(dec.reasons)
    kind, head, todo = REASONS.get(top, ("neutral", "No trade", ""))
    if top == "small_edge":
        best = max((s for s in dec.sides if s.edge is not None), key=lambda s: s.edge, default=None)
        if best:
            todo = (f"Best is {best.side.upper()}: model {pct(best.model_prob)} vs cost {cents(best.all_in_cost_per_contract)} "
                    f"— the app wants a bigger gap before trading.")
    return kind, head, todo


_RISK_NAMES = {"cash (no leverage)": "your virtual cash", "max_stake_per_market": "the per-contract limit",
               "max_total_exposure": "the total-exposure limit", "max_daily_loss (worst case)": "the daily-loss limit"}


def risk_room(notes: list[str]) -> str:
    """'X leaves $Y' notes -> one plain sentence naming the tightest limit."""
    import re
    room = []
    for n in notes:
        m = re.match(r"(.+) leaves \$([0-9.,]+)$", n)
        if m:
            room.append((float(m.group(2).replace(",", "")), _RISK_NAMES.get(m.group(1), m.group(1))))
    if not room:
        return ""
    amt, name = min(room)
    return f"You can put up to {money(amt)} more into this contract right now (the tightest cap is {name})."


class Dashboard:
    def __init__(self, app: App):
        self.app = app

    # ------------------------------------------------------------ helpers
    def lt(self, ts, tz: str | None = None, fmt: str = "%b %d, %I:%M %p %Z") -> str:
        if ts is None:
            return "—"
        dt = parse_ts(ts) if isinstance(ts, str) else ts
        return dt.astimezone(ZoneInfo(tz or self.app.tz)).strftime(fmt).replace(" 0", " ")

    def ago(self, ts) -> str:
        if ts is None:
            return "never"
        s = (self.app.clock() - (parse_ts(ts) if isinstance(ts, str) else ts)).total_seconds()
        if s < 90:
            return f"{s:.0f} seconds ago"
        if s < 5400:
            return f"{s / 60:.0f} minutes ago"
        if s < 172800:
            return f"{s / 3600:.1f} hours ago"
        return f"{s / 86400:.0f} days ago"

    @staticmethod
    def day_name(d: date, today: date) -> str:
        rel = "Today" if d == today else "Tomorrow" if (d - today).days == 1 else ""
        return f"{rel + ' · ' if rel else ''}{d.strftime('%a %b')} {d.day}"

    def page(self, title: str, body: str, active: str = "", flash: str = "", err: bool = False) -> str:
        src = self.app.source
        tag = ("<span class='badge sample'>SAMPLE DATA — FICTIONAL</span>" if src.is_sample else "")
        nav = "".join(f"<a href='{h}' class='{'on' if k == active else ''}'>{n}</a>" for k, h, n in [
            ("today", "/", "Today"), ("cities", "/cities", "Cities"), ("ledger", "/ledger", "Paper account"),
            ("results", "/evaluate", "Results"), ("help", "/help", "How it works")])
        fl = f"<div class='flash{' err' if err else ''}' role='status'>{E(flash)}</div>" if flash else ""
        return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
                f"<title>{E(title)} · KalshiKommander</title><style>{CSS}</style></head><body>"
                f"<header><div class='row'><span class='brand'>KalshiKommander</span>"
                f"<span class='badge paper'>{PAPER_LABEL}</span>{tag}<nav>{nav}</nav></div></header>"
                f"<main>{fl}{body}</main><footer>Research tool. Every trade here is simulated with virtual money — "
                f"no real orders are ever placed. Times shown in your timezone ({E(self.app.tz)}) unless marked as city time."
                f"</footer></body></html>")

    def _forecast_form(self, city: City, d: date, compact: bool = True) -> str:
        return (f"<form method='post' action='/forecast' class='formrow'>"
                f"<input type='hidden' name='series' value='{E(city.series_ticker)}'>"
                f"<input type='hidden' name='target_date' value='{d.isoformat()}'>"
                f"<label>Expected high<span><input type='number' step='0.1' name='expected_high' required> "
                f"<select name='unit'><option>F</option><option>C</option></select></span></label>"
                f"<label>Give or take (±)<input type='number' step='0.1' min='0.1' name='sigma' "
                f"placeholder='default {self.app.cfg.model.default_sigma_f:g}'></label>"
                f"<label>Where it came from<input name='source' required size='22' placeholder='e.g. NWS forecast page'></label>"
                f"<label>When it was issued (your time)<input type='datetime-local' name='issued_at' required></label>"
                + ("" if compact else "<label>Link / detail<input name='source_detail' size='30'></label>")
                + "<label>&nbsp;<button class='primary'>Save forecast</button></label></form>")

    def _bar(self, p_yes, yes_cost) -> str:
        parts = ["<div class='bar' role='img' aria-label='model "
                 f"{pct(p_yes)}, YES cost {cents(yes_cost)}'><div class='t'></div>"]
        if yes_cost is not None:
            parts.append(f"<div class='p' style='left:{yes_cost * 100:.1f}%' title='Cost to buy YES: {cents(yes_cost)}'></div>")
        if p_yes is not None:
            parts.append(f"<div class='m' style='left:{p_yes * 100:.1f}%' title='Model chance of YES: {pct(p_yes)}'></div>")
        return "".join(parts) + "</div>"

    # ------------------------------------------------------------ Today
    def index(self, q: dict) -> str:
        app = self.app
        cities = app.cities()
        sel = q.get("city", "")
        perf = app.performance()
        last = app.store.one("SELECT MAX(captured_at) t FROM orderbook_snapshots")["t"]
        n_fc = app.store.one("SELECT COUNT(*) n FROM forecasts")["n"]
        steps = ("<details class='card' " + ("open" if n_fc == 0 else "") + "><summary><b>How to use this page</b></summary>"
                 "<ol class='steps'><li><b>Refresh prices</b> to take a timestamped snapshot of every contract.</li>"
                 "<li><b>Enter your forecast</b> for each city and day, with where it came from.</li>"
                 "<li><b>Open a contract</b> and read its official rules once, then confirm.</li>"
                 "<li><b>Record a decision.</b> The app says paper-buy or no trade, and why.</li>"
                 "<li><b>After the day ends</b>, record the result on the Paper account page.</li></ol></details>")
        kp = (f"<div class='kpis'><div class='kpi'><div class='l'>Virtual cash</div><div class='v'>{money(perf['cash'])}</div></div>"
              f"<div class='kpi'><div class='l'>Open paper positions</div><div class='v'>{perf['open_positions']}</div></div>"
              f"<div class='kpi'><div class='l'>Realized paper P&amp;L</div><div class='v'>{money(perf['realized_pnl'])}</div></div>"
              f"<div class='kpi'><div class='l'>Prices last refreshed</div><div class='v' style='font-size:1rem'>{self.ago(last)}</div></div></div>")
        if not cities:
            return self.page("Today", f"<h1>Today</h1>{steps}<div class='card'><h2>No cities yet</h2>"
                             "<p>Go to <a href='/cities'>Cities</a> and add one or more daily-high-temperature markets.</p></div>",
                             "today", q.get("msg", ""), q.get("err") == "1")
        chips = "<div class='chips'>" + "".join(
            f"<a href='/?city={urllib.parse.quote(k)}' class='{'on' if sel == k else ''}'>{E(n)}</a>"
            for k, n in [("", "All cities")] + [(c.series_ticker, c.name) for c in cities]) + "</div>"
        toolbar = ("<div class='toolbar'><form class='inline' method='post' action='/refresh'>"
                   f"<button class='primary'>Refresh prices{' for all cities' if len(cities) > 1 else ''}</button></form>"
                   f"<span class='muted'>Each refresh saves a timestamped copy of prices and order books. "
                   f"Prices older than {app.cfg.paper.max_quote_age_seconds // 60} minutes are treated as stale.</span></div>")
        cards = "".join(self._city_card(c) for c in cities if not sel or c.series_ticker == sel)
        body = (f"<h1>Today’s weather contracts</h1><p class='sub'>Daily high-temperature markets for "
                f"{len(cities)} {'city' if len(cities) == 1 else 'cities'}. Model estimates are not calibrated.</p>"
                f"{steps}<div class='card'>{kp}</div>{toolbar}{chips}{cards}")
        return self.page("Today", body, "today", q.get("msg", ""), q.get("err") == "1")

    def _city_card(self, city: City) -> str:
        app = self.app
        now = app.clock()
        dates = app.city_dates(city)
        tickers = app.todays_tickers(city.series_ticker)
        by_date: dict[date, list] = {d: [] for d in dates}
        for t in tickers:
            a = app.analyze(t)
            if a["contract"] and a["contract"].target_date in by_date:
                by_date[a["contract"].target_date].append(a)
        head = (f"<div class='city-h'><h2>{E(city.name)}</h2><span class='muted'>City time: "
                f"{self.lt(now, city.timezone, '%a %I:%M %p %Z')} · series {E(city.series_ticker)} · "
                f"<form class='inline' method='post' action='/refresh'><input type='hidden' name='series' "
                f"value='{E(city.series_ticker)}'><button class='link'>refresh this city</button></form></span></div>")
        days = []
        for d in dates:
            f = app.forecast_at(city.series_ticker, d, now)
            nws = ""
            if app.cfg.weather.provider == "nws":
                nws = (f"<form method='post' action='/nws' class='inline'><input type='hidden' name='series' value='{E(city.series_ticker)}'>"
                       f"<input type='hidden' name='target_date' value='{d.isoformat()}'>"
                       f"<button>Fetch NWS forecast</button></form> <span class='muted'>optional helper, US only</span>")
            if f is None:
                fc = (f"<div class='fc'>{pill('warn', 'No forecast yet')} <span class='small'>Enter one to get estimates "
                      f"for this day. The app never makes one up.</span>{self._forecast_form(city, d)}{nws}</div>")
            else:
                assumed = " (default guess)" if f["sigma_is_assumption"] else ""
                fc = (f"<div class='fc'><b>Your forecast:</b> high of {f['expected_high']:g}°{E(f['unit'])} "
                      f"± {f['sigma_f']:.1f}°F{assumed} · from {E(f['source'])}, issued {self.lt(f['issued_at'])} "
                      f"<details><summary class='small'>Enter a newer forecast</summary>{self._forecast_form(city, d)}{nws}</details></div>")
            rows = []
            for a in by_date[d]:
                c, b, dec = a["contract"], a["book"], a["decision"]
                ya, na = (b.best_ask("yes") if b else None), (b.best_ask("no") if b else None)
                kind, headline, why = verdict(dec)
                rows.append(
                    f"<tr><td class='nowrap'><b>{E(c.outcome_label())}</b></td>"
                    f"<td class='num' data-l='YES costs'>{cents(ya.price) if ya else '—'}<div class='muted nowrap'>{format(ya.qty, 'g') + ' for sale' if ya else 'none for sale'}</div></td>"
                    f"<td class='num' data-l='NO costs'>{cents(na.price) if na else '—'}<div class='muted nowrap'>{format(na.qty, 'g') + ' for sale' if na else 'none for sale'}</div></td>"
                    f"<td class='num' data-l='Model’s chance of YES'><b>{pct(a['p_yes'])}</b></td>"
                    f"<td>{self._bar(a['p_yes'], ya.price if ya else None)}</td>"
                    f"<td>{pill(kind, headline)}<div class='why'>{E(why)}</div></td>"
                    f"<td class='nowrap'><a href='/market?t={urllib.parse.quote(c.ticker)}'>Details →</a></td></tr>")
            table = ("<div class='tw'><table class='ladder'><thead><tr><th>If the high is…</th><th class='num'>YES costs</th>"
                     "<th class='num'>NO costs</th><th class='num'>Model’s chance of YES</th>"
                     "<th><div class='legend'><span><span class='sw-m'></span>model</span><span><span class='sw-p'></span>YES cost</span></div></th>"
                     "<th>What the app says</th><th></th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
                     ) if rows else "<p class='muted'>No contracts saved for this day yet — refresh prices.</p>"
            record = ""
            if rows:
                record = (f"<form method='post' action='/decide_city' style='margin-top:8px'>"
                          f"<input type='hidden' name='series' value='{E(city.series_ticker)}'>"
                          f"<input type='hidden' name='date' value='{d.isoformat()}'>"
                          f"<button>Record decisions for this day</button> <span class='muted'>Saves a timestamped snapshot "
                          f"of each verdict so it can be scored later.</span></form>")
            days.append(f"<div class='day'><h3>{self.day_name(d, dates[0])}</h3>{fc}{table}{record}</div>")
        return f"<section class='card'>{head}{''.join(days)}</section>"

    # ------------------------------------------------------------ Contract detail
    def market(self, q: dict) -> str:
        app = self.app
        t = q.get("t", "")
        try:
            sigma = float(q["sigma"]) if q.get("sigma") else None
        except ValueError:
            sigma = None
        a = app.analyze(t, sigma_f=sigma)
        c = a["contract"]
        if c is None:
            return self.page("Not found", "<p>No saved data for that contract.</p>")
        city = app.city(c.series_ticker)
        ctz = city.timezone if city else app.tz
        d, b, p = a["decision"], a["book"], app.cfg.paper
        kind, headline, why = verdict(d)
        cname = city.name if city else c.series_ticker
        dstr = f"{c.target_date.strftime('%a %b')} {c.target_date.day}" if c.target_date else "?"
        # --- verdict
        all_reasons = "".join(f"<li>{E(REASONS.get(code, ('', r, ''))[1] if code in REASONS else r)}"
                              f"<div class='muted'>{E(r)}</div></li>"
                              for code, r in zip(d.codes, d.reasons) if code != "trade")
        verdict_box = (f"<div class='card'><div class='verdict'><div>{pill(kind, headline)}</div><div>{E(why)}"
                       + (f"<p class='small' style='margin:8px 0 0'>All reasons:</p><ul class='plain small'>{all_reasons}</ul>"
                          if len(set(d.codes) - {"trade"}) > 1 else "") + "</div></div>"
                       "<p class='muted'>This is a live check using the latest saved data. "
                       "“Record decision” saves it permanently with a timestamp.</p>"
                       f"<form method='post' action='/decide' class='inline'><input type='hidden' name='ticker' value='{E(t)}'>"
                       f"<button class='primary'>Record decision</button></form> {self._pending_exec(t)}</div>")
        # --- rules
        probs = c.verification_problems()
        checks = ("<p>" + pill("good", "Automatic rule checks passed") + "</p>" if not probs else
                  "<p>" + pill("bad", "Automatic rule checks failed") + "</p><ul class='plain small'>" +
                  "".join(f"<li>{E(x)}</li>" for x in probs) + "</ul>")
        src = ", ".join(E(s.get("name", "")) + (" " + self._link(s.get("url"), "(link)") if s.get("url") else "")
                        for s in c.settlement_sources) or "none listed"
        ack = (pill("good", "You confirmed reading these rules") if a["acked"] else
               f"<form method='post' action='/ack'><input type='hidden' name='ticker' value='{E(t)}'>"
               "<button class='primary'>I’ve read the official rules and the summary above matches them</button></form>")
        links = " · ".join(x for x in [
            self._link(c.market_url, "Open on Kalshi (URL pattern assumed)") if c.market_url else "",
            self._link(c.contract_url, "Contract terms PDF") if c.contract_url else "",
            self._link(c.contract_terms_url, "Contract terms") if c.contract_terms_url else ""] if x)
        rules = (f"<div class='card'><h2>1 · Official rules — read these</h2>"
                 f"<p class='small'>The app's summary: pays $1 per YES contract if the reported high is "
                 f"<b>{E(c.describe_yes_set().replace('reported high ', ''))}</b>. Only the official text below counts.</p>"
                 f"<pre>{E(c.rules_primary) or '(missing)'}</pre>"
                 + (f"<pre>{E(c.rules_secondary)}</pre>" if c.rules_secondary else "")
                 + f"<p class='small'><b>Settlement source:</b> {src}<br><b>Trading closes:</b> {self.lt(c.close_time, ctz)} (city time)"
                 + (f"<br>{links}" if links else "") + f"</p>{checks}{ack}</div>")
        # --- prices
        def side_box(side):
            best = b.best_ask(side) if b else None
            label = "YES" if side == "yes" else "NO"
            if not best:
                return f"<div class='box'><b>Buy {label}</b><div class='big'>—</div><div class='muted'>Nobody is selling right now.</div></div>"
            meaning = (f"the market prices YES at about {pct(best.price)}" if side == "yes"
                       else f"the market prices NO at about {pct(best.price)}")
            return (f"<div class='box'><b>Buy {label}</b><div class='big'>{cents(best.price)}</div>"
                    f"<div class='small'>{best.qty:g} contracts for sale at this price. Each pays $1 if {label} wins, "
                    f"so {meaning}.</div></div>")
        depth = ""
        if b:
            def lv(levels):
                return "".join(f"<tr><td class='num'>{cents(x.price)}</td><td class='num'>{x.qty:g}</td></tr>" for x in levels[:8]) or "<tr><td colspan=2 class='muted'>none</td></tr>"
            depth = ("<details><summary>Full order book</summary><div class='two'>"
                     f"<div><b>Buy YES</b> (from people bidding on NO)<table><tr><th class='num'>Price</th><th class='num'>For sale</th></tr>{lv(b.asks('yes'))}</table></div>"
                     f"<div><b>Buy NO</b> (from people bidding on YES)<table><tr><th class='num'>Price</th><th class='num'>For sale</th></tr>{lv(b.asks('no'))}</table></div>"
                     "</div><p class='muted'>Kalshi lists bids only. The price to buy YES is $1 minus the best NO bid, and vice versa. "
                     "The app never uses the midpoint or last trade as a buy price.</p></details>")
        stamp = f"Saved {self.ago(a['book_row']['captured_at'])} ({self.lt(a['book_row']['captured_at'])})." if a["book_row"] else "No prices saved yet."
        prices = (f"<div class='card'><h2>2 · Prices you could actually pay</h2><div class='two'>{side_box('yes')}{side_box('no')}</div>"
                  f"<p class='muted'>{stamp}</p>{depth}</div>")
        # --- forecast & model
        f = a["forecast_row"]
        if f is None:
            fc = (f"<p>{pill('warn', 'No forecast for this day')} The model needs your forecast — nothing is made up.</p>"
                  + (self._forecast_form(city, c.target_date, compact=False) if city and c.target_date else ""))
        else:
            sens_rows = "".join(
                f"<tr><td>± {s:g}°F{' <b>(used)</b>' if a['sigma_f'] and abs(s - a['sigma_f']) < 1e-9 else ''}</td>"
                f"<td><div class='hbar'><div class='f' style='width:{max(2, pv * 160):.0f}px'></div>{pct(pv)}</div></td></tr>"
                for s, pv in a["sensitivity"])
            fc = (f"<div class='two'><div><div class='muted'>Model’s chance of YES</div><div class='big'>{pct(a['p_yes'])}</div>"
                  f"<p class='small'>Your forecast: high of <b>{f['expected_high']:g}°{E(f['unit'])}</b> "
                  f"give or take <b>{a['sigma_f']:g}°F</b>{' (default guess)' if f['sigma_is_assumption'] and not sigma else ''}. "
                  f"Source: {E(f['source'])} {E(f['source_detail'] or '')}, issued {self.lt(f['issued_at'])}.</p>"
                  f"<form method='get' action='/market' class='formrow'><input type='hidden' name='t' value='{E(t)}'>"
                  f"<label>Try a different ± (°F)<input type='number' step='0.1' min='0.1' name='sigma' value='{E(q.get('sigma', ''))}'></label>"
                  f"<label>&nbsp;<button>Recalculate (view only)</button></label></form></div>"
                  f"<div><div class='muted'>How much the “±” assumption matters</div><table>{sens_rows}</table></div></div>"
                  "<p class='muted'>Method: assumes the real high lands near your forecast with a bell-curve spread of ±, rounded "
                  "to whole degrees. The ± is your assumption and hasn't been checked against real outcomes.</p>")
        model = f"<div class='card'><h2>3 · Your forecast and the model’s estimate</h2>{fc}</div>"
        # --- math
        receipts = []
        for s in d.sides:
            if s.best_ask is None:
                continue
            fee = round((s.all_in_cost_per_contract or 0) - s.best_ask - p.slippage_per_contract, 4)
            ok = s.edge is not None and s.edge >= p.safety_margin
            receipts.append(
                f"<div class='box'><b>Buying {s.side.upper()}</b><table class='receipt'>"
                f"<tr><td>Price</td><td class='num'>{cents(s.best_ask)}</td></tr>"
                f"<tr><td>+ Kalshi fee (worst case)</td><td class='num'>{cents(fee)}</td></tr>"
                f"<tr><td>+ Assumed slippage</td><td class='num'>{cents(p.slippage_per_contract)}</td></tr>"
                f"<tr class='total'><td>= All-in cost</td><td class='num'>{cents(s.all_in_cost_per_contract)}</td></tr>"
                f"<tr><td>Model’s chance of {s.side.upper()}</td><td class='num'>{pct(s.model_prob)}</td></tr>"
                f"<tr class='total'><td>Edge (chance − cost)</td><td class='num'>{(s.edge or 0) * 100:+.1f} pts</td></tr>"
                f"</table><p class='small'>{pill('good', 'Clears the bar') if ok else pill('neutral', 'Below the bar')} "
                f"needs +{p.safety_margin * 100:.0f} pts or more.</p></div>")
        math = (f"<div class='card'><h2>4 · The math behind the verdict</h2><div class='two'>{''.join(receipts) or '<p class=muted>No prices to compare.</p>'}</div>"
                f"<p class='muted'>Paper fills only use {p.fill_fraction_of_displayed:.0%} of the contracts shown for sale. "
                f"{E(risk_room(d.risk_notes))}</p></div>")
        tech = (f"<details class='card'><summary><b>Technical details</b></summary><table class='small'>"
                f"<tr><th>Contract</th><td>{E(c.ticker)}</td></tr><tr><th>Event / series</th><td>{E(c.event_ticker)} / {E(c.series_ticker)}</td></tr>"
                f"<tr><th>Title (not used for rules)</th><td>{E(c.title)}</td></tr><tr><th>Sub-title</th><td>{E(c.yes_sub_title)}</td></tr>"
                f"<tr><th>Structured strike</th><td>{E(c.threshold_text())}</td></tr><tr><th>Status</th><td>{E(c.status)}</td></tr>"
                f"<tr><th>Open / close / expiration</th><td>{self.lt(c.open_time, ctz)} / {self.lt(c.close_time, ctz)} / {self.lt(c.expiration_time, ctz)}</td></tr>"
                f"<tr><th>Summary prices</th><td>YES bid {cents(c.yes_bid)} · YES ask {cents(c.yes_ask)} · NO bid {cents(c.no_bid)} · NO ask {cents(c.no_ask)} · last {cents(c.last_price)} · volume {c.volume} · open interest {c.open_interest}</td></tr>"
                f"<tr><th>Market snapshot</th><td>#{a['market_row']['id']} saved {self.lt(a['market_row']['captured_at'])} from {E(a['market_row']['source'])}</td></tr>"
                f"<tr><th>Fee info</th><td>series fee_type={E(c.fee_type or '—')}, multiplier={c.fee_multiplier}; simulator taker rate {p.taker_fee_rate}</td></tr>"
                f"<tr><th>Climate day note</th><td>NWS-style climate days run midnight to midnight local <i>standard</i> time. The rules above are what count.</td></tr>"
                f"<tr><th>Decision engine reasons</th><td>{E('; '.join(d.reasons))}</td></tr></table></details>")
        body = (f"<p class='small'><a href='/?city={urllib.parse.quote(c.series_ticker)}'>← {E(cname)}</a></p>"
                f"<h1>Will the high in {E(cname)} on {dstr} be {E(c.outcome_label())}?</h1>"
                f"<p class='sub'>{'SAMPLE contract — fictional. ' if c.is_sample else ''}Question written by the app from the contract’s structured fields.</p>"
                f"{verdict_box}{rules}{prices}{model}{math}{tech}")
        return self.page(c.outcome_label(), body, "today", q.get("msg", ""), q.get("err") == "1")

    def _pending_exec(self, ticker: str) -> str:
        d = self.app.store.one("SELECT d.* FROM decisions d LEFT JOIN paper_orders o ON o.decision_id=d.id "
                               "WHERE d.ticker=? AND d.action!='NO_TRADE' AND o.id IS NULL ORDER BY d.id DESC LIMIT 1", (ticker,))
        if not d:
            return ""
        return (f"<form class='inline' method='post' action='/execute'><input type='hidden' name='decision_id' value='{d['id']}'>"
                f"<button>Simulate paper order for decision #{d['id']} ({E(d['action'].replace('_', ' ').lower())}, up to {d['qty']})</button></form>")

    # ------------------------------------------------------------ Cities
    def cities_page(self, q: dict) -> str:
        app = self.app
        tz_opts = lambda sel: "".join(f"<option{' selected' if z == sel else ''}>{z}</option>" for z in US_TIMEZONES + (
            [sel] if sel and sel not in US_TIMEZONES else []))
        rows = "".join(
            f"<tr><td><b>{E(c.name)}</b></td><td>{E(c.series_ticker)}</td><td>{E(c.timezone)}</td>"
            f"<td>{'' if c.latitude is None else f'{c.latitude:.3f}, {c.longitude:.3f}'}</td>"
            f"<td class='muted'>{ {'config': 'config.toml', 'dashboard': 'added here', 'sample': 'sample data'}[c.origin] }</td>"
            f"<td>{self._untrack_btn(c)}</td></tr>" for c in app.cities())
        tracked = (f"<div class='card'><h2>Cities you’re following</h2><div class='tw'><table><thead><tr><th>City</th><th>Series</th>"
                   f"<th>City timezone</th><th>Lat, lon (optional)</th><th>Added via</th><th></th></tr></thead><tbody>{rows}"
                   "</tbody></table></div></div>") if rows else ""
        if app.source.is_sample:
            find = ("<div class='card'><h2>Add more cities</h2><p>You're in <b>sample mode</b>, which shows two fictional cities. "
                    "To follow real cities, set <code>source = \"kalshi_public\"</code> in <code>config.toml</code>, restart the app, "
                    "and come back to this page.</p></div>")
        else:
            try:
                found = app.discover_cities()
                err = ""
            except Exception as e:
                found, err = [], str(e)
            frows = []
            for s in found:
                if s["tracked"]:
                    act = pill("good", "Following")
                else:
                    act = (f"<form method='post' action='/track' class='formrow'><input type='hidden' name='series' value='{E(s['ticker'])}'>"
                           f"<label>Name<input name='label' value='{E(s['label'])}' size='14'></label>"
                           f"<label>Timezone{' (guessed — check)' if s['tz_guess'] else ' (pick one)'}<select name='timezone' required>"
                           f"{'' if s['tz_guess'] else CHOOSE_OPT}{tz_opts(s['tz_guess'])}</select></label>"
                           f"<label>&nbsp;<button class='primary'>Follow</button></label></form>")
                frows.append(f"<tr><td><b>{E(s['label'])}</b><div class='muted'>{E(s['title'])}</div></td>"
                             f"<td>{E(s['ticker'])}</td><td class='small'>{E(s['sources'] or '—')}</td><td>{act}</td></tr>")
            listing = ("<div class='tw'><table><thead><tr><th>Market</th><th>Series</th><th>Settles on</th><th></th></tr></thead><tbody>"
                       + "".join(frows) + "</tbody></table></div>") if frows else (
                f"<p>{pill('bad', 'Could not load the list')} {E(err)}</p>" if err else "<p class='muted'>No daily-high series found right now.</p>")
            find = (f"<div class='card'><h2>Find more cities</h2><p class='small'>Daily high-temperature series Kalshi lists right now. "
                    f"Pick the timezone of the <i>city</i> (it decides what “today” means for its markets). "
                    f"Open a contract afterwards and read which weather station settles it.</p>{listing}"
                    f"<details><summary>Add a series by ticker instead</summary><form method='post' action='/track' class='formrow'>"
                    f"<label>Series ticker<input name='series' required size='14'></label><label>Name<input name='label' size='14'></label>"
                    f"<label>Timezone<select name='timezone'>{tz_opts('America/New_York')}</select></label>"
                    f"<label>&nbsp;<button>Follow</button></label></form></details></div>")
        help_cfg = ("<details class='card'><summary><b>Prefer a config file?</b></summary><p class='small'>You can also list cities in "
                    "<code>config.toml</code>:</p><pre>[[cities]]\nseries_ticker = \"KXHIGHCHI\"\nlabel = \"Chicago\"\n"
                    "timezone = \"America/Chicago\"\n# latitude = 41.79   # optional, for the NWS helper\n# longitude = -87.75</pre></details>")
        body = (f"<h1>Cities</h1><p class='sub'>Each city is one Kalshi daily high-temperature series. Everything else in the app "
                f"(prices, forecasts, decisions) is kept separately per city.</p>{tracked}{find}{help_cfg}")
        return self.page("Cities", body, "cities", q.get("msg", ""), q.get("err") == "1")

    def _untrack_btn(self, c: City) -> str:
        if c.origin != "dashboard":
            return ""
        return (f"<form class='inline' method='post' action='/untrack'><input type='hidden' name='series' value='{E(c.series_ticker)}'>"
                f"<button>Stop following</button></form>")

    # ------------------------------------------------------------ Paper account
    def ledger_page(self, q: dict) -> str:
        app = self.app
        perf = app.performance()
        kp = "".join(f"<div class='kpi'><div class='l'>{E(k)}</div><div class='v'>{v}</div></div>" for k, v in [
            ("Virtual cash", money(perf["cash"])), ("Money in open positions", money(perf["open_cost"])),
            ("Realized P&L", money(perf["realized_pnl"])), ("Fees paid", money(perf["fees_paid"])),
            ("Settled positions", perf["settled_positions"]), ("Winners", perf["wins"])])
        pos = app.positions()
        prow = "".join(
            f"<tr><td><a href='/market?t={urllib.parse.quote(x['ticker'])}'>{E(self._label(x['ticker']))}</a></td>"
            f"<td>{x['side'].upper()}</td><td class='num'>{x['qty']}</td><td class='num'>{money(x['cost'])}</td>"
            f"<td class='num'>{money(x['fees'])}</td><td>{self.lt(x['opened_at'])}</td>"
            f"<td>{pill('neutral', 'Open') if not x['result'] else pill('good' if x['pnl'] > 0 else 'bad', ('Won' if x['pnl'] > 0 else 'Lost'))}</td>"
            f"<td class='num'>{money(x['pnl'])}</td></tr>" for x in pos)
        ptable = ("<div class='tw'><table><thead><tr><th>Contract</th><th>Side</th><th class='num'>Qty</th><th class='num'>Cost incl. fees</th>"
                  "<th class='num'>Fees</th><th>Opened</th><th>Status</th><th class='num'>P&amp;L</th></tr></thead><tbody>" + prow +
                  "</tbody></table></div>") if prow else "<p class='muted'>No paper positions yet.</p>"
        led = "".join(f"<tr><td>{self.lt(r['created_at'])}</td><td>{E(r['kind'])}</td><td>{E(self._label(r['ticker']) if r['ticker'] else '')}</td>"
                      f"<td class='num'>{money(r['amount'])}</td></tr>"
                      for r in app.store.all("SELECT * FROM cash_ledger ORDER BY id DESC LIMIT 40"))
        body = (f"<h1>Paper account</h1><p class='sub'>{PAPER_LABEL}: virtual money only. Small samples are mostly luck — "
                f"see <a href='/evaluate'>Results</a> before drawing conclusions.</p>"
                f"<div class='card'><div class='kpis'>{kp}</div></div>"
                f"<div class='card'><h2>Account value over time</h2><p class='muted'>Cash plus open positions at what they cost. "
                f"It only moves when a contract settles.</p>{self._equity_svg(app.equity_curve())}</div>"
                f"<div class='card'><h2>Positions</h2>{ptable}</div>{self._settle_html()}"
                f"<details class='card'><summary><b>Cash history (latest 40)</b></summary><div class='tw'><table><thead><tr><th>When</th>"
                f"<th>What</th><th>Contract</th><th class='num'>Amount</th></tr></thead><tbody>{led}</tbody></table></div></details>")
        return self.page("Paper account", body, "ledger", q.get("msg", ""), q.get("err") == "1")

    def _label(self, ticker: str) -> str:
        c, _ = self.app.contract_at(ticker, self.app.clock())
        if not c:
            return ticker
        city = self.app.city(c.series_ticker)
        d = f"{c.target_date.strftime('%b')} {c.target_date.day}" if c.target_date else ""
        return f"{city.name if city else c.series_ticker} · {d} · {c.outcome_label()}"

    def _equity_svg(self, pts) -> str:
        if len(pts) < 2:
            return "<p class='muted'>The chart appears after your first paper trade.</p>"
        w, h, l, r, t, b = 900, 220, 70, 16, 14, 30
        ys = [v for _, v in pts]
        lo, hi = min(ys), max(ys)
        if hi - lo < 1:
            lo, hi = lo - 1, hi + 1
        X = lambda i: l + i * (w - l - r) / (len(pts) - 1)
        Y = lambda v: t + (hi - v) * (h - t - b) / (hi - lo)
        data = [{"x": round(X(i), 1), "y": round(Y(v), 1), "v": money(v), "t": self.lt(ts), "k": PAPER_LABEL}
                for i, (ts, v) in enumerate(pts)]
        path = " ".join(f"{p['x']},{p['y']}" for p in data)
        grid = "".join(f"<line x1='{l}' x2='{w - r}' y1='{Y(v):.1f}' y2='{Y(v):.1f}' stroke='var(--border)' stroke-width='1'/>"
                       f"<text x='{l - 8}' y='{Y(v) + 4:.1f}' text-anchor='end' font-size='12' fill='var(--ink-3)'>{money(v)}</text>"
                       for v in (lo, (lo + hi) / 2, hi))
        return (f"<div style='position:relative'><svg id='eq' viewBox='0 0 {w} {h}' style='width:100%;height:auto' role='img' "
                f"aria-label='Paper account value over time, from {money(ys[0])} to {money(ys[-1])}' "
                f"data-pts='{E(json.dumps(data))}'>{grid}"
                f"<polyline fill='none' stroke='var(--accent)' stroke-width='2' stroke-linejoin='round' points='{path}'/>"
                f"<line id='eqx' y1='{t}' y2='{h - b}' stroke='var(--ink-3)' stroke-width='1' style='display:none'/>"
                f"<circle id='eqd' r='5' fill='var(--accent)' stroke='var(--surface)' stroke-width='2' style='display:none'/>"
                f"<text x='{l}' y='{h - 8}' font-size='12' fill='var(--ink-3)'>{E(data[0]['t'])}</text>"
                f"<text x='{w - r}' y='{h - 8}' font-size='12' text-anchor='end' fill='var(--ink-3)'>{E(data[-1]['t'])}</text>"
                f"</svg><div id='eqtip'></div></div><script>{EQUITY_JS}</script>")

    def _settle_html(self) -> str:
        now = self.app.clock()
        done = {r["ticker"] for r in self.app.store.all("SELECT ticker FROM settlements")}
        closed = []
        for t in self.app.known_tickers():
            if t in done:
                continue
            c, _ = self.app.contract_at(t, now)
            if c and c.close_time and c.close_time <= now:
                closed.append(t)
        opts = "".join(f"<option value='{E(t)}'>{E(self._label(t))}</option>" for t in closed)
        s = self.app.store.all("SELECT * FROM settlements ORDER BY id DESC LIMIT 20")
        srows = "".join(f"<tr><td>{E(self._label(r['ticker']))}</td><td>{pill('good' if r['result'] == 'yes' else 'neutral', r['result'].upper())}</td>"
                        f"<td class='small'>{E(r['source'])}</td><td>{'' if r['observed_high'] is None else r['observed_high']}</td>"
                        f"<td>{self.lt(r['recorded_at'])}</td></tr>" for r in s)
        form = (f"<form method='post' action='/settle' class='formrow'><label>Contract<select name='ticker'>{opts}</select></label>"
                f"<label>Result<select name='result'><option value='yes'>YES won</option><option value='no'>NO won</option></select></label>"
                f"<label>Where you saw it<input name='source' required placeholder='e.g. Kalshi market page'></label>"
                f"<label>Reported high (optional)<input type='number' step='0.1' name='observed_high'></label>"
                f"<label>&nbsp;<button class='primary'>Record result</button></label></form>") if opts else (
            "<p class='muted'>No closed, unrecorded contracts right now. Contracts show up here after trading closes.</p>")
        return (f"<div class='card'><h2>Record results</h2><p class='small'>Results are stored separately from predictions and can't "
                f"be edited afterwards.</p><form class='inline' method='post' action='/fetch_settlements'>"
                f"<button>Fetch results from Kalshi automatically</button></form>{form}"
                + (f"<h3>Recorded results</h3><div class='tw'><table><thead><tr><th>Contract</th><th>Result</th><th>Source</th><th>Reported high</th>"
                   f"<th>Recorded</th></tr></thead><tbody>{srows}</tbody></table></div>" if srows else "") + "</div>")

    # ------------------------------------------------------------ Results
    def evaluate_page(self, q: dict) -> str:
        r = evaluate(self.app.store)
        f = lambda x: "—" if x is None else f"{x:.3f}"
        n = r["n"]
        progress = min(1.0, n / MIN_MEANINGFUL_N)
        cal = "".join(f"<tr><td>{b['range'].replace('-', '–')}</td><td class='num'>{b['n']}</td><td class='num'>{pct(b['mean_pred'])}</td>"
                      f"<td class='num'>{pct(b['observed'])}</td></tr>" for b in r["calibration"])
        preds = "".join(f"<tr><td>{E(self._label(p['ticker']))}</td><td>{self.lt(p['created_at'])}</td><td class='num'>{pct(p['p_yes'])}</td>"
                        f"<td class='num'>{pct(p['market_mid_yes'])}</td><td>{'YES' if p['y'] else 'NO'}</td></tr>" for p in r["predictions"])
        mb, kb = r["model_brier_on_mid_subset"], r["market_mid_brier"]
        cmp = ("—" if mb is None or kb is None else
               ("model was more accurate on these" if mb < kb else "market was more accurate on these" if kb < mb else "tie"))
        perf = self.app.performance()
        body = (f"<h1>Results</h1><p class='sub'>How the recorded predictions did once the real results came in. {PAPER_LABEL}.</p>"
                "<div class='card'>" + "".join(f"<p>{pill('warn', 'Note')} {E(w)}</p>" for w in r["warnings"]) +
                f"<p class='small'>Settled predictions so far: <b>{n}</b> of the {MIN_MEANINGFUL_N}+ needed before the numbers mean much.</p>"
                f"<div style='background:var(--track);border-radius:4px;height:8px;max-width:420px'><div style='width:{progress * 100:.0f}%;"
                f"height:8px;border-radius:4px;background:var(--accent)'></div></div></div>"
                f"<div class='card'><div class='kpis'>"
                f"<div class='kpi'><div class='l'>Model accuracy score (Brier)</div><div class='v'>{f(r['model_brier'])}</div></div>"
                f"<div class='kpi'><div class='l'>Market’s own score, same contracts</div><div class='v'>{f(kb)}</div></div>"
                f"<div class='kpi'><div class='l'>Comparison</div><div class='v' style='font-size:1rem'>{E(cmp)}</div></div>"
                f"<div class='kpi'><div class='l'>Paper P&amp;L after fees</div><div class='v'>{money(perf['realized_pnl'])}</div></div></div>"
                "<p class='muted'>Brier score = average squared gap between the predicted chance and what happened (1 or 0). "
                "0 is perfect and lower is better; always saying 50% scores 0.25. The market's score uses the midpoint "
                "price at decision time as its prediction.</p></div>"
                "<div class='card'><h2>Is the model's “70%” really 70%?</h2><p class='small'>Predictions grouped by how likely the model "
                "said YES was, next to how often YES actually happened. With a well-calibrated model the two columns are close.</p>"
                "<div class='tw'><table><thead><tr><th>Model said</th><th class='num'>Count</th><th class='num'>Average prediction</th>"
                f"<th class='num'>Actually YES</th></tr></thead><tbody>{cal}</tbody></table></div></div>"
                "<details class='card'><summary><b>Every scored prediction</b></summary><p class='muted'>One per contract: the last decision "
                "recorded before trading closed.</p><div class='tw'><table><thead><tr><th>Contract</th><th>Decided</th>"
                f"<th class='num'>Model</th><th class='num'>Market mid</th><th>Outcome</th></tr></thead><tbody>{preds}</tbody></table></div></details>")
        return self.page("Results", body, "results")

    # ------------------------------------------------------------ Help
    def help_page(self, q: dict) -> str:
        p = self.app.cfg.paper
        items = [
            ("Contract", "Each contract is a yes/no question like “Will the high be 75°F or above?”. A YES contract pays $1 if "
                         "the answer is yes and $0 otherwise. NO is the opposite."),
            ("Price", "What one contract costs, in cents. A YES price of 16¢ means traders collectively put the chance near 16%."),
            ("YES costs / NO costs", "The cheapest price you could actually buy at right now, from the order book — not the "
                                     "midpoint or the last trade."),
            ("Your forecast", "The expected high you enter, where it came from, and when it was issued. The app never invents one."),
            ("Give or take (±)", f"How far off you think the forecast could be (one standard deviation). The default is "
                                 f"{self.app.cfg.model.default_sigma_f:g}°F and is a guess until checked against real results."),
            ("Model’s chance", "The chance of YES if the real high lands around your forecast with that ± spread, rounded to "
                               "whole degrees like official reports."),
            ("All-in cost", f"Price + Kalshi's trading fee + {cents(p.slippage_per_contract)} assumed slippage."),
            ("Edge", f"Model's chance minus all-in cost. The app only paper-buys when the edge is at least "
                     f"{p.safety_margin * 100:.0f} points."),
            ("Paper trade", f"A simulated purchase with virtual money. It only “fills” against contracts shown for sale, and only "
                            f"{p.fill_fraction_of_displayed:.0%} of them, to stay conservative."),
            ("Record decision", "Saves the verdict, prices and forecast with a timestamp that can't be changed later, so results "
                                "can be scored honestly."),
            ("Stale", f"Prices older than {p.max_quote_age_seconds // 60} minutes or forecasts older than "
                      f"{p.max_forecast_age_hours:g} hours aren't used for decisions."),
            ("Risk limits", f"Virtual limits: {money(p.max_stake_per_market)} per contract, {money(p.max_total_exposure)} total, "
                            f"{money(p.max_daily_loss)} worst-case per day. No borrowing."),
        ]
        rows = "".join(f"<tr><th style='width:200px'>{E(k)}</th><td>{E(v)}</td></tr>" for k, v in items)
        body = (f"<h1>How it works</h1><p class='sub'>Plain-English guide to the terms on these pages.</p>"
                f"<div class='card'><table>{rows}</table></div><div class='card'><h2>What this app will never do</h2>"
                "<ul class='plain'><li>Place a real order or touch real money.</li><li>Invent a forecast or a result.</li>"
                "<li>Change what it recorded earlier.</li><li>Claim the model is accurate before enough real results exist.</li></ul></div>")
        return self.page("How it works", body, "help")

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
            r = app.refresh(g("series") or None)
            msg = f"Saved fresh prices for {r['markets']} contracts."
            if r["errors"]:
                msg += " Problems: " + "; ".join(r["errors"][:3])
            return msg
        if path == "/forecast":
            fid = app.add_forecast(target_date=date.fromisoformat(g("target_date")), expected_high=float(g("expected_high")),
                                   unit=g("unit") or "F", sigma=float(g("sigma")) if g("sigma") else None,
                                   issued_at=parse_local_input(g("issued_at"), app.tz), source=g("source"),
                                   series_ticker=g("series") or None, source_detail=g("source_detail"), notes=g("notes"))
            return f"Saved forecast #{fid}."
        if path == "/nws":
            return f"Saved NWS forecast #{app.fetch_nws(date.fromisoformat(g('target_date')), g('series') or None)}."
        if path == "/ack":
            app.ack_terms(g("ticker"))
            return "Noted that you've read these rules. If the rules text ever changes, you'll be asked again."
        if path == "/decide":
            did = app.record_decision(g("ticker"))
            d = app.store.one("SELECT action FROM decisions WHERE id=?", (did,))
            return f"Recorded decision #{did}: {d['action'].replace('_', ' ').lower()} ({PAPER_LABEL})."
        if path == "/decide_city":
            d = date.fromisoformat(g("date"))
            n = buys = 0
            for t in app.todays_tickers(g("series")):
                c, _ = app.contract_at(t, app.clock())
                if c is None or c.target_date != d:
                    continue
                did = app.record_decision(t)
                n += 1
                buys += app.store.one("SELECT action FROM decisions WHERE id=?", (did,))["action"] != "NO_TRADE"
            return f"Recorded {n} decisions ({buys} paper-buy signals). Open a contract to simulate a paper order."
        if path == "/execute":
            r = app.execute_paper(int(g("decision_id")))
            return (f"{PAPER_LABEL} order: {r['status'].lower()}, {r['qty']} contracts for {money(r['cost'])} "
                    f"including {money(r['fees'])} fees.")
        if path == "/settle":
            oh = float(g("observed_high")) if g("observed_high") else None
            app.record_settlement(g("ticker"), g("result"), g("source"), oh)
            return "Result recorded."
        if path == "/fetch_settlements":
            got = app.fetch_settlements()
            return f"Recorded {len(got)} results." if got else "No new results available yet."
        if path == "/track":
            if not g("timezone"):
                raise ValueError("pick the city's timezone")
            app.track_city(g("series"), g("label"), g("timezone"))
            return f"Now following {g('label') or g('series')}. Go to Today and refresh prices."
        if path == "/untrack":
            app.untrack_city(g("series"))
            return "Stopped following. Saved history is kept."
        raise ValueError("unknown action")


ROUTES = {"/": "index", "/market": "market", "/evaluate": "evaluate_page", "/cities": "cities_page",
          "/ledger": "ledger_page", "/help": "help_page"}


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
                if u.path in ROUTES:
                    return self._send(200, getattr(dash, ROUTES[u.path])(q))
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
            base = bu.path if bu.path in ROUTES else "/"
            keep = {k: v[0] for k, v in urllib.parse.parse_qs(bu.query).items() if k in ("t", "city")}
            try:
                msg, err = dash.post(urllib.parse.urlparse(self.path).path, form), "0"
            except Exception as e:
                msg, err = f"Couldn't do that: {e}", "1"
            qs = urllib.parse.urlencode({**keep, "msg": msg, "err": err})
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
