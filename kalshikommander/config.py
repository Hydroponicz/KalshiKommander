"""Configuration loading. There is intentionally NO setting that enables live trading."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class MarketConfig:
    source: str = "sample"          # "sample" (clearly labeled fake data) or "kalshi_public"
    series_ticker: str = ""         # legacy single-city setting; prefer [[cities]] or the Cities page
    city_label: str = ""
    timezone: str = "America/New_York"  # YOUR timezone: display + daily-loss day boundary
    follow_all: bool = True             # automatically follow every Kalshi daily-high-temperature city


@dataclass
class CityConfig:
    series_ticker: str
    label: str = ""
    timezone: str = "America/New_York"  # the city's own IANA timezone
    latitude: float | None = None       # optional, for the NWS forecast helper
    longitude: float | None = None


@dataclass
class ModelConfig:
    default_sigma_f: float = 3.0    # ASSUMPTION: forecast error std dev (°F); not calibrated
    sensitivity_sigmas_f: list = field(default_factory=lambda: [1.5, 2.0, 3.0, 4.0, 5.0])


@dataclass
class PaperConfig:
    starting_cash: float = 1000.0           # virtual dollars
    taker_fee_rate: float = 0.07            # check Kalshi's current fee schedule
    safety_margin: float = 0.05             # required edge (prob points) after fees+slippage
    slippage_per_contract: float = 0.01     # extra $ per contract added to every simulated fill
    fill_fraction_of_displayed: float = 0.5 # only this share of displayed qty is assumed fillable
    min_contracts: int = 1                  # below this: "book too thin"
    max_quote_age_seconds: int = 300
    max_forecast_age_hours: float = 12.0
    max_stake_per_market: float = 25.0      # virtual $ cost (incl. fees) per market
    max_total_exposure: float = 100.0       # virtual $ cost of all open positions
    max_daily_loss: float = 50.0            # worst-case virtual $ loss for positions opened today + realized
    require_terms_ack: bool = True          # require you to confirm you read the rules text


@dataclass
class WeatherConfig:
    # Automatic forecast source: "open_meteo" (free, worldwide), "nws" (free, US only) or "manual" (off).
    provider: str = "open_meteo"
    refetch_minutes: int = 60        # fetch at most this often per city
    latitude: float | None = None    # legacy single-city location
    longitude: float | None = None
    nws_user_agent: str = "KalshiKommander-research (set-your-email@example.com)"


@dataclass
class ReadinessConfig:
    """Go/no-go targets for the Results page scorecard. Decide these BEFORE looking at results."""
    min_predictions: int = 100          # settled pre-close predictions
    min_settled_days: int = 30          # distinct contract dates (one day's contracts move together)
    min_paper_trades: int = 50          # settled paper positions
    confidence: float = 0.90            # share of day-bootstrap resamples where the model beats the market
    stress_fill_fraction: float = 0.25  # re-simulate fills with this share of displayed size...
    stress_extra_slippage: float = 0.01  # ...and this much extra slippage per contract


@dataclass
class AutoConfig:
    update_every_minutes: int = 0    # while `serve` runs: update prices+forecasts every N minutes (0 = off)
    record_decisions: bool = True    # automatic updates also record a timestamped decision per contract
    paper_trade: bool = False        # automatic updates also place every paper-buy signal (PAPER only)


@dataclass
class AppConfig:
    market: MarketConfig = field(default_factory=MarketConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    auto: AutoConfig = field(default_factory=AutoConfig)
    readiness: ReadinessConfig = field(default_factory=ReadinessConfig)
    cities: list = field(default_factory=list)  # list[CityConfig]
    data_dir: str = "data"
    host: str = "127.0.0.1"
    port: int = 8765

    @property
    def db_path(self) -> Path:
        # Sample data and real data never share a ledger.
        name = "sample.db" if self.market.source == "sample" else "kalshi_public.db"
        return Path(self.data_dir) / name

    def to_dict(self) -> dict:
        return asdict(self)


_FORBIDDEN_KEYS = {"live", "live_trading", "enable_live", "api_key", "private_key", "key_id", "trading_endpoint"}


def _apply(dc, data: dict, section: str):
    known = {f.name for f in fields(dc)}
    for k, v in data.items():
        if k.lower() in _FORBIDDEN_KEYS:
            raise ValueError(f"[{section}] {k}: live-trading/credential settings are not supported in this milestone")
        if k not in known:
            raise ValueError(f"unknown config key [{section}] {k}")
        setattr(dc, k, v)


def _check_tz(name: str):
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo(name)
    except Exception as e:
        raise ValueError(f"unknown timezone {name!r} (use an IANA name like America/Chicago)") from e


def load_config(path: str | Path | None = None) -> AppConfig:
    cfg = AppConfig()
    if path is None:
        path = Path("config.toml")
        if not path.exists():
            return cfg
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    for section in ("market", "model", "paper", "weather", "auto", "readiness"):
        if section in data:
            _apply(getattr(cfg, section), data.pop(section), section)
    for i, c in enumerate(data.pop("cities", []) or []):
        city = CityConfig(series_ticker="")
        _apply(city, c, f"cities[{i}]")
        if not city.series_ticker:
            raise ValueError(f"cities[{i}] needs series_ticker")
        _check_tz(city.timezone)
        cfg.cities.append(city)
    _apply(cfg, data, "top-level")
    _check_tz(cfg.market.timezone)
    if cfg.weather.provider not in ("open_meteo", "nws", "manual"):
        raise ValueError("weather.provider must be 'open_meteo', 'nws' or 'manual'")
    if cfg.auto.update_every_minutes and cfg.auto.update_every_minutes < 5:
        raise ValueError("auto.update_every_minutes must be 0 (off) or at least 5")
    if cfg.market.source not in ("sample", "kalshi_public"):
        raise ValueError("market.source must be 'sample' or 'kalshi_public'")
    if cfg.host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("dashboard binds to localhost only")
    return cfg
