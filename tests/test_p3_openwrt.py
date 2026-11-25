"""OpenWrt über ubus (JSON-RPC): Anmeldung, HTTPS→HTTP, Ports (DSA), WAN-Traffic, Clients aus Leases und iwinfo, WLANs,
VLANs aus bridge-vlan, Übernahme als Router mit WLAN-Clients, Aktionen (WLAN per UCI, Neustart), Konfigurations-Backup."""
import gzip
import io
import json
import tarfile

import httpx

from app import actions, configbackup, integrations, vlanplan
from app.db import db
from app.drivers import openwrt
from tests.test_m6 import H, login

SID = "a" * 32
REAL_CLIENT = httpx.Client
CALLS, STATE = [], {"wan_rx": 1000, "https": False, "bad_pw": False}
PHONE, LAPTOP, PC = "DA:00:00:00:01:01", "DA:00:00:00:01:02", "AA:BB:CC:00:01:03"


def _dev(up, carrier, speed, mac, rx=0, tx=0):
    return {"up": up, "carrier": carrier, "speed": speed, "macaddr": mac, "present": True, "statistics": {"rx_bytes": rx, "tx_bytes": tx}}


def ubus(obj, method, args):
    if (obj, method) == ("system", "board"):
        return {"hostname": "OpenWrt-Flur", "model": "GL.iNet GL-MT6000", "release": {"distribution": "OpenWrt", "version": "24.10.2", "revision": "r28739"}}
    if (obj, method) == ("system", "info"):
        return {"uptime": 93784}
    if (obj, method) == ("network.device", "status"):
        return {"eth0": _dev(True, True, "10000F", "94:83:C4:00:00:01"), "eth1": _dev(True, True, "2500F", "94:83:C4:00:00:02"),
                "lan1": _dev(True, True, "1000F", "94:83:C4:00:00:01", 500, 900), "lan2": _dev(True, False, "-1", "94:83:C4:00:00:01"),
                "lan10": _dev(True, True, "100F", "94:83:C4:00:00:01"), "wan": _dev(True, True, "1000F", "94:83:C4:00:00:03", STATE["wan_rx"], 2000),
                "br-lan": {"up": True, "macaddr": "94:83:C4:00:00:01", "statistics": {}}, "br-lan.20": {"up": True, "macaddr": "94:83:C4:00:00:01"},
                "phy0-ap0": _dev(True, True, "", "94:83:C4:00:00:05")}
    if (obj, method) == ("network.interface", "dump"):
        return {"interface": [{"interface": "lan", "up": True, "l3_device": "br-lan", "ipv4-address": [{"address": "192.0.2.1", "mask": 24}]},
                              {"interface": "wan", "up": True, "l3_device": "wan", "ipv4-address": [{"address": "198.51.100.7", "mask": 24}]}]}
    if (obj, method) == ("luci-rpc", "getDHCPLeases"):
        return {"dhcp_leases": [{"hostname": "pc-buero", "ipaddr": "192.0.2.10", "macaddr": PC.lower(), "expires": 3000},
                                {"hostname": "handy", "ipaddr": "192.0.2.11", "macaddr": PHONE.lower(), "expires": 3000}]}
    if (obj, method) == ("luci-rpc", "getHostHints"):
        return {LAPTOP.lower(): {"name": "laptop", "ipaddrs": ["192.0.2.12"]}, PHONE.lower(): {"name": "handy", "ipaddrs": ["192.0.2.11"]}}
    if (obj, method) == ("network.wireless", "status"):
        return {"radio0": {"up": True, "config": {"band": "2g"}, "interfaces": [{"section": "default_radio0", "ifname": "phy0-ap0", "config": {"ssid": "Zuhause", "mode": "ap"}}]},
                "radio1": {"up": True, "config": {"band": "5g"}, "interfaces": [
                    {"section": "wifinet2", "ifname": "phy1-ap0", "config": {"ssid": "Zuhause", "mode": "ap"}},
                    {"section": "gast", "ifname": "", "config": {"ssid": "Gast", "mode": "ap", "disabled": "1"}},
                    {"section": "mesh0", "ifname": "phy1-mesh0", "config": {"mode": "mesh"}}]}}
    if (obj, method) == ("iwinfo", "assoclist"):
        return {"results": [{"mac": PHONE, "signal": -52}]} if args["device"] == "phy0-ap0" else \
            {"results": [{"mac": LAPTOP, "signal": -61}]} if args["device"] == "phy1-ap0" else {"results": []}
    if (obj, method) == ("uci", "get"):
        return {"values": {"lan": {".type": "interface", ".name": "lan", "device": "br-lan"},
                           "iot": {".type": "interface", ".name": "iot", "device": "br-lan.20"},
                           "cfg1": {".type": "bridge-vlan", "device": "br-lan", "vlan": "1", "ports": ["lan1:t", "lan2:u*", "lan10"]},
                           "cfg2": {".type": "bridge-vlan", "device": "br-lan", "vlan": "20", "ports": ["lan1:t", "lan10:u*"]}}}
    if (obj, method) in (("uci", "set"), ("uci", "commit"), ("network", "reload"), ("system", "reboot")):
        return {}
    return None


