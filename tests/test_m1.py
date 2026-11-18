"""M1: Geräte mit Ports und Anschluss, Standorte, IPAM, Katalog, Ausgabe, Sicherung und Wiederherstellung."""
import io
import zipfile

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import db as dbmod
from app import main, users
from app.db import db

H = {"X-Requested-With": "diktyo"}


def login(email="m1@x.de", admin=True):
    with db() as c:
        if not users.by_email(c, email):
            users.create(c, email, "passwort123", is_admin=admin)
    cl = TestClient(main.app)
    assert cl.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H).status_code == 200
    return cl


def model_id(cl, model):
    return next(m["id"] for m in cl.get("/api/catalog").json()["models"] if m["model"] == model)


def test_inventory_ipam_export_backup(tmp_path, monkeypatch):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Heimnetz"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"

    # Standorte
    locs = cl.post(f"{P}/locations", json={"name": "Haus"}, headers=H).json()["locations"]
    haus = locs[0]["id"]
    locs = cl.post(f"{P}/locations", json={"name": "Keller", "parent_id": haus}, headers=H).json()["locations"]
    keller = next(x for x in locs if x["name"] == "Keller")
    assert keller["path"] == "Haus › Keller"
    assert cl.put(f"{P}/locations/{haus}", json={"name": "Haus", "parent_id": keller["id"]}, headers=H).status_code == 400

    # Katalog: Ports aus dem Startkatalog
    zy, fb, eb = model_id(cl, "XGS1935-28"), model_id(cl, "FRITZ!Box 6591 Cable"), model_id(cl, "ExpertWiFi EBM68")
    cat = {m["id"]: m for m in cl.get("/api/catalog").json()["models"]}

    def dev(name, typ, mid=None, **kw):
        body = dict(name=name, type=typ, model_id=mid, ports=cat[mid]["ports"] if mid else [], **kw)
        r = cl.post(f"{P}/devices", json=body, headers=H)
        assert r.status_code == 200, r.text
        return r.json()

    fritz = dev("FRITZ!Box", "router", fb, mac="dc-39-6f-00-00-01", ips=[{"address": "192.168.178.1", "kind": "static"}], location_id=keller["id"])
    assert fritz["mac"] == "DC:39:6F:00:00:01" and len(fritz["ports"]) == 5
    switch = dev("Zyxel", "switch", zy, ips=[{"address": "192.168.178.2"}], location_id=keller["id"])
    assert len(switch["ports"]) == 28 and switch["ports"][-1]["kind"] == "sfp+"
    lan1 = next(p for p in fritz["ports"] if p["name"] == "LAN 1")
    # Switch hängt mit seinem Port 25 an LAN 1 der FRITZ!Box
    switch = cl.put(f"{P}/devices/{switch['id']}", json=dict(name="Zyxel", type="switch", model_id=zy, ips=[{"address": "192.168.178.2"}],
                    uplink=dict(device_id=fritz["id"], port_id=lan1["id"], local_port_id=switch["ports"][24]["id"], medium="lan")), headers=H).json()
    assert switch["uplink"]["port_name"] == "LAN 1" and switch["uplink"]["local_port_name"] == "25"
    p1 = switch["ports"][0]
    ebm = dev("EBM68 Wohnzimmer", "mesh", eb, ips=[{"address": "192.168.178.3"}], uplink=dict(device_id=switch["id"], port_id=p1["id"], medium="lan"))
    node2 = dev("EBM68 OG", "mesh", eb, ips=[{"address": "192.168.178.4"}], uplink=dict(device_id=ebm["id"], medium="mesh"))
    echo = dev("Echo Küche", "speaker", ips=[{"address": "192.168.178.25", "kind": "dhcp"}], mac="44:00:49:00:00:01",
               uplink=dict(device_id=node2["id"], medium="wlan"))
    # belegter Port wird abgelehnt
    r = cl.post(f"{P}/devices", json=dict(name="NAS", type="nas", uplink=dict(device_id=switch["id"], port_id=p1["id"])), headers=H)
    assert r.status_code == 400 and "schon mit EBM68 Wohnzimmer belegt" in r.json()["error"]
    r = cl.post(f"{P}/devices", json=dict(name="NAS", type="nas", uplink=dict(device_id=switch["id"], port_id=p1["id"])), headers={**H, "X-Lang": "en"})
    assert r.json()["error"] == "Port 1 is already connected to EBM68 Wohnzimmer"
    # Ring wird abgelehnt
    r = cl.put(f"{P}/devices/{fritz['id']}", json=dict(name="FRITZ!Box", type="router", model_id=fb, uplink=dict(device_id=echo["id"], medium="lan")), headers=H)
    assert r.status_code == 400
    # Detail: Port 1 zeigt den EBM68, der EBM68 zeigt seine WLAN-Clients
    det = cl.get(f"{P}/devices/{switch['id']}").json()
    assert det["ports"][0]["peer"]["device_name"] == "EBM68 Wohnzimmer" and det["ports"][0]["peer"]["ip"] == "192.168.178.3"
    assert det["ports"][24]["peer"]["device_name"] == "FRITZ!Box" and det["ports_used"] == 2
    assert [k["name"] for k in cl.get(f"{P}/devices/{node2['id']}").json()["connected"]] == ["Echo Küche"]
    # weniger Ports: Verbindung an entferntem Port verschwindet, Rest bleibt
    cl.put(f"{P}/devices/{switch['id']}", json=dict(name="Zyxel", type="switch", model_id=zy, ports=[{"count": 8, "kind": "rj45", "speed": "1G"}]), headers=H)
    det = cl.get(f"{P}/devices/{switch['id']}").json()
    assert len(det["ports"]) == 8 and det["ports"][0]["peer"]["device_name"] == "EBM68 Wohnzimmer" and det["uplink"] is None

    # IPAM
    v = cl.post(f"{P}/vlans", json={"vid": 10, "name": "IoT"}, headers=H).json()["vlans"][0]
    assert cl.post(f"{P}/vlans", json={"vid": 10}, headers=H).status_code == 409
    assert cl.post(f"{P}/subnets", json={"cidr": "192.168.178.0/24", "gateway": "10.0.0.1"}, headers=H).status_code == 400
    r = cl.post(f"{P}/subnets", json={"cidr": "192.168.178.7/24", "name": "Heimnetz", "gateway": "192.168.178.1",
                                       "dhcp_start": "192.168.178.20", "dhcp_end": "192.168.178.200", "dns": "192.168.178.1"}, headers=H).json()
    sn = r["subnets"][0]
    assert sn["cidr"] == "192.168.178.0/24" and sn["size"] == 254 and sn["used"] == 5 and sn["dhcp_size"] == 181
    cl.post(f"{P}/subnets", json={"cidr": "192.168.10.0/24", "vlan_id": v["id"]}, headers=H)
    det = cl.get(f"{P}/subnets/{sn['id']}").json()
    assert det["addresses"][0]["address"] == "192.168.178.1" and det["addresses"][0]["gateway"]
    static_free = [f for f in det["free"] if not f["dhcp"]]
    assert static_free[0]["start"] == "192.168.178.5" and static_free[0]["end"] == "192.168.178.19"
    # Konflikte: doppelte IP, statische IP im DHCP-Bereich, IP außerhalb, doppelte MAC
    dev("Drucker", "printer", ips=[{"address": "192.168.178.3"}], mac="44:00:49:00:00:01")
    dev("Kamera", "camera", ips=[{"address": "192.168.178.50", "kind": "static"}, {"address": "10.9.9.9"}])
    codes = {x["code"] for x in cl.get(f"{P}/subnets").json()["conflicts"]}
    assert {"dup_ip", "in_dhcp", "outside", "dup_mac"} <= codes
    assert cl.get(f"{P}/vlans").json()["vlans"][0]["subnets"] == ["192.168.10.0/24"]

    # Ausgabe
    r = cl.get(f"{P}/export/devices.csv")
    assert r.status_code == 200 and "Echo Küche" in r.text and "EBM68 OG" in r.text
    assert "192.168.178.25" in cl.get(f"{P}/export/ips.csv").text
    r = cl.get(f"{P}/export/report.pdf?sections=devices,ipplan,vlans,ports,wlan,notes")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    text = "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(r.content)).pages)
    assert "Geräteliste" in text and "192.168.178.0/24" in text and "Portbelegung" in text and "WLAN-Übersicht" in text
    en = cl.get(f"{P}/export/report.pdf?sections=devices&lang=en")
    assert "Device list" in "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(en.content)).pages)

    # Rechte: Lesende dürfen nicht ändern
    viewer = login("viewer@x.de", admin=False)
    cl.post(f"/api/profiles/{pid}/members", json={"email": "viewer@x.de", "role": "view"}, headers=H)
    assert viewer.get(f"{P}/devices").status_code == 200
    assert viewer.post(f"{P}/devices", json={"name": "X"}, headers=H).status_code == 403

    # Standort löschen: Geräte rücken nach oben
    cl.delete(f"{P}/locations/{keller['id']}", headers=H)
    assert next(d for d in cl.get(f"{P}/devices").json()["devices"] if d["name"] == "FRITZ!Box")["location"] == "Haus"

    # Sicherung mit Passphrase und SMTP-Passwort, dann Profil-Import in dieselbe Installation
    cl.put("/api/settings", json={"smtp": {"host": "mail.example", "password": "smtp-geheim"}}, headers=H)
    cl.put("/api/backup", json={"targets": [{"type": "local", "path": str(tmp_path / "bk")}], "auto_hours": 24, "passphrase": "kurz"}, headers=H)
    assert cl.put("/api/backup", json={"targets": [], "passphrase": "kurz"}, headers=H).status_code == 400
    r = cl.put("/api/backup", json={"targets": [{"type": "local", "path": str(tmp_path / "bk")}], "auto_hours": 24, "passphrase": "backup-pass"}, headers=H).json()
    assert r["settings"]["passphrase"] == "••••••"
    res = cl.post("/api/backup/run", headers=H).json()
    assert res["results"][0]["ok"], res
    raw = cl.get("/api/backup/download").content
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    assert "export.json" in names and any(n.endswith("netzwerk.pdf") for n in names)
    assert b"smtp-geheim" not in zipfile.ZipFile(io.BytesIO(raw)).read("export.json")
    imp = cl.post("/api/backup/import", files={"file": ("b.zip", raw, "application/zip")}, headers=H).json()
    assert imp["profiles"] >= 1
    copy = next(p for p in cl.get("/api/profiles").json()["profiles"] if p["name"] == "Heimnetz (importiert)")
    devs = {d["name"]: d for d in cl.get(f"/api/profiles/{copy['id']}/devices").json()["devices"]}
    assert devs["Echo Küche"]["uplink"]["device_name"] == "EBM68 OG" and devs["EBM68 Wohnzimmer"]["uplink"]["port_name"] == "1"

    # Vollständige Wiederherstellung in eine leere Installation
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "frisch.db")
    dbmod.migrate()
    with db() as c:
        from app import catalog
        catalog.merge_seed(c)
    fresh = TestClient(main.app)
    assert fresh.get("/api/state").json()["first_run"]
    bad = fresh.post("/api/restore", files={"file": ("b.zip", raw, "application/zip")}, data={"passphrase": "falsch!!"}, headers=H)
    assert bad.status_code == 400
    r = fresh.post("/api/restore", files={"file": ("b.zip", raw, "application/zip")}, data={"passphrase": "backup-pass"}, headers=H).json()
    assert r["users"] >= 2 and not r["secrets_dropped"]
    assert fresh.post("/api/auth/login", json={"email": "m1@x.de", "password": "passwort123"}, headers=H).status_code == 200
    s = fresh.get("/api/settings").json()
    assert s["smtp"]["password"] == "••••••"
    with db() as c:
        from app import mailer, security
        assert security.decrypt(mailer.smtp_config(c)["password"]) == "smtp-geheim"
    assert fresh.post("/api/restore", files={"file": ("b.zip", raw, "application/zip")}, headers=H).status_code == 403


def test_catalog_csv():
    cl = login()
    tpl = cl.get("/api/catalog/export.csv?template=1").text
    assert "24:rj45:1G, 4:sfp+:10G" in tpl
    csv_data = "Typ;Hersteller;Modell;Ports;WLAN\nSwitch;Testfirma;TS-10;8:rj45:1G::poe, 2:sfp+:10G;\nAccess Point;Testfirma;AP-1;1:rj45:2.5G:LAN;Wi-Fi 7\n;;ohne Hersteller;;\n"
    r = cl.post("/api/catalog/import/csv", files={"file": ("k.csv", csv_data.encode(), "text/csv")}, headers=H).json()
    assert r["new"] == 2 and len(r["errors"]) == 1
    m = next(x for x in cl.get("/api/catalog").json()["models"] if x["model"] == "TS-10")
    assert m["type"] == "switch" and m["port_summary"] == "8× RJ45 1G PoE + 2× SFP+ 10G" and m["custom"]
    viewer = login("viewer2@x.de", admin=False)
    assert viewer.post("/api/catalog", json={"manufacturer": "A", "model": "B"}, headers=H).status_code == 403
