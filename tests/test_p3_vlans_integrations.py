"""VLANs aus MikroTik (Bridge-VLAN-Tabelle, PVID, VLAN-Schnittstellen), OPNsense (VLAN-Geräte), UniFi (Netze, Port-Profile,
Überschreibungen) und Omada (Netze je Switch) – Übernahme in den VLAN-Plan mit Quelle, SNMP hat Vorrang."""
import json

from app import integrations, vlanplan
from app.db import db, now
from app.drivers import controller, mikrotik, omada, opnsense, unifi
from tests.test_m6 import H, login


def test_vid_list_and_result():
    assert controller.vid_list("10,20-22") == [10, 20, 21, 22] and controller.vid_list(["5", 7, "x", 0, 5000]) == [5, 7]
    assert controller.vid_list("") == [] and controller.vid_list("3-1") == []
    r = controller.vlan_result({10: "IoT", 30: "frei"}, {1: dict(untagged=1, tagged={10, 1}), 2: dict(untagged=None, tagged=set())})
    assert r == dict(vlans=[dict(vid=1, name=""), dict(vid=10, name="IoT"), dict(vid=30, name="frei")], ports={1: dict(untagged=1, tagged=[10])})
    assert controller.vlan_result({}, {1: dict(untagged=None, tagged=set())}) is None


def _mt_ports(n=5):
    return [dict(iface=f"ether{i}", port_no=i) for i in range(1, n + 1)]


def test_mikrotik_bridge_vlans():
    raw = dict(
        bridges=[{"name": "bridge", "vlan-filtering": "true"}, {"name": "br-alt", "vlan-filtering": "false"}],
        bridge_vlans=[{"bridge": "bridge", "vlan-ids": "10", "tagged": "bridge,ether1", "untagged": "ether2", "current-untagged": "ether2"},
                      {"bridge": "bridge", "vlan-ids": "20,30", "tagged": "bridge,ether1,ether3"},
                      {"bridge": "br-alt", "vlan-ids": "99", "tagged": "ether4"},  # Bridge ohne vlan-filtering: zählt nicht
                      {"bridge": "bridge", "vlan-ids": "1", "current-untagged": "ether1,ether3,bridge", "dynamic": "true"}],
        bridge_ports=[{"bridge": "bridge", "interface": "ether1", "pvid": "1"}, {"bridge": "bridge", "interface": "ether2", "pvid": "10"},
                      {"bridge": "bridge", "interface": "ether3", "pvid": "1"},
                      {"bridge": "bridge", "interface": "ether4", "pvid": "40", "frame-types": "admit-only-vlan-tagged"}],
        vlan_ifaces=[{"name": "vlan10-iot", "vlan-id": "10", "interface": "bridge"}, {"name": "gast", "vlan-id": "50", "interface": "ether5"}])
    r = mikrotik.vlans(raw, _mt_ports())
    assert r["ports"][1] == dict(untagged=1, tagged=[10, 20, 30]) and r["ports"][2] == dict(untagged=10, tagged=[])
    assert r["ports"][3] == dict(untagged=1, tagged=[20, 30]) and 4 not in r["ports"] and r["ports"][5] == dict(untagged=None, tagged=[50])
    names = {v["vid"]: v["name"] for v in r["vlans"]}
    assert names[10] == "vlan10-iot" and names[50] == "gast" and 99 not in names
    assert mikrotik.vlans(dict(bridges=[], bridge_vlans=[], bridge_ports=[], vlan_ifaces=[]), _mt_ports()) is None


def test_opnsense_vlan_devices():
    ports = [dict(port_no=1, device="igb0"), dict(port_no=2, device="igb1", name="LAN (igb1)"), dict(port_no=3, device="vlan0.10", name="IOT (vlan0.10)"),
             dict(port_no=4, device="")]
    rows = [{"vlanif": "vlan0.10", "if": "igb1", "tag": "10", "descr": ""}, {"vlanif": "vlan0.20", "if": "igb1", "tag": "20", "descr": "Kameras"},
            {"vlanif": "vlan0.30", "if": "igb9", "tag": "30"}]
    r = opnsense.vlans(rows, ports)
    assert r["ports"] == {2: dict(untagged=None, tagged=[10, 20]), 3: dict(untagged=10, tagged=[])}
    assert {v["vid"]: v["name"] for v in r["vlans"]} == {10: "IOT", 20: "Kameras", 30: ""}


