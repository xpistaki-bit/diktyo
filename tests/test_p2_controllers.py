"""Phase 2: Controller-Integrationen Omada und UniFi gegen nachgebildete APIs (keine echte Hardware vorhanden)."""
import json

import httpx
from fastapi.testclient import TestClient

from app import integrations, main, topology, users
from app.db import db, now
from app.drivers import omada, unifi

H = {"X-Requested-With": "diktyo"}


def login(email="p2@x.de"):
    with db() as c:
        if not users.by_email(c, email):
            users.create(c, email, "passwort123", is_admin=True)
    cl = TestClient(main.app)
    cl.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H)
    return cl


def integration(cl, name, driver, host, options, secret):
    pid = cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, port, username, secret, options, created) VALUES(?,?,?,?,?,?,?,?,?)",
                        (pid, driver, driver, host, None, options.pop("username", ""), integrations.security.encrypt(json.dumps(secret)),
                         json.dumps(options), now())).lastrowid
    return pid, f"/api/profiles/{pid}", iid


def mock(monkeypatch, module, handler):
    real = module._client

    def fake(conf):
        c = real(conf)
        return httpx.Client(base_url=c.base_url, headers=c.headers, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(module, "_client", fake)


# ------------------------------------------------------------ Omada
OMADA_DEVICES = [
    dict(mac="AA-00-00-00-00-01", name="ER605", model="ER605", type="gateway", ip="192.168.0.1", statusCategory=1),
    dict(mac="AA-00-00-00-00-02", name="SG2210P", model="SG2210P", type="switch", ip="192.168.0.2", statusCategory=1,
         uplinkDeviceMac="AA-00-00-00-00-01", uplinkDevicePort=2),
    dict(mac="AA-00-00-00-00-03", name="EAP650 Flur", model="EAP650", type="ap", ip="192.168.0.3", statusCategory=1,
         uplinkDeviceMac="AA-00-00-00-00-02", uplinkDevicePort=5, clientNum=1),
    dict(mac="AA-00-00-00-00-04", name="EAP615 Garten", model="EAP615-Wall", type="ap", ip="192.168.0.4", statusCategory=0,
         uplinkDeviceMac="AA-00-00-00-00-03"),
]
OMADA_CLIENTS = [
    dict(mac="10-20-30-40-50-60", ip="192.168.0.50", name="Handy", wireless=True, apMac="AA-00-00-00-00-03", ssid="Zuhause", radioId=1, active=True),
    dict(mac="10-20-30-40-50-61", ip="192.168.0.51", hostName="nas", wireless=False, switchMac="AA-00-00-00-00-02", port=7, active=True),
]


def omada_handler(calls):
    def h(req):
        p = req.url.path
        calls.append(p)
        if p == "/openapi/authorize/token":
            body = json.loads(req.content)
            assert req.url.params["grant_type"] == "client_credentials" and body == {"omadacId": "oid", "client_id": "cid", "client_secret": "sec"}
            n = sum(1 for x in calls if x == p)
            return httpx.Response(200, json={"errorCode": 0, "result": {"accessToken": f"T{n}", "expiresIn": 7200, "refreshToken": "r"}})
        assert p.startswith("/openapi/v1/oid/")
        if req.headers["Authorization"] == "AccessToken=T1" and p.endswith("/devices"):
            return httpx.Response(200, json={"errorCode": -44112, "msg": "The access token has expired"})
        data = {"/openapi/v1/oid/sites": [{"siteId": "s1", "name": "Home"}],
                "/openapi/v1/oid/sites/s1/devices": OMADA_DEVICES, "/openapi/v1/oid/sites/s1/clients": OMADA_CLIENTS}[p]
        return httpx.Response(200, json={"errorCode": 0, "result": {"totalRows": len(data), "currentPage": 1, "data": data}})
    return h


def test_omada_poll_builds_tree(monkeypatch):
    calls = []
    mock(monkeypatch, omada, omada_handler(calls))
    cl = login()
    pid, P, iid = integration(cl, "Omada", "omada", "192.168.0.10", {"username": "cid", "omada_id": "oid"}, {"password": "sec"})
    s = integrations.poll(iid)
    assert s["devices"] == 4 and s["clients"] == 2 and s["new"] >= 4, s
    assert calls.count("/openapi/authorize/token") == 2  # abgelaufener Token wurde erneuert
    with db() as c:
        t = topology.build(c, pid, status=None)
    names = {n["id"]: n.get("name") for n in t["nodes"]}
    online = {n.get("name"): n.get("online") for n in t["nodes"]}
    by_target = {names[e["target"]]: (names[e["source"]], e) for e in t["edges"] if e["source"] != "internet"}
    assert by_target["SG2210P"][0] == "ER605" and by_target["EAP650 Flur"][0] == "SG2210P"
    assert by_target["EAP615 Garten"][0] == "EAP650 Flur" and by_target["EAP615 Garten"][1]["medium"] == "mesh"
    assert by_target["Handy"][0] == "EAP650 Flur" and by_target["Handy"][1]["medium"] == "wlan"
    assert by_target["nas"][0] == "SG2210P"
    assert online["EAP615 Garten"] == 0
    i = next(x for x in cl.get(f"{P}/integrations").json()["integrations"] if x["id"] == iid)
    assert not i["last_error"]


def test_omada_bad_credentials(monkeypatch):
    mock(monkeypatch, omada, lambda req: httpx.Response(200, json={"errorCode": -44106, "msg": "Invalid client credentials"}))
    try:
        omada.test(dict(host="h", omada_id="oid", username="x", password="y"))
        raise AssertionError
    except omada.DriverError as ex:
        assert "Anmeldung abgelehnt" in str(ex) and "Invalid client credentials" in str(ex)


# ------------------------------------------------------------ UniFi
U_DEV = [
    dict(id="d-gw", name="UCG Ultra", model="UCG-Ultra", macAddress="cc:00:00:00:00:01", ipAddress="10.0.0.1", state="ONLINE", features={},
         interfaces={"ports": [dict(idx=i, state="UP" if i in (1, 5) else "DOWN", connector="RJ45", maxSpeedMbps=2500 if i == 5 else 1000,
                                    speedMbps=1000) for i in range(1, 6)]}),
    dict(id="d-sw", name="USW Lite 8", model="USL8LP", macAddress="cc:00:00:00:00:02", ipAddress="10.0.0.2", state="ONLINE",
         features={"switching": {}}, interfaces={"ports": [dict(idx=i, state="UP" if i < 3 else "DOWN", connector="RJ45", maxSpeedMbps=1000,
                                                                speedMbps=1000 if i < 3 else 0) for i in range(1, 9)]}),
    dict(id="d-ap", name="U7 Pro", model="U7PRO", macAddress="cc:00:00:00:00:03", ipAddress="10.0.0.3", state="ONLINE",
         features={"accessPoint": {}}, interfaces={"radios": [{"frequencyGHz": 5}]}),
]
U_UPLINK = {"d-sw": "d-gw", "d-ap": "d-sw"}
U_CLIENTS = [
    dict(type="WIRELESS", id="c1", name="Tablet", ipAddress="10.0.0.60", macAddress="de:ad:be:ef:00:01", uplinkDeviceId="d-ap"),
    dict(type="WIRED", id="c2", name="Drucker", ipAddress="10.0.0.61", macAddress="de:ad:be:ef:00:02", uplinkDeviceId="d-sw"),
    dict(type="VPN", id="c3", name="VPN-Laptop", ipAddress="10.8.0.2"),
]


def unifi_handler(seen):
    def page(data):
        return httpx.Response(200, json={"offset": 0, "limit": 200, "count": len(data), "totalCount": len(data), "data": data})

    def h(req):
        assert req.headers["X-API-KEY"] == "key123"
        p = req.url.path
        seen.append(p)
        if p.startswith("/proxy/"):
            return httpx.Response(404, text="not found")  # selbst gehosteter Controller
        p = p.removeprefix("/integration/v1")
        if p == "/info":
            return httpx.Response(200, json={"applicationVersion": "10.0.160"})
        if p == "/sites":
            return page([{"id": "site-1", "internalReference": "default", "name": "Default"}])
        if p == "/sites/site-1/devices":
            return page([{k: v for k, v in d.items() if k != "uplink"} for d in U_DEV])
        if p == "/sites/site-1/clients":
            return page(U_CLIENTS)
        if p == "/sites/site-1/devices/d-gw/statistics/latest":
            return httpx.Response(200, json={"uptimeSec": 999, "uplink": {"rxRateBps": 87_000_000, "txRateBps": 9_000_000}})
        for d in U_DEV:
            if p == f"/sites/site-1/devices/{d['id']}":
                return httpx.Response(200, json={**d, "uplink": {"deviceId": U_UPLINK[d["id"]]} if d["id"] in U_UPLINK else None})
        return httpx.Response(404)
    return h


def test_unifi_poll_ports_wan_and_tree(monkeypatch):
    seen = []
    mock(monkeypatch, unifi, unifi_handler(seen))
    cl = login()
    pid, P, iid = integration(cl, "UniFi", "unifi", "10.0.0.1", {}, {"password": "key123"})
    assert unifi.test(dict(host="10.0.0.1", password="key123"))["devices"] == 3
    s = integrations.poll(iid)
    assert s["devices"] == 3 and s["clients"] == 2 and s["device_id"], s  # VPN-Client bleibt draußen
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
        st = json.loads(row["state"])
        assert st["prefix"] == "/integration" and st["result"]["wan"]["rx_bps"] == 87_000_000
        sw = c.execute("SELECT id FROM devices WHERE profile_id=? AND name='USW Lite 8'", (pid,)).fetchone()["id"]
        assert c.execute("SELECT COUNT(*) FROM interfaces WHERE device_id=? AND role='port'", (sw,)).fetchone()[0] == 8
        live = integrations.live_ports(c, sw)
        assert live[1]["oper"] == "up" and live[5]["oper"] == "down"
        t = topology.build(c, pid, status=None)
    names = {n["id"]: n.get("name") for n in t["nodes"]}
    parent = {names[e["target"]]: names[e["source"]] for e in t["edges"]}
    assert parent["USW Lite 8"] == "UCG Ultra" and parent["U7 Pro"] == "USW Lite 8" and parent["Tablet"] == "U7 Pro" and parent["Drucker"] == "USW Lite 8"
    assert "VPN-Laptop" not in names.values()
    # Internet hängt am Gateway, mit Traffic aus den Gateway-Statistiken
    inet = next(e for e in t["edges"] if e["source"] == "internet")
    assert names[inet["target"]] == "UCG Ultra" and inet["rx_bps"] == 87_000_000 and inet["connected"] == 1
    # Frontplatte zeigt den Port-Status vom Controller
    det = cl.get(f"{P}/devices/{sw}").json()
    assert det["ports"][0]["live"]["oper"] == "up"
    # zweite Abfrage nutzt den gemerkten Pfad direkt
    seen.clear()
    integrations.poll(iid)
    assert not any(x.startswith("/proxy/") for x in seen)


def test_unifi_wrong_key(monkeypatch):
    mock(monkeypatch, unifi, lambda req: httpx.Response(401, json={"message": "unauthorized"}))
    try:
        unifi.test(dict(host="h", password="falsch"))
        raise AssertionError
    except unifi.DriverError as ex:
        assert "API-Schlüssel abgelehnt" in str(ex)
