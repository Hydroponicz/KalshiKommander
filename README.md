# KalshiKommander

A local research and **PAPER / SIMULATED** trading tool for Kalshi daily-high-temperature markets.

- It reads Kalshi's **public** market data. You don't need an account, API key, deposit or payment details.
- Weather forecasts arrive **automatically** from a free service (Open-Meteo by default, or the US National Weather Service), or you can enter your own.
- It estimates P(YES) with a simple model that is documented below and is **not calibrated**.
- It compares that estimate with the **executable ask**, after fees, slippage and a safety margin.
- It records every input, estimate, quote and decision as an **append-only**, timestamped snapshot.
- It simulates fills locally against the visible order-book depth.

> **No real orders.** This codebase contains no order-placement code, no authenticated or trading
> endpoints, no request signing and no setting or environment variable that enables live trading.
> Tests enforce this (`tests/test_sources_and_safety.py`).

## Install, run and test

You need Python **3.11 or newer**. There are no paid services and no compiled dependencies.

**Windows (PowerShell)**

```powershell
git clone <this repo> KalshiKommander; cd KalshiKommander
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest -q                     # run the tests
copy config.example.toml config.toml    # starts in clearly labeled SAMPLE mode
python -m kalshikommander serve         # open http://127.0.0.1:8765/
```

