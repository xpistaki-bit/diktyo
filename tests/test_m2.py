"""M2: Erkennung (Regeln, Katalog, Namen), Parser, Einsortieren, Posteingang, Scan-API, Regel-CSV."""
import asyncio
import json
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from app import main, users
from app.db import db, now
from app.scan import discover, ident, oui, runner

H = {"X-Requested-With": "diktyo"}


def login(email="m2@x.de"):
    with db() as c:
        if not users.by_email(c, email):
            users.create(c, email, "passwort123", is_admin=True)
    cl = TestClient(main.app)
    assert cl.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H).status_code == 200
    return cl


def host(**kw):
    h = dict(ip="192.168.50.99", mac="", vendor="", random=False, hostname="", netbios="", mdns=None, ssdp=None, http=None, ports=[], services={}, os="")
    h.update(kw)
    return h


def idf(h):
    with db() as c:
        return ident.identify(ident.load_rules(c), ident.catalog_index(c), h)


def test_identification_rules_and_catalog():
    # Amazon Echo: Hersteller + typische Ports
    i = idf(host(mac="44:00:49:00:00:01", vendor="Amazon Technologies Inc.", ports=[55442, 55443]))
    assert i["label"] == "Amazon Echo (Alexa)" and i["type"] == "speaker" and i["confidence"] >= 75
    assert {"k": "vendor", "v": "Amazon Technologies Inc."} in i["reasons"] and {"k": "port", "v": "55442"} in i["reasons"]
    # Fire TV gewinnt mit mDNS gegen Echo
    i = idf(host(vendor="Amazon Technologies Inc.", ports=[55442, 8009], mdns=dict(services=["_amzn-wplay._tcp"], names=["amzn"], txt={})))
    assert i["label"] == "Amazon Fire TV"
    # nur Hersteller Amazon: Vermutung mit niedriger Sicherheit („könnte eine Alexa sein“)
    i = idf(host(vendor="Amazon Technologies Inc."))
    assert "Echo" in i["label"] and i["confidence"] <= 50
    # ASUS EBM68 per UPnP -> Katalogmodell
    i = idf(host(vendor="ASUSTek COMPUTER INC.", ssdp=dict(manufacturer="ASUSTeK Computer Inc.", modelName="Wi-Fi Protected Setup Router ExpertWiFi_EBM68",
                                                            friendlyName="WPS Access Point")))
    assert i["model"] == "ExpertWiFi EBM68" and i["manufacturer"] == "ASUS" and i["type"] == "mesh" and i["model_id"]
    # FRITZ!Box 7590 AX schlägt 7590 (spezifischer)
    i = idf(host(vendor="AVM Audiovisuelles Marketing und Computersysteme GmbH", ssdp=dict(modelName="FRITZ!Box 7590 AX")))
    assert i["model"] == "FRITZ!Box 7590 AX"
    # Proxmox
    assert idf(host(ports=[22, 8006], http=dict(title="pve - Proxmox Virtual Environment", server="pve-api-daemon/3.0")))["type"] == "hypervisor"
    # zufällige MAC
    assert oui.is_random("DA:A1:19:00:00:01") and not oui.is_random("DC:39:6F:00:00:01")
    i = idf(host(mac="DA:A1:19:00:00:01", random=True))
    assert i["type"] == "phone" and {"k": "random", "v": ""} in i["reasons"]
    # nichts bekannt
    assert idf(host())["label"] == ""


