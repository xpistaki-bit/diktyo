"""ASUS: Traffic Monitor (netdev) und Traffic Analyzer gegen einen nachgebildeten Router."""
import json

import httpx

from app import integrations, topology
from app.db import db, now
from app.drivers import asuswrt
from tests.test_m6 import H, login

R = {"wan_rx": 0x10000000, "logins": 0, "ta": True}


def handler(req):
    p = req.url.path
    if p == "/login.cgi":
        R["logins"] += 1
        return httpx.Response(200, json={"asus_token": "TOK"})
    assert req.headers.get("cookie", "").find("asus_token=TOK") >= 0
    if p == "/appGet.cgi":
        hook = req.url.params["hook"]
        data = {"productid": "EBM68", "firmver": "3.0.0.6", "buildno": "102", "lan_ipaddr": "192.168.50.1", "label_mac": "AA:00:00:00:00:01",
                "get_clientlist": {"maclist": ["11:22:33:44:55:01", "11:22:33:44:55:02"],
                                   "11:22:33:44:55:01": {"mac": "11:22:33:44:55:01", "ip": "192.168.50.20", "nickName": "HisenseTV", "isWL": "2",
                                                         "isOnline": "1", "curTx": "866", "curRx": "780", "amesh_papMac": "AA:00:00:00:00:01"},
                                   "11:22:33:44:55:02": {"mac": "11:22:33:44:55:02", "ip": "192.168.50.21", "name": "S25-Ultra", "isWL": "1",
                                                         "isOnline": "1", "amesh_papMac": "AA:00:00:00:00:01"}},
                "get_cfg_clientlist": [{"mac": "AA:00:00:00:00:01", "ip": "192.168.50.1", "alias": "EBM68", "level": "0", "online": "1"}],
                "bwdpi_db_enable": "1"}
        if "netdev(appobj)" in hook:
            data["netdev"] = {"INTERNET_rx": hex(R["wan_rx"]), "INTERNET_tx": "0x2000000", "WIRED_rx": "0x100", "WIRED_tx": "0x200",
                              "WIRELESS0_rx": "0x0", "WIRELESS0_tx": "0x0", "WIRELESS1_rx": "0x5000", "WIRELESS1_tx": "0x9000"}
        return httpx.Response(200, text=json.dumps(data))
    if p == "/getAppTraffic.asp" and R["ta"]:
        assert req.url.params["client"] == "all" and req.url.params["mode"] == "detail"
        return httpx.Response(200, text='array_statistics = [["11:22:33:44:55:01", 263100000, 11200000000], ["11:22:33:44:55:02", 471600000, 2500000000]];')
    if p == "/getWanTraffic.asp" and R["ta"]:
        return httpx.Response(200, text="array_statistics = [[1000, 20000], [3000, 90000]];")
    return httpx.Response(404, text="")


def mock(monkeypatch):
    real = asuswrt._client
    monkeypatch.setattr(asuswrt, "_client", lambda conf: httpx.Client(base_url=real(conf).base_url, transport=httpx.MockTransport(handler)))


def test_parsers():
    tr, cnt = asuswrt.parse_netdev({"INTERNET_rx": "0x10", "INTERNET_tx": "32", "WIRELESS1_rx": "bad"}, {}, 100.0)
    assert tr["wan"]["rx_total"] == 16 and tr["wan"]["tx_total"] == 32 and "wl1" not in tr and cnt["wan"] == (16, 32, 100.0)
    tr, _ = asuswrt.parse_netdev({"INTERNET_rx": "0x110", "INTERNET_tx": "0x20"}, cnt, 110.0)
    assert tr["wan"]["rx_bps"] == round(256 * 8 / 10) and tr["wan"]["tx_bps"] == 0
    assert asuswrt.parse_statistics("var x; array_statistics = [['aa:bb', 1, 2]];") == [["aa:bb", 1, 2]]
    assert asuswrt.parse_statistics("<html>login</html>") is None


def test_asus_poll_traffic_and_views(monkeypatch):
    mock(monkeypatch)
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "ASUS-Traffic"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, port, username, secret, options, created) VALUES(?,?,?,?,?,?,?,?,?)",
                        (pid, "asuswrt", "ASUS", "192.168.50.1", 8443, "admin", integrations.security.encrypt(json.dumps({"password": "x"})),
                         json.dumps({"scheme": "https", "cfg_schedule": "no"}), now())).lastrowid
    integrations.poll(iid)
    R["wan_rx"] += 12_500_000
    integrations.poll(iid)
    assert R["logins"] == 1  # Sitzung wird weiterverwendet
    with db() as c:
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()["state"])
        c.execute("UPDATE devices SET status='confirmed' WHERE profile_id=?", (pid,))
    res = st["result"]
    assert res["traffic"]["wan"]["rx_bps"] > 0 and res["wan"]["rx_bps"] == res["traffic"]["wan"]["rx_bps"]
    assert set(res["traffic"]) >= {"wan", "lan", "wl0", "wl1"}
    assert res["analyzer"]["clients"][0] == {"mac": "11:22:33:44:55:01", "tx": 263100000, "rx": 11200000000}
    assert res["analyzer"]["wan_hours"] == [[1000, 20000], [3000, 90000]]
    m = cl.get(f"{P}/metrics?keys=i{iid}:wan:rx&since=7200").json()
    assert m["series"][f"i{iid}:wan:rx"]
    # Karte: Namen zu den MACs
    card = next(x for x in cl.get(f"{P}/integrations").json()["integrations"] if x["id"] == iid)
    assert {x["name"] for x in card["devices_by_mac"]} == {"HisenseTV", "S25-Ultra"}
    # Topologie mit Durchsatz: WLAN-Geräte zeigen den Tagesverbrauch
    with db() as c:
        t = topology.build(c, pid, traffic=True)
        tv = c.execute("SELECT id FROM devices WHERE profile_id=? AND name='HisenseTV'", (pid,)).fetchone()["id"]
    e = next(x for x in t["edges"] if x["target"] == f"d{tv}")
    assert e["today_bytes"] == 263100000 + 11200000000
    # Gerätedialog und Übersicht
    h = cl.get(f"{P}/devices/{tv}/health").json()
    assert h["today"] == {"rx": 11200000000, "tx": 263100000, "source": "ASUS Traffic Analyzer"}
    d = cl.get(f"{P}/dashboard").json()
    assert d["top_today"][0]["name"] == "HisenseTV" and d["wan"]["integration"] == iid


def test_asus_diagnose(monkeypatch):
    mock(monkeypatch)
    R["ta"] = False
    try:
        r = asuswrt.diagnose(dict(host="192.168.50.1", port=8443, scheme="https", username="admin", password="x"))
    finally:
        R["ta"] = True
    t = {s["title"]: s for s in r["steps"]}
    assert t["Anmeldung"]["ok"] and "EBM68" in t["Anmeldung"]["detail"]
    assert t["Client-Liste"]["ok"] and "curTx" in t["Client-Liste"]["detail"]
    assert t["Traffic Monitor (netdev)"]["ok"] and "WAN" in t["Traffic Monitor (netdev)"]["detail"]
    assert t["Traffic Analyzer (pro Client)"]["ok"] is False and "Nicht alle Daten" in r["summary"]