**macOS / Linux**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
cp config.example.toml config.toml
python -m kalshikommander serve
```

`requirements.txt` holds only `tzdata`, which supplies the timezone database `zoneinfo` needs on Windows. Everything else uses the standard library.

### Following several cities

Each city is one Kalshi daily-high-temperature series. Prices, forecasts, decisions and rule confirmations are all kept per city. There are three ways to add cities; use whichever you like, and they can be mixed:

1. **In the dashboard (easiest).** Go to the **Cities** page. It lists every daily-high series Kalshi offers right now. Check the pre-filled timezone (it's a *guess* from the city name, so confirm it) and click **Follow**. **Stop following** removes a city but keeps its saved history.
2. **From the command line:** `python -m kalshikommander track KXHIGHCHI --timezone America/Chicago --label Chicago`. `python -m kalshikommander cities` lists what you follow.
3. **In `config.toml`**, one block per city:

   ```toml
   [[cities]]
   series_ticker = "KXHIGHCHI"
   label = "Chicago"
   timezone = "America/Chicago"   # the city's timezone: decides what "today" means for its markets
   # latitude = 41.79             # optional: forecast location (known cities get a suggested station)
   # longitude = -87.75
   ```

The older single-city `[market] series_ticker` setting still works and shows up as one city. Forecasts saved before multi-city support stay attached to that city.

On the command line, pass `--city SERIES` to `add-forecast`, `nws` and `refresh` when you follow more than one city.

### Follow every city automatically

With real data, `[market] follow_all = true` (the default) makes each update check Kalshi's list of daily-high-temperature series, at most every 6 hours, and follow any new city.

- **Timezone and forecast location are filled in automatically**, in this order:
  1. The settlement station named in the contract's settlement source or rules. For example an NWS climate-report link `…issuedby=MDW` or `CLIMDW` becomes station KMDW, which is looked up on the NWS stations API for exact coordinates and timezone (US stations).
  2. A built-in list of stations public guides say Kalshi uses, marked "suggested — check".
  3. The city centre from Open-Meteo's free geocoding, marked "approximate".
- A city whose timezone can't be determined is **not** followed. It is listed under "Needs your attention" instead of being guessed.
- The Cities page shows where every location came from and lets you change it.
- **Stop following** works for automatic cities too, and they stay stopped.
- **Follow all Kalshi weather cities now** on the Cities page, or `python -m kalshikommander follow-all`, runs discovery immediately.
- Kalshi requests are paced (about 12 per second, with a back-off on HTTP 429). With 20+ cities an update takes on the order of a minute.

### Review everything at once

The **Review & approve** page collects what needs you across all cities:

1. **Rules.** New cities' rules wordings are listed on one page with a single **accept all** button. Wordings that fail the automatic checks are never accepted, and a changed wording asks again.
2. **Paper-buy signals.** Every current signal across all cities is shown in one table, all ticked. **Approve selected paper buys** re-checks prices first (re-snapshotting a city whose prices are over 2 minutes old). It simulates each trade only if it is still a paper-buy at the new prices, and it respects the risk limits.

To skip even that click, set `[auto] paper_trade = true`: the auto-update then simulates every paper-buy signal itself. Approving everything, or using this option, gives the least biased test, because hand-picked trades measure your picks rather than the model. It is paper only; there is still no real-money code.

On the Today page, city cards fold into a one-line summary when you follow more than three cities.

### Automatic forecasts (no typing needed)

With real data, every **Update prices & forecasts** click also fetches today's and tomorrow's expected high for each city. The provider is set in `config.toml`:

```toml
[weather]
provider = "open_meteo"   # default. "nws" = US National Weather Service, "manual" = off
refetch_minutes = 60      # fetch at most this often per city
```

Each city needs a **forecast location**, ideally the weather station its contracts settle on. New York, Chicago, Austin, Miami, Los Angeles, Philadelphia and Denver get a suggested station automatically (for example Chicago → Midway Airport). These are taken from public guides, so check them against the station named in the contract rules. Change or set a location on the **Cities** page ("Change location") or with `python -m kalshikommander set-location KXHIGHCHI 41.7861 -87.7522`.

**Hands-free mode.** Start the dashboard with `python -m kalshikommander serve --auto-update 15` (or set `[auto] update_every_minutes = 15`). While it runs, every 15 minutes it:

1. saves fresh prices,
2. fetches forecasts that are due, and
3. records a timestamped decision for every contract (turn this off with `[auto] record_decisions = false`).

Paper orders are never placed automatically; you still click **Simulate paper order**.

If the dashboard isn't running, `python -m kalshikommander update` does the same once. You can schedule it with Windows Task Scheduler.

What stays manual, on purpose:

- **Reading each city's rules once and confirming** (one click per city; it asks again only if the wording changes).
- **The "±" uncertainty**, which is a configured assumption (`[model] default_sigma_f`), not something the weather services provide.

A forecast you type yourself is still accepted. Whichever forecast was issued most recently is used.

### Switching to real Kalshi public data

```bash
python -m kalshikommander discover --check-open   # lists daily-high-temperature series that exist now
```

In `config.toml` set:

```toml
[market]
source = "kalshi_public"
timezone = "<YOUR timezone, e.g. America/New_York>"   # used for display and the daily paper-loss limit
```

Then run `python -m kalshikommander serve`, add cities on the **Cities** page (see above), and click **Refresh prices** on the Today page.

Sample data and real data use separate databases: `data/sample.db` and `data/kalshi_public.db`. They never mix.

### CLI commands

| Command | What it does |
|---|---|
| `discover [--check-open]` | Find current daily-high-temperature series (public API). |
| `refresh [--city SERIES]` | Snapshot today's and tomorrow's markets and order books (each city's own local dates). |
| `cities` / `track SERIES --timezone TZ [--label NAME]` / `untrack SERIES` | List, follow or stop following cities. |
| `follow-all` | Follow every Kalshi daily-high city now, with timezone and location filled in. |
| `serve [--port N]` | Run the dashboard, bound to 127.0.0.1 only. |
| `add-forecast [--city SERIES] --date 2026-10-01 --high 74 --unit F [--sigma 3] --issued 2026-09-30T16:00 --source "NWS forecast page" [--detail URL]` | Record a forecast. |
| `update [--no-decisions] [--force] [--paper-trade]` | One-shot: follow new cities, refresh prices, fetch forecasts and results, record decisions (and optionally simulate every paper-buy). |
| `set-location SERIES LAT LON` | Set a city's forecast location. |
| `serve --auto-update MINUTES` | Dashboard plus automatic updates every N minutes (minimum 5). |
| `nws [--city SERIES] --date YYYY-MM-DD` | Record an NWS gridpoint forecast for one day by hand. |
| `decide [--ticker T ...]` | Record timestamped estimate and decision snapshots. |
| `paper-execute <decision_id>` | Simulate a stored BUY decision against *its own* order-book snapshot. |
| `settle <ticker> yes\|no --source "..." [--observed-high 77]` | Record a settlement by hand. |
| `fetch-settlements` | Record results that the public market data reports as settled. |
| `evaluate` | Score predictions against settlements. |
| `status` | Paper ledger summary. |

## The dashboard

| Page | What it shows |
|---|---|
| **Today** | One card per city, filterable with the chips at the top. Each card shows today and tomorrow in the city's local time: your forecast (or a form to enter one), then one row per outcome ("75°F or above"). Each row has the price to buy YES and NO with how many are for sale, the model's chance, a small chart comparing the two, and a plain-English verdict with what to do next. |
| **Contract details** | The question in plain words, the verdict and every reason behind it. Then the official rules to read and confirm, the prices you could actually pay (full order book on request), your forecast with a "±" what-if, and a receipt-style breakdown of price + fee + slippage vs. the model's chance. Technical fields are tucked into a collapsible section. |
| **Cities** | The cities you follow, and every daily-high series Kalshi lists, each with a Follow button. |
| **Paper account** | Virtual cash, positions, an account-value chart (hover for values), and recording results. |
| **Results** | Accuracy scores explained in plain language, a "is 70% really 70%?" calibration table, and progress toward the 100+ settled predictions needed to mean anything. |
| **How it works** | A glossary of every term on the pages. |

Verdict colours always come with an icon and a label: green ✓ = paper-buy signal, yellow ! = something needs your action (refresh, forecast, read rules), grey – = no trade, red ✕ = a problem the app won't trade through. The pages follow your system's light/dark setting and stack into cards on phone-width screens.

## Daily workflow

1. Click **Update prices & forecasts** (or leave `serve --auto-update 15` running). This snapshots the markets and order books and fetches forecasts.
2. **Review each city's rules once.** A city's contracts share one rules wording apart from the date and temperature. Use **Review rules** on the city card, read the example for each wording (usually three: "or below", a range, "or above"), and accept them all with one click.
   - Contracts whose wording matches exactly are then accepted automatically, today and in future.
   - If anything else changes, such as the weather station, settlement source or comparison wording, those contracts ask again. Only dates and numbers are allowed to differ.
   - Wordings that fail the automatic checks can't be accepted.
   - You can still accept a single contract from its details page.
3. Check the forecast. It arrives automatically, or you can enter one with its source, *issue* time, expected high and uncertainty σ.
4. **Record a decision snapshot**. You get either a BUY decision or NO_TRADE with reasons.
5. For a BUY, optionally **Simulate paper order**.
6. Results are fetched automatically on each update once markets settle. This includes the reported high when Kalshi's data provides it. You can also record a result by hand on the Paper account page. Then check the **Readiness scorecard** on **Results**.

## Architecture

The components are separate and each can be tested on its own.

| Layer | Module | Notes |
|---|---|---|
| Market data (read-only) | `marketdata/kalshi_public.py`, `marketdata/sample.py` | GET-only, with an allowlist of paths: `/series`, `/events`, `/markets`, `/markets/{t}/orderbook`. |
| Contract terms | `contracts.py` | Uses the structured strike fields, checks them against the verbatim rules, and never reads the title. |
| Order book | `orderbook.py` | Book lists bids only. YES ask = 1 − best NO bid, and vice versa. |
| Forecasts | `service.add_forecast` / `auto_forecasts`, `weather/open_meteo.py`, `weather/nws.py` | Automatic (Open-Meteo or NWS) or manual. |
| Model | `probability.py` | Pure function. |
| Fees | `fees.py` | Pure function. |
| Decision | `decision.py` | Pure function. Returns NO_TRADE with reasons. |
| Risk | `risk.py` | Pure function. |
| Execution | `execution/base.py` (interface), `execution/paper.py` (only implementation) | No network access. |
| Storage | `storage.py` | SQLite. Triggers abort any UPDATE or DELETE on every table. |
| Evaluation | `evaluation.py` | Forward-test scoring only. |
| Cities | `cities.py` | Tracked-city record and the timezone guess used on the Cities page. |
| UI | `web.py` (stdlib HTTP server), `cli.py` | |

## Data sources and their limitations

**Kalshi public market data** is read from `https://api.elections.kalshi.com/trade-api/v2` without authentication.

