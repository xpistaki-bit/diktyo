"""Pi-hole (v6, v5) und AdGuard Home: Hostnamen, Anfragen/Blockierte je Gerät, Sitzung wiederverwenden, Werbeblocker schalten."""
import json

import httpx

from app import actions, integrations
from app.db import db, now
from app.drivers import dnsfilter
from tests.test_m6 import H, login

CALLS = []


def pihole6(req):
    p = req.url.path
    CALLS.append((req.method, p))
    if p == "/api/auth":
        assert json.loads(req.content)["password"] == "app-pw"
        return httpx.Response(200, json={"session": {"valid": True, "sid": "SID1", "validity": 1800}})
    assert req.headers.get("X-FTL-SID") == "SID1"
    data = {
        "/api/info/version": {"version": {"core": {"local": {"version": "v6.1"}}}},
        "/api/stats/summary": {"queries": {"total": 20000, "blocked": 3000, "percent_blocked": 15.0}, "gravity": {"domains_being_blocked": 180000}},
        "/api/stats/top_domains": {"domains": [{"domain": "ads.example", "count": 900}]},
        "/api/dns/blocking": {"blocking": "enabled", "timer": None},
        "/api/network/devices": {"devices": [{"hwaddr": "02:00:00:00:0b:01", "ips": [{"ip": "192.0.2.21", "name": "laptop-anna.fritz.box"}]},
                                             {"hwaddr": "02:00:00:00:0b:02", "ips": [{"ip": "192.0.2.22", "name": "esp-steckdose.lan"}]},
                                             {"hwaddr": "02:00:00:00:0b:03", "ips": [{"ip": "192.0.2.23", "name": "tv-wohnzimmer"}]}]},
    }
    if p == "/api/stats/top_clients":
        if req.url.params["blocked"] == "true":
            return httpx.Response(200, json={"clients": [{"ip": "192.0.2.23", "name": "tv-wohnzimmer", "count": 1200}, {"ip": "192.0.2.21", "name": "", "count": 100}]})
        return httpx.Response(200, json={"clients": [{"ip": "192.0.2.21", "name": "", "count": 9000}, {"ip": "192.0.2.23", "name": "", "count": 4000}]})
    if p == "/api/dns/blocking" and req.method == "POST":
        return httpx.Response(200, json={"blocking": "disabled" if not json.loads(req.content)["blocking"] else "enabled"})
    if p in data:
        return httpx.Response(200, json=data[p])
    return httpx.Response(404, json={"error": {"key": "not_found"}})


def adguard(req):
    p = req.url.path
    assert req.headers["authorization"].startswith("Basic ")
    if p == "/control/status":
        return httpx.Response(200, json={"version": "v0.107.55", "protection_enabled": True})
    if p == "/control/stats":
        return httpx.Response(200, json={"num_dns_queries": 5000, "num_blocked_filtering": 500, "top_clients": [{"192.0.2.31": 3000}, {"192.0.2.32": 1500}],
                                         "top_blocked_domains": [{"tracker.example": 120}]})
    if p == "/control/clients":
        return httpx.Response(200, json={"clients": [{"name": "Kinder-Tablet", "ids": ["192.0.2.32"]}], "auto_clients": [{"ip": "192.0.2.31", "name": "nas.local", "source": "rdns"}]})
    if p == "/control/dhcp/status":
        return httpx.Response(200, json={"leases": [{"mac": "02:00:00:00:0c:01", "ip": "192.0.2.31", "hostname": "nas"}]})
    if p == "/control/querylog":
        return httpx.Response(200, json={"data": [{"client": "192.0.2.32"}] * 40 + [{"client": "192.0.2.31"}] * 5})
    if p == "/control/protection":
        CALLS.append(("POST", p, json.loads(req.content)))
        return httpx.Response(200, json={})
    return httpx.Response(404)


def pihole5(req):
    if req.url.path == "/api/auth":
        return httpx.Response(404)
    q = req.url.params
    if "summaryRaw" in q:
        return httpx.Response(200, json={"dns_queries_today": 800, "ads_blocked_today": 80, "domains_being_blocked": 99999, "status": "enabled"})
    if "getQuerySources" in q:
        return httpx.Response(200, json={"top_sources": {"pc.lan|192.0.2.41": 500, "192.0.2.42": 300}})
    if "topClientsBlocked" in q:
        return httpx.Response(200, json={"top_sources_blocked": {"pc.lan|192.0.2.41": 50}})
    return httpx.Response(404)


