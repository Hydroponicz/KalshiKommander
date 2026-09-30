import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kalshikommander.config import AppConfig  # noqa: E402
from kalshikommander.marketdata.sample import SampleSource  # noqa: E402
from kalshikommander.service import App  # noqa: E402
from kalshikommander.storage import Store  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    # 2026-09-30 10:00 America/New_York (EDT, UTC-4)
    return Clock(datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc))


@pytest.fixture
def app(clock):
    cfg = AppConfig()
    src = SampleSource("America/New_York", today=date(2026, 9, 30))
    return App(cfg, source=src, store=Store(":memory:"), clock=clock)


def market_json(**over):
    m = {
        "ticker": "KXTEST-26SEP30-T80", "event_ticker": "KXTEST-26SEP30", "status": "active",
        "title": "Highest temperature in Testville on Sep 30, 2026?", "yes_sub_title": "81° or above",
        "open_time": "2026-09-29T14:00:00Z", "close_time": "2026-10-01T04:59:00Z",
        "expiration_time": "2026-10-01T15:00:00Z", "strike_type": "greater", "floor_strike": 80,
        "cap_strike": None,
        "rules_primary": "If the highest temperature recorded at Testville for September 30, 2026 as reported "
                         "by the Test Service is greater than 80°, then the market resolves to Yes.",
        "rules_secondary": "", "yes_bid": 40, "yes_ask": 45, "no_bid": 55, "no_ask": 60, "last_price": 42,
        "volume": 10, "open_interest": 5, "result": "",
    }
    m.update(over)
    return m


SERIES = {"ticker": "KXTEST", "settlement_sources": [{"name": "Test Service", "url": "https://example.com"}],
          "contract_url": "https://example.com/terms.pdf"}