- Fields used:
  - Series: `settlement_sources`, `contract_url`, `fee_type`
  - Events, with nested markets
  - Markets: `rules_primary`, `rules_secondary`, `strike_type`, `floor_strike`, `cap_strike`, `open_time`, `close_time`, `status`, `result`, prices
  - Order book
- Prices are read either as the newer `*_dollars` strings or as the older integer-cent fields. The order book is read either as `orderbook_fp.yes_dollars/no_dollars` or as the older `orderbook.yes/no` in cents.
- **Not verified from the build environment.** The sandbox's network policy blocked this host, so the client was written against the published documentation and exercised only with fixtures. If a field name has changed, the terms checks fail closed and the app shows NO_TRADE. Run `discover` on your PC first.
- The market's date comes from the event ticker (`...-26SEP30`) or from `strike_date`. It is then cross-checked against the rules text.
- The contract link points to the series page, `https://kalshi.com/markets/<series>`. That URL pattern is assumed. The series `contract_url` is shown when the data provides one.
- Settlement sources can change. Secondary reports say high/low series moved from NWS to another reporting authority in 2026. Always read the rules shown for *each* market; the app does not assume a source.

**Open-Meteo (default automatic provider)** is at `api.open-meteo.com`. It is free, needs no key, and the free tier is for non-commercial use.

