# KalshiKommander

A local research and **PAPER / SIMULATED** trading tool for Kalshi daily-high-temperature markets.

- It reads Kalshi's **public** market data. You don't need an account, API key, deposit or payment details.
- You enter weather forecasts by hand, with their sources. There is also an optional helper that fetches a forecast from api.weather.gov.
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

### Switching to real Kalshi public data

```bash
python -m kalshikommander discover --check-open   # lists daily-high-temperature series that exist now
```

Edit `config.toml` with the series you picked:

```toml
[market]
source = "kalshi_public"
series_ticker = "<a ticker printed by discover>"
city_label = "<city>"
timezone = "<IANA zone of that city, e.g. America/Chicago>"
```

Then run `python -m kalshikommander serve` and click **Refresh market data**.

Sample data and real data use separate databases: `data/sample.db` and `data/kalshi_public.db`. They never mix.

### CLI commands

| Command | What it does |
|---|---|
| `discover [--check-open]` | Find current daily-high-temperature series (public API). |
| `refresh` | Snapshot today's and tomorrow's markets and order books. |
| `serve [--port N]` | Run the dashboard, bound to 127.0.0.1 only. |
| `add-forecast --date 2026-10-01 --high 74 --unit F [--sigma 3] --issued 2026-09-30T16:00 --source "NWS forecast page" [--detail URL]` | Record a forecast. |
| `nws --date YYYY-MM-DD` | Optional: record an NWS gridpoint forecast. Needs `provider="nws"` and a latitude/longitude. |
| `decide [--ticker T ...]` | Record timestamped estimate and decision snapshots. |
| `paper-execute <decision_id>` | Simulate a stored BUY decision against *its own* order-book snapshot. |
| `settle <ticker> yes\|no --source "..." [--observed-high 77]` | Record a settlement by hand. |
| `fetch-settlements` | Record results that the public market data reports as settled. |
| `evaluate` | Score predictions against settlements. |
| `status` | Paper ledger summary. |

## Daily workflow

1. **Refresh** to snapshot the markets and order books.
2. Open a contract. **Read the verbatim rules.** If the "Interpreted YES set" matches them, click the acknowledgment. The acknowledgment is tied to a hash of that exact rules text, so a rules change requires a new acknowledgment.
3. **Enter a forecast** with its source, the forecast's *issue* time, the expected high and your uncertainty σ.
4. **Record a decision snapshot**. You get either a BUY decision or NO_TRADE with reasons.
5. For a BUY, optionally **Simulate paper order**.
6. After the market closes, use **Fetch settled results** or record the result manually. Then check **Evaluation**.

## Architecture

The components are separate and each can be tested on its own.

| Layer | Module | Notes |
|---|---|---|
| Market data (read-only) | `marketdata/kalshi_public.py`, `marketdata/sample.py` | GET-only, with an allowlist of paths: `/series`, `/events`, `/markets`, `/markets/{t}/orderbook`. |
| Contract terms | `contracts.py` | Uses the structured strike fields, checks them against the verbatim rules, and never reads the title. |
| Order book | `orderbook.py` | Book lists bids only. YES ask = 1 − best NO bid, and vice versa. |
| Forecasts | `service.add_forecast`, `weather/nws.py` | Manual entry by default. The NWS provider is optional. |
| Model | `probability.py` | Pure function. |
| Fees | `fees.py` | Pure function. |
| Decision | `decision.py` | Pure function. Returns NO_TRADE with reasons. |
| Risk | `risk.py` | Pure function. |
| Execution | `execution/base.py` (interface), `execution/paper.py` (only implementation) | No network access. |
| Storage | `storage.py` | SQLite. Triggers abort any UPDATE or DELETE on every table. |
| Evaluation | `evaluation.py` | Forward-test scoring only. |
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

**NWS api.weather.gov (optional provider)** is free and needs no key, but it requires a User-Agent.

- **Coverage:** the US only.
- **Units:** the forecast's `temperatureUnit`, normally °F.
- **Timezone:** period times carry their local offset. The app uses the daytime period that starts on the target local date.
- **Update cadence:** roughly hourly. `updateTime` is stored as the issue time.
- **Limitations:**
  - A gridpoint forecast is **not** the settlement station's reading.
  - It gives no uncertainty, so σ is your stored assumption and is labeled as one.
  - If the period is missing, nothing is recorded. The app never fills in a value.
- **Not reachable from the build environment either**, so it is tested only with a fixture.

**Sample data** is fictional ("Sampleville"). It is shown with orange **SAMPLE DATA — FICTIONAL** banners and stored in its own database. It exists only to exercise the app.

## How to choose a city or series

1. Run `discover --check-open` and pick a series that has open events.
2. Open one of its markets in the dashboard. Read the settlement source, the station and the verbatim rules.
3. Set `timezone` to the city's IANA zone.
4. If you use NWS, set a latitude/longitude close to the **settlement station**.

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
