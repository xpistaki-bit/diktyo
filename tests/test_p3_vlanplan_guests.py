"""VLAN-Plan: geplante VLAN-Wechsel von VMs/Containern (Proxmox) – setzen, Umstellungsliste, Prüfung des Host-Ports im Plan,
von selbst erledigt, sobald Proxmox das neue Tag meldet, Abschließen, Verwerfen, Rechte, PDF."""
import io
import json

from pypdf import PdfReader

from app import integrations
from app.db import db
from tests.test_m6 import H, login


def _setup(cl, name):
    pid = cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    mk = lambda **kw: cl.post(f"{P}/devices", json={"status": "confirmed", **kw}, headers=H).json()["id"]  # noqa: E731
    sw = mk(name="Switch", type="switch", ports=[{"count": 8, "kind": "rj45", "speed": "1G"}])
    pve = mk(name="pve1", type="hypervisor", ports=[{"count": 1, "kind": "rj45", "speed": "1G", "label": "LAN"}])
    ha, ph = mk(name="homeassistant", type="server"), mk(name="pihole", type="server")
    with db() as c:
        port3 = c.execute("SELECT id FROM interfaces WHERE device_id=? AND port_no=3", (sw,)).fetchone()["id"]
        integrations.set_auto_uplink(c, pid, pve, sw, "lan", port_id=port3)
        for vm, tag in ((ha, ""), (ph, "")):
            integrations.set_auto_uplink(c, pid, vm, pve, "virtual")
            c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(dict(proxmox=dict(vmid=100 + vm, node="pve1", kind="qemu" if vm == ha else "lxc",
                                                                                         bridge="vmbr0", tag=tag))), vm))
    v1 = cl.post(f"{P}/vlans", json={"vid": 1, "name": "LAN"}, headers=H).json()["vlans"][0]["id"]
    cl.put(f"{P}/vlanplan/ports", json={"mode": "prod", "ports": [port3], "untagged": v1}, headers=H)
    return pid, P, sw, pve, ha, ph, port3


def _set_tag(vm, tag):
    with db() as c:
        d = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (vm,)).fetchone()["data"])
        d["proxmox"]["tag"] = tag
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(d), vm))


def test_guest_plan_flow():
    cl = login()
    pid, P, sw, pve, ha, ph, port3 = _setup(cl, "VLAN-Gäste-Plan")
    # ohne Plan nicht möglich
    assert cl.put(f"{P}/vlanplan/plan/guests", json={"guests": [ha], "vid": 20}, headers=H).status_code == 400
    cl.post(f"{P}/vlanplan/plan", json={"note": "IoT trennen"}, headers=H)
    # VLAN muss es geben (auch geplant)
    r = cl.put(f"{P}/vlanplan/plan/guests", json={"guests": [ha], "vid": 20}, headers=H)
    assert r.status_code == 400 and "zuerst anlegen" in r.json()["error"]
    cl.post(f"{P}/vlans", json={"vid": 20, "name": "IoT", "planned": True}, headers=H)
    # kein Gast / fremdes Gerät
    assert cl.put(f"{P}/vlanplan/plan/guests", json={"guests": [sw], "vid": 20}, headers=H).status_code == 400
    st = cl.put(f"{P}/vlanplan/plan/guests", json={"guests": [ha], "vid": 20}, headers=H).json()
    assert st["result"] == 1
    host = next(s for s in st["switches"] if s["name"] == "pve1")
    g = {x["name"]: x for x in host["guests"]}
    assert (g["homeassistant"]["vid"], g["homeassistant"]["plan_vid"], g["homeassistant"]["changed"]) == (None, 20, True)
    assert g["pihole"]["changed"] is False and g["homeassistant"]["plan_vlan_id"]
    assert st["guest_diff"] == [dict(device_id=ha, name="homeassistant", kind="qemu", vmid=100 + ha, host_id=pve, host="pve1", prod_vid=None, plan_vid=20)]
    # Prüfung im Plan: Port 3 zum Host führt VLAN 20 nicht; im Ist-Stand keine Warnung
    assert [w for w in st["warnings"]["plan"] if w["code"] == "guest_vlan" and "homeassistant" in w["text"]]
    assert not [w for w in st["warnings"]["prod"] if w["code"] == "guest_vlan"]
    v20 = next(v["id"] for v in st["vlans"] if v["vid"] == 20)
    st = cl.put(f"{P}/vlanplan/ports", json={"mode": "plan", "ports": [port3], "tagged": {str(v20): True}}, headers=H).json()
    assert not [w for w in st["warnings"]["plan"] if w["code"] == "guest_vlan"]
    # PDF-Umstellungsliste enthält den Gast
    pdf = cl.get(f"{P}/export/report.pdf?sections=vlans&lang=de")
    assert pdf.status_code == 200 and pdf.headers["content-type"].startswith("application/pdf")
    text = "".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "homeassistant" in text and "ohne Tag" in text and "Tag 20" in text
    # zurück auf den Ist-Stand -> kein Eintrag mehr
    st = cl.put(f"{P}/vlanplan/plan/guests", json={"guests": [ha], "vid": None}, headers=H).json()
    assert st["guest_diff"] == []
    # wieder planen; Proxmox meldet das neue Tag -> erledigt sich von selbst
    cl.put(f"{P}/vlanplan/plan/guests", json={"guests": [ha, ph], "vid": 20}, headers=H)
    _set_tag(ha, "20")
    st = cl.get(f"{P}/vlanplan").json()
    assert [x["name"] for x in st["guest_diff"]] == ["pihole"]
    # Abschließen: offener Gast zählt als offen, Plan weg, geplantes VLAN wird normal
    st = cl.post(f"{P}/vlanplan/plan/finish", headers=H).json()
    assert st["result"] == 1 and st["plan"] is None and st["guest_diff"] == []
    assert not next(v for v in st["vlans"] if v["vid"] == 20)["planned"]


def test_guest_plan_discard_and_rights():
    cl = login()
    pid, P, sw, pve, ha, ph, port3 = _setup(cl, "VLAN-Gäste-Verwerfen")
    cl.post(f"{P}/vlanplan/plan", json={}, headers=H)
    cl.post(f"{P}/vlans", json={"vid": 30, "name": "Server", "planned": True}, headers=H)
    cl.put(f"{P}/vlanplan/plan/guests", json={"guests": [ph], "vid": 30}, headers=H)
    # Lesen-Recht darf nicht planen
    from fastapi.testclient import TestClient
    from app import main, users
    with db() as c:
        if not users.by_email(c, "vg-view@x.de"):
            users.create(c, "vg-view@x.de", "passwort123", is_admin=False)
    cl.post(f"{P}/members", json=dict(email="vg-view@x.de", role="view"), headers=H)
    ro = TestClient(main.app)
    ro.post("/api/auth/login", json={"email": "vg-view@x.de", "password": "passwort123"}, headers=H)
    assert ro.get(f"{P}/vlanplan").json()["guest_diff"][0]["name"] == "pihole"
    assert ro.put(f"{P}/vlanplan/plan/guests", json={"guests": [ph], "vid": None}, headers=H).status_code == 403
    st = cl.delete(f"{P}/vlanplan/plan", headers=H).json()
    assert st["plan"] is None and st["guest_diff"] == [] and not any(v["vid"] == 30 for v in st["vlans"])
    # neuer Plan beginnt ohne alte Gast-Einträge
    st = cl.post(f"{P}/vlanplan/plan", json={}, headers=H).json()
    assert st["guest_diff"] == []