def mock(monkeypatch, handler):
    real = dnsfilter._client
    monkeypatch.setattr(dnsfilter, "_client", lambda conf: httpx.Client(base_url=str(real(conf).base_url), auth=real(conf).auth,
                                                                        transport=httpx.MockTransport(handler)))


def test_pihole6_poll_apply_session_and_action(monkeypatch):
    mock(monkeypatch, pihole6)
    CALLS.clear()
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Pi-hole"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    mk = lambda **kw: cl.post(f"{P}/devices", json=kw, headers=H).json()["id"]  # noqa: E731
    pihole = mk(name="Pi-hole", type="server", ips=[{"address": "192.0.2.53"}])
    anna = mk(name="Laptop Anna (selbst benannt)", type="laptop", mac="02:00:00:00:0B:01", ips=[{"address": "192.0.2.21"}])
    esp = mk(name="Espressif .22", type="iot", mac="02:00:00:00:0B:02", ips=[{"address": "192.0.2.22"}], status="discovered")
    tv = mk(name="Fernseher", type="tv", ips=[{"address": "192.0.2.23"}])
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, secret, created) VALUES(?,?,?,?,?,?,?)",
                        (pid, "dnsfilter", "Pi-hole", "192.0.2.53", json.dumps({"kind": "pihole"}),
                         integrations.security.encrypt(json.dumps({"password": "app-pw"})), now())).lastrowid
    s1 = integrations.poll(iid)
    s2 = integrations.poll(iid)
    assert s1["matched"] == 3 and s1["device_id"] == pihole and s2["named"] == 0
    assert sum(1 for m, p in CALLS if p == "/api/auth") == 1  # Sitzung wird wiederverwendet
    devs = {d["id"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    assert devs[anna]["name"] == "Laptop Anna (selbst benannt)" and devs[anna]["hostname"] == "laptop-anna"
    assert devs[esp]["name"] == "esp-steckdose"  # Platzhalter im Posteingang ersetzt
    d_tv = cl.get(f"{P}/devices/{tv}").json()
    assert d_tv["dns"]["queries"] == 4000 and d_tv["dns"]["blocked"] == 1200 and d_tv["dns"]["pct"] == 30.0 and d_tv["dns"]["source"] == "Pi-hole"
    dash = cl.get(f"{P}/dashboard").json()["dns"]
    assert dash["summary"]["pct"] == 15.0 and dash["top"][0]["label"] == "Fernseher" and dash["top_domains"][0]["domain"] == "ads.example"
    with db() as c:
        act = next(a for a in actions.available(c, pid, pihole) if a["kind"] == "dns_blocking")
    assert act["label"] == "Pi-hole-Werbeblocker ausschalten" and act["undo"]
    r = actions.run(pid, 1, pihole, act["key"], undo="15")
    assert r["status"] == "done" and ("POST", "/api/dns/blocking") in CALLS


def test_adguard(monkeypatch):
    mock(monkeypatch, adguard)
    res, metrics, st = dnsfilter.poll(dict(kind="adguard", host="192.0.2.3", username="admin", password="pw"), {})
    c = {x["ip"]: x for x in res["clients"]}
    assert res["info"] == dict(kind="adguard", version="v0.107.55", blocking=True, window="Abfrage-Protokoll")
    assert c["192.0.2.32"]["name"] == "Kinder-Tablet" and c["192.0.2.32"]["blocked"] == 40 and c["192.0.2.31"]["mac"] == "02:00:00:00:0C:01"
    assert c["192.0.2.31"]["name"] == "nas.local" and res["summary"] == dict(queries=5000, blocked=500, pct=10.0, listed=None)
    assert res["top_domains"] == [dict(domain="tracker.example", count=120)] and metrics["dns:blocked_pct"] == 10.0
    CALLS.clear()
    dnsfilter.action(dict(kind="adguard", host="192.0.2.3", username="admin", password="pw"), {}, "dns_blocking", {"on": False})
    assert CALLS == [("POST", "/control/protection", {"enabled": False})]


def test_pihole5_fallback(monkeypatch):
    mock(monkeypatch, pihole5)
    res, _, _ = dnsfilter.poll(dict(kind="pihole", host="192.0.2.53", password="token"), {})
    c = {x["ip"]: x for x in res["clients"]}
    assert res["info"]["version"] == "v5" and c["192.0.2.41"] == dict(ip="192.0.2.41", mac="", name="pc.lan", queries=500, blocked=50, pct=10.0)
    assert res["summary"]["listed"] == 99999
