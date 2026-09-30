import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer

from kalshikommander.web import Dashboard, make_handler

T = "SAMPLE-HIGHTEMP-26SEP30-T74"


def test_pages_render_and_label_paper(app, clock):
    d = Dashboard(app)
    assert "PAPER / SIMULATED" in d.index({}) and "SAMPLE DATA" in d.index({})
    app.refresh()
    d.post("/forecast", {"target_date": "2026-09-30", "expected_high": "75.5", "unit": "F", "sigma": "",
                         "issued_at": "2026-09-30T08:00", "source": "manual", "source_detail": ""})
    d.post("/ack", {"ticker": T})
    msg = d.post("/decide", {"ticker": T})
    assert "BUY_YES" in msg
    page = d.market({"t": T})
    assert "Order book depth" in page and "reported high ≥ 75°F" in page and "Rules (verbatim" in page
    assert "Try σ" in page
    assert "Simulate paper order" in d.index({})
    assert "Forward-test evaluation" in d.evaluate_page({})


def test_server_rejects_foreign_host_and_origin(app):
    srv = HTTPServer(("127.0.0.1", 0), make_handler(Dashboard(app), {"127.0.0.1", "localhost"}))
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/").status == 200
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