- **Coverage:** worldwide. It blends national weather models, about 1–11 km grid.
- **Units:** requested in °F. The response's unit is checked.
- **Timezone:** requested in the city's timezone, so the daily maximum covers that city's local calendar day. That is midnight to midnight clock time, not the local-standard-time day some official reports use.
- **Update cadence:** models refresh every 1–6 hours. The API doesn't say when the model run was made, so the **retrieval time is stored as the issue time**. That's when the app knew the value, which is what matters for look-ahead safety, but the forecast can look fresher than it is.
- **Limitations:**
  - A grid forecast is not the settlement station's reading.
  - It gives no uncertainty, so σ stays your assumption.
  - Missing values are skipped, never filled in.
- **Not reachable from the build environment**, so it is tested only with a fixture.

**NWS api.weather.gov (optional automatic provider, `provider = "nws"`)** is free and needs no key, but it requires a User-Agent.

- **Coverage:** the US only.
- **Units:** the forecast's `temperatureUnit`, normally °F.
- **Timezone:** period times carry their local offset. The app uses the daytime period that starts on the target local date.
- **Update cadence:** roughly hourly. `updateTime` is stored as the issue time.
- **Limitations:**
  - A gridpoint forecast is **not** the settlement station's reading.
  - It gives no uncertainty, so σ is your stored assumption and is labeled as one.
  - If the period is missing, nothing is recorded. The app never fills in a value.
- **Not reachable from the build environment either**, so it is tested only with a fixture.

**Sample data** is fictional: two cities, "Sampleville" (Eastern time) and "Testburg" (Central time). It is shown with orange **SAMPLE DATA — FICTIONAL** banners and stored in its own database. It exists only to exercise the app.

## How to choose a city or series

1. Open the **Cities** page (or run `discover --check-open`) and pick a series that has open events.
2. Open one of its markets in the dashboard. Read the settlement source, the station and the verbatim rules.
3. Confirm the city's timezone. It decides which contracts count as "today" for that city.
4. Make sure the city's **forecast location** is the settlement station (Cities page → Change location, `set-location`, or `[[cities]]`).

Prefer a city where you can find a documented, timestamped forecast source you'll use consistently.

## The probability model and its assumptions

The reported daily high is modeled as your forecast's expected high μ plus Normal(0, σ) error, rounded to a whole degree because official reports use whole degrees:

    P(report = k) = Φ((k+0.5−μ)/σ) − Φ((k−0.5−μ)/σ)
    P(YES)        = Σ P(report = k) over the integers k that the contract maps to YES

