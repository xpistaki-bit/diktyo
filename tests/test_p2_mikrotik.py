"""MikroTik RouterOS 7 (REST-API) gegen eine nachgebildete API – Antworten wie bei einem hAP ax³ (Werte als Zeichenketten)."""
import json

import httpx

from app import actions, integrations, sshcfg, topology
from app.db import db, now
from app.drivers import mikrotik
from tests.test_m6 import H, login

STATE = {"rx": 1_000_000, "patched": [], "posted": []}


def iface(n, name, typ, mac, running=True, disabled=False, rx=0, tx=0):
    return {".id": f"*{n}", "name": name, "type": typ, "mac-address": mac, "running": str(running).lower(), "disabled": str(disabled).lower(),
            "rx-byte": str(rx), "tx-byte": str(tx), "comment": ""}


def handler(req):
    assert req.headers["authorization"].startswith("Basic ")
    p = req.url.path.removeprefix("/rest/")
    if req.method == "PATCH":
        STATE["patched"].append((p, json.loads(req.content)))
        return httpx.Response(200, json={})
    if req.method == "POST":
        STATE["posted"].append((p, json.loads(req.content or b"{}")))
        return httpx.Response(200, json=[])
    data = {
        "system/resource": {"board-name": "hAP ax^3", "version": "7.16.2 (stable)", "uptime": "3d4h", "cpu-load": "3"},
        "system/identity": {"name": "Buero-MikroTik"},
        "system/routerboard": {"model": "C53UiG+5HPaxD2HPaxD", "serial-number": "HGX0000"},
        "interface": [
            iface(1, "ether1", "ether", "48:A9:8A:00:00:01", rx=STATE["rx"], tx=200_000),
            iface(2, "ether2", "ether", "48:A9:8A:00:00:02", rx=5000, tx=5000),
            iface(3, "ether3", "ether", "48:A9:8A:00:00:03", running=False),
            iface(4, "ether4", "ether", "48:A9:8A:00:00:04", disabled=True, running=False),
            iface(5, "ether5", "ether", "48:A9:8A:00:00:05"),
            iface(6, "wifi1", "wifi", "48:A9:8A:00:00:06"), iface(7, "wifi2", "wifi", "48:A9:8A:00:00:07", disabled=True, running=False),
            iface(8, "bridge", "bridge", "48:A9:8A:00:00:02"),
        ],
        "interface/ethernet": [{"name": "ether1", "speed": "2.5Gbps"}, {"name": "ether2", "speed": "1Gbps"}, {"name": "ether5", "speed": "1Gbps"}],
        "interface/ethernet/poe": [{"name": "ether5", "poe-out": "auto-on"}],
        "ip/address": [{"address": "192.168.88.1/24", "interface": "bridge"}],
        "ip/dhcp-server/lease": [
            {"address": "192.168.88.10", "mac-address": "11:22:33:44:55:01", "host-name": "nas", "status": "bound", "dynamic": "false"},
            {"address": "192.168.88.20", "mac-address": "11:22:33:44:55:02", "host-name": "handy", "status": "bound", "dynamic": "true"},
            {"address": "192.168.88.30", "mac-address": "11:22:33:44:55:03", "host-name": "alt", "status": "waiting", "dynamic": "true"},
        ],
        "ip/arp": [{"address": "192.168.88.40", "mac-address": "11:22:33:44:55:04", "interface": "bridge", "complete": "true"}],
        "interface/bridge/host": [
            {"mac-address": "11:22:33:44:55:01", "on-interface": "ether2", "local": "false"},
            {"mac-address": "11:22:33:44:55:04", "on-interface": "ether5", "local": "false"},
            {"mac-address": "48:A9:8A:00:00:02", "on-interface": "bridge", "local": "true"},
        ],
        "interface/wifi": [{".id": "*6", "name": "wifi1", "configuration.ssid": "Buero", "configuration.band": "5ghz-ax", "disabled": "false", "running": "true"},
                           {".id": "*7", "name": "wifi2", "configuration.ssid": "Buero-2G", "configuration.band": "2ghz-ax", "disabled": "true", "running": "false"}],
        "interface/wifi/registration-table": [{"mac-address": "11:22:33:44:55:02", "interface": "wifi1", "signal": "-58"}],
        "ip/neighbor": [{"interface": "ether1", "mac-address": "AA:AA:AA:AA:AA:01", "identity": "fritz.box", "address": "192.168.178.1"}],
        "interface/list/member": [{"list": "WAN", "interface": "ether1"}, {"list": "LAN", "interface": "bridge"}],
    }.get(p)
    if data is None:
        return httpx.Response(400, json={"error": 400, "message": "no such command"})
    return httpx.Response(200, json=data)


def mock(monkeypatch):
    real = mikrotik._client
    monkeypatch.setattr(mikrotik, "_client", lambda conf: httpx.Client(base_url=real(conf).base_url, auth=("diktyo", "x"),
                                                                       transport=httpx.MockTransport(handler)))


