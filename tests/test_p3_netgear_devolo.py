"""SNMP-Profile (Netgear: ENTITY-MIB, Inventar, Temperatur; Hersteller-Erkennung, Hinweise) und devolo Powerline
(mDNS-Unicast, Protobuf-Antworten, Digest-Anmeldung mit SHA-256-Ersatz, Adapter, Datenraten, WLAN-Geräte, Firmware)."""
import hashlib
import json
import socket
import struct
import threading

import httpx

from app import integrations
from app.db import db
from app.drivers import devolo, snmp, snmplib as s, snmpprofiles as sp
from tests.test_m3 import Agent, switch_tree
from tests.test_m6 import H, login

NG = "1.3.6.1.4.1.4526.10"


def netgear_tree():
    t = switch_tree(100)
    t[snmp.SYS["descr"]] = b"GS724TPv2 24-Port Gigabit Smart Managed Pro Switch"
    t[snmp.SYS["object_id"]] = b"1.3.6.1.4.1.4526.100.4.39"
    t[snmp.SYS["name"]] = b"Netgear Buero"
    # ENTITY-MIB: Modul (Klasse 9) zuerst, dann das Gehäuse (Klasse 3) mit Modell, aber ohne Seriennummer
    t[f"{sp.ENT_CLASS}.1"], t[f"{sp.ENT_CLASS}.2"] = 9, 3
    t[f"{sp.ENT_MODEL}.2"], t[f"{sp.ENT_SERIAL}.2"], t[f"{sp.ENT_MFG}.2"] = b"GS724TPv2", b"", b"NETGEAR"
    t[f"{sp.ENT_HW}.2"] = b"V2.0"
    # Netgear-Inventar und zwei Temperaturfühler
    t[f"{NG}.1.1.1.4.0"], t[f"{NG}.1.1.1.13.0"], t[f"{NG}.1.1.1.3.0"] = b"4CR1234567890", b"6.0.10.18", b"GS724TPv2"
    t[f"{NG}.43.1.8.1.5.1.0"], t[f"{NG}.43.1.8.1.5.1.1"] = 41, 47
    t[f"{sp.HR_CPU}.1"], t[f"{sp.HR_CPU}.2"] = 12, 20
    return t


def test_profile_detection_and_hints():
    assert sp.enterprise("1.3.6.1.4.1.4526.100.4.39") == "4526" and sp.enterprise(".1.3.6.1.4.1.890.1.15") == "890" and sp.enterprise("1.3.6.1.2.1") == ""
    assert sp.detect("1.3.6.1.4.1.4526.100.4.39") == "netgear" and sp.detect("1.3.6.1.4.1.890") == "zyxel"
    assert sp.detect("1.3.6.1.4.1.99999", "NETGEAR GS110TP") == "netgear" and sp.detect("", "irgendwas") == "generic"
    assert sp.detect("1.3.6.1.4.1.890", choice="generic") == "generic"
    assert "Read-Write" in sp.hint("netgear", "write") and "GS308E" in sp.hint("netgear", "enable") and sp.hint("generic", "write") == ""
    keys = [k for k, _ in sp.CHOICES]
    assert keys[0] == "auto" and "netgear" in keys
    assert next(f for f in snmp.FIELDS if f["key"] == "profile")["default"] == "auto"


