import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

from kalshikommander.web import Dashboard, make_handler

T = "SAMPLE-HIGHTEMP-26SEP30-T74"


def test_pages_render_and_label_paper(app, clock):
    d = Dashboard(app)
    page = d.index({})
    assert "PAPER / SIMULATED" in page and "SAMPLE DATA" in page and "How to use this page" in page
    assert "Sampleville" in page and "Testburg" in page
    app.refresh()
    assert "Needs your forecast" in d.index({})
    d.post("/forecast", {"series": "SAMPLE-HIGHTEMP", "target_date": "2026-09-30", "expected_high": "75.5", "unit": "F",
                         "sigma": "", "issued_at": "2026-09-30T08:00", "source": "manual"})
    assert "Review this city&#x27;s rules once" in d.index({}) or "Review this city's rules once" in d.index({})
    d.post("/ack", {"ticker": T})
    msg = d.post("/decide", {"ticker": T})
    assert "buy yes" in msg
    page = d.market({"t": T})
    for s in ("Will the high in Sampleville (SAMPLE) on Wed Sep 30 be 75°F or above?", "Official rules",
              "Prices you could actually pay", "Full order book", "Try a different ±", "The math behind the verdict",
              "Simulate paper order"):
        assert s in page, s
    assert "Paper-buy YES" in d.index({"city": "SAMPLE-HIGHTEMP"})
    assert d.index({"city": "SAMPLE-HIGHTEMP"}).count("<section class='card'>") == 1  # city filter
    assert d.index({}).count("<section class='card'>") == 2
    clock.advance(seconds=30)
    assert "order: filled, 2 contracts" in d.post("/execute", {"decision_id": "1"})
    for page in (d.ledger_page({}), d.evaluate_page({}), d.cities_page({}), d.help_page({})):
        assert "PAPER / SIMULATED" in page
    assert "id='eq'" in d.ledger_page({})


def test_decide_city_records_one_day(app, clock):
    app.refresh()
    msg = Dashboard(app).post("/decide_city", {"series": "SAMPLE-HIGHTEMP2", "date": "2026-09-30"})
    assert msg.startswith("Recorded 5 decisions")


def test_server_rejects_foreign_host_and_origin(app):
    srv = HTTPServer(("127.0.0.1", 0), make_handler(Dashboard(app), {"127.0.0.1", "localhost"}))
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        for path in ("/", "/cities", "/ledger", "/evaluate", "/help"):
            assert urllib.request.urlopen(f"http://127.0.0.1:{port}{path}").status == 200
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": "evil.example"})
        try:
            urllib.request.urlopen(req)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 403
        req = urllib.request.Request(f"http://127.0.0.1:{port}/refresh", data=b"", method="POST",
                                     headers={"Origin": "http://evil.example"})
        try:
            urllib.request.urlopen(req)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        srv.shutdown()


def test_sample_mode_says_auto_forecasts_off(app):
    page = Dashboard(app).index({})
    assert "Automatic forecasts are off in sample mode" in page
    assert "Refresh prices for all cities" in page
