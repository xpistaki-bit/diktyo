"""MikroTik per SNMP (v2c und v3) gegen simulierte Agenten: Board/Version (MIKROTIK-MIB), Ports, PoE, ARP, Bridge-Tabelle,
WLAN-Registrierungen, Nachbarn, WAN über die Standardroute; Aktionen sind bei SNMP gesperrt."""
from app.drivers import mikrotik, mikrotik_snmp as ms, snmp, snmplib as s
from tests import test_m3_snmpv3 as v3
from tests.test_m3 import Agent

MAC_WLAN_CLIENT = (0x11, 0x22, 0x33, 0x44, 0x55, 0x02)


def mikrotik_tree():
    t = {snmp.SYS["descr"]: b"RouterOS RB2011UiAS-2HnD", snmp.SYS["name"]: b"Thessaloniki Core", snmp.SYS["object_id"]: b"1.3.6.1.4.1.14988.1",
         snmp.SYS["uptime"]: (s.TIMETICKS, 8640000), snmp.SYS["location"]: b""}
    ifs = {1: ("ether1", 6), 2: ("ether2", 6), 3: ("ether3", 6), 4: ("ether4", 6), 5: ("ether5", 6), 6: ("wlan1", 71), 7: ("bridge", 209)}
    for i, (name, typ) in ifs.items():
        t[f"{ms.IF_TYPE}.{i}"] = typ
        t[f"{ms.IF_NAME}.{i}"] = name.encode()
        t[f"{ms.IF_ADMIN}.{i}"] = 2 if i == 4 else 1
        t[f"{ms.IF_OPER}.{i}"] = 2 if i in (3, 4) else 1
        t[f"{ms.IF_MAC}.{i}"] = bytes([0x48, 0xA9, 0x8A, 0, 0, i])
        t[f"{ms.IF_IN}.{i}"] = (s.COUNTER64, 1000 * i)
        t[f"{ms.IF_OUT}.{i}"] = (s.COUNTER64, 2000 * i)
        t[f"{ms.IF_SPEED}.{i}"] = (s.GAUGE32, 1000 if i <= 5 else 0)
        if i <= 6:
            t[f"{snmp.BASE_PORT_IF}.{i}"] = i
    t[f"{ms.IF_ALIAS}.2"] = b"NAS"
    t[f"{ms.IP_ADDR}.192.168.88.1"] = b"\xc0\xa8\x58\x01"
    # ARP (ifIndex 7 = bridge): NAS, Handy, Kamera
    for ip, mac in (("192.168.88.10", (0x11, 0x22, 0x33, 0x44, 0x55, 0x01)), ("192.168.88.20", MAC_WLAN_CLIENT), ("192.168.88.40", (0x11, 0x22, 0x33, 0x44, 0x55, 0x04))):
        t[f"{ms.ARP_MAC}.7.{ip}"] = bytes(mac)
        t[f"{ms.ARP_TYPE}.7.{ip}"] = 3
    # Bridge-Tabelle: NAS an ether2, Kamera an ether5
    t[f"{snmp.FDB_PORT}.17.34.51.68.85.1"] = 2
    t[f"{snmp.FDB_PORT}.17.34.51.68.85.4"] = 5
    # WLAN: SSID, Registrierung des Handys an wlan1
    t[f"{ms.MT_AP_SSID}.6"] = b"Buero"
    t[f"{ms.MT_AP_BAND}.6"] = b"2ghz-b/g/n"
    idx = ".".join(map(str, MAC_WLAN_CLIENT)) + ".6"
    t[f"{ms.MT_RTAB_STRENGTH}.{idx}"] = 58
    # Nachbar an ether1 (Uplink), Standardroute über ether1, PoE an ether5
    t[f"{ms.MT_NB_IP}.1"] = bytes([192, 168, 178, 1])
    t[f"{ms.MT_NB_MAC}.1"] = bytes([0xAA, 0xAA, 0xAA, 0xAA, 0xAA, 1])
    t[f"{ms.MT_NB_IDENTITY}.1"] = b"fritz.box"
    t[f"{ms.MT_NB_PLATFORM}.1"] = b"AVM"
    t[f"{ms.MT_NB_IF}.1"] = 1
    t[f"{ms.ROUTE_IF}.0.0.0.0.0.0.0.0.0.192.168.178.1"] = 1
    t[f"{ms.MT_POE_NAME}.5"] = b"ether5"
    t[f"{ms.MT_POE_STATUS}.5"] = 3
    t[ms.MT_VERSION], t[ms.MT_SERIAL], t[ms.MT_BOARD] = b"6.49.10", b"HGX0001", b"RB2011UiAS-2HnD"
    t[ms.MT_FW], t[ms.MT_FW_UP] = b"6.48.6", b"6.49.10"
    t["1.3.6.1.2.1.25.3.3.1.2.1"] = 7
    return t