def test_netgear_poll_and_apply():
    agent = Agent(netgear_tree())
    agent.start()
    conf = dict(host="127.0.0.1", port=agent.port, password="geheim")
    res, metrics, state = snmp.poll(conf, {})
    i = res["info"]
    assert (i["profile"], i["vendor"], i["model"], i["serial"], i["firmware"], i["hardware"]) == \
        ("netgear", "Netgear", "GS724TPv2", "4CR1234567890", "6.0.10.18", "V2.0")
    assert i["temperature"] == 47 and i["cpu"] == 16 and metrics["temperature"] == 47 and metrics["cpu"] == 16
    assert res["firmware"] == {"installed": "6.0.10.18"} and state["profile"] == "netgear" and len(res["ports"]) == 4
    # generischer Switch ohne Zusatz-MIBs: weiter wie bisher, nur Profil vermerkt
    plain = Agent(switch_tree(100))
    plain.start()
    r2, m2, st2 = snmp.poll(dict(conf, port=plain.port), {})
    assert r2["info"]["profile"] == "zyxel" and "serial" not in r2["info"] and "firmware" not in r2 and m2 == {}
    # Übernahme: Hersteller, Modell und Firmware am Switch
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Netgear"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    r = cl.post(f"{P}/integrations", json=dict(driver="snmp", host="127.0.0.1", port=agent.port, password="geheim", profile="auto"), headers=H)
    assert r.status_code == 200, r.text
    summary = integrations.poll(r.json()["id"])
    d = cl.get(f"{P}/devices/{summary['device_id']}").json()
    assert d["manufacturer"] == "Netgear" and d["model"] == "GS724TPv2"
    with db() as c:
        data = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (summary["device_id"],)).fetchone()["data"])
    assert data["firmware"]["installed"] == "6.0.10.18" and data["firmware"]["source"] == "snmp"


def test_write_hint_by_profile(monkeypatch):
    class C:
        def set_int(self, oid, v):
            raise s.SNMPError("Keine Antwort von 192.0.2.1")
    monkeypatch.setattr(snmp, "_client", lambda conf: C())
    try:
        snmp.action(dict(host="192.0.2.1"), {"profile": "netgear"}, "port", dict(ifindex=1, port_no=1, up=False))
        raise AssertionError
    except snmp.DriverError as ex:
        assert "Read-Write" in str(ex)


# ------------------------------------------------------------ devolo
def _key(n, w):
    return _vi(n << 3 | w)


def _vi(v):
    out = b""
    while True:
        b = v & 0x7F
        v >>= 7
        out += bytes([b | (0x80 if v else 0)])
        if not v:
            return out


def enc(*fields):
    out = b""
    for n, v in fields:
        if isinstance(v, bool) or isinstance(v, int):
            out += _key(n, 0) + _vi(int(v))
        elif isinstance(v, float):
            out += _key(n, 1) + struct.pack("<d", v)
        else:
            v = v.encode() if isinstance(v, str) else v
            out += _key(n, 2) + _vi(len(v)) + v
    return out


A1, A2 = "B8:BE:F4:00:00:01", "B8:BE:F4:00:00:02"
ROUTER, PC, PHONE = "1C:ED:6F:00:00:01", "AA:BB:CC:00:00:10", "DA:00:00:00:00:20"


def overview():
    dev1 = enc((1, "Magic 2 LAN 1-1"), (3, "7.12.5.124"), (5, "Keller"), (6, "Haus"), (7, "B8BEF4000001"), (8, 1), (9, 7),
               (10, ROUTER), (11, "192.0.2.40"), (12, True))
    dev2 = enc((1, "Magic 2 WiFi next"), (3, "5.10.2"), (5, "Wohnzimmer"), (7, "B8BEF4000002"), (8, 2), (9, 7),
               (10, PC), (10, PHONE), (11, "192.0.2.41"), (12, False))
    rate = enc((1, "B8BEF4000001"), (2, "B8BEF4000002"), (3, 812.4), (4, 655.0))
    back = enc((1, "B8BEF4000002"), (2, "B8BEF4000001"), (3, 640.0), (4, 800.0))
    return enc((1, enc((1, dev1), (1, dev2), (2, rate), (2, back))))


def svc(features=""):
    txt = {"Path": "abc123", "Version": "v0", "SN": "1234567890123456", "MT": "8601"}
    if features:
        txt["Features"] = features
    return {devolo.PLCNET: dict(port=47219, txt=txt), devolo.DEVICEAPI: dict(port=14791, txt=txt)}


CALLS = []
PW_SHA = hashlib.sha256(b"geheim").hexdigest()


