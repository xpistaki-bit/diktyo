"""Regressionstests für die Fehler aus dem ersten Praxistest (0.3.1)."""
import asyncio
import datetime
import resource

from fastapi.testclient import TestClient

from app import main, users
from app.db import db, now, parse_ts
from app.scan import discover

H = {"X-Requested-With": "diktyo"}


def login(email="fix@x.de"):
    with db() as c:
        if not users.by_email(c, email):
            users.create(c, email, "passwort123", is_admin=True)
    cl = TestClient(main.app)
    assert cl.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H).status_code == 200
    return cl


def test_full_sweep_with_low_file_limit():
    """„Too many open files“: der volle Scan darf auch mit 1024 offenen Dateien nicht scheitern."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (512, hard))
    try:
        ips = [f"127.0.0.{i}" for i in range(1, 60)]
        res = asyncio.run(discover.sweep(ips, discover.FULL_PORTS))
        assert len(res) == len(ips)
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def test_timestamps_have_timezone():
    assert parse_ts(now()).tzinfo is not None
    assert parse_ts("2026-11-18T23:11:00").tzinfo is not None  # alte Werte ohne Zone
    assert parse_ts(now()) > datetime.datetime.now().astimezone() - datetime.timedelta(minutes=1)


def test_scan_ips_follow_dhcp_range_and_hints_can_be_acked():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Hinweise"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    sn = cl.post(f"{P}/subnets", json={"cidr": "192.168.50.0/24", "gateway": "192.168.50.1"}, headers=H).json()["subnets"][0]
    # doppelt anlegen geht nicht, Meldung auf Englisch übersetzt
    r = cl.post(f"{P}/subnets", json={"cidr": "192.168.50.0/24"}, headers={**H, "X-Lang": "en"})
    assert r.status_code == 409 and r.json()["error"] == "The subnet 192.168.50.0/24 already exists"
    # vom Scan gefunden (statisch, weil es noch keinen DHCP-Bereich gibt) und ein von Hand eingetragenes Gerät
    cl.post(f"{P}/devices", json={"name": "Shelly", "status": "discovered", "ips": [{"address": "192.168.50.30", "kind": "static", "source": "scan"}]}, headers=H)
    cl.post(f"{P}/devices", json={"name": "NAS", "ips": [{"address": "192.168.50.40", "kind": "static"}]}, headers=H)
    r = cl.put(f"{P}/subnets/{sn['id']}", json={"cidr": "192.168.50.0/24", "gateway": "192.168.50.1",
                                                 "dhcp_start": "192.168.50.20", "dhcp_end": "192.168.50.220"}, headers=H).json()
    hints = r["conflicts"]
    # nur das manuell statisch eingetragene NAS erzeugt den Hinweis, der Scan-Eintrag wurde zu DHCP
    assert [h["ip"] for h in hints if h["code"] == "in_dhcp"] == ["192.168.50.40"]
    shelly = next(d for d in cl.get(f"{P}/devices").json()["devices"] if d["name"] == "Shelly")
    assert shelly["ips"][0]["kind"] == "dhcp"
    # Hinweis als gelesen markieren und wieder einblenden
    key = hints[0]["key"]
    r = cl.post(f"{P}/hints/ack", json={"keys": [key], "ack": True}, headers=H).json()
    assert all(h["acked"] for h in r["conflicts"] if h["key"] == key)
    r = cl.post(f"{P}/hints/ack", json={"keys": [key], "ack": False}, headers=H).json()
    assert not any(h["acked"] for h in r["conflicts"])
    # Gerät bearbeiten, ohne die IP zu ändern: Herkunft bleibt „scan“
    cl.put(f"{P}/devices/{shelly['id']}", json={"name": "Shelly Küche", "ips": [{"address": "192.168.50.30", "kind": "dhcp"}]}, headers=H)
    with db() as c:
        assert c.execute("SELECT source FROM ip_addresses WHERE address='192.168.50.30'").fetchone()["source"] == "scan"


def test_job_keeps_mode_and_targets():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Verlauf"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    cl.put(f"{P}/scan", json={"mode": "light", "targets": ["192.168.178.0/24"]}, headers=H)
    job = cl.post(f"{P}/scan/run", json={}, headers=H).json()["job"]
    assert job["params"]["mode"] == "light" and job["params"]["targets"] == ["192.168.178.0/24"]
    cl.put(f"{P}/scan", json={"mode": "passive"}, headers=H)  # spätere Änderung verfälscht den Verlauf nicht
    jobs = cl.get(f"{P}/scan").json()["jobs"]
    assert jobs[0]["params"]["mode"] == "light"
    with db() as c:
        c.execute("UPDATE jobs SET status='error', message='Test' WHERE id=?", (job["id"],))
