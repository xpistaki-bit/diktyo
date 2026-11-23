"""Nur Netzwerkanschlüsse am Gerät: USB, HDMI, Thunderbolt, MagSafe, Kartenleser bleiben im Katalog, werden aber keine
Ports; bestehende Geräte werden einmalig umnummeriert (Verbindungen und Kabelwege bleiben am richtigen Port)."""
import json

from app import catalog
from app.db import db, now
from tests.test_m6 import H, login

FEDORA = [dict(count=1, kind="rj45", speed="1G", label="LAN (RJ45 Gigabit)"), dict(count=6, kind="usb", speed="", label="USB 3.0 (USB-A)"),
          dict(count=1, kind="rj45", speed="", label="USB-C (vorne laut Handbuch)")]
MAC = [dict(count=3, kind="rj45", speed="", label="Thunderbolt 4"), dict(count=1, kind="rj45", speed="", label="HDMI"),
       dict(count=1, kind="rj45", speed="", label="SDXC-Kartenleser"), dict(count=1, kind="rj45", speed="", label="MagSafe 3 (Ladeanschluss)")]
PC = [dict(count=2, kind="usb", speed="", label="USB"), dict(count=2, kind="rj45", speed="2.5G", label="LAN"),
      dict(count=1, kind="rj45", speed="", label="Power over Ethernet")]


def test_is_network():
    assert [catalog.is_network(g) for g in FEDORA] == [True, False, False]
    assert not any(catalog.is_network(g) for g in MAC)
    assert [catalog.is_network(g) for g in PC] == [False, True, True]  # „Power over Ethernet“ ist ein Netzwerkport
    assert [(p["port_no"], p["name"]) for p in catalog.expand_ports(PC)] == [(1, "LAN 1"), (2, "LAN 2"), (3, "Power over Ethernet")]
    assert len(catalog.expand_ports(PC, network_only=False)) == 5
    assert catalog.format_ports(FEDORA).count("usb") == 1  # Katalog behält alles


def test_device_gets_network_ports_only():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Nur Netzwerk"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    did = cl.post(f"{P}/devices", json={"name": "Fedora", "type": "computer", "ports": FEDORA}, headers=H).json()["id"]
    d = cl.get(f"{P}/devices/{did}").json()
    assert [p["name"] for p in d["ports"]] == ["LAN (RJ45 Gigabit)"] and [g["label"] for g in d["port_groups"]] == ["LAN (RJ45 Gigabit)"]
    mac = cl.post(f"{P}/devices", json={"name": "MacBook", "type": "laptop", "ports": MAC}, headers=H).json()["id"]
    assert cl.get(f"{P}/devices/{mac}").json()["ports"] == []


def test_migration_renumbers_once():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Umnummerieren"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    sw = cl.post(f"{P}/devices", json={"name": "Switch", "type": "switch", "ports": [dict(count=8, kind="rj45", speed="1G")]}, headers=H).json()["id"]
    pc = cl.post(f"{P}/devices", json={"name": "PC", "type": "computer"}, headers=H).json()["id"]
    nas = cl.post(f"{P}/devices", json={"name": "NAS", "type": "nas"}, headers=H).json()["id"]
    with db() as c:  # Stand vor 0.30.1: Ports über alle Gruppen gezählt, USB als eigene Ports
        c.execute("DELETE FROM settings WHERE key='ports_network_only'")
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(dict(ports=PC)), pc))
        old = {}
        for no, (name, kind) in enumerate([("USB 1", "usb"), ("USB 2", "usb"), ("LAN 1", "rj45"), ("LAN 2", "rj45"), ("Power over Ethernet", "rj45")], start=1):
            old[no] = c.execute("INSERT INTO interfaces(device_id, role, name, kind, port_no) VALUES(?, 'port', ?, ?, ?)", (pc, name, kind, no)).lastrowid
        nic = c.execute("SELECT id FROM interfaces WHERE device_id=? AND role='nic'", (nas,)).fetchone()["id"]
        c.execute("INSERT INTO links(profile_id, a_if, b_if, medium, uplink, source) VALUES(?,?,?,'lan',1,'manual')", (pid, nic, old[4]))
        c.execute("INSERT INTO cable_runs(profile_id, switch_id, switch_port, cable_a, updated) VALUES(?,?,?,?,?)", (pid, pc, 4, "K-7", now()))
        catalog.network_ports_once(c)
        ports = [(r["port_no"], r["name"], r["id"]) for r in c.execute("SELECT * FROM interfaces WHERE device_id=? AND role='port' ORDER BY port_no", (pc,))]
        assert [(n, nm) for n, nm, _ in ports] == [(1, "LAN 1"), (2, "LAN 2"), (3, "Power over Ethernet")]
        assert ports[1][2] == old[4]  # gleiche Schnittstelle, Verbindung zum NAS hängt weiter daran
        assert c.execute("SELECT COUNT(*) FROM links WHERE b_if=?", (old[4],)).fetchone()[0] == 1
        assert c.execute("SELECT switch_port FROM cable_runs WHERE switch_id=?", (pc,)).fetchone()[0] == 2
        assert [g["label"] for g in json.loads(c.execute("SELECT data FROM devices WHERE id=?", (pc,)).fetchone()["data"])["ports"]] == ["LAN", "Power over Ethernet"]
        # Switch ohne Nicht-Netzwerkgruppen bleibt unberührt; zweiter Lauf tut nichts
        assert c.execute("SELECT COUNT(*) FROM interfaces WHERE device_id=? AND role='port'", (sw,)).fetchone()[0] == 8
        assert catalog.network_ports_once(c) == 0
