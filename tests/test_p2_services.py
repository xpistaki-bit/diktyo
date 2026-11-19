"""Dienste-Scan (nmap) auf Knopfdruck – echter nmap-Lauf gegen einen kleinen Webserver auf 127.0.0.1."""
import http.server
import shutil
import threading

import pytest

from app import worker
from app.db import db
from app.scan import services
from tests.test_m6 import H, login

SAMPLE = """<?xml version="1.0"?><nmaprun><host><address addr="192.0.2.5" addrtype="ipv4"/><ports>
<port protocol="tcp" portid="443"><state state="open"/><service name="http" product="nginx" version="1.24" tunnel="ssl"/>
 <script id="http-title" output="FRITZ!Box"/><script id="ssl-cert" output="..."><table key="subject"><elem key="commonName">fritz.box</elem></table>
 <table key="issuer"><elem key="organizationName">AVM</elem></table><table key="validity"><elem key="notAfter">2038-01-15T00:00:00</elem></table></script></port>
<port protocol="tcp" portid="22"><state state="open"/><service name="ssh" product="OpenSSH" version="9.6"/></port>
<port protocol="tcp" portid="23"><state state="closed"/></port></ports>
<os><osmatch name="Linux 5.X" accuracy="95"/></os></host></nmaprun>"""


def test_parse_nmap_xml():
    h = services.parse(SAMPLE)["192.0.2.5"]
    assert [p["port"] for p in h["ports"]] == [22, 443] and h["os"] == "Linux 5.X"
    web = h["ports"][1]
    assert web["web"] == "https" and web["tls"] and web["title"] == "FRITZ!Box"
    assert web["cert"] == {"subject": "fritz.box", "issuer": "AVM", "not_after": "2038-01-15T00:00:00"}
    assert h["ports"][0]["web"] == "" and h["ports"][0]["product"] == "OpenSSH"


class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><head><title>diktyo Testseite</title></head><body>ok</body></html>")

    def log_message(self, *a):
        pass


@pytest.mark.skipif(not shutil.which("nmap"), reason="nmap fehlt")
def test_services_scan_job_real_nmap():
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8080), Page)
    except OSError:
        pytest.skip("Port 8080 belegt")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cl = login()
        pid = cl.post("/api/profiles", json={"name": "Dienste"}, headers=H).json()["profile"]["id"]
        P = f"/api/profiles/{pid}"
        did = cl.post(f"{P}/devices", json={"name": "Testserver", "type": "server", "ips": [{"address": "127.0.0.1"}]}, headers=H).json()["id"]
        r = cl.post(f"{P}/devices/{did}/services-scan", json={"depth": "quick"}, headers=H).json()
        assert r["job"]["status"] == "queued" and r["job"]["params"]["ips"] == ["127.0.0.1"]
        # doppelt starten liefert denselben Auftrag
        assert cl.post(f"{P}/devices/{did}/services-scan", json={}, headers=H).json()["job"]["id"] == r["job"]["id"]
        assert cl.get(f"{P}/devices/{did}").json()["services_job"] == r["job"]["id"]
        with db() as c:
            job = c.execute("SELECT * FROM jobs WHERE id=?", (r["job"]["id"],)).fetchone()
        worker.run_job(job)
        j = cl.get(f"/api/jobs/{r['job']['id']}").json()
        assert j["status"] == "done", j
        d = cl.get(f"{P}/devices/{did}").json()
        port = next(p for p in d["services_scan"]["hosts"]["127.0.0.1"]["ports"] if p["port"] == 8080)
        assert port["web"] == "http" and "Testseite" in port["title"] and d["services_job"] is None
    finally:
        srv.shutdown()


def test_services_scan_needs_ip():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Dienste2"}, headers=H).json()["profile"]["id"]
    did = cl.post(f"/api/profiles/{pid}/devices", json={"name": "ohne IP", "type": "other"}, headers=H).json()["id"]
    r = cl.post(f"/api/profiles/{pid}/devices/{did}/services-scan", json={}, headers=H)
    assert r.status_code == 400 and "IPv4" in r.json()["error"]
