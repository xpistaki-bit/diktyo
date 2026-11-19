"""M4: Topologie-Baum (Gruppen, Ports, ohne Verbindung), Schnell-Ping, Topologie im PDF."""
import io

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import main, users
from app.db import db

H = {"X-Requested-With": "diktyo"}


def setup_net():
    with db() as c:
        if not users.by_email(c, "m4@x.de"):
            users.create(c, "m4@x.de", "passwort123", is_admin=True)
    cl = TestClient(main.app)
    cl.post("/api/auth/login", json={"email": "m4@x.de", "password": "passwort123"}, headers=H)
    pid = cl.post("/api/profiles", json={"name": "Topo"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    cat = {m["model"]: m for m in cl.get("/api/catalog").json()["models"]}

    def dev(name, typ, model=None, **kw):
        m = cat.get(model)
        r = cl.post(f"{P}/devices", json=dict(name=name, type=typ, model_id=m and m["id"], ports=m["ports"] if m else [], **kw), headers=H)
        assert r.status_code == 200, r.text
        return r.json()

    fb = dev("FRITZ!Box", "router", "FRITZ!Box 6591 Cable", ips=[{"address": "127.0.0.1"}])
    sw = dev("Zyxel", "switch", "XGS1935-28", uplink=dict(device_id=fb["id"], port_id=fb["ports"][2]["id"], medium="lan"))
    ap = dev("EBM68", "mesh", "ExpertWiFi EBM68", uplink=dict(device_id=sw["id"], port_id=sw["ports"][0]["id"], medium="lan"))
    for i in range(6):
        dev(f"Handy {i}", "phone", uplink=dict(device_id=ap["id"], medium="wlan"))
    pve = dev("Proxmox", "hypervisor", uplink=dict(device_id=sw["id"], port_id=sw["ports"][4]["id"], medium="lan"))
    dev("VM 1", "vm", uplink=dict(device_id=pve["id"], medium="virtual"))
    dev("Drucker", "printer", ips=[{"address": "192.0.2.77"}])  # ohne Verbindung
    return cl, pid, P, dict(fb=fb, sw=sw, ap=ap, pve=pve)


def test_topology_tree_and_groups():
    cl, pid, P, d = setup_net()
    t = cl.get(f"{P}/topology").json()
    nodes = {n["id"]: n for n in t["nodes"]}
    assert t["total"] == 12
    # die 6 WLAN-Handys sind zu einer Gruppe zusammengefasst, die eine VM nicht
    groups = [n for n in t["nodes"] if n["kind"] == "group"]
    assert len(groups) == 1 and groups[0]["count"] == 6 and groups[0]["medium"] == "wlan" and groups[0]["parent"] == d["ap"]["id"]
    assert f"d{d['pve']['id']}" in {e["source"] for e in t["edges"]} and any(n.get("name") == "VM 1" for n in t["nodes"])
    # Kanten tragen die Port-Namen der Gegenstelle
    e = next(e for e in t["edges"] if e["target"] == f"d{d['sw']['id']}")
    assert e["source"] == f"d{d['fb']['id']}" and e["label"] == "LAN 3" and e["medium"] == "lan"
    assert next(e for e in t["edges"] if e["target"] == f"d{d['ap']['id']}")["label"] == "1"
    # Spalten = Tiefe, Eltern mittig zu ihren Kindern
    assert nodes[f"d{d['fb']['id']}"]["x"] == 0 and nodes[f"d{d['sw']['id']}"]["x"] == 280 and nodes[f"d{d['ap']['id']}"]["x"] == 560
    # Drucker ohne Verbindung steht unten in eigenem Bereich
    pr = next(n for n in t["nodes"] if n.get("name") == "Drucker")
    assert t["loose_from"] is not None and pr["y"] >= t["loose_from"] - 1
    # Gruppe aufklappen
    t2 = cl.get(f"{P}/topology?expanded={d['ap']['id']}:wlan").json()
    assert not [n for n in t2["nodes"] if n["kind"] == "group"] and sum(1 for n in t2["nodes"] if n.get("type") == "phone") == 6


def test_quick_ping_and_pdf():
    cl, pid, P, d = setup_net()
    r = cl.post(f"{P}/ping", json={}, headers=H).json()
    assert r["checked"] == 2 and r["results"][str(d["fb"]["id"])] is True and r["online"] == 1
    r = cl.post(f"{P}/ping", json={"device_ids": [d["fb"]["id"]]}, headers=H).json()
    assert r["checked"] == 1
    t = cl.get(f"{P}/topology").json()
    assert next(n for n in t["nodes"] if n.get("device_id") == d["fb"]["id"])["online"] == 1
    pdf = cl.get(f"{P}/export/report.pdf?sections=topology").content
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Topologie" in text and "Zyxel" in text and "6 WLAN-Geräte" in text and "Ohne Verbindung".upper() in text
