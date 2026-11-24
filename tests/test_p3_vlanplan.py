"""VLAN-Plan: produktiv von Hand und vom Switch (SNMP, Q-BRIDGE-MIB), Plan anlegen/ändern, Umstellungsliste, Prüfungen,
übernehmen, abschließen, verwerfen, PDF."""
import io

from pypdf import PdfReader

from app import actions, integrations, vlanplan
from app.db import db
from app.drivers import snmp
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


class FakeQ:
    """Switch mit 8 Ports: VLAN 1 untagged auf 1–8, VLAN 20 „IoT“ tagged auf Port 1; Bridge-Port n = ifIndex 100+n."""
    def __init__(self, vlan20_untagged_on_5=False):
        self.u5 = vlan20_untagged_on_5

    def walk(self, base):
        bm = lambda ports: bytes(sum(0x80 >> (p - 1) for p in ports if p <= 8) for _ in range(1))  # noqa: E731
        if base == snmp.QV_EGRESS:
            return {f"{base}.1": bm([1, 2, 3, 4, 6, 7, 8] + ([] if self.u5 else [5])), f"{base}.20": bm([1] + ([5] if self.u5 else []))}
        if base == snmp.QV_UNTAG:
            return {f"{base}.1": bm([1, 2, 3, 4, 6, 7, 8] + ([] if self.u5 else [5])), f"{base}.20": bm([5] if self.u5 else [])}
        if base == snmp.QV_NAME:
            return {f"{base}.1": b"default", f"{base}.20": b"IoT"}
        if base == snmp.QV_PVID:
            return {f"{base}.{n}": (20 if self.u5 and n == 5 else 1) for n in range(1, 9)}
        return {}


def test_read_vlans_bitmaps():
    ports = [dict(port_no=n, ifindex=100 + n) for n in range(1, 9)]
    r = snmp.read_vlans(FakeQ(), ports, lambda b: 100 + b)
    assert [(v["vid"], v["name"]) for v in r["vlans"]] == [(1, "default"), (20, "IoT")]
    assert r["ports"][1] == dict(untagged=1, tagged=[20]) and r["ports"][5] == dict(untagged=1, tagged=[])
    r = snmp.read_vlans(FakeQ(True), ports, lambda b: 100 + b)
    assert r["ports"][5] == dict(untagged=20, tagged=[])


