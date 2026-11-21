"""Katalog-Import nur mit Netzwerkanschlüssen (Geräte ziehen mit), Topologie-Raster für viele Endgeräte, WAN-Eingang am Router."""
import io

from app import catalog, topology
from app.db import db
from tests.test_m6 import H, login


def test_only_network_ports_from_csv():
    assert catalog.parse_ports("1:hdmi:1.4b, 1:rj45:100M:LAN, 1:usb-a:2.0, 1:microsd") == [
        dict(count=1, kind="rj45", speed="100M", label="LAN", poe=False)]
    assert catalog.parse_ports("1:rj45:3.5mm:Out") == []
    assert len(catalog.parse_ports("24:rj45:1G, 2:sfp+:10G, 1:rj45:2,5G:WAN, 1:rj45:1000BASE-T")) == 4


def test_reimport_fixes_models_and_devices():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Amazon"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    with db() as c:  # so sah es nach dem alten Import aus: Klinke als RJ45
        mid = c.execute("INSERT INTO device_models(type, manufacturer, model, data, custom) VALUES('speaker','Amazon','Echo (3. Gen.)',?,1)",
                        ('{"ports": [{"count": 1, "kind": "rj45", "speed": "3.5mm", "label": "In/Out", "poe": false}], "wifi": "Wi-Fi 5"}',)).lastrowid
    dev = cl.post(f"{P}/devices", json=dict(name="Echo Küche", type="speaker", model_id=mid,
                                            ports=[dict(count=1, kind="rj45", speed="3.5mm", label="In/Out")]), headers=H).json()
    csv = "type;manufacturer;model;ports;wifi;managed;driver;verified;note\nSmart speaker;Amazon;Echo (3. Gen.);1:audio:3.5mm:In/Out;Wi-Fi 5;;;;\n"
    r = cl.post("/api/catalog/import/csv", files={"file": ("k.csv", io.BytesIO(csv.encode()), "text/csv")}, headers=H).json()
    assert r["updated"] == 1
    d = cl.get(f"{P}/devices/{dev['id']}").json()
    assert d["ports"] == [] and d["port_groups"] == []


def test_topology_grid_and_wan_port():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Breit"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    cat = {m["model"]: m for m in cl.get("/api/catalog").json()["models"]}
    fb = cat["FRITZ!Box 6591 Cable"]
    rt = cl.post(f"{P}/devices", json=dict(name="FRITZ!Box", type="router", model_id=fb["id"], ports=fb["ports"]), headers=H).json()
    ap = cl.post(f"{P}/devices", json=dict(name="AP", type="ap", uplink=dict(device_id=rt["id"], port_id=rt["ports"][0]["id"], medium="lan")), headers=H).json()
    for i in range(30):
        cl.post(f"{P}/devices", json=dict(name=f"Gerät {i:02d}", type="phone", uplink=dict(device_id=ap["id"], medium="lan")), headers=H)
    with db() as c:
        c.execute("UPDATE devices SET status='confirmed' WHERE profile_id=?", (pid,))
        t = topology.build(c, pid)
    leaves = [n for n in t["nodes"] if n.get("name", "").startswith("Gerät")]
    cols = {n["x"] for n in leaves}
    ys = {n["y"] for n in leaves}
    assert len(leaves) == 30 and len(cols) >= 3 and len(ys) <= 12  # breiter statt 30 Zeilen hoch
    assert t["width"] >= max(n["x"] for n in leaves) + t["node_w"]
    wan = next(e for e in t["edges"] if e["source"] == "internet")
    assert wan["child_label"].startswith("Kabel")
