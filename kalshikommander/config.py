"""Configuration loading. There is intentionally NO setting that enables live trading."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class MarketConfig:
    source: str = "sample"          # "sample" (clearly labeled fake data) or "kalshi_public"
    series_ticker: str = ""         # choose with `python -m kalshikommander discover`
    city_label: str = ""
    timezone: str = "America/New_York"


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
    provider: str = "manual"        # "manual" or "nws" (optional api.weather.gov helper)
    latitude: float | None = None
    longitude: float | None = None
    nws_user_agent: str = "KalshiKommander-research (set-your-email@example.com)"


@dataclass
class AppConfig:
    market: MarketConfig = field(default_factory=MarketConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
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


def load_config(path: str | Path | None = None) -> AppConfig:
    cfg = AppConfig()
    if path is None:
        path = Path("config.toml")
        if not path.exists():
            return cfg
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    for section in ("market", "model", "paper", "weather"):
        if section in data:
            _apply(getattr(cfg, section), data.pop(section), section)
    _apply(cfg, data, "top-level")
    if cfg.market.source not in ("sample", "kalshi_public"):
        raise ValueError("market.source must be 'sample' or 'kalshi_public'")
    if cfg.host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("dashboard binds to localhost only")
    return cfg
