"""Typen (alphabetisch, neue), Vermutung verwerfen, WLAN statt LAN bei Geräten ohne Buchse, Software-Feld und Übernahme vom Hypervisor."""
import copy
import json

from app import integrations
from app.db import db, now
from app.drivers import proxmox
from tests import test_m5
from tests.test_m6 import H, login


def _profile(name):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]
    return cl, pid, f"/api/profiles/{pid}"


def test_types_sorted_and_extended():
    cl, pid, P = _profile("Typen")
    types = cl.get(f"{P}/meta").json()["types"]
    names = [t["name"] for t in types]
    assert names[-1] == "Sonstiges" and names[:-1] == sorted(names[:-1], key=str.lower)
    keys = {t["key"] for t in types}
    assert {"vacuum", "printer3d", "doorbell", "hub", "esp", "plug"} <= keys
    r = cl.post(f"{P}/devices", json=dict(name="Roborock", type="vacuum"), headers=H).json()
    assert r["type"] == "vacuum"
    rules = {x["label"]: x["type"] for x in json.load(open("app/ident_rules.json", encoding="utf-8"))}
    assert rules["Saugroboter"] == "vacuum" and rules["Philips Hue Bridge"] == "hub"


def test_dismiss_ident():
    cl, pid, P = _profile("Vermutung")
    did = cl.post(f"{P}/devices", json=dict(name="HP Proxmoxone", type="computer"), headers=H).json()["id"]
    with db() as c:
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps({"ident": {"label": "Drucker", "confidence": 45}}), did))
    assert cl.get(f"{P}/devices/{did}").json()["ident_full"]["label"] == "Drucker"
    assert cl.post(f"{P}/devices/{did}/ident/dismiss", headers=H).json()["ok"]
    assert cl.get(f"{P}/devices/{did}").json()["ident_full"] is None
    with db() as c:  # der Scan erkennt später etwas anderes -> wieder sichtbar
        d = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()["data"])
        d["ident"] = {"label": "Linux-Server", "confidence": 70}
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(d), did))
    assert cl.get(f"{P}/devices/{did}").json()["ident_full"]["label"] == "Linux-Server"


def test_wireless_only_model_gets_wlan_link():
    cl, pid, P = _profile("Nur WLAN")
    m = cl.post("/api/catalog", json=dict(manufacturer="roborock", model="q8 max", type="vacuum", ports=[], wifi="Wi-Fi 4"), headers=H).json()
    mid = m.get("id") or m["model"]["id"]
    node = cl.post(f"{P}/devices", json=dict(name="EBM68 -KUE", type="mesh"), headers=H).json()["id"]
    robo = cl.post(f"{P}/devices", json=dict(name="roborock-Q8", type="vacuum", model_id=mid), headers=H).json()["id"]
    with db() as c:
        assert integrations.set_auto_uplink(c, pid, robo, node, "lan", source="asuswrt")
    assert cl.get(f"{P}/devices/{robo}").json()["uplink"]["medium"] == "wlan"


def test_software_field_and_proxmox_inherit(monkeypatch):
    cl, pid, P = _profile("Proxmox-Software")
    loc = cl.post(f"{P}/locations", json={"name": "Keller"}, headers=H).json()
    loc_id = next(x["id"] for x in loc["locations"] if x["name"] == "Keller")
    host = cl.post(f"{P}/devices", json=dict(name="HP Proxmoxone", type="hypervisor", manufacturer="HP", model="EliteDesk 800 G4",
                                             location_id=loc_id, ips=[{"address": "192.168.50.12"}]), headers=H).json()["id"]
    data = copy.deepcopy(test_m5.FakeProxmox.DATA)
    data["/nodes/proxmoxone/qemu/101/config"]["ostype"] = "l26"
    data["/nodes/proxmoxone/qemu/101/agent/get-osinfo"] = {"result": {"pretty-name": "Home Assistant OS 16.3"}}
    data["/nodes/proxmoxtwo/lxc/103/config"]["ostype"] = "debian"
    monkeypatch.setattr(proxmox, "_get", lambda cl_, path: data.get(path))
    res, _, _ = proxmox.poll(dict(host="192.168.50.12", username="d@pve!d", password="s"), {})
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, created) VALUES(?,?,?,?,?,?)",
                        (pid, "proxmox", "PVE", "192.168.50.12", "{}", now())).lastrowid
    monkeypatch.setattr(proxmox, "poll", lambda conf, state: (res, {}, state))
    integrations.poll(iid)
    devs = {d["name"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    h = cl.get(f"{P}/devices/{host}").json()
    assert h["software"] == "Proxmox VE 9.2.28" and h["manufacturer"] == "HP"
    ha = cl.get(f"{P}/devices/{devs['homeassistant']['id']}").json()
    assert ha["software"] == "Home Assistant OS 16.3" and ha["manufacturer"] == "Proxmox" and ha["model"] == "QEMU-VM" and ha["location_id"] == loc_id
    ct = cl.get(f"{P}/devices/{devs['diktyo']['id']}").json()
    assert ct["software"] == "Debian" and ct["model"] == "LXC-Container"
    # von Hand eingetragen -> bleibt
    body = dict(name="homeassistant", type="vm", software="HAOS (meine Angabe)")
    cl.put(f"{P}/devices/{devs['homeassistant']['id']}", json=body, headers=H)
    integrations.poll(iid)
    assert cl.get(f"{P}/devices/{devs['homeassistant']['id']}").json()["software"] == "HAOS (meine Angabe)"