def fake_get(url, auth=None, timeout=None):
    ip, port, sub = url.split("//")[1].split(":")[0], url.split(":")[2].split("/")[0], url.rsplit("/", 1)[1]
    CALLS.append((ip, sub))
    pw = auth._password.decode()
    if ip == "192.0.2.41" and pw != PW_SHA:  # zweiter Adapter erwartet den SHA-256 des Passworts
        return httpx.Response(401)
    if ip == "192.0.2.40" and pw != "geheim":
        return httpx.Response(401)
    if sub == "GetNetworkOverview":
        return httpx.Response(200, content=overview())
    if sub == "WifiConnectedStationsGet":
        return httpx.Response(200, content=enc((1, enc((1, PHONE), (2, 1), (3, 2), (4, 866), (5, 780)))))
    if sub == "UpdateFirmwareCheck":
        return httpx.Response(200, content=enc((1, 0), (2, "5.10.4")) if ip == "192.0.2.41" else enc((1, 1)))
    return httpx.Response(404)


def mock(monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(devolo.httpx, "get", fake_get)
    monkeypatch.setattr(devolo, "mdns", lambda ip, timeout=2.0: {"192.0.2.40": svc("reset,update,led"), "192.0.2.41": svc("wifi1,update,restart")}.get(ip, {}))


def test_protobuf_parsers():
    ov = devolo.parse_overview(overview())
    d1, d2 = ov["devices"]
    assert (d1["mac"], d1["name"], d1["product"], d1["firmware"], d1["local"], d1["router"], d1["technology"], d1["ip"]) == \
        (A1, "Keller", "Magic 2 LAN 1-1", "7.12.5.124", True, True, "G.hn (Magic)", "192.0.2.40")
    assert d2["bridged"] == [PC, PHONE] and d2["local"] is False and d1["network"] == "Haus"
    assert ov["rates"][0] == dict(src=A1, dst=A2, tx=812.4, rx=655.0)
    st = devolo.parse_stations(enc((1, enc((1, PHONE), (2, 2), (3, 1), (4, 144), (5, 72)))))
    assert st == [dict(mac=PHONE, guest=True, band="2,4 GHz", rx=144, tx=72)]
    assert devolo.parse_fw_check(enc((1, 0), (2, "5.10.4"))) == dict(update=True, latest="5.10.4")
    assert devolo.parse_fw_check(enc((1, 1))) == dict(update=False, latest="")
    assert devolo.pb(b"") == {}


def _rr(name, typ, rdata):
    return devolo._name(name) + struct.pack(">HHIH", typ, 0x8001, 120, len(rdata)) + rdata


def test_mdns_unicast_query():
    inst = "devolo-123._dvl-plcnetapi._tcp.local"
    txt = b"".join(bytes([len(x)]) + x for x in (b"Path=abc123", b"Version=v0", b"PlcMacAddress=B8BEF4000001"))
    resp = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 2) + _rr(devolo.PLCNET, 12, devolo._name(inst)) \
        + _rr(inst, 33, struct.pack(">HHH", 0, 0, 47219) + devolo._name("devolo-123.local")) + _rr(inst, 16, txt)
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    seen = []

    def run():
        srv.settimeout(3)
        try:
            q, addr = srv.recvfrom(2048)
            seen.append(q)
            srv.sendto(resp, addr)
        except OSError:
            pass
    th = threading.Thread(target=run, daemon=True)
    th.start()
    got = devolo.mdns("127.0.0.1", timeout=1.0, port=srv.getsockname()[1])
    th.join()
    srv.close()
    assert got == {devolo.PLCNET: dict(port=47219, txt={"Path": "abc123", "Version": "v0", "PlcMacAddress": "B8BEF4000001"})}
    assert devolo.PLCNET.split(".")[0].encode() in seen[0] and seen[0][-2:] == b"\x80\x01"  # QU-Bit gesetzt