def test_vlan_plan(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "VLAN-Plan")  # Switch 8 Ports: Port 1 Router, Port 5 Fernseher (192.168.178.50, statisch)
    st = cl.get(f"{P}/vlanplan").json()
    assert st["plan"] is None and "Switch" in [s["name"] for s in st["switches"]]
    sw = next(s for s in st["switches"] if s["name"] == "Switch")
    port = {p["no"]: p for p in sw["ports"]}
    assert port[5]["peers"][0]["name"] == "Fernseher"
    # produktiv von Hand: VLAN 1 überall untagged
    v1 = cl.post(f"{P}/vlans", json={"vid": 1, "name": "Standard"}, headers=H).json()["vlans"][0]["id"]
    st = cl.put(f"{P}/vlanplan/ports", json={"mode": "prod", "ports": [p["id"] for p in sw["ports"]], "untagged": v1}, headers=H).json()
    assert all(p["prod"]["u"] == v1 for p in next(s for s in st["switches"] if s["name"] == "Switch")["ports"])
    # ohne Plan kein Plan-Modus; geplantes VLAN nur mit Plan
    assert cl.put(f"{P}/vlanplan/ports", json={"mode": "plan", "ports": [port[5]["id"]], "untagged": v1}, headers=H).status_code == 400
    st = cl.post(f"{P}/vlanplan/plan", json={"note": "IoT trennen"}, headers=H).json()
    assert st["plan"]["note"] == "IoT trennen" and st["diff"] == []
    vl = cl.post(f"{P}/vlans", json={"vid": 20, "name": "IoT", "planned": True}, headers=H).json()["vlans"]
    v20 = next(v for v in vl if v["vid"] == 20)
    assert v20["planned"] and v20["color"].startswith("#")
    # produktiv darf kein geplantes VLAN bekommen
    assert cl.put(f"{P}/vlanplan/ports", json={"mode": "prod", "ports": [port[5]["id"]], "untagged": v20["id"]}, headers=H).status_code == 400
    # Plan: Fernseher-Port 5 in VLAN 20, Uplink (Port 1) bekommt 20 noch nicht
    with db() as c:
        c.execute("INSERT INTO subnets(profile_id, vlan_id, cidr) VALUES(?,?,?)", (pid, v20["id"], "10.0.20.0/24"))
    st = cl.put(f"{P}/vlanplan/ports", json={"mode": "plan", "ports": [port[5]["id"]], "untagged": v20["id"]}, headers=H).json()
    assert [(x["port"], x["prod"]["u"], x["plan"]["u"]) for x in st["diff"]] == [("5", v1, v20["id"])]
    codes = {w["code"] for w in st["warnings"]["plan"]}
    assert "ip_static" in codes  # 192.168.178.50 passt nicht zu 10.0.20.0/24
    # tagged hinzufügen auf Port 1 (Uplink) im Plan, mehrere Ports auf einmal
    st = cl.put(f"{P}/vlanplan/ports", json={"mode": "plan", "ports": [port[1]["id"], port[2]["id"]], "untagged": "keep", "tagged": {str(v20["id"]): True}},
                headers=H).json()
    p1 = next(p for p in next(s for s in st["switches"] if s["name"] == "Switch")["ports"] if p["no"] == 1)
    assert p1["plan"] == dict(u=v1, t=[v20["id"]]) and len(st["diff"]) == 3
    st = cl.put(f"{P}/vlanplan/ports", json={"mode": "plan", "ports": [port[2]["id"]], "tagged": {str(v20["id"]): False}}, headers=H).json()
    assert len(st["diff"]) == 2
    # Port übernehmen (von Hand gepflegter Switch): Port 5 produktiv, VLAN 20 nicht mehr „geplant“
    st = cl.post(f"{P}/vlanplan/plan/adopt/{port[5]['id']}", headers=H).json()
    assert len(st["diff"]) == 1 and not next(v for v in st["vlans"] if v["vid"] == 20)["planned"]
    # PDF
    txt = "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(cl.get(f"{P}/export/report.pdf?sections=vlans").content)).pages)
    assert "Geplante Umstellung" in txt and "VLANs je Port (produktiv) · Switch" in txt
    # abschließen: Rest wird produktiv, Plan weg
    st = cl.post(f"{P}/vlanplan/plan/finish", headers=H).json()
    assert st["plan"] is None and st["result"] == 0
    p1 = next(p for p in next(s for s in st["switches"] if s["name"] == "Switch")["ports"] if p["no"] == 1)
    assert p1["prod"] == dict(u=v1, t=[v20["id"]])
    # Plan verwerfen entfernt nur geplante VLANs
    cl.post(f"{P}/vlanplan/plan", json={}, headers=H)
    cl.post(f"{P}/vlans", json={"vid": 30, "name": "Gäste", "planned": True}, headers=H)
    st = cl.delete(f"{P}/vlanplan/plan", headers=H).json()
    assert st["plan"] is None and sorted(v["vid"] for v in st["vlans"]) == [1, 20]
    # Lesende
    with db() as c:
        from app import users
        if not users.by_email(c, "leser@x.de"):
            users.create(c, "leser@x.de", "passwort123")
        c.execute("INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?,'view')", (pid, users.by_email(c, "leser@x.de")["id"]))
    rd = login("leser@x.de")
    assert rd.get(f"{P}/vlanplan").status_code == 200
    assert rd.post(f"{P}/vlanplan/plan", json={}, headers=H).status_code == 403


