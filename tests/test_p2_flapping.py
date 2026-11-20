"""Kein Hin und Her mehr: genauere Verbindungen haben Vorrang, und andere Quellen halten ein Gerät online, wenn nur der Ping scheitert."""
import time

from app import integrations, monitor
from app.db import db, now
from app.scan import discover, runner
from tests.test_m6 import H, login


def _setup(name):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    mk = lambda n, t, ip: cl.post(f"{P}/devices", json=dict(name=n, type=t, ips=[{"address": ip}]), headers=H).json()["id"]  # noqa: E731
    return cl, pid, P, mk


def _uplink(cl, P, did):
    d = cl.get(f"{P}/devices/{did}").json()["uplink"]
    return (d["device_name"], d["medium"]) if d else None


def test_router_lan_does_not_override_proxmox_virtual():
    cl, pid, P, mk = _setup("Uplink-Vorrang")
    router, host, vm = mk("Router", "router", "192.0.2.1"), mk("Dell", "hypervisor", "192.0.2.13"), mk("panelatlas", "vm", "192.0.2.40")
    with db() as c:
        assert integrations.set_auto_uplink(c, pid, vm, host, "virtual", source="proxmox")
        # der Router sieht die VM als kabelgebundenen Client in seinem LAN – ungenauer, darf nicht überschreiben
        assert not integrations.set_auto_uplink(c, pid, vm, router, "lan", source="asuswrt")
        assert integrations.set_auto_uplink(c, pid, vm, host, "virtual", source="proxmox") is False  # nur bestätigt
    assert _uplink(cl, P, vm) == ("Dell", "virtual")
    # Proxmox bestätigt lange nicht mehr (VM umgezogen, Integration entfernt): dann darf die ungenauere Quelle
    with db() as c:
        c.execute("UPDATE links SET confirmed=? WHERE profile_id=?", (time.time() - 2 * integrations.STALE_LINK, pid))
        assert integrations.set_auto_uplink(c, pid, vm, router, "lan", source="asuswrt")
    assert _uplink(cl, P, vm) == ("Router", "lan")
    # genauere Angabe setzt sich jederzeit durch
    with db() as c:
        assert integrations.set_auto_uplink(c, pid, vm, host, "virtual", source="proxmox")
    assert _uplink(cl, P, vm) == ("Dell", "virtual")


def test_ping_failure_ignored_when_other_source_saw_device(monkeypatch):
    cl, pid, P, mk = _setup("NAT-Switch")
    sw = mk("XGS1935", "switch", "192.0.2.2")
    with db() as c:
        c.execute("UPDATE devices SET status='confirmed' WHERE id=?", (sw,))
        runner._set_online(c, sw, 1, now(), "fritzbox")  # FRITZ!Box meldet ihn aktiv

    async def no(*a, **k):
        return None

    async def no_tcp(*a, **k):
        return False
    monkeypatch.setattr(discover, "ping_rtt", no)
    monkeypatch.setattr(discover, "tcp", no_tcp)
    monitor._misses.clear()
    for _ in range(3):
        monitor.run(pid)
    state = lambda: cl.get(f"{P}/devices/{sw}").json()["online"]  # noqa: E731
    assert state() == 1
    assert cl.post(f"{P}/ping", json={"device_ids": [sw]}, headers=H).json()["online"] == 0 and state() == 1  # Schnell-Ping ebenso
    # die FRITZ!Box hat ihn schon lange nicht mehr gesehen: dann zählt der Ping
    with db() as c:
        c.execute("UPDATE device_seen SET ts=? WHERE device_id=?", (time.time() - 3600, sw))
    monitor.run(pid)
    monitor.run(pid)
    assert state() == 0
    with db() as c:
        n = c.execute("SELECT COUNT(*) FROM status_events WHERE device_id=?", (sw,)).fetchone()[0]
    assert n == 2  # einmal online, einmal offline – kein Flattern


def test_grace_follows_integration_interval_and_quick_ping_rechecks(monkeypatch):
    cl, pid, P, mk = _setup("Mesh-Knoten")
    node = mk("EBM68 Küche", "mesh", "192.0.2.95")
    with db() as c:
        c.execute("UPDATE devices SET status='confirmed' WHERE id=?", (node,))
        runner._set_online(c, node, 1, now(), "asuswrt")
        c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, interval_s, created) VALUES(?,?,?,?,?,?,?)",
                  (pid, "asuswrt", "ASUS", "192.0.2.1", "{}", 900, now()))
        # ASUS fragt nur alle 15 Minuten ab: eine 12 Minuten alte Sichtung zählt noch
        c.execute("UPDATE device_seen SET ts=? WHERE device_id=?", (time.time() - 720, node))
        assert node in monitor.seen_by_others(c, pid, 600)
        c.execute("UPDATE device_seen SET ts=? WHERE device_id=?", (time.time() - 3000, node))
        assert node not in monitor.seen_by_others(c, pid, 600)
    calls = []

    async def flaky(ip, timeout=1.0):  # in der Lastspitze keine Antwort, einzeln mit Geduld schon
        calls.append(timeout)
        return 4.2 if timeout >= 3.0 else None

    async def no_tcp(*a, **k):
        return False
    monkeypatch.setattr(discover, "ping_rtt", flaky)
    monkeypatch.setattr(discover, "tcp", no_tcp)
    r = cl.post(f"{P}/ping", json={"device_ids": [node]}, headers=H).json()
    assert r["online"] == 1 and 3.0 in calls
    assert cl.get(f"{P}/devices/{node}").json()["online"] == 1
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM status_events WHERE device_id=? AND online=0", (node,)).fetchone()[0] == 0