def test_omada_networks_detail():
    nets = [{"name": "Default", "vlan": 1, "portLagNetworkInfo": {"nativePorts": [1, 2, 3], "untagPorts": [1, 2, 3]}},
            {"name": "IoT", "vlan": 20, "portLagNetworkInfo": {"tagPorts": [1], "untagPorts": [4], "nativePorts": [4]}},
            {"name": "kaputt", "vlan": None}]
    r = omada.vlans(nets)
    assert r["ports"] == {1: dict(untagged=1, tagged=[20]), 2: dict(untagged=1, tagged=[]), 3: dict(untagged=1, tagged=[]), 4: dict(untagged=20, tagged=[])}
    # über normalize am Gerät
    devs, _ = omada.normalize([({"siteId": "s1"}, [{"mac": "AA-BB-CC-00-00-01", "type": "switch", "name": "SW"}], [], {},
                                {"AA-BB-CC-00-00-01": nets})])
    assert devs[0]["vlans"]["ports"][4]["untagged"] == 20


def test_unifi_port_vlans():
    nets = [{"_id": "lan", "name": "Default", "purpose": "corporate", "attr_no_delete": True},
            {"_id": "iot", "name": "IoT", "purpose": "corporate", "vlan_enabled": True, "vlan": "20"},
            {"_id": "cam", "name": "Kameras", "purpose": "vlan-only", "vlan": 30},
            {"_id": "wan", "name": "Internet", "purpose": "wan"},
            {"_id": "alt", "name": "ohne VLAN", "purpose": "corporate"}]
    profiles = [{"_id": "pc-trunk", "name": "Trunk IoT", "native_networkconf_id": "lan", "forward": "customize", "tagged_networkconf_ids": ["iot"]}]
    devs = [{"type": "usw", "mac": "f0:9f:c2:00:00:01", "port_table": [{"port_idx": i} for i in range(1, 6)] + [{"port_idx": 6, "portconf_id": "pc-trunk"}],
             "port_overrides": [{"port_idx": 2, "native_networkconf_id": "iot", "tagged_vlan_mgmt": "block_all"},
                                {"port_idx": 3, "tagged_vlan_mgmt": "custom", "excluded_networkconf_ids": ["cam"]},
                                {"port_idx": 4, "native_networkconf_id": "cam", "tagged_vlan_mgmt": "custom", "tagged_networkconf_ids": []},
                                {"port_idx": 5, "forward": "disabled"}]},
            {"type": "uap", "mac": "f0:9f:c2:00:00:02"}]
    r = unifi.port_vlans(nets, profiles, devs)
    p = r["F0:9F:C2:00:00:01"]["ports"]
    assert p[1] == dict(untagged=1, tagged=[20, 30])        # ohne Einstellung: Standardnetz untagged, alle anderen tagged
    assert p[2] == dict(untagged=20, tagged=[])             # Zugangsport IoT
    assert p[3] == dict(untagged=1, tagged=[20])            # alle außer Kameras
    assert p[4] == dict(untagged=30, tagged=[])
    assert 5 not in p and p[6] == dict(untagged=1, tagged=[20])  # deaktiviert; Port-Profil
    assert {v["vid"]: v["name"] for v in r["F0:9F:C2:00:00:01"]["vlans"]} == {1: "Default", 20: "IoT", 30: "Kameras"}
    assert "F0:9F:C2:00:00:02" not in r and unifi.port_vlans([], [], devs) == {}