def _check(res):
    i = res["info"]
    assert (i["name"], i["model"], i["version"], i["serial"], i["cpu"]) == ("Thessaloniki Core", "RB2011UiAS-2HnD", "6.49.10", "HGX0001", "7")
    ports = {p["name"]: p for p in res["ports"]}
    assert list(ports) == ["ether1", "ether2", "ether3", "ether4", "ether5"]
    assert ports["ether2"]["alias"] == "NAS" and ports["ether2"]["speed"] == 1000 and ports["ether4"]["admin"] == "down" and ports["ether3"]["oper"] == "down"
    assert ports["ether5"]["poe"] is True and ports["ether2"]["poe"] is None
    assert ports["ether1"]["lldp"]["name"] == "fritz.box" and ports["ether1"]["lldp"]["ip"] == "192.168.178.1"
    assert res["wifi"][0]["ssid"] == "Buero" and res["wifi"][0]["band"] == "2,4 GHz"
    cl = {c["ip"]: c for c in res["clients"]}
    assert cl["192.168.88.10"]["port"] == 2 and cl["192.168.88.40"]["port"] == 5
    assert cl["192.168.88.20"]["medium"] == "wlan" and cl["192.168.88.20"]["signal"] == "58"
    assert res["wan"]["iface"] == "ether1"


def test_mikrotik_snmp_v2c():
    agent = Agent(mikrotik_tree(), community="geheim")
    agent.start()
    conf = dict(host="127.0.0.1", access="snmp", port=agent.port, snmp_version="v2c", community="geheim")
    assert mikrotik.test(conf)["name"] == "Thessaloniki Core"
    res, metrics, state = mikrotik.poll(conf, {})
    _check(res)
    assert res["firmware"]["update"] and "RouterBOOT 6.49.10" in res["firmware"]["latest"]
    # Aktionen gehen über SNMP nicht
    try:
        mikrotik.action(conf, {}, "reboot", {})
        raise AssertionError
    except mikrotik.DriverError as ex:
        assert "nur lesen" in str(ex)
    # falsche Community: Fehler statt leerer Daten
    try:
        mikrotik.test(dict(conf, community="falsch"))
        raise AssertionError
    except mikrotik.DriverError:
        pass


def test_mikrotik_snmp_v3(monkeypatch):
    monkeypatch.setattr(v3, "TREE", mikrotik_tree())
    a = v3.AgentV3()
    a.start()
    conf = dict(host="127.0.0.1", access="snmp", port=a.port, snmp_version="v3", snmp_user="monitor", auth_proto="SHA", auth_pass="auth-pass-1",
                priv_proto="AES", priv_pass="priv-pass-2")
    res, _, _ = mikrotik.poll(conf, {})
    _check(res)


def test_snmp_access_fields_and_actions():
    keys = {f["key"]: f for f in mikrotik.FIELDS}
    assert ["snmp", "SNMP (v2c oder v3, nur lesen)"] in keys["access"]["options"]
    assert keys["community"]["show"] == {"access": "snmp", "snmp_version": "v2c"} and keys["password"]["show"]["access"] == ["api", "api-ssl", "https", "http"]
    assert mikrotik.access_of(dict(port=161)) == "snmp" and mikrotik._port(dict(access="snmp")) == 161
    assert ms.snmp_conf(dict(host="h", snmp_version="v3", snmp_user="u", community="c"))["username"] == "u"
