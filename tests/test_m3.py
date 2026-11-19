"""M3: SNMP-Client und -Treiber (gegen einen simulierten Agenten), FRITZ!Box-Mesh, Übernahme in den Bestand, Überwachung, API."""
import socket
import threading

from fastapi.testclient import TestClient

from app import integrations, main, monitor, users
from app.db import db, now
from app.drivers import fritzbox, snmp, snmplib as s

H = {"X-Requested-With": "diktyo"}


# ------------------------------------------------------------ simulierter SNMP-Agent
def _val(v):
    if isinstance(v, tuple):  # (Tag, Zahl) für Zähler
        tag, n = v
        return s._tlv(tag, n.to_bytes(max(1, (n.bit_length() + 7) // 8), "big"))
    if isinstance(v, int):
        return s._int(v)
    if isinstance(v, bytes):
        return s._tlv(s.OCTETS, v)
    return s._tlv(s.OCTETS, str(v).encode())


def _key(o):
    return [int(x) for x in o.split(".")]


class Agent(threading.Thread):
    def __init__(self, tree, community="geheim"):
        super().__init__(daemon=True)
        self.tree, self.community = tree, community
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]

    def run(self):
        while True:
            data, addr = self.sock.recvfrom(65535)
            _, msg, _ = s._read(data, 0)
            i = 0
            _, _, i = s._read(msg, i)
            _, comm, i = s._read(msg, i)
            if bytes(comm).decode() != self.community:
                continue
            ptype, pdu, _ = s._read(msg, i)
            j = 0
            _, rid, j = s._read(pdu, j)
            _, _, j = s._read(pdu, j)
            _, maxrep, j = s._read(pdu, j)
            _, vbl, _ = s._read(pdu, j)
            _, vb, _ = s._read(vbl, 0)
            _, ob, _ = s._read(vb, 0)
            oid = s._decode_oid(ob)
            keys = sorted(self.tree, key=_key)
            out = []
            if ptype == s.GET:
                k = 0
                while k < len(vbl):
                    _, vb2, k = s._read(vbl, k)
                    _, ob2, _ = s._read(vb2, 0)
                    o = s._decode_oid(ob2)
                    out.append(s._tlv(s.SEQ, s._oid(o) + (_val(self.tree[o]) if o in self.tree else s._tlv(s.NOSUCHOBJECT, b""))))
            else:
                n = int.from_bytes(maxrep, "big") or 10
                nxt = [k for k in keys if _key(k) > _key(oid)][:n]
                for k in nxt:
                    out.append(s._tlv(s.SEQ, s._oid(k) + _val(self.tree[k])))
                if not nxt:
                    out.append(s._tlv(s.SEQ, s._oid(oid) + s._tlv(s.ENDOFMIB, b"")))
            resp_pdu = s._tlv(s.RESPONSE, s._tlv(s.INT, bytes(rid)) + s._int(0) + s._int(0) + s._tlv(s.SEQ, b"".join(out)))
            self.sock.sendto(s._tlv(s.SEQ, s._int(1) + s._tlv(s.OCTETS, comm) + resp_pdu), addr)


def switch_tree(octets=0):
    t = {snmp.SYS["descr"]: b"XGS1935-28 Lite-L3 Smart Managed Switch", snmp.SYS["name"]: b"XGS1935", snmp.SYS["object_id"]: b"1.3.6.1.4.1.890",
         snmp.SYS["uptime"]: (s.TIMETICKS, 123400), snmp.SYS["location"]: b"Keller"}
    for i in range(1, 5):  # 4 Ethernet-Ports + 1 VLAN-Schnittstelle
        t[f"{snmp.IF_TYPE}.{i}"] = 6
        t[f"{snmp.IF_NAME}.{i}"] = f"Port{i}".encode()
        t[f"{snmp.IF_OPER}.{i}"] = 1 if i in (1, 2, 4) else 2
        t[f"{snmp.IF_SPEED}.{i}"] = (s.GAUGE32, 1000)
        t[f"{snmp.IF_IN}.{i}"] = (s.COUNTER64, octets * i)
        t[f"{snmp.IF_OUT}.{i}"] = (s.COUNTER64, octets * 2 * i)
        t[f"{snmp.BASE_PORT_IF}.{i}"] = i
    t[f"{snmp.IF_TYPE}.1000"] = 136
    macs = {1: [(0xF0, 0x2F, 0x74, 0, 0, 3)], 2: [(0x1C, 0xED, 0x6F, 7, 0x5B, 0x7A), (0xD8, 0xBB, 0xC1, 0x3F, 0x6A, 3), (0x34, 0x98, 0x7A, 0x46, 0xCC, 0x47)],
            4: [(0xAA, 0, 0, 0, 0, 1)]}
    for port, ms in macs.items():
        for m in ms:
            t[f"{snmp.QFDB_PORT}.1." + ".".join(map(str, m))] = port
    t[f"{snmp.LLDP_NAME}.0.4.1"] = b"AP-Keller"
    t[f"{snmp.LLDP_PORTDESC}.0.4.1"] = b"eth0"
    t[f"{snmp.LLDP_CHASSIS}.0.4.1"] = bytes([0xAA, 0, 0, 0, 0, 1])
    return t


def test_snmp_client_and_driver():
    agent = Agent(switch_tree(1000))
    agent.start()
    conf = dict(host="127.0.0.1", port=agent.port, password="geheim")
    assert snmp.test(conf)["name"] == "XGS1935"
    try:
        snmp.test(dict(conf, password="falsch"))
        raise AssertionError("falsche Community muss scheitern")
    except snmp.DriverError:
        pass
    res, metrics, state = snmp.poll(conf, {})
    assert res["info"]["name"] == "XGS1935" and res["info"]["uptime"] == 1234
    assert [p["port_no"] for p in res["ports"]] == [1, 2, 3, 4] and res["ports"][2]["oper"] == "down"
    assert sorted(res["ports"][1]["macs"]) == ["1C:ED:6F:07:5B:7A", "34:98:7A:46:CC:47", "D8:BB:C1:3F:6A:03"]
    assert res["ports"][3]["lldp"] == {"name": "AP-Keller", "port": "eth0", "chassis": "AA:00:00:00:00:01"}
    assert metrics == {}  # Raten erst ab der zweiten Abfrage
    agent.tree.update(switch_tree(1000 + 125000))  # +125 000 Byte je Port-Faktor
    state["counters"] = {k: (v[0], v[1], v[2] - 10) for k, v in state["counters"].items()}  # 10 s früher
    res2, metrics2, _ = snmp.poll(conf, state)
    assert abs(metrics2["port:1:rx"] - 100000) < 2000 and abs(metrics2["port:1:tx"] - 200000) < 4000


def test_mesh_parser():
    data = {"nodes": [
        {"uid": "m", "device_name": "FRITZ!Box", "device_mac_address": "1C:ED:6F:07:5B:7A", "mesh_role": "master", "node_interfaces": [
            {"uid": "m-lan3", "name": "LAN:3", "type": "LAN", "node_links": [{"node_interface_1_uid": "m-lan3", "node_interface_2_uid": "sw-1", "state": "CONNECTED", "cur_data_rate_rx": 1000000}]},
            {"uid": "m-5g", "name": "AP:5G:0", "type": "WLAN", "node_links": [{"node_interface_1_uid": "m-5g", "node_interface_2_uid": "ph-w", "state": "CONNECTED"}]}]},
        {"uid": "sw", "device_name": "XGS1935", "device_mac_address": "70:49:A2:55:28:34", "node_interfaces": [{"uid": "sw-1", "name": "eth0", "type": "LAN", "node_links": []}]},
        {"uid": "ph", "device_name": "Handy", "device_mac_address": "DA:00:00:00:00:01", "node_interfaces": [{"uid": "ph-w", "name": "wlan", "type": "WLAN", "node_links": []}]},
    ]}
    m = fritzbox.parse_mesh(data)
    assert m["70:49:A2:55:28:34"] == dict(node="1C:ED:6F:07:5B:7A", node_name="FRITZ!Box", iface="LAN 3", medium="lan", rate=1000, master=True)
    assert m["DA:00:00:00:00:01"]["iface"] == "WLAN 5 GHz" and m["DA:00:00:00:00:01"]["medium"] == "wlan"


def _profile(cl, name):
    return cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]


def login():
    with db() as c:
        if not users.by_email(c, "m3@x.de"):
            users.create(c, "m3@x.de", "passwort123", is_admin=True)
    cl = TestClient(main.app)
    cl.post("/api/auth/login", json={"email": "m3@x.de", "password": "passwort123"}, headers=H)
    return cl


def test_apply_fritz_and_snmp(monkeypatch):
    cl = login()
    pid = _profile(cl, "Fritz-Test")
    P = f"/api/profiles/{pid}"
    # David-PC hat eine von Hand gesetzte Verbindung, die nicht überschrieben werden darf
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, created) VALUES(?, 'fritzbox', 'FB', '192.168.178.1', ?)", (pid, now())).lastrowid
    res = dict(info=dict(model="FRITZ!Box 6591 Cable"), wan=dict(rx_bps=8000, tx_bps=800), auth=True, wlan=[], hosts=[
        dict(ip="192.168.178.2", mac="70:49:A2:55:28:34", name="XGS1935", interface="Ethernet", active=True),
        dict(ip="192.168.178.3", mac="E8:9C:25:24:B6:60", name="Asus-Router-oben", interface="Ethernet", active=True),
        dict(ip="192.168.178.131", mac="D8:BB:C1:3F:6A:03", name="David-PC", interface="Ethernet", active=True),
        dict(ip="192.168.178.60", mac="DA:00:00:00:00:01", name="Handy", interface="802.11", active=True),
        dict(ip="192.168.178.99", mac="AA:BB:CC:00:00:99", name="alt", interface="Ethernet", active=False)],
        mesh={"70:49:A2:55:28:34": dict(node="1C:ED:6F:07:5B:7A", iface="LAN 3", medium="lan", master=True),
              "E8:9C:25:24:B6:60": dict(node="1C:ED:6F:07:5B:7A", iface="LAN 3", medium="lan", master=True),
              "D8:BB:C1:3F:6A:03": dict(node="1C:ED:6F:07:5B:7A", iface="LAN 3", medium="lan", master=True),
              "DA:00:00:00:00:01": dict(node="1C:ED:6F:07:5B:7A", iface="WLAN 5 GHz", medium="wlan", master=True)})
    monkeypatch.setattr(fritzbox, "poll", lambda conf, state: (res, {"wan:rx": 8000, "wan:tx": 800}, state))
    summary = integrations.poll(iid)
    assert summary["new"] == 4 and summary["links"] == 2  # Switch an LAN 3, Handy per WLAN; die anderen hängen hinter dem Switch
    devs = {d["name"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    fb = devs["FRITZ!Box 6591 Cable"]
    assert fb["model"] == "FRITZ!Box 6591 Cable" and fb["mac"] == "1C:ED:6F:07:5B:7A" and fb["online"] == 1
    assert devs["XGS1935"]["uplink"]["port_name"] == "LAN 3" and devs["XGS1935"]["type"] == "switch"
    assert devs["Handy"]["uplink"]["medium"] == "wlan" and devs["Asus-Router-oben"]["uplink"] is None
    assert "alt" not in devs
    wan = cl.get(f"{P}/metrics?keys=i{iid}:wan:rx,i{iid}:wan:tx&since=3600").json()
    assert wan["series"][f"i{iid}:wan:rx"][0][1] == 8000

    # SNMP-Switch: gelernte MACs -> Verbindungen an Switch-Ports
    sw = devs["XGS1935"]
    cl.put(f"{P}/devices/{sw['id']}", json={"name": "XGS1935", "type": "switch", "status": "confirmed",
                                             "ports": [{"count": 4, "kind": "rj45", "speed": "1G"}]}, headers=H)
    pc = devs["David-PC"]
    cl.put(f"{P}/devices/{pc['id']}", json={"name": "David-PC", "uplink": {"device_id": devs["Handy"]["id"], "medium": "lan"}}, headers=H)  # manuell
    cl.post(f"{P}/devices", json={"name": "EBM68 Keller", "type": "mesh", "mac": "F0:2F:74:00:00:03"}, headers=H)
    cl.post(f"{P}/devices", json={"name": "AP Keller", "type": "ap", "mac": "AA:00:00:00:00:01"}, headers=H)
    agent = Agent(switch_tree(500))
    agent.start()
    with db() as c:
        c.execute("UPDATE devices SET type='router' WHERE id=?", (fb["id"],))
        sid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, port, secret, device_id, created) VALUES(?, 'snmp', 'SW', '127.0.0.1', ?, ?, ?, ?)",
                        (pid, agent.port, integrations.security.encrypt("geheim"), sw["id"], now())).lastrowid
    summary = integrations.poll(sid)
    assert summary["ports"] == 4 and summary["up"] == 3
    devs = {d["name"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    assert devs["EBM68 Keller"]["uplink"]["port_name"] == "1" and devs["AP Keller"]["uplink"]["port_name"] == "4"
    assert devs["David-PC"]["uplink"]["device_name"] == "Handy"  # manuelle Verbindung bleibt
    det = cl.get(f"{P}/devices/{sw['id']}").json()
    assert det["ports"][0]["live"]["oper"] == "up" and det["ports"][2]["live"]["oper"] == "down" and det["ports"][3]["live"]["lldp"]["name"] == "AP-Keller"
    # Port 2: FRITZ!Box (Router) mit weiteren Adressen -> Uplink des Switches, bestehende Verbindung an LAN 3 bleibt
    assert devs["XGS1935"]["uplink"]["device_name"] == "FRITZ!Box 6591 Cable"


def test_integration_api_and_monitor():
    cl = login()
    pid = _profile(cl, "API-Test")
    P = f"/api/profiles/{pid}"
    r = cl.get(f"{P}/integrations").json()
    assert {d["key"] for d in r["drivers"]} == {"fritzbox", "snmp", "asuswrt", "proxmox", "homeassistant", "omada", "unifi"} and r["monitor"] == {"enabled": True, "interval_s": 60}
    i = cl.post(f"{P}/integrations", json={"driver": "snmp", "host": "127.0.0.1", "port": 1, "password": "abc", "interval_s": 5}, headers=H).json()
    assert i["password"] == "••••••" and i["interval_s"] == 15
    i2 = cl.put(f"{P}/integrations/{i['id']}", json={"host": "127.0.0.2", "password": "••••••"}, headers=H).json()
    assert i2["host"] == "127.0.0.2" and i2["password"] == "••••••"
    with db() as c:
        assert integrations.secrets_of(c.execute("SELECT * FROM integrations WHERE id=?", (i["id"],)).fetchone())["password"] == "abc"
    r = cl.post(f"{P}/integrations/test", json={"driver": "snmp", "host": "127.0.0.1", "port": 9, "password": "x"}, headers=H)
    assert r.status_code == 400 and "Keine Antwort" in r.json()["error"]
    assert cl.put(f"{P}/monitor", json={"interval_s": 30, "enabled": True}, headers=H).json() == {"enabled": True, "interval_s": 30}
    assert cl.put(f"{P}/monitor", json={"interval_s": 7}, headers=H).json()["interval_s"] == 30
    # Ping-Überwachung: localhost ist online, eine nicht vergebene Adresse offline
    a = cl.post(f"{P}/devices", json={"name": "lokal", "ips": [{"address": "127.0.0.1"}]}, headers=H).json()
    b = cl.post(f"{P}/devices", json={"name": "weg", "ips": [{"address": "192.0.2.123"}]}, headers=H).json()
    res = monitor.run(pid)
    assert res["checked"] == 2 and res["online"] == 1
    devs = {d["name"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    assert devs["lokal"]["online"] == 1 and devs["weg"]["online"] == 0 and a["id"] and b["id"]
    assert cl.delete(f"{P}/integrations/{i['id']}", headers=H).json()["ok"]