The structured strike maps to a YES set as follows:

| `strike_type` | YES when the reported value v is |
|---|---|
| `greater` | v > floor |
| `greater_or_equal` | v ≥ floor |
| `less` | v < cap |
| `less_or_equal` | v ≤ cap |
| `between` | floor ≤ v ≤ cap (inclusive) |

The dashboard shows the resulting set, for example "reported high ≥ 81°F", next to the verbatim rules so you can confirm it.

Limitations of the model:

- It assumes the error is unbiased and Normal with a fixed σ. Neither assumption has been checked.
- It ignores station and measurement quirks, intraday information after the forecast was issued, and the climate-day definition. NWS reports use local *standard* time; see `timeutil.climate_day_window_utc`.

**σ is an assumption. The estimate is not calibrated.** The market page shows how P(YES) changes across a range of σ values, and you can try any σ.

## Decision rule: executable prices, fees and margins

For each side, the app walks the **ask** levels, which come from the opposite side's bids. It never uses the midpoint or the last trade.

    all-in cost = ask + worst-case taker fee per contract + slippage
    fee         = ceil_to_cent(0.07 × C × P × (1−P))   (rate is configurable; check Kalshi's current fee schedule)
    edge        = model probability − all-in cost

It buys only when edge ≥ `safety_margin`. It shows **NO_TRADE** with every applicable reason when any of these is true:

- The forecast is missing, stale, dated after the decision time, or for a different date.
- The quote is stale (older than `max_quote_age_seconds`) or from after the decision time.
- The book is empty or too thin after the fill haircut.
- The terms fail automated checks:
  - the rules text is missing
  - the strike number is not found in the rules
  - the date is not found in the rules
  - there is no settlement source
  - the strike type is unsupported
- You haven't acknowledged this exact rules text.
- The market is not open or has passed its close time.
- A risk limit is exhausted.
- This order-book snapshot was already used by a paper order.

### Risk limits

These are in `[paper]` and all amounts are virtual dollars, fees included:

- `max_stake_per_market`
- `max_total_exposure`
- `max_daily_loss`: worst case, counting every position opened today at full cost plus today's realized losses
- no leverage: cost cannot exceed virtual cash

### Paper fill assumptions (conservative)

- Orders are immediate-or-cancel. There are no resting orders, no queue position and no maker fees or rebates.
- Fills come only from levels **visible in the stored snapshot**, and only up to `fill_fraction_of_displayed` (50% by default) of each level's quantity. The app never fills an order just because a price was displayed.
- Every fill pays the taker fee, rounded up per level, plus `slippage_per_contract`.
- The execution snapshot must be the decision's own snapshot and younger than `max_quote_age_seconds`. Otherwise the order is REJECTED.
- A snapshot's liquidity is used at most once.
- Contracts are whole numbers. Positions are held until settlement.
- Latency is **not** modeled beyond the staleness check. A real order would arrive after the snapshot was taken, and the book may have moved by then.

## Point-in-time integrity and look-ahead prevention

- Every snapshot row has `captured_at` or `recorded_at`. Forecasts also store their `issued_at`.
- SQLite triggers make every table INSERT-only.
- Reads are point-in-time (`as_of`): they never return rows captured or recorded later. A forecast entered later with an earlier issue time is still invisible to earlier decisions.
- A forecast's issue time cannot be in the future.
- Settlements go in their own table. They can't be recorded before the market closes, and each contract gets exactly one.
- Evaluation counts only the last decision recorded **before close** for each contract.
- **A historical backtest is not possible.** The app has no archive of past quotes or forecasts as they were at the time. Rebuilding them from later data would leak future information, so the app does not attempt it.

## What would and would not count as evidence of an edge

**Would not count:**

- Any results on SAMPLE data.
- A handful of winning paper trades.
- Paper P&L over days or weeks. Daily weather markets are highly correlated within a single day, so 5 contracts on one date are closer to 1 observation than to 5.
- Results after changing σ, the margin or the forecast source after seeing outcomes. That is overfitting.
- Beating the midpoint rather than the executable price.

**Might begin to count**, and only if all of the following hold:

- Well over 100 settled, pre-registered predictions spread across many distinct dates.
- A model Brier score and log loss that beat the market-midpoint baseline on the same contracts, with a calibration table that roughly matches observed frequencies.
- Positive paper P&L **after** fees, slippage and the fill haircut, still positive under harsher assumptions (a 25% fill fraction and 2¢ of slippage).
- Stable results across months and seasons.
- Parameters fixed in advance.

Even then, paper fills overstate real fills. Treat any edge as a hypothesis to test at tiny size.

### The readiness scorecard (Results page)

The scorecard turns the criteria above into a checklist. Each check shows pass/not-yet and its current value:

| Check | Default target |
|---|---|
| Settled predictions | ≥ 100 |
| Different contract days | ≥ 30 |
| Model beats the market midpoint (day-resampled bootstrap of the Brier score) | ≥ 90% of resamples |
| Settled paper trades | ≥ 50 |
| Paper P&L after fees | > 0 |
| Paper P&L with worse fills (same trades re-simulated on their own saved order books at 25% of shown size and +1¢ slippage) | > 0 |
| Settings unchanged across the scored results | 1 combination |

It also compares your "±" assumption with the forecast errors actually observed, once reported highs are recorded.

- Targets live in `[readiness]` in `config.toml`. **Set them before looking at results and don't move them.**
- SAMPLE data never counts.
- Passing every check is **necessary, not sufficient**.

### From paper to real money: the path

1. **Now: forward-test on paper.**
   - Leave `serve --auto-update 15` running with fixed settings.
   - Let predictions, trades and results accumulate until the scorecard passes. For daily weather markets that is typically a few months.
   - If you change a setting, treat it as a new test and start the count again.
2. **Then: a separate, reviewed live-trading milestone.** This is not in this codebase, and no setting enables it. In order:
   - Kalshi account verification and eligibility checks.
   - API keys that you create and store outside the repo.
   - A live adapter that runs first against **Kalshi's demo environment** (fake money).
   - **Shadow mode:** logging the exact real orders it *would* place beside the paper fills, to measure the gap.
   - Finally tiny real orders that **you confirm one by one**, with hard caps, a kill switch and account reconciliation.
3. **Only risk money you can afford to lose entirely.** A model can pass every check and still stop working when the season or the market changes.

## What live trading would require (not built)

The following are prerequisites for a **separate, explicitly reviewed milestone**. None of it exists in this codebase.

**Account and legal**

- A verified Kalshi account in an eligible jurisdiction.
- An understanding of Kalshi's API terms, rate limits, fee schedule and tax reporting.
- API keys created by you and stored outside the repo, in the OS keychain. They would never go in config files or the dashboard.
- A dedicated low-balance account or sub-account.

**Safeguards**

- A distinct `LiveExecutionAdapter` that no configuration flag can select. Enabling it would take a code change plus a signed-off review.
- A demo-environment phase first.
- Hard-coded per-order, per-day and total notional caps enforced *both* before submission and by reconciling against exchange balances and positions.
- A kill switch and automatic halt on:
  - any reconciliation mismatch
  - stale data
  - a clock skew check failure
  - repeated rejects
- Idempotent client order IDs.
- Limit orders only, with price bands relative to the verified book.
- Duplicate-order protection.
- Manual confirmation for every order in the first phase.
- Audit logs of every request and response.
- Handling for partial fills, cancels and exchange downtime.
- Monitoring and alerts.

**Tests**

- Contract tests against the demo environment.
- Fault injection: timeouts, 5xx errors, partial fills, network splits.
- Reconciliation tests.
- Property tests showing that limits can never be exceeded.
- A shadow mode that logs intended orders beside paper fills for weeks, measuring slippage against the paper assumptions.
- A documented go/no-go review of the forward-test evidence above.

## Project layout

```
kalshikommander/   core package (see Architecture)
tests/             pytest suite + fixtures
config.example.toml
requirements.txt / requirements-dev.txt
```
