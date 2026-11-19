"""Erreichbarkeit (Verfügbarkeit, Ausfälle, Antwortzeit) und Firmware-Hinweise."""
import datetime as dt
import json

from app import health, monitor
from app.db import db, now
from app.scan import discover
from tests.test_m6 import H, login

TZ = dt.datetime.now().astimezone().tzinfo


def ev(c, did, t, online):
    c.execute("INSERT INTO status_events(device_id, ts, online, source) VALUES(?,?,?,?)", (did, t.isoformat(timespec="seconds"), online, "ping"))


def test_availability_segments():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Health"}, headers=H).json()["profile"]["id"]
    did = cl.post(f"/api/profiles/{pid}/devices", json={"name": "AP", "type": "ap", "status": "confirmed"}, headers=H).json()["id"]
    t = dt.datetime(2026, 11, 20, 12, 0, tzinfo=TZ)
    with db() as c:
        c.execute("DELETE FROM status_events WHERE device_id=?", (did,))
        assert health.availability(c, did, 24, t) is None  # nie überwacht
        ev(c, did, t - dt.timedelta(hours=30), 1)    # schon vor dem Zeitraum online
        ev(c, did, t - dt.timedelta(hours=10), 0)    # Ausfall 1: 1 h (mit doppelter Offline-Meldung)
        ev(c, did, t - dt.timedelta(hours=9, minutes=30), 0)
        ev(c, did, t - dt.timedelta(hours=9), 1)
        ev(c, did, t - dt.timedelta(hours=8), 1)     # doppelte Online-Meldung darf nicht doppelt zählen
        ev(c, did, t - dt.timedelta(hours=2), 0)     # Ausfall 2: 30 min
        ev(c, did, t - dt.timedelta(hours=1, minutes=30), 1)
        a = health.availability(c, did, 24, t)
    assert a["covered_s"] == 24 * 3600 and a["outages"] == 2 and a["longest_s"] == 3600
    assert a["pct"] == round(100 * (24 - 1.5) / 24, 2)


def test_rtt_from_monitor_and_health_api(monkeypatch):
    async def fake_rtt(ip, timeout=1.0):
        return 3.4 if ip.endswith(".10") else None

    async def fake_tcp(ip, port, timeout=0.8):
        return False
    monkeypatch.setattr(discover, "ping_rtt", fake_rtt)
    monkeypatch.setattr(discover, "tcp", fake_tcp)
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Health-RTT"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    nas = cl.post(f"{P}/devices", json={"name": "NAS", "type": "nas", "status": "confirmed", "ips": [{"address": "192.0.2.10"}]}, headers=H).json()["id"]
    cam = cl.post(f"{P}/devices", json={"name": "Kamera", "type": "camera", "status": "confirmed", "ips": [{"address": "192.0.2.11"}]}, headers=H).json()["id"]
    r = monitor.run(pid)
    assert r == {"checked": 2, "online": 1}
    h = cl.get(f"{P}/devices/{nas}/health").json()
    assert h["rtt_24h"] == 3.4 and h["availability"]["24"] is None  # erst eine Messung: noch kein Zeitraum abgedeckt
    m = cl.get(f"{P}/metrics?keys=d{nas}:rtt&since=7200").json()
    assert m["series"][f"d{nas}:rtt"][0][1] == 3.4
    ov = {x["name"]: x for x in cl.get(f"{P}/health").json()["devices"]}
    assert ov["Kamera"]["online"] == 0 and ov["NAS"]["rtt"] == 3.4
    q = cl.post(f"{P}/ping", json={"device_ids": [nas]}, headers=H).json()
    assert q["rtt"] == {str(nas): 3.4}
    assert cam


def test_firmware_apply_history_and_event():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Firmware"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    fb = cl.post(f"{P}/devices", json={"name": "FRITZ!Box", "type": "router", "status": "confirmed"}, headers=H).json()["id"]
    with db() as c:
        health.apply_firmware(c, pid, fb, dict(installed="7.57", latest="", update=False), "fritzbox")
        health.apply_firmware(c, pid, fb, dict(installed="7.57", latest="8.02", update=True, info="https://avm.de/x"), "fritzbox")
        health.apply_firmware(c, pid, fb, dict(installed="7.57", latest="8.02", update=True), "fritzbox")  # keine zweite Meldung
        health.apply_firmware(c, pid, fb, dict(installed="8.02", latest="", update=False), "fritzbox")
        evs = [json.loads(r["data"]) for r in c.execute("SELECT data FROM events WHERE profile_id=? AND kind='firmware_update'", (pid,))]
        hist = c.execute("SELECT old, new FROM changes WHERE profile_id=? AND field='firmware'", (pid,)).fetchall()
    assert len(evs) == 1 and evs[0]["latest"] == "8.02" and evs[0]["installed"] == "7.57"
    assert [tuple(x) for x in hist] == [("7.57", "8.02")]
    h = cl.get(f"{P}/devices/{fb}/health").json()
    assert h["firmware"]["installed"] == "8.02" and h["firmware"]["update"] is False
    # Topologie-Markierung
    with db() as c:
        health.apply_firmware(c, pid, fb, dict(installed="8.02", latest="8.10", update=True), "fritzbox")
    t = cl.get(f"{P}/topology").json()
    assert next(n for n in t["nodes"] if n.get("device_id") == fb)["fw_update"] is True
    hist = cl.get(f"{P}/history?device_id={fb}").json()["items"]
    assert any(x.get("field") == "firmware" for x in hist)
    assert now()
