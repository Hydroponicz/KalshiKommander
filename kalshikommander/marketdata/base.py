from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    name: str = "base"
    is_sample: bool = False

    @abstractmethod
    def list_series(self) -> list[dict]: ...

    @abstractmethod
    def get_series(self, series_ticker: str) -> dict: ...

    @abstractmethod
    def list_events(self, series_ticker: str) -> list[dict]:
        """Events with nested `markets` lists."""

    @abstractmethod
    def get_market(self, ticker: str) -> dict: ...

    @abstractmethod
    def get_orderbook(self, ticker: str) -> dict: ...


HIGH_TEMP_WORDS = ("high temp", "highest temp", "high temperature", "highest temperature", "max temp")


def looks_like_daily_high_series(series: dict) -> bool:
    text = " ".join(str(series.get(k, "")) for k in ("title", "ticker")).lower()
    freq = str(series.get("frequency", "")).lower()
    return any(w in text for w in HIGH_TEMP_WORDS) and freq in ("", "daily")