def test_mikrotik_poll_apply_actions(monkeypatch):
    mock(monkeypatch)
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    t = mikrotik.test(dict(host="192.168.88.1", username="diktyo", password="x"))
    assert t == {"name": "Buero-MikroTik", "model": "hAP ax^3", "version": "7.16.2 (stable)", "ports": 5, "clients": 4, "wifi": 2}
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "MikroTik"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    fb = cl.post(f"{P}/devices", json={"name": "FRITZ!Box", "type": "router", "status": "confirmed", "mac": "AA:AA:AA:AA:AA:01",
                                        "ips": [{"address": "192.168.178.1"}]}, headers=H).json()["id"]
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, username, secret, options, created) VALUES(?,?,?,?,?,?,?,?)",
                        (pid, "mikrotik", "MikroTik", "192.168.88.1", "diktyo", integrations.security.encrypt(json.dumps({"password": "x"})),
                         json.dumps({"scheme": "https", "cfg_schedule": "no"}), now())).lastrowid
    s = integrations.poll(iid)
    assert s["ports"] == 5 and s["clients"] == 4 and s["device_id"], s
    STATE["rx"] += 12_500_000  # 100 Mbit in der zweiten Abfrage (Zeitabstand klein, Rate also hoch)
    integrations.poll(iid)
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
        st = json.loads(row["state"])
        own = row["device_id"]
        res = st["result"]
        assert res["wan"]["iface"] == "ether1" and res["wan"]["rx_bps"] > 0 and res["wifi"][0]["band"] == "5 GHz"
        ports = {p["iface"]: p for p in res["ports"]}
        assert ports["ether4"]["admin"] == "down" and ports["ether5"]["poe"] is True and ports["ether1"]["speed"] == 2500
        assert ports["ether1"]["lldp"]["name"] == "fritz.box"
        assert c.execute("SELECT COUNT(*) FROM interfaces WHERE device_id=? AND role='port'", (own,)).fetchone()[0] == 5
        t = topology.build(c, pid, status=None)
    names = {n["id"]: n.get("name") for n in t["nodes"]}
    parent = {names[e["target"]]: (names[e["source"]], e) for e in t["edges"]}
    assert parent["Buero-MikroTik"][0] == "FRITZ!Box"  # Nachbar am WAN-Port ist der Uplink
    assert parent["nas"][0] == "Buero-MikroTik" and parent["nas"][1]["label"] == "2"
    assert parent["handy"][0] == "Buero-MikroTik" and parent["handy"][1]["medium"] == "wlan"
    # Aktionen am MikroTik: WLAN, Neustart, Port-Auswahl; am NAS: Port 2 + Wake-on-LAN
    acts = {a["label"]: a for a in cl.get(f"{P}/devices/{own}/actions").json()["actions"]}
    assert {"WLAN „Buero“ (5 GHz) ausschalten", "WLAN „Buero-2G“ (2,4 GHz) einschalten", "MikroTik neu starten"} <= set(acts)
    r = cl.get(f"{P}/devices/{own}/actions").json()
    assert [p["port_no"] for p in r["ports"]] == [1, 2, 3, 4, 5]
    nas = next(n for n in t["nodes"] if n.get("name") == "nas")["device_id"]
    na = {a["label"]: a for a in cl.get(f"{P}/devices/{nas}/actions").json()["actions"]}
    assert "Port 2 abschalten" in na and "Aufwecken (Wake-on-LAN)" in na
    assert cl.post(f"{P}/devices/{nas}/actions", json={"key": na["Port 2 abschalten"]["key"]}, headers=H).json()["status"] == "done"
    assert STATE["patched"][-1] == ("interface/*2", {"disabled": "true"})
    cl.post(f"{P}/devices/{own}/actions", json={"key": acts["WLAN „Buero“ (5 GHz) ausschalten"]["key"]}, headers=H)
    assert STATE["patched"][-1] == ("interface/wifi/*6", {"disabled": "true"})
    cl.post(f"{P}/devices/{nas}/actions", json={"key": na["Aufwecken (Wake-on-LAN)"]["key"]}, headers=H)
    assert STATE["posted"][-1] == ("tool/wol", {"mac": "11:22:33:44:55:01"})
    # Port 1 (WAN zur FRITZ!Box) ist gegen Aussperren geschützt
    p1 = {a["label"]: a for a in cl.get(f"{P}/devices/{own}/actions?port=1").json()["actions"]}
    assert "aussperren" in p1["Port 1 abschalten"]["blocked"]
    assert fb


def test_mikrotik_backup_export(monkeypatch):
    calls = []
    monkeypatch.setattr(sshcfg, "run", lambda host, port, user, pw, cmd, known=None: calls.append((host, port, user, cmd)) or (
        "# 2026-11-19 10:00:00 by RouterOS 7.16.2\n/interface bridge\nadd name=bridge\n/ip address\nadd address=192.168.88.1/24 interface=bridge\n", "ssh-ed25519 SHA256:x"))
    name, data, is_text = mikrotik.backup(dict(host="192.168.88.1", username="diktyo", password="x"), st := {})
    assert name == "mikrotik.rsc" and is_text and b"/ip address" in data and b"2026-11-19" not in data and st["ssh_hostkey"].startswith("ssh-ed25519")
    assert calls == [("192.168.88.1", 22, "diktyo", "/export")]


def test_mikrotik_errors(monkeypatch):
    real = mikrotik._client
    monkeypatch.setattr(mikrotik, "_client", lambda conf: httpx.Client(base_url=real(conf).base_url, transport=httpx.MockTransport(lambda r: httpx.Response(401))))
    try:
        mikrotik.test(dict(host="h", username="u", password="p"))
        raise AssertionError
    except mikrotik.DriverError as ex:
        assert "rest-api" in str(ex)