def test_apply_with_source_and_snmp_precedence(monkeypatch):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "VLAN-Quellen"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    # MikroTik-Router: Ports und VLANs aus der Integration
    ports = [dict(port_no=i, iface=f"ether{i}", id=f"*{i}", name=f"ether{i}", alias="", kind="rj45", oper="up", admin="up", speed=1000,
                  poe=None, in_bps=None, out_bps=None, macs=[], lldp=None, mac="") for i in range(1, 4)]
    res = dict(info=dict(name="hEX", model="RB750Gr3", version="7.16"), ports=ports, wifi=[], clients=[], wan=None, fdb_size=0,
               vlans=dict(vlans=[dict(vid=1, name=""), dict(vid=10, name="IoT")], ports={1: dict(untagged=1, tagged=[10]), 2: dict(untagged=10, tagged=[])}))
    monkeypatch.setattr(mikrotik, "poll", lambda conf, state: (res, {}, state))
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, created) VALUES(?, 'mikrotik', 'MT', '192.0.2.1', ?)", (pid, now())).lastrowid
    s = integrations.poll(iid)
    assert s["vlan_ports"] == 2
    cl.put(f"{P}/devices/{s['device_id']}", json={"name": "hEX", "status": "confirmed"}, headers=H)
    with db() as c:
        view = vlanplan.state(c, pid)
        rows = c.execute("""SELECT i.port_no, v.vid, pv.tagged, pv.source FROM port_vlans pv JOIN interfaces i ON i.id=pv.interface_id
                            JOIN vlans v ON v.id=pv.vlan_id WHERE i.device_id=? ORDER BY 1, 2""", (s["device_id"],)).fetchall()
        desc = c.execute("SELECT description FROM vlans WHERE profile_id=? AND vid=10", (pid,)).fetchone()["description"]
    assert [tuple(r) for r in rows] == [(1, 1, 0, "mikrotik"), (1, 10, 1, "mikrotik"), (2, 10, 0, "mikrotik")]
    sw = next(x for x in view["switches"] if x["id"] == s["device_id"])
    assert sw["snmp"] is True and sw["source"] == "MikroTik" and desc == "aus MikroTik gelesen"
    # Produktiver Stand eines Geräts mit Integration ist nicht von Hand änderbar
    with db() as c:
        iface = c.execute("SELECT id FROM interfaces WHERE device_id=? AND port_no=3", (s["device_id"],)).fetchone()["id"]
        try:
            vlanplan.set_ports(c, pid, "prod", [iface], untagged=None)
            raise AssertionError
        except vlanplan.VlanError as ex:
            assert "Integration" in str(ex)
    # SNMP hat Vorrang: ein Controller überschreibt den Stand vom Switch nicht
    with db() as c:
        sw_id = c.execute("SELECT id FROM devices WHERE id=?", (s["device_id"],)).fetchone()["id"]
        c.execute("UPDATE port_vlans SET source='snmp' WHERE interface_id IN (SELECT id FROM interfaces WHERE device_id=?)", (sw_id,))
        n = vlanplan.apply_switch(c, pid, sw_id, dict(vlans=[], ports={1: dict(untagged=99, tagged=[])}), "unifi")
        assert n == 0 and not c.execute("SELECT 1 FROM vlans WHERE profile_id=? AND vid=99", (pid,)).fetchone()
        # vorhandenes VLAN ohne Namen bekommt den Namen aus dem Gerät
        c.execute("UPDATE vlans SET name='' WHERE profile_id=? AND vid=10", (pid,))
        c.execute("UPDATE port_vlans SET source='mikrotik' WHERE interface_id IN (SELECT id FROM interfaces WHERE device_id=?)", (sw_id,))
        vlanplan.apply_switch(c, pid, sw_id, res["vlans"], "mikrotik")
        assert c.execute("SELECT name FROM vlans WHERE profile_id=? AND vid=10", (pid,)).fetchone()["name"] == "IoT"


def test_controller_devices_vlans(monkeypatch):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "UniFi-VLAN"}, headers=H).json()["profile"]["id"]
    vl = dict(vlans=[dict(vid=1, name="Default"), dict(vid=20, name="IoT")], ports={1: dict(untagged=1, tagged=[20]), 2: dict(untagged=20, tagged=[])})
    dev = dict(mac="F0:9F:C2:00:00:01", ip="192.0.2.10", name="USW Lite 8", model="USL8LP", type="switch", online=True, uplink_mac="", uplink_port=None,
               clients=0, firmware="7.1", ports=[dict(port_no=i, oper="up", speed="1G", kind="rj45", in_bps=None, out_bps=None, macs=[], lldp=[], poe=None)
                                                   for i in range(1, 9)], ref={}, firmware_info=None, vlans=vl)
    monkeypatch.setattr(unifi, "poll", lambda conf, state: (dict(info=dict(controller="UniFi"), devices=[dev], clients=[]), {}, state))
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, created) VALUES(?, 'unifi', 'UniFi', '192.0.2.1', ?)", (pid, now())).lastrowid
    s = integrations.poll(iid)
    assert s["vlan_ports"] == 2
    with db() as c:
        src = vlanplan.snmp_devices(c, pid)
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()["state"])
    assert list(src.values()) == ["unifi"] and "vlans" not in json.dumps(st["result"]["devices"])