def test_names_and_vendor():
    assert ident.clean_host("proxmoxone.matrix") == "proxmoxone" and ident.clean_host("192.168.1.1") == "192.168.1.1"
    assert ident.vendor_short("AVM Audiovisuelles Marketing und Computersysteme GmbH") == "AVM"
    assert ident.vendor_short("Beijing Roborock Technology Co., Ltd.") == "Beijing Roborock"
    i = dict(model="", label_short="Shelly", manufacturer="")
    assert ident.suggest_name(host(hostname="ServerRackShelly.matrix", ssdp=dict(friendlyName="WPS Access Point")), i) == "ServerRackShelly"
    assert ident.suggest_name(host(ssdp=dict(friendlyName="WPS Access Point"), mdns=dict(names=["78E2287EC3EB10E0._matterd._udp"], services=[], txt={})), i) == "Shelly .99"
    assert ident.suggest_name(host(mdns=dict(names=["amzn.dmgr:1731703A95BAD5388A011C34BEBF4345:xnVDMM+4u1:291666"], services=[], txt={})), i) == "Shelly .99"
    assert ident.good_host("_gateway") == "" and ident.good_host("proxmoxone.matrix") == "proxmoxone"
    assert ident.suggest_name(host(hostname="_gateway", mdns=dict(names=["none", "shelly1-E8DB84AB9DEC"], services=[], txt={})), i) == "shelly1-E8DB84AB9DEC"


def test_parsers():
    xml = ET.fromstring("""<nmaprun><host><address addr="192.168.50.12" addrtype="ipv4"/><ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh" product="OpenSSH" version="9.2p1"/></port>
      <port protocol="tcp" portid="23"><state state="closed"/></port>
      <port protocol="tcp" portid="8006"><state state="open"/><service name="https" product="pve-api-daemon"/></port></ports>
      <os><osmatch name="Linux 5.15 - 6.1" accuracy="96"/></os></host></nmaprun>""")
    r = discover.parse_nmap(xml)["192.168.50.12"]
    assert r["ports"] == [22, 8006] and r["services"]["22"] == "OpenSSH 9.2p1" and r["os"] == "Linux 5.15 - 6.1"
    assert discover.hosts_of("192.168.50.0/29", ["192.168.50.4/31"]) == ["192.168.50.1", "192.168.50.2", "192.168.50.3", "192.168.50.6"]
    assert discover._nb_name("*")[:3] == b"\x20CK"
    # Ping/TCP gegen localhost (läuft ohne Root)
    res = asyncio.run(discover.sweep(["127.0.0.1"], [1]))
    assert "127.0.0.1" in res