def test_snmp_switch_is_authoritative(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "VLAN-SNMP")
    with db() as c:
        vlanplan.apply_switch(c, pid, d["sw"], dict(vlans=[dict(vid=1, name="default"), dict(vid=20, name="IoT")],
                                                   ports={n: dict(untagged=1, tagged=[20] if n == 1 else []) for n in range(1, 9)}))
    st = cl.get(f"{P}/vlanplan").json()
    sw = next(s for s in st["switches"] if s["name"] == "Switch")
    assert sw["snmp"] and {v["vid"]: v["name"] for v in st["vlans"]} == {1: "default", 20: "IoT"}
    port = {p["no"]: p for p in sw["ports"]}
    v20 = next(v["id"] for v in st["vlans"] if v["vid"] == 20)
    # produktiv nicht von Hand änderbar
    assert cl.put(f"{P}/vlanplan/ports", json={"mode": "prod", "ports": [port[5]["id"]], "untagged": v20}, headers=H).status_code == 400
    cl.post(f"{P}/vlanplan/plan", json={}, headers=H)
    st = cl.put(f"{P}/vlanplan/ports", json={"mode": "plan", "ports": [port[5]["id"]], "untagged": v20}, headers=H).json()
    assert len(st["diff"]) == 1
    assert cl.post(f"{P}/vlanplan/plan/adopt/{port[5]['id']}", headers=H).status_code == 400
    # Umstellung am Switch gemacht -> nächste Abfrage meldet es, die Umstellungsliste ist leer
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (d["siid"],)).fetchone()
        res = dict(info=dict(name="Switch"), ports=[dict(port_no=n, ifindex=100 + n, name=f"Port{n}", oper="up", macs=[], lldp=None) for n in range(1, 9)],
                   vlans=dict(vlans=[dict(vid=1, name="default"), dict(vid=20, name="IoT")],
                              ports={n: dict(untagged=20 if n == 5 else 1, tagged=[20] if n == 1 else []) for n in range(1, 9)}))
        assert integrations.apply_snmp(c, row, res)["vlan_ports"] == 8
    assert cl.get(f"{P}/vlanplan").json()["diff"] == []


def test_trunk_check():
    """Uplink zwischen zwei Switches führt ein VLAN nicht, das auf dem anderen Switch genutzt wird."""
    st = dict(vlans=[dict(id=1, vid=1, name="", subnets=[]), dict(id=2, vid=20, name="IoT", subnets=["10.0.20.0/24"])], switches=[
        dict(id=10, name="Core", ports=[dict(id=101, name="1", peers=[dict(id=11, name="Büro", type="switch")], prod=dict(u=1, t=[]), plan=dict(u=1, t=[]))]),
        dict(id=11, name="Büro", ports=[dict(id=111, name="8", peers=[dict(id=10, name="Core", type="switch")], prod=dict(u=1, t=[]), plan=dict(u=1, t=[])),
                                        dict(id=112, name="3", peers=[], prod=dict(u=1, t=[]), plan=dict(u=2, t=[]))])])

    class C:
        def execute(self, *a):
            return []
    w = vlanplan.checks(C(), 1, st, "plan")
    trunk = [x for x in w if x["code"] == "trunk"]
    assert len(trunk) == 1 and "Core · Port 1 → Büro" in trunk[0]["text"] and "VLAN 20 (IoT)" in trunk[0]["text"]
    st["switches"][0]["ports"][0]["plan"] = dict(u=1, t=[2])
    assert not [x for x in vlanplan.checks(C(), 1, st, "plan") if x["code"] == "trunk"]
    assert not [x for x in vlanplan.checks(C(), 1, st, "prod") if x["code"] == "trunk"]


