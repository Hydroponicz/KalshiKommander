import threading
import time
import urllib.request
from datetime import date
from http.server import HTTPServer

from kalshikommander.config import AppConfig
from kalshikommander.marketdata.sample import SampleSource
from kalshikommander.service import App
from kalshikommander.storage import Store
from kalshikommander.web import BackgroundUpdater, Dashboard, make_handler


class SlowSource(SampleSource):
    """Simulates a long update (many cities, slow network)."""
    def get_series(self, series_ticker):
        time.sleep(1.5)
        return super().get_series(series_ticker)


def _cfg(tmp_path):
    cfg = AppConfig()
    cfg.data_dir = str(tmp_path)
    return cfg


def _wait(pred, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_dashboard_stays_responsive_during_a_slow_update(tmp_path):
    cfg = _cfg(tmp_path)
    ui = App(cfg, source=SampleSource(today=date.today()), store=Store(cfg.db_path))
    updater = BackgroundUpdater(ui, 5, lambda: App(cfg, source=SlowSource(today=date.today()),
                                                   store=Store(cfg.db_path))).start()
    srv = HTTPServer(("127.0.0.1", 0), make_handler(Dashboard(ui, updater), {"127.0.0.1"}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert _wait(lambda: updater.running, 5)  # scheduled update starts immediately...
        t0 = time.time()
        page = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/", timeout=5).read().decode()
        assert time.time() - t0 < 1.0          # ...but the page still answers right away
        assert "Updating now" in page and "http-equiv='refresh'" in page
        assert _wait(lambda: not updater.running and ui.last_update is not None, 15)
        assert ui.last_update[1]["prices"]["markets"] == 20  # worker's writes visible to the dashboard
        assert ui.store.one("SELECT COUNT(*) n FROM market_snapshots")["n"] == 20
    finally:
        srv.shutdown()


def test_update_button_runs_in_background_and_reports_busy(tmp_path):
    cfg = _cfg(tmp_path)
    ui = App(cfg, source=SampleSource(today=date.today()), store=Store(cfg.db_path))
    updater = BackgroundUpdater(ui, 0, lambda: App(cfg, source=SlowSource(today=date.today()),
                                                   store=Store(cfg.db_path))).start()
    d = Dashboard(ui, updater)
    assert not updater.running  # manual mode: nothing runs until asked
    assert "started in the background" in d.post("/update", {})
    assert _wait(lambda: updater.running, 5)
    assert "already running" in d.post("/update", {})
    assert _wait(lambda: not updater.running, 15)
    assert ui.last_update[1]["decisions"] == 0  # button-only mode doesn't record decisions
