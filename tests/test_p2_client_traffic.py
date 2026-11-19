"""Datenverkehr je Gerät aus den Integrationen: Treiber (Raten aus Zählern), Topologie, Gerätedialog, Übersicht."""
import copy
import json
import time

from app import integrations, topology
from app.db import db, now
from app.drivers import mikrotik, omada, opnsense, proxmox
from app.drivers.controller import counter_rates, parse_rate
from tests import test_m5, test_p2_mikrotik, test_p2_opn_docker
from tests.test_m6 import H, login


def test_counter_rates_and_parse_rate():
    items = [dict(mac="A", _down=1000, _up=500), dict(mac="B", _down=None, _up=None)]
    cnt = counter_rates(items, {}, 100.0)
    assert cnt == {"A": [1000, 500, 100.0]} and "down_bps" not in items[0] and "_down" not in items[0]
    items = [dict(mac="A", _down=11000, _up=1500)]
    counter_rates(items, cnt, 110.0)
    assert items[0]["down_bps"] == 8000 and items[0]["up_bps"] == 800
    items = [dict(mac="A", _down=10, _up=10)]  # Zähler zurückgesetzt (Neuverbindung) -> keine Rate
    counter_rates(items, cnt, 120.0)
    assert "down_bps" not in items[0]
    assert parse_rate("1.5Mbps") == 1_500_000 and parse_rate("800kbps") == 800_000 and parse_rate("1200") == 1200 and parse_rate("x") is None


def _mt_raw(reg_bytes, kid=None):
    data = {}
    for p in ("system/resource", "system/identity", "system/routerboard", "interface", "interface/ethernet", "interface/ethernet/poe",
              "ip/address", "ip/dhcp-server/lease", "ip/arp", "interface/bridge/host", "ip/neighbor", "interface/list/member", "interface/wifi"):
        data[p] = json.loads(test_p2_mikrotik.handler(_Req(p)).content)
    wan = [m for m in data["interface/list/member"] if m.get("list") == "WAN"]
    return dict(resource=data["system/resource"], identity=data["system/identity"], routerboard=data["system/routerboard"],
                interfaces=data["interface"], ethernet=data["interface/ethernet"], poe=data["interface/ethernet/poe"],
                addresses=data["ip/address"], leases=data["ip/dhcp-server/lease"], arp=data["ip/arp"], hosts=data["interface/bridge/host"],
                neighbors=data["ip/neighbor"], wan_members=wan, wifi_menu="interface/wifi", wifi=data["interface/wifi"],
                registrations=[{"mac-address": "11:22:33:44:55:02", "interface": "wifi1", "signal": "-58", "bytes": reg_bytes}],
                kid=kid or [])


class _Req:
    def __init__(self, p):
        self.method = "GET"
        self.headers = {"authorization": "Basic x"}
        self.url = type("U", (), {"path": "/rest/" + p})()


def test_mikrotik_wifi_bytes_and_kid_control():
    res, _, cnt = mikrotik.normalize(_mt_raw("1000000,200000"), {}, now=100.0)
    handy = next(x for x in res["clients"] if x["mac"] == "11:22:33:44:55:02")
    assert "down_bps" not in handy and cnt["clients"]["11:22:33:44:55:02"][:2] == [1000000, 200000]
    res, _, _ = mikrotik.normalize(_mt_raw("2000000,300000"), {"counters": cnt}, now=110.0)
    handy = next(x for x in res["clients"] if x["mac"] == "11:22:33:44:55:02")
    assert handy["down_bps"] == 800_000 and handy["up_bps"] == 80_000
    # Kid Control hat Vorrang und gilt auch für kabelgebundene Clients
    res, _, _ = mikrotik.normalize(_mt_raw("1,1", kid=[{"mac-address": "11:22:33:44:55:01", "rate-down": "2.5Mbps", "rate-up": "100kbps"}]), {}, now=100.0)
    nas = next(x for x in res["clients"] if x["mac"] == "11:22:33:44:55:01")
    assert nas["down_bps"] == 2_500_000 and nas["up_bps"] == 100_000
    assert integrations.client_rates(res)["11:22:33:44:55:01"] == [2_500_000, 100_000]


