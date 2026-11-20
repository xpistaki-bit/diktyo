"""Aktionen über UniFi und Omada: Neustart verwalteter Geräte, PoE an Switch-Ports (angeboten, Anfragen, Zurückschalten)."""
import json

import httpx

from app import actions
from app.db import db, now
from app.drivers import omada, unifi
from tests.test_m6 import H, login


def _setup(driver):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": f"Aktionen {driver}"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    sw = cl.post(f"{P}/devices", json=dict(name="Switch", type="switch", mac="02:00:00:00:0A:01", ports=[dict(count=8, kind="rj45", speed="1G")]),
                 headers=H).json()
    ap = cl.post(f"{P}/devices", json=dict(name="AP Flur", type="ap", mac="02:00:00:00:0A:02",
                                            uplink=dict(device_id=sw["id"], port_id=sw["ports"][2]["id"], medium="lan")), headers=H).json()
    ref = dict(site="s1", id="dev-sw") if driver == "unifi" else dict(site="s1", mac="02-00-00-00-0A-01")
    ports = [dict(port_no=n, oper="up", poe=(n == 3) if driver == "unifi" else (n in (3, 4)), macs=[]) for n in range(1, 9)]
    state = dict(result=dict(devices=[dict(name="Switch", model="X", type="switch", ip="192.0.2.2", online=True, clients=1, mac="02:00:00:00:0A:01", ref=ref)],
                             port_status={"02:00:00:00:0A:01": ports}))
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, state, created) VALUES(?,?,?,?,?,?,?)",
                        (pid, driver, driver.capitalize(), "192.0.2.10", json.dumps({"omada_id": "oid"}), json.dumps(state), now())).lastrowid
    return cl, pid, P, sw["id"], ap["id"], iid


def test_unifi_offers_and_sends(monkeypatch):
    cl, pid, P, sw, ap, iid = _setup("unifi")
    with db() as c:
        on_sw = {a["label"] for a in actions.available(c, pid, sw)}
        on_ap = [a for a in actions.available(c, pid, ap)]
        port3 = actions.available(c, pid, sw, port_no=3)
        port4 = actions.available(c, pid, sw, port_no=4)
    assert "Switch neu starten (über Unifi)" in on_sw
    assert [a["label"] for a in on_ap] == ["PoE an Port 3 neu starten"] and on_ap[0]["params"] == dict(site="s1", id="dev-sw", port_no=3)
    assert [a["kind"] for a in port3] == ["poe_cycle"] and port4 == []
    sent = []

    def handler(req):
        sent.append((req.method, req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={})
    real = unifi._client
    monkeypatch.setattr(unifi, "_client", lambda conf: httpx.Client(base_url=real(conf).base_url, transport=httpx.MockTransport(handler)))
    r = actions.run(pid, 1, ap, on_ap[0]["key"])
    assert r["status"] == "done" and sent[-1] == ("POST", "/proxy/network/integration/v1/sites/s1/devices/dev-sw/interfaces/ports/3/actions",
                                                  {"action": "POWER_CYCLE"})
    with db() as c:
        reboot = next(a for a in actions.available(c, pid, sw) if a["kind"] == "reboot")
    actions.run(pid, 1, sw, reboot["key"])
    assert sent[-1] == ("POST", "/proxy/network/integration/v1/sites/s1/devices/dev-sw/actions", {"action": "RESTART"})


def test_omada_poe_on_off_with_undo(monkeypatch):
    cl, pid, P, sw, ap, iid = _setup("omada")
    with db() as c:
        acts = {a["label"]: a for a in actions.available(c, pid, ap)}
    assert set(acts) == {"PoE an Port 3 ausschalten", "PoE an Port 3 neu starten"} and acts["PoE an Port 3 ausschalten"]["undo"]
    sent = []

    def handler(req):
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"errorCode": 0, "result": {"accessToken": "T", "expiresIn": 7200}})
        sent.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(200, json={"errorCode": 0, "result": {}})
    monkeypatch.setattr(omada, "_client", lambda conf: httpx.Client(base_url="https://192.0.2.10:8043", transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(omada, "_token", lambda cl, conf: ("T", 9e9))
    r = actions.run(pid, 1, ap, acts["PoE an Port 3 ausschalten"]["key"], undo="30")
    assert r["status"] == "done" and r["undo_at"]
    assert sent[-1] == ("PUT", "/openapi/v1/oid/sites/s1/switches/02-00-00-00-0A-01/ports/3/poe-mode", {"poeMode": 0})
    assert actions.inverse("poe", acts["PoE an Port 3 ausschalten"]["params"])["on"] is True
    monkeypatch.setattr(omada.time, "sleep", lambda s: None)
    actions.run(pid, 1, ap, acts["PoE an Port 3 neu starten"]["key"])
    assert [x[2] for x in sent[-2:]] == [{"poeMode": 0}, {"poeMode": 1}]
    with db() as c:
        reboot = next(a for a in actions.available(c, pid, sw) if a["kind"] == "reboot")
    actions.run(pid, 1, sw, reboot["key"])
    assert sent[-1] == ("POST", "/openapi/v1/oid/sites/s1/devices/02-00-00-00-0A-01/reboot", None)


def test_omada_reads_switch_ports():
    devs, _ = omada.normalize([({"siteId": "s1"}, [dict(mac="02-00-00-00-0A-01", type="switch", name="SW")], [],
                                 {"02-00-00-00-0A-01": [dict(port=1, linkStatus=1, poe=True), dict(port=2, linkStatus=0, poeMode=0)]})])
    assert devs[0]["ref"] == {"site": "s1", "mac": "02-00-00-00-0A-01"}
    assert [(p["port_no"], p["oper"], p["poe"]) for p in devs[0]["ports"]] == [(1, "up", True), (2, "down", False)]
