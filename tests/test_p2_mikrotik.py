"""MikroTik RouterOS über REST und die RouterOS-API gegen nachgebildete Schnittstellen – Antworten wie bei einem hAP ax³ (Werte als Zeichenketten)."""
import json

import httpx

from app import actions, integrations, topology
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
    monkeypatch.setattr(mikrotik, "_client", lambda conf: mikrotik._Conn(dict(conf, access="https"), http=httpx.Client(
        base_url=mikrotik._base(dict(conf, access="https")), auth=("diktyo", "x"), transport=httpx.MockTransport(handler))))


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


def test_mikrotik_no_config_backup():
    """MikroTik hat eigene Backups (auch in die Cloud) – díktyo bietet dafür keins an."""
    assert mikrotik.CAN_BACKUP is False and not hasattr(mikrotik, "backup")
    assert not any(f["key"] in ("cfg_schedule", "ssh_port") for f in mikrotik.FIELDS)


def test_mikrotik_errors(monkeypatch):
    monkeypatch.setattr(mikrotik, "_client", lambda conf: mikrotik._Conn(dict(conf, access="https"), http=httpx.Client(
        base_url="https://h/rest", transport=httpx.MockTransport(lambda r: httpx.Response(401)))))
    try:
        mikrotik.test(dict(host="h", username="u", password="p"))
        raise AssertionError
    except mikrotik.DriverError as ex:
        assert "rest-api" in str(ex)


# ------------------------------------------------------------ RouterOS-API (Port 8728) über einen echten Socket
import socket  # noqa: E402
import threading  # noqa: E402

from app.drivers import routeros_api  # noqa: E402


def _word(w):
    b = w.encode()
    return routeros_api._enc_len(len(b)) + b


class FakeAPI(threading.Thread):
    """Spricht das RouterOS-API-Protokoll; Daten wie der REST-Nachbau (handler)."""

    def __init__(self, user="diktyo", password="x", legacy=False):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.user, self.password, self.legacy, self.calls = user, password, legacy, []

    def run(self):
        conn, _ = self.srv.accept()
        f = conn.makefile("rb")

        def read_len():
            b = f.read(1)[0]
            if b < 0x80:
                return b
            if b < 0xC0:
                return ((b & 0x3F) << 8) + f.read(1)[0]
            return ((b & 0x1F) << 16) + int.from_bytes(f.read(2), "big")

        def send(*sentences):
            conn.sendall(b"".join(b"".join(_word(w) for w in s) + b"\x00" for s in sentences))

        while True:
            words = []
            try:
                while (n := read_len()):
                    words.append(f.read(n).decode())
            except (IndexError, OSError):
                return
            cmd, attrs = words[0], dict(w[1:].split("=", 1) for w in words[1:] if w.startswith("="))
            self.calls.append((cmd, attrs))
            if cmd == "/login":
                if self.legacy and "response" not in attrs:
                    send(["!done", "=ret=0123456789abcdef0123456789abcdef"])
                elif attrs.get("name") == self.user and (attrs.get("password") == self.password or "response" in attrs):
                    send(["!done"])
                else:
                    send(["!trap", "=message=invalid user name or password (6)"], ["!done"])
                continue
            if cmd.endswith("/print"):
                path = cmd[1:-6]
                resp = handler(httpx.Request("GET", f"https://h/rest/{path}", headers={"authorization": "Basic x"}))
                if resp.status_code >= 400:
                    send(["!trap", "=message=no such command prefix"], ["!done"])
                    continue
                data = resp.json()
                rows = data if isinstance(data, list) else [data]
                send(*[["!re"] + [f"={k}={v}" for k, v in r.items()] for r in rows], ["!done"])
                continue
            if cmd == "/system/reboot":
                conn.close()
                return
            send(["!done"])


def test_routeros_api_poll_and_actions():
    srv = FakeAPI()
    srv.start()
    conf = dict(host="127.0.0.1", access="api", port=srv.port, username="diktyo", password="x")
    r = mikrotik.test(conf)
    assert (r["name"], r["model"], r["ports"], r["wifi"]) == ("Buero-MikroTik", "hAP ax^3", 5, 2) and r["clients"] >= 3, r
    cmds = [c for c, _ in srv.calls]
    assert cmds[0] == "/login" and "/interface/print" in cmds and "/interface/wifi/registration-table/print" in cmds
    # Aktionen über die API: set mit .id, Befehl mit Parametern, Neustart (Verbindung bricht ab)
    srv = FakeAPI()
    srv.start()
    conf["port"] = srv.port
    assert "abgeschaltet" in mikrotik.action(conf, {}, "port", dict(iface="ether4", id="*4", up=False))
    assert srv.calls[-1] == ("/interface/set", {".id": "*4", "disabled": "true"})
    for kind, params, cmd in (("poe_cycle", dict(iface="ether5"), "/interface/ethernet/poe/power-cycle"),
                              ("wol", dict(mac="11:22:33:44:55:01", iface="bridge"), "/tool/wol"), ("reboot", {}, "/system/reboot")):
        srv = FakeAPI()
        srv.start()
        conf["port"] = srv.port
        mikrotik.action(conf, {}, kind, params)
        assert srv.calls[-1][0] == cmd


def test_routeros_api_login_and_errors():
    srv = FakeAPI(legacy=True)  # RouterOS vor 6.43: Challenge-Response
    srv.start()
    assert mikrotik.test(dict(host="127.0.0.1", access="api", port=srv.port, username="diktyo", password="x"))["name"] == "Buero-MikroTik"
    assert srv.calls[1][1]["response"].startswith("00") and len(srv.calls[1][1]["response"]) == 34
    srv = FakeAPI(password="anders")
    srv.start()
    try:
        mikrotik.test(dict(host="127.0.0.1", access="api", port=srv.port, username="diktyo", password="x"))
        raise AssertionError
    except mikrotik.DriverError as ex:
        assert "Rechte read und api" in str(ex)
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    try:
        mikrotik.test(dict(host="127.0.0.1", access="api", port=port, username="u", password="p"))
        raise AssertionError
    except mikrotik.DriverError as ex:
        assert f"Port {port}" in str(ex) and "IP → Services" in str(ex)


def test_access_compat():
    assert mikrotik.access_of(dict(scheme="https", port=443)) == "https"  # alte REST-Integration bleibt
    assert mikrotik.access_of(dict(scheme="https", port=8728)) == "api"  # API-Port heißt immer API
    assert mikrotik.access_of(dict(port="8729")) == "api-ssl"
    assert mikrotik.access_of(dict()) == "https" and mikrotik.access_of(dict(access="api")) == "api"
    assert mikrotik._port(dict(access="api")) == 8728 and mikrotik._port(dict(access="http", port="")) == 80