def test_omada_client_counters():
    cls = [dict(mac="AA-00-00-00-00-01", wireless=True, apMac="AA-00-00-00-00-AP", trafficDown=1_000_000, trafficUp=10_000)]
    _, clients = omada.normalize([({}, [], cls)])
    cnt = counter_rates(clients, {}, 100.0)
    cls[0].update(trafficDown=3_500_000, trafficUp=60_000)
    _, clients = omada.normalize([({}, [], cls)])
    counter_rates(clients, cnt, 110.0)
    assert clients[0]["down_bps"] == 2_000_000 and clients[0]["up_bps"] == 40_000


def test_opnsense_top_talkers(monkeypatch):
    test_p2_opn_docker.mock(monkeypatch, opnsense, test_p2_opn_docker.opn_handler)
    raw = opnsense.collect(dict(host="192.0.2.1", username="k", password="s"), {})
    ip = (raw["leases"] or raw["arp"])[0]
    ip = ip.get("address") or ip.get("ip")
    raw["top"] = {"lan": {"records": [{"address": ip, "rate_bits_in": 4000, "rate_bits_out": 90000}]}}
    res, _, _ = opnsense.normalize(raw, {})
    c = next(x for x in res["clients"] if x["ip"] == ip)
    assert c["down_bps"] == 90000 and c["up_bps"] == 4000


def test_proxmox_guest_rates(monkeypatch):
    data = copy.deepcopy(test_m5.FakeProxmox.DATA)
    monkeypatch.setattr(proxmox, "_get", lambda cl, path: data.get(path))
    data["/cluster/resources?type=vm"][0].update(netin=1_000_000, netout=500_000)
    conf = dict(host="192.0.2.12", username="d@pve!d", password="s")
    _, _, st = proxmox.poll(conf, {})
    data["/cluster/resources?type=vm"][0].update(netin=2_000_000, netout=600_000)
    st["guest_counters"]["101"][2] -= 10  # zehn Sekunden später
    res, _, _ = proxmox.poll(conf, st)
    ha = next(g for g in res["guests"] if g["vmid"] == 101)
    assert abs(ha["down_bps"] - 800_000) < 2000 and abs(ha["up_bps"] - 80_000) < 500 and "_down" not in ha
    assert list(integrations.client_rates(res)) == ["02:8F:B9:9E:84:82"]


def test_topology_dialog_dashboard_live_rates():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Live-Raten"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"

    def dev(name, typ, **kw):
        r = cl.post(f"{P}/devices", json=dict(name=name, type=typ, **kw), headers=H)
        assert r.status_code == 200, r.text
        return r.json()

    rt = dev("Router", "router", ips=[{"address": "192.0.2.1"}])
    phones = [dev(f"Handy {i}", "phone", mac=f"02:00:00:00:00:0{i}", uplink=dict(device_id=rt["id"], medium="wlan")) for i in range(5)]
    tv = dev("TV", "tv", mac="02:00:00:00:00:10", uplink=dict(device_id=rt["id"], medium="lan"))
    rates = {"02:00:00:00:00:00": [1_000_000, 100_000], "02:00:00:00:00:01": [3_000_000, 50_000], "02:00:00:00:00:10": [20_000_000, 1_000_000]}
    with db() as c:
        c.execute("UPDATE devices SET status='confirmed' WHERE profile_id=?", (pid,))
        c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, created, state) VALUES(?,?,?,?,?,?,?)",
                  (pid, "mikrotik", "hAP", "192.0.2.1", "{}", now(), json.dumps(dict(ts=time.time(), result=dict(rates=rates)))))
        t = topology.build(c, pid, traffic=True)
    grp = next(e for e in t["edges"] if str(e["target"]).startswith("g"))
    assert grp["down_bps"] == 4_000_000 and grp["up_bps"] == 150_000 and grp["traffic_src"] == "hAP"
    e_tv = next(e for e in t["edges"] if e["target"] == f"d{tv['id']}")
    assert e_tv["down_bps"] == 20_000_000
    assert not any("member_ids" in n for n in t["nodes"])
    h = cl.get(f"{P}/devices/{phones[1]['id']}/health").json()
    assert h["live"] == {"down": 3_000_000, "up": 50_000, "source": "hAP"}
    d = cl.get(f"{P}/dashboard").json()
    assert [x["name"] for x in d["top_now"]] == ["TV", "Handy 1", "Handy 0"]
    with db() as c:
        c.execute("UPDATE integrations SET state=? WHERE profile_id=?", (json.dumps(dict(ts=time.time() - 3600, result=dict(rates=rates))), pid))
        t_old = topology.build(c, pid, traffic=True)
    assert not any("down_bps" in e for e in t_old["edges"])
