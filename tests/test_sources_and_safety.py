import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from kalshikommander.config import load_config
from kalshikommander.marketdata.base import looks_like_daily_high_series
from kalshikommander.marketdata.kalshi_public import KalshiPublicClient, NotAllowedError
from kalshikommander.weather.nws import extract_daily_high
from tests.conftest import FIXTURES

PKG = Path(__file__).resolve().parents[1] / "kalshikommander"


def test_nws_parser_picks_daytime_period_for_local_date():
    fc = json.loads((FIXTURES / "nws_forecast.json").read_text())
    r = extract_daily_high(fc, date(2026, 10, 1))
    assert r["expected_high"] == 70 and r["unit"] == "F"
    assert r["issued_at"] == datetime(2026, 9, 30, 8, 12, 34, tzinfo=timezone.utc)
    assert extract_daily_high(fc, date(2026, 10, 5)) is None  # never invented


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_public_client_is_get_only_and_allowlisted():
    seen = []

    def opener(req, timeout):
        seen.append((req.get_method(), req.full_url, dict(req.header_items())))
        return FakeResp(json.dumps({"market": {"ticker": "X"}}).encode())

    c = KalshiPublicClient(opener=opener, min_interval=0)
    assert c.get_market("KXHIGHNY-26SEP30-T80")["ticker"] == "X"
    assert seen[0][0] == "GET" and "/markets/KXHIGHNY-26SEP30-T80" in seen[0][1]
    assert not any(k.lower().startswith("kalshi-access") or k.lower() == "authorization" for k in seen[0][2])
    for bad in ("/portfolio/orders", "/portfolio/balance", "/markets/X/../../portfolio/orders", "/login"):
        with pytest.raises(NotAllowedError):
            c._get(bad)


def test_series_filter():
    assert looks_like_daily_high_series({"ticker": "KXHIGHNY", "title": "Highest temperature in NYC", "frequency": "daily"})
    assert not looks_like_daily_high_series({"ticker": "KXRAIN", "title": "Rain in NYC", "frequency": "daily"})


def test_no_order_placement_code_in_package():
    """Guard: the package must not reference order/portfolio endpoints or request signing."""
    pattern = re.compile(r"portfolio|/orders|create_order|place_order|\bRSA\b|private_key|KALSHI-ACCESS", re.I)
    offenders = []
    for p in PKG.rglob("*.py"):
        code = re.sub(r"#.*|\"\"\"[\s\S]*?\"\"\"", "", p.read_text())
        # the config deny-list names forbidden keys in order to REJECT them
        code = "\n".join(l for l in code.splitlines() if "_FORBIDDEN_KEYS =" not in l)
        if pattern.search(code):
            offenders.append(p.name)
    assert offenders == []


def test_no_http_write_methods_in_package():
    for p in PKG.rglob("*.py"):
        assert not re.search(r"method\s*=\s*[\"'](POST|PUT|DELETE|PATCH)[\"']", p.read_text()), p


def test_config_rejects_live_or_credential_keys(tmp_path):
    for key in ("live_trading = true", "api_key = \"x\"", "enable_live = true"):
        f = tmp_path / "c.toml"
        f.write_text(f"[paper]\n{key}\n")
        with pytest.raises(ValueError):
            load_config(f)
    f = tmp_path / "c.toml"
    f.write_text('host = "0.0.0.0"\n')
    with pytest.raises(ValueError):
        load_config(f)


def test_example_config_loads():
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.example.toml")
    assert cfg.market.source == "sample" and cfg.paper.max_stake_per_market > 0