def test_end_devices_and_subnet_assignment():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "VLAN-Endgeräte"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    cl.post(f"{P}/devices", json={"status": "confirmed", "name": "Switch", "type": "switch", "ports": [{"count": 4, "kind": "rj45", "speed": "1G"}]}, headers=H)
    cl.post(f"{P}/devices", json={"status": "confirmed", "name": "Fedora", "type": "computer", "ports": [{"count": 1, "kind": "rj45", "speed": "1G", "label": "LAN"}]}, headers=H)
    st = cl.get(f"{P}/vlanplan").json()
    assert {s["name"]: s["infra"] for s in st["switches"]} == {"Switch": True, "Fedora": False}
    # Subnetz aus IPAM im VLAN-Dialog zuordnen und wieder lösen
    sid = cl.post(f"{P}/subnets", json={"cidr": "192.0.2.0/24", "name": "LAN"}, headers=H).json()
    sid = sid.get("id") or cl.get(f"{P}/subnets").json()["subnets"][0]["id"]
    v1 = cl.post(f"{P}/vlans", json={"vid": 1, "name": "Standard", "subnets": [sid]}, headers=H).json()["vlans"][0]
    assert v1["subnets"] == ["192.0.2.0/24"]
    assert cl.put(f"{P}/vlans/{v1['id']}", json={"vid": 1, "name": "Standard", "subnets": []}, headers=H).json()["vlans"][0]["subnets"] == []
    assert cl.put(f"{P}/vlans/{v1['id']}", json={"vid": 1, "name": "Standard", "subnets": [sid]}, headers=H).json()["vlans"][0]["subnets"] == ["192.0.2.0/24"]
    # ohne „subnets“ im Aufruf bleibt die Zuordnung
    assert cl.put(f"{P}/vlans/{v1['id']}", json={"vid": 1, "name": "Default"}, headers=H).json()["vlans"][0]["subnets"] == ["192.0.2.0/24"]


def test_proxmox_guest_vlans():
    """VLAN-Tag der VMs/Container (aus Proxmox) beim Host; Switch-Port zum Host muss diese VLANs tagged führen."""
    import json as _json
    from app import integrations
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "VLAN-Gäste"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    mk = lambda **kw: cl.post(f"{P}/devices", json={"status": "confirmed", **kw}, headers=H).json()["id"]  # noqa: E731
    sw = mk(name="Switch", type="switch", ports=[{"count": 8, "kind": "rj45", "speed": "1G"}])
    pve = mk(name="pve1", type="hypervisor", ports=[{"count": 1, "kind": "rj45", "speed": "1G", "label": "LAN"}])
    vm_iot = mk(name="homeassistant", type="server")
    vm_lan = mk(name="pihole", type="server")
    with db() as c:
        port3 = c.execute("SELECT id FROM interfaces WHERE device_id=? AND port_no=3", (sw,)).fetchone()["id"]
        integrations.set_auto_uplink(c, pid, pve, sw, "lan", port_id=port3)
        for vm, tag in ((vm_iot, "20"), (vm_lan, "")):
            integrations.set_auto_uplink(c, pid, vm, pve, "virtual")
            c.execute("UPDATE devices SET data=? WHERE id=?", (_json.dumps(dict(proxmox=dict(vmid=100 + vm, node="pve1", kind="qemu", bridge="vmbr0", tag=tag))), vm))
    v1 = cl.post(f"{P}/vlans", json={"vid": 1, "name": "LAN"}, headers=H).json()["vlans"][0]["id"]
    cl.put(f"{P}/vlanplan/ports", json={"mode": "prod", "ports": [port3], "untagged": v1}, headers=H)
    st = cl.get(f"{P}/vlanplan").json()
    host = next(s for s in st["switches"] if s["name"] == "pve1")
    assert {(g["name"], g["vid"]) for g in host["guests"]} == {("homeassistant", 20), ("pihole", None)}
    codes = {w["code"] for w in st["warnings"]["prod"]}
    assert "guest_unknown_vlan" in codes  # VLAN 20 noch nicht angelegt
    v20 = cl.post(f"{P}/vlans", json={"vid": 20, "name": "IoT"}, headers=H).json()["vlans"]
    v20 = next(v["id"] for v in v20 if v["vid"] == 20)
    w = [x for x in cl.get(f"{P}/vlanplan").json()["warnings"]["prod"] if x["code"] == "guest_vlan"]
    assert len(w) == 1 and "Port 3 → pve1" in w[0]["text"] and "homeassistant" in w[0]["text"]
    cl.put(f"{P}/vlanplan/ports", json={"mode": "prod", "ports": [port3], "tagged": {str(v20): True}}, headers=H)
    assert not [x for x in cl.get(f"{P}/vlanplan").json()["warnings"]["prod"] if x["code"] == "guest_vlan"]