def handler(req):
    if req.url.scheme == "https" and not STATE["https"]:
        raise httpx.ConnectError("refused", request=req)
    if req.url.path == "/cgi-bin/cgi-backup":
        assert b"sessionid=" + SID.encode() in req.content
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, data in (("etc/config/network", b"config interface 'lan'\n"), ("etc/config/wireless", b"config wifi-iface 'default_radio0'\n")):
                ti = tarfile.TarInfo(name)
                ti.size, ti.mtime = len(data), STATE.get("mtime", 1000)
                tf.addfile(ti, io.BytesIO(data))
        return httpx.Response(200, content=buf.getvalue())
    body = json.loads(req.content)
    sid, obj, method, args = body["params"]
    CALLS.append((obj, method, args))
    if (obj, method) == ("session", "login"):
        if STATE["bad_pw"] or args["password"] != "geheim":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": [6]})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": [0, {"ubus_rpc_session": SID}]})
    if sid != SID:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32002, "message": "Access denied"}})
    res = ubus(obj, method, args)
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": [0, res] if res is not None else [4]})


def mock(monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(openwrt.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


CONF = dict(host="192.0.2.1", username="root", password="geheim", scheme="auto")


def test_poll_normalize(monkeypatch):
    mock(monkeypatch)
    assert openwrt.test(CONF) == dict(name="OpenWrt-Flur", model="GL.iNet GL-MT6000", version="24.10.2 r28739", ports=4, clients=3, wifi=3)
    res, metrics, state = openwrt.poll(CONF, {})
    assert state["base"] == "http://192.0.2.1"  # HTTPS verweigert -> HTTP
    i = res["info"]
    assert (i["vendor"], i["uptime"], i["addresses"]) == ("GL.iNet", 93784, ["192.0.2.1", "198.51.100.7"])
    assert [p["iface"] for p in res["ports"]] == ["lan1", "lan2", "lan10", "wan"]  # DSA: eth0/eth1 sind CPU-Anschlüsse
    assert res["ports"][0]["oper"] == "up" and res["ports"][0]["speed"] == 1000 and res["ports"][1]["oper"] == "down"
    assert res["wan"]["iface"] == "wan" and res["wan"]["connected"] is True and res["role"] == "router"
    wifi = {w["id"]: w for w in res["wifi"]}
    assert set(wifi) == {"default_radio0", "wifinet2", "gast"} and wifi["gast"]["enabled"] is False and wifi["wifinet2"]["band"] == "5 GHz"
    cl = {c["mac"]: c for c in res["clients"]}
    assert cl[PC]["medium"] == "lan" and cl[PC]["name"] == "pc-buero" and cl[PC]["port"] is None
    assert cl[PHONE]["medium"] == "wlan" and cl[PHONE]["band"] == "2,4 GHz" and cl[PHONE]["signal"] == "-52"
    assert cl[LAPTOP]["ip"] == "192.0.2.12" and cl[LAPTOP]["name"] == "laptop" and cl[LAPTOP]["band"] == "5 GHz"
    assert res["vlans"]["ports"] == {1: dict(untagged=None, tagged=[1, 20]), 2: dict(untagged=1, tagged=[]), 3: dict(untagged=20, tagged=[])}
    assert {v["vid"]: v["name"] for v in res["vlans"]["vlans"]} == {1: "", 20: "iot"}
    assert res["firmware"]["installed"] == "24.10.2"
    STATE["wan_rx"] = 1000 + 125000
    state["counters"] = {k: (v[0], v[1], v[2] - 10) for k, v in state["counters"].items()}
    _, m2, _ = openwrt.poll(CONF, state)
    assert abs(m2["wan:rx"] - 100000) < 2000
    STATE["wan_rx"] = 1000


def test_errors(monkeypatch):
    mock(monkeypatch)
    try:
        openwrt.test(dict(CONF, password="falsch"))
        raise AssertionError
    except openwrt.DriverError as ex:
        assert "Anmeldung abgelehnt" in str(ex)
    monkeypatch.setattr(openwrt.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(lambda r: httpx.Response(404)), **kw))
    try:
        openwrt.test(dict(CONF, scheme="http"))
        raise AssertionError
    except openwrt.DriverError as ex:
        assert "uhttpd-mod-ubus" in str(ex)


def test_apply_actions_backup(monkeypatch):
    mock(monkeypatch)
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "OpenWrt"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    r = cl.post(f"{P}/integrations", json=dict(driver="openwrt", host="192.0.2.1", username="root", password="geheim"), headers=H)
    assert r.status_code == 200, r.text
    iid = r.json()["id"]
    s = integrations.poll(iid)
    assert s["vlan_ports"] == 3 and s["new"] >= 3
    devs = {d["name"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    rt = devs["OpenWrt-Flur"]
    assert rt["type"] == "router" and rt["manufacturer"] == "GL.iNet" and rt["model"] == "GL.iNet GL-MT6000"
    assert devs["handy"]["uplink"]["device_name"] == "OpenWrt-Flur" and devs["handy"]["uplink"]["medium"] == "wlan"
    assert devs["pc-buero"]["uplink"] is None  # Port unbekannt: nicht raten
    with db() as c:
        assert vlanplan.snmp_devices(c, pid)[rt["id"]] == "openwrt"
        acts = {a["label"]: a for a in actions.available(c, pid, rt["id"])}
    assert set(acts) >= {"WLAN „Zuhause“ (2,4 GHz) ausschalten", "WLAN „Gast“ (5 GHz) einschalten", "OpenWrt neu starten"}
    CALLS.clear()
    actions.run(pid, 1, rt["id"], acts["WLAN „Zuhause“ (2,4 GHz) ausschalten"]["key"])
    assert ("uci", "set", {"config": "wireless", "section": "default_radio0", "values": {"disabled": "1"}}) in CALLS
    assert ("uci", "commit", {"config": "wireless"}) in CALLS and ("network", "reload", {}) in CALLS
    actions.run(pid, 1, rt["id"], acts["OpenWrt neu starten"]["key"])
    assert ("system", "reboot", {}) in CALLS
    try:
        openwrt.action(CONF, {}, "wlan", dict(id="x'; reboot", on=True))
        raise AssertionError
    except openwrt.DriverError:
        pass
    # Backup: zweimal mit anderen Zeitstempeln -> gleiche Datei (unverändert), Inhalt bleibt ein gültiges tar.gz
    r1 = configbackup.run(iid, interactive=True)
    STATE["mtime"] = 99999
    r2 = configbackup.run(iid, interactive=True)
    STATE.pop("mtime")
    assert r1["status"] in ("new", "unchanged") and r2["status"] == "unchanged"  # vor der WLAN-Aktion schon automatisch gesichert
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM config_backups WHERE integration_id=?", (iid,)).fetchone()[0] == 1
    name, data, is_text = openwrt.backup(CONF, {})
    assert name == "backup-192.0.2.1.tar.gz" and is_text is False and data[:2] == b"\x1f\x8b"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        assert sorted(tf.getnames()) == ["etc/config/network", "etc/config/wireless"] and all(m.mtime == 0 for m in tf.getmembers())
    assert gzip.decompress(data)