def test_poll_and_errors(monkeypatch):
    mock(monkeypatch)
    conf = dict(host="192.0.2.40", password="geheim", fw_check="daily")
    assert devolo.test(conf) == dict(name="Keller", product="Magic 2 LAN 1-1", adapters=2)
    res, metrics, state = devolo.poll(conf, {})
    a1, a2 = res["adapters"]
    assert a2["clients"] == [dict(mac=PHONE, guest=False, band="5 GHz", rx=866, tx=780)] and a1["clients"] == []
    assert a2["firmware_info"] == dict(installed="5.10.2", latest="5.10.4", update=True) and a1["firmware_info"]["update"] is False
    assert a1["serial"] == "1234567890123456" and res["host_mac"] == A1 and res["info"]["adapters"] == 2
    assert metrics["plc:B8BEF4000001:B8BEF4000002:tx"] == 812.4 and metrics["plc:B8BEF4000002:B8BEF4000001:rx"] == 800.0
    # Firmware-Prüfung höchstens einmal am Tag
    n = sum(1 for _, sub in CALLS if sub == "UpdateFirmwareCheck")
    res2, _, state2 = devolo.poll(conf, state)
    assert sum(1 for _, sub in CALLS if sub == "UpdateFirmwareCheck") == n and res2["adapters"][1]["firmware_info"]["update"] is True
    # falsches Passwort, kein devolo-Gerät
    for bad, text in ((dict(conf, password="falsch"), "Gerätepasswort"), (dict(conf, host="192.0.2.99"), "_dvl-plcnetapi")):
        try:
            devolo.poll(bad, {})
            raise AssertionError
        except devolo.DriverError as ex:
            assert text in str(ex)


def test_apply_powerline_topology(monkeypatch):
    mock(monkeypatch)
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Powerline"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    ids = {}
    for name, typ, mac in (("FRITZ!Box", "router", ROUTER), ("PC Wohnzimmer", "computer", PC), ("Handy", "phone", PHONE)):
        ids[name] = cl.post(f"{P}/devices", json=dict(name=name, type=typ, mac=mac, status="confirmed"), headers=H).json()["id"]
    r = cl.post(f"{P}/integrations", json=dict(driver="devolo", host="192.0.2.40", password="geheim"), headers=H)
    assert r.status_code == 200, r.text
    iid = r.json()["id"]
    s1 = integrations.poll(iid)
    assert s1["adapters"] == 2 and s1["new"] == 2 and s1["clients"] == 1
    devs = {d["name"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    k, w = devs["Keller"], devs["Wohnzimmer"]
    assert k["type"] == w["type"] == "powerline" and k["manufacturer"] == "devolo" and w["model"] == "Magic 2 WiFi next"
    assert w["uplink"]["device_name"] == "Keller" and w["uplink"]["medium"] == "powerline"
    assert k["uplink"]["device_name"] == "FRITZ!Box" and k["uplink"]["medium"] == "lan"
    assert devs["PC Wohnzimmer"]["uplink"]["device_name"] == "Wohnzimmer" and devs["PC Wohnzimmer"]["uplink"]["medium"] == "lan"
    assert devs["Handy"]["uplink"]["device_name"] == "Wohnzimmer" and devs["Handy"]["uplink"]["medium"] == "wlan"
    assert s1["device_id"] == k["id"]
    with db() as c:
        fw = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (w["id"],)).fetchone()["data"])["firmware"]
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()["state"])
    assert fw["update"] is True and fw["latest"] == "5.10.4" and fw["source"] == "devolo"
    assert [a["name"] for a in st["result"]["adapters"]] == ["Keller", "Wohnzimmer"] and st["result"]["adapters"][1]["update"] is True
    assert len(st["result"]["rates"]) == 2 and st["result"]["adapters"][0]["clients"] == 0 and st["result"]["adapters"][1]["bridged"] == 1
    # Powerline als Verbindungsart: Topologie, Exporte, Auswahl im Gerätedialog (Topologie zeigt bestätigte Geräte)
    assert "powerline" in cl.get(f"{P}/meta").json()["media"]
    for x in (k, w):
        cl.put(f"{P}/devices/{x['id']}", json={"name": x["name"], "status": "confirmed"}, headers=H)
    topo = cl.get(f"{P}/topology").json()
    assert any(e["medium"] == "powerline" for e in topo["edges"])
    assert "Powerline" in cl.get(f"{P}/export/netplan.drawio").text or "C77700" in cl.get(f"{P}/export/netplan.drawio").text
    # zweite Abfrage: nichts Neues, Verbindungen bleiben
    s2 = integrations.poll(iid)
    assert s2["new"] == 0 and s2["links"] == 0