def test_merge_inbox_and_api(monkeypatch):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Scan-Test"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    cl.post(f"{P}/subnets", json={"cidr": "192.168.50.0/24", "gateway": "192.168.50.1", "dhcp_start": "192.168.50.100", "dhcp_end": "192.168.50.200"}, headers=H)
    # bestehendes, von Hand angelegtes Gerät mit statischer IP und eigenem Namen
    fb = cl.post(f"{P}/devices", json={"name": "Mein Router", "type": "router", "mac": "E8:9C:25:00:00:01", "ips": [{"address": "192.168.50.1"}]}, headers=H).json()
    echo_h = host(ip="192.168.50.155", mac="44:00:49:00:00:01", vendor="Amazon Technologies Inc.", ports=[55443], hostname="echo-kueche.matrix")
    router_h = host(ip="192.168.50.1", mac="E8:9C:25:00:00:01", vendor="ASUSTek COMPUTER INC.", hostname="asus-router.matrix",
                    ssdp=dict(modelName="ExpertWiFi_EBM68"))
    with db() as c:
        rules, index = ident.load_rules(c), ident.catalog_index(c)
        for h in (echo_h, router_h):
            h["ident"] = ident.identify(rules, index, h)
        jid = c.execute("INSERT INTO jobs(profile_id, kind, status, created) VALUES(?, 'scan', 'done', ?)", (pid, now())).lastrowid
        stats = runner.merge(c, pid, jid, [echo_h, router_h], probed={"192.168.50.1", "192.168.50.155", "192.168.50.77"})
    assert stats["new"] == 1 and stats["known"] == 1
    devs = {d["name"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    # manuelle Angaben bleiben, Erkennung wird ergänzt
    assert devs["Mein Router"]["type"] == "router" and devs["Mein Router"]["status"] == "confirmed" and devs["Mein Router"]["online"] == 1
    assert devs["Mein Router"]["hostname"] == "asus-router" and devs["Mein Router"]["ident"]["model"] == "ExpertWiFi EBM68"
    echo = devs["echo-kueche"]
    assert echo["status"] == "discovered" and echo["type"] == "speaker" and echo["ips"][0] == {"address": "192.168.50.155", "kind": "dhcp"}
    assert cl.get(f"/api/profiles/{pid}").json()["inbox"] == 1
    # zweiter Scan: Echo hat neue DHCP-Adresse, Router antwortet nicht mehr
    echo_h2 = dict(echo_h, ip="192.168.50.160")
    with db() as c:
        jid = c.execute("INSERT INTO jobs(profile_id, kind, status, created) VALUES(?, 'scan', 'done', ?)", (pid, now())).lastrowid
        stats = runner.merge(c, pid, jid, [echo_h2], probed={"192.168.50.1", "192.168.50.160"})
    assert stats["known"] == 1 and stats["offline"] == 1
    det = cl.get(f"{P}/devices/{fb['id']}").json()
    assert det["online"] == 0 and [e["online"] for e in det["events"]] == [False, True]
    assert next(d for d in cl.get(f"{P}/devices").json()["devices"] if d["name"] == "echo-kueche")["ips"][0]["address"] == "192.168.50.160"
    # Posteingang: ignorieren, wiederherstellen, übernehmen
    eid = echo["id"]
    assert cl.post(f"{P}/inbox", json={"action": "ignore", "ids": [eid]}, headers=H).json()["changed"] == 1
    assert cl.get(f"/api/profiles/{pid}").json()["inbox"] == 0
    cl.post(f"{P}/inbox", json={"action": "restore", "ids": [eid]}, headers=H)
    r = cl.put(f"{P}/devices/{eid}", json={"name": "Echo Küche", "type": "speaker", "status": "confirmed"}, headers=H).json()
    assert r["status"] == "confirmed"
    # bestätigte Geräte lassen sich über den Posteingang nicht löschen
    assert cl.post(f"{P}/inbox", json={"action": "delete", "ids": [eid]}, headers=H).json()["changed"] == 0
    # PDF/CSV enthalten nur bestätigte Geräte
    assert "Echo Küche" in cl.get(f"{P}/export/devices.csv").text

    # Scan-Einstellungen und Start
    r = cl.put(f"{P}/scan", json={"mode": "light", "targets": ["192.168.50.0/24"], "exclude": ["192.168.50.64/28"], "schedule_hours": 24}, headers=H).json()
    assert r["settings"]["mode"] == "light" and r["settings"]["exclude"] == ["192.168.50.64/28"]
    assert cl.put(f"{P}/scan", json={"targets": ["10.0.0.0/8"]}, headers=H).status_code == 400
    job = cl.post(f"{P}/scan/run", json={}, headers=H).json()["job"]
    assert job["status"] == "queued"
    assert cl.post(f"{P}/scan/run", json={}, headers=H).status_code == 409
    assert cl.get(f"/api/jobs/{job['id']}").json()["id"] == job["id"]
    with db() as c:
        c.execute("UPDATE jobs SET status='done' WHERE id=?", (job["id"],))


def test_rules_api_csv():
    cl = login()
    n0 = len(cl.get("/api/rules").json()["rules"])
    assert n0 > 80
    r = cl.post("/api/rules", json={"label": "Saugroboter Test", "type": "iot", "weight": 90, "hostname": "robbi"}, headers=H).json()
    assert r["custom"] and r["cond"] == {"hostname": "robbi"}
    assert cl.post("/api/rules", json={"label": "kaputt", "vendor": "(["}, headers=H).status_code == 400
    assert cl.post("/api/rules", json={"label": "ohne Bedingung"}, headers=H).status_code == 400
    assert "robbi" in cl.get("/api/rules/export.csv").text
    csv_data = "label;type;weight;vendor;ports\nTestgerät;iot;60;testvendor;80,443\n;iot;60;x;\n"
    res = cl.post("/api/rules/import/csv", files={"file": ("r.csv", csv_data.encode(), "text/csv")}, headers=H).json()
    assert res["new"] == 1 and len(res["errors"]) == 1
    i = idf(host(vendor="TestVendor GmbH", ports=[80, 443]))
    assert i["label"] == "Testgerät"
