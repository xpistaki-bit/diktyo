"""Portfreigaben und UPnP: Leser je Treiber (FRITZ!Box, ASUS, OpenWrt, MikroTik, OPNsense, UniFi), gemeinsames Format,
neue Freigaben erkennen und melden, Quittieren, Notizen, Gerätezuordnung, Übersicht, CSV, Rechte, Löschen der Integration."""
import json

from app import actions, integrations, notify
from app.db import db
from app.drivers import asuswrt, fritzbox, mikrotik, openwrt, opnsense, unifi
from app.drivers.controller import forward, proto_name
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


def test_common_format():
    assert [proto_name(x) for x in ("tcp", "UDP", "tcp udp", "tcp_udp", "BOTH", ["tcp", "udp"], "6", "", "icmp")] == \
        ["TCP", "UDP", "TCP/UDP", "TCP/UDP", "TCP/UDP", "TCP/UDP", "TCP", "TCP/UDP", "ICMP"]
    f = forward("static", "tcp", "8000:8010", " 192.0.2.5 ", "", "Kamera", True, "any", "0")
    assert f == dict(kind="static", proto="TCP", ext="8000-8010", ip="192.0.2.5", port="8000-8010", desc="Kamera", enabled=True, remote="", lease=None)
    assert forward("upnp", "udp", "any", "192.0.2.6", None, lease="3600")["ext"] == "" and forward("upnp", "udp", 1, "x", lease="3600")["lease"] == 3600


class FritzActionError(Exception):  # wie fritzconnection: UPnP-Fehler 401 = Aktion/Dienst fehlt (keine Anmeldefrage)
    pass


class FritzSecurityError(Exception):  # UPnP-Fehler 606 = Aktion nicht erlaubt (Benutzerrecht fehlt)
    pass


class FritzArrayIndexError(Exception):  # UPnP-Fehler 713 = Index gibt es nicht (Ende der Liste)
    pass


class FakeFC:
    def __init__(self, entries, svc="WANIPConn1", count=True, perm=True, default=None):
        self.entries, self.svc, self.calls, self.count, self.perm, self.default = entries, svc, 0, count, perm, default

    def call_action(self, svc, act, **kw):
        self.calls += 1
        if svc == "Layer3Forwarding1" and self.default:
            return {"NewDefaultConnectionService": self.default}
        if svc != self.svc:
            raise FritzActionError("UPnPError:\nerrorCode: 401\nerrorDescription: Invalid Action")
        if not self.perm:
            raise FritzSecurityError("UPnPError:\nerrorCode: 606\nerrorDescription: Action not authorized")
        if act == "GetPortMappingNumberOfEntries":
            if not self.count:
                raise FritzActionError("UPnPError:\nerrorCode: 401\nerrorDescription: Invalid Action")
            return {"NewPortMappingNumberOfEntries": len(self.entries)}
        if kw["NewPortMappingIndex"] >= len(self.entries):
            raise FritzArrayIndexError("UPnPError:\nerrorCode: 713\nerrorDescription: SpecifiedArrayIndexInvalid")
        return self.entries[kw["NewPortMappingIndex"]]


FB_ENTRIES = [
    {"NewRemoteHost": "", "NewExternalPort": 443, "NewProtocol": "TCP", "NewInternalPort": 443, "NewInternalClient": "192.168.178.50",
     "NewEnabled": "1", "NewPortMappingDescription": "Nextcloud", "NewLeaseDuration": 0},
    {"NewRemoteHost": "", "NewExternalPort": 51413, "NewProtocol": "UDP", "NewInternalPort": 51413, "NewInternalClient": "192.168.178.77",
     "NewEnabled": "1", "NewPortMappingDescription": "Transmission", "NewLeaseDuration": 3500},
]


def test_fritzbox_reader_and_interval():
    lst = fritzbox.forwards(FakeFC(FB_ENTRIES))
    assert [(x["kind"], x["proto"], x["ext"], x["ip"], x["desc"], x["lease"]) for x in lst] == [
        ("", "TCP", "443", "192.168.178.50", "Nextcloud", None), ("upnp", "UDP", "51413", "192.168.178.77", "Transmission", 3500)]
    assert len(fritzbox.forwards(FakeFC(FB_ENTRIES, svc="WANPPPConnection1"))) == 2  # DSL mit PPPoE
    fc, st = FakeFC(FB_ENTRIES), {}
    assert fritzbox.poll_forwards(fc, {}, st) == (None, False, fritzbox.PF_ERR["nopw"])  # ohne Benutzer/Passwort nicht lesbar
    lst, cached, err = fritzbox.poll_forwards(fc, {"password": "pw"}, st, now=1000)
    assert len(lst) == 2 and not cached and err == ""
    n = fc.calls
    lst, cached, _ = fritzbox.poll_forwards(fc, {"password": "pw"}, st, now=1000 + 60)
    assert cached and fc.calls == n  # innerhalb von 5 Minuten keine neuen TR-064-Abfragen
    assert not fritzbox.poll_forwards(fc, {"password": "pw"}, st, now=1000 + fritzbox.FORWARDS_S)[1]
    # Box ohne GetPortMappingNumberOfEntries: bis zum ungültigen Index (713) lesen
    assert len(fritzbox.forwards(FakeFC(FB_ENTRIES, count=False))) == 2
    assert fritzbox.forwards(FakeFC([], count=False)) == []  # keine Freigaben ist kein Fehler
    # Standardverbindung (Layer3Forwarding) zuerst
    fc = FakeFC(FB_ENTRIES, svc="WANPPPConnection1", default="InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1")
    assert len(fritzbox.forwards(fc)) == 2 and fritzbox._pf_services(fc)[0] == "WANPPPConnection1"
    # Benutzerrecht fehlt (606) -> Grund im Ergebnis statt stiller Lücke
    lst, _, err = fritzbox.poll_forwards(FakeFC(FB_ENTRIES, perm=False), {"password": "pw"}, {}, now=1)
    assert lst is None and err == fritzbox.PF_ERR["perm"]
    # Box ohne die Aktionen
    lst, _, err = fritzbox.poll_forwards(FakeFC(FB_ENTRIES, svc="X"), {"password": "pw"}, {}, now=1)
    assert lst is None and err == fritzbox.PF_ERR["missing"]
    # UPnP-Fehler 401 ist keine abgelehnte Anmeldung
    try:
        fritzbox._call(FakeFC([], svc="X"), "WANIPConn1", "GetInfo")
    except PermissionError:
        raise AssertionError("Invalid Action als Anmeldefehler gewertet")
    except FritzActionError:
        pass


def test_router_readers():
    # ASUS: vts_rulelist (mit/ohne Quell-IP) und UPnP-Liste
    vts = "<NAS>5001>192.168.50.10>5001>TCP><Spiel>3074:3075>192.168.50.20>>BOTH>203.0.113.0/24"
    a = asuswrt.parse_vts(vts, True)
    assert [(x["desc"], x["proto"], x["ext"], x["port"], x["remote"]) for x in a] == [
        ("NAS", "TCP", "5001", "5001", ""), ("Spiel", "TCP/UDP", "3074-3075", "3074-3075", "203.0.113.0/24")]
    assert asuswrt.parse_vts("", True) == []
    up = asuswrt.parse_upnp('{"get_upnp_array":[["TCP", "51413", "192.168.50.20", "51413", "Transmission"],\n["UDP", "3478", "192.168.50.30", "3479", "Konsole"],]}')
    assert [(x["kind"], x["proto"], x["ext"], x["ip"], x["port"], x["desc"]) for x in up] == [
        ("upnp", "TCP", "51413", "192.168.50.20", "51413", "Transmission"), ("upnp", "UDP", "3478", "192.168.50.30", "3479", "Konsole")]
    # OpenWrt: Redirects (DNAT) und miniupnpd
    fw = {"r1": {".type": "redirect", ".index": 5, "name": "SSH", "src": "wan", "src_dport": "2222", "dest_ip": "192.168.1.10", "dest_port": "22", "proto": ["tcp"]},
          "r2": {".type": "redirect", ".index": 6, "name": "aus", "src_dport": "80", "dest_ip": "192.168.1.11", "enabled": "0"},
          "r3": {".type": "redirect", ".index": 7, "target": "SNAT", "dest_ip": "192.168.1.12"},
          "z": {".type": "zone", "name": "wan"}}
    o = openwrt.forwards(fw, {"rules": [{"proto": "UDP", "extport": 9000, "intaddr": "192.168.1.20", "intport": 9000, "descr": "App", "expires": 120}]})
    assert [(x["kind"], x["desc"], x["proto"], x["ext"], x["port"], x["enabled"], x["lease"]) for x in o] == [
        ("static", "SSH", "TCP", "2222", "22", True, None), ("static", "aus", "TCP/UDP", "80", "80", False, None), ("upnp", "App", "UDP", "9000", "9000", True, 120)]
    assert openwrt.forwards(None, None) is None  # Firewall-Konfiguration nicht lesbar (ACL)
    # MikroTik: dst-nat-Regeln, dynamische von UPnP
    nat = [{"chain": "dstnat", "action": "dst-nat", "protocol": "tcp", "dst-port": "443", "to-addresses": "192.168.88.5", "to-ports": "8443", "comment": "Web"},
           {"chain": "dstnat", "action": "dst-nat", "protocol": "udp", "dst-port": "3074", "to-addresses": "192.168.88.9", "dynamic": "true", "comment": "upnp 192.168.88.9: Xbox"},
           {"chain": "srcnat", "action": "masquerade"}]
    m = mikrotik.forwards(nat)
    assert [(x["kind"], x["ext"], x["port"], x["ip"]) for x in m] == [("static", "443", "8443", "192.168.88.5"), ("upnp", "3074", "3074", "192.168.88.9")]
    assert mikrotik.forwards(None) is None
    # OPNsense (Destination NAT ab 25.7), tolerante Feldnamen
    d = opnsense.forwards({"rows": [{"enabled": "1", "protocol": "TCP", "destination_port": "8080", "target": "10.0.0.5", "local-port": "80", "description": "Web"},
                                    {"enabled": "0", "protocol": "UDP", "destination_port": "53", "target": "10.0.0.6"}, {"description": "ohne Ziel"}]})
    assert [(x["ext"], x["ip"], x["port"], x["enabled"]) for x in d] == [("8080", "10.0.0.5", "80", True), ("53", "10.0.0.6", "53", False)]
    assert opnsense.forwards(None) is None
    # UniFi (klassische API rest/portforward)
    calls = []

    def classic(cl, state, path):
        calls.append(path)
        return [{"name": "Plex", "enabled": True, "proto": "tcp_udp", "dst_port": "32400", "fwd": "192.168.1.30", "fwd_port": "32400", "src": "any"}]
    orig = unifi._classic
    unifi._classic = classic
    try:
        u = unifi._portforwards(None, {}, ["default"])
    finally:
        unifi._classic = orig
    assert calls == ["/api/s/default/rest/portforward"] and [(x["proto"], x["ext"], x["ip"], x["remote"]) for x in u] == [("TCP/UDP", "32400", "192.168.1.30", "")]


def test_track_events_ack_notes_and_dashboard(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Portfreigaben")
    fb_list = fritzbox.forwards(FakeFC(FB_ENTRIES))
    out = {"forwards": fb_list[:1], "cached": False}

    def fake_poll(conf, state):
        res = dict(info=dict(model="FRITZ!Box 7590"), wan={}, hosts=[], mesh={}, auth=True, wlan=[])
        if out.get("error"):
            res["forwards_error"] = out["error"]
        else:
            res.update(forwards=out["forwards"], forwards_cached=out["cached"])
        return res, {}, state
    monkeypatch.setattr(fritzbox, "poll", fake_poll)

    def events():
        with db() as c:
            return [json.loads(r["data"]) for r in c.execute("SELECT data FROM events WHERE profile_id=? AND kind='port_forward_new'", (pid,))]
    # erste Abfrage: Vorhandenes gilt als bekannt, keine Meldung
    integrations.poll(d["fiid"])
    st = cl.get(f"{P}/portforwards").json()
    assert (st["total"], st["new"], events()) == (1, 0, [])
    x = st["items"][0]
    assert x["device"]["id"] == d["tv"] and x["device"]["name"] == "Fernseher" and x["source"] == "FRITZ!Box"
    assert st["sources"][0]["kind"] == "FRITZ!Box"
    # zwischengespeicherte Liste mit neuem Eintrag zählt nicht
    out.update(forwards=fb_list, cached=True)
    integrations.poll(d["fiid"])
    assert cl.get(f"{P}/portforwards").json()["new"] == 0 and events() == []
    # frische Liste: neue UPnP-Freigabe -> Ereignis und „neu“
    out["cached"] = False
    integrations.poll(d["fiid"])
    st = cl.get(f"{P}/portforwards").json()
    assert st["new"] == 1 and st["upnp"] == 1 and st["items"][0]["new"] and st["items"][0]["device"] is None  # neue zuerst, IP unbekannt
    ev = events()
    assert len(ev) == 1 and ev[0]["target"] == "192.168.178.77:51413" and ev[0]["desc"] == "Transmission"
    assert notify.line("port_forward_new", ev[0], "en") == "New port forward: UDP 51413 → 192.168.178.77:51413 Transmission (FRITZ!Box)"
    assert cl.get(f"{P}/dashboard").json()["counts"]["portfw_new"] == 1
    # Gerätedialog zeigt die Freigaben des Geräts
    dev = cl.get(f"{P}/devices/{d['tv']}").json()
    assert [(f["proto"], f["ext"], f["desc"]) for f in dev["forwards"]] == [("TCP", "443", "Nextcloud")]
    # Notiz, Quittieren
    k_new = st["items"][0]["key"]
    st = cl.put(f"{P}/portforwards/note", json={"key": k_new, "note": "Torrent – bewusst"}, headers=H).json()
    assert next(i for i in st["items"] if i["key"] == k_new)["note"] == "Torrent – bewusst"
    assert cl.put(f"{P}/portforwards/note", json={"key": "gibt-es-nicht", "note": "x"}, headers=H).status_code == 400
    st = cl.post(f"{P}/portforwards/ack", json={"keys": [k_new]}, headers=H).json()
    assert st["new"] == 0 and cl.get(f"{P}/dashboard").json()["counts"]["portfw_new"] == 0
    csv = cl.get(f"{P}/portforwards.csv?lang=de").text
    assert "Torrent – bewusst" in csv and "Fernseher" in csv and csv.splitlines()[0].lstrip("﻿").startswith("Neu;Art;Protokoll")
    # Ziel geändert = neue Freigabe (z. B. Port auf ein anderes Gerät umgebogen); die alte verschwindet
    out["forwards"] = [fb_list[0], dict(fb_list[1], ip="192.168.178.50")]
    integrations.poll(d["fiid"])
    st = cl.get(f"{P}/portforwards").json()
    assert st["total"] == 2 and st["new"] == 1 and len(events()) == 2
    # Liste nicht lesbar: Grund erscheint im Reiter, Bekanntes wird nicht verworfen
    out["error"] = fritzbox.PF_ERR["perm"]
    integrations.poll(d["fiid"])
    st = cl.get(f"{P}/portforwards").json()
    assert st["total"] == 0 and st["problems"] == [dict(id=d["fiid"], name="FRITZ!Box", driver="fritzbox", error=fritzbox.PF_ERR["perm"])]
    out.pop("error")
    integrations.poll(d["fiid"])
    assert cl.get(f"{P}/portforwards").json()["new"] == 1 and len(events()) == 2
    # Lesen-Recht: sehen ja, quittieren nein
    from fastapi.testclient import TestClient
    from app import main, users
    with db() as c:
        if not users.by_email(c, "pf-view@x.de"):
            users.create(c, "pf-view@x.de", "passwort123", is_admin=False)
    cl.post(f"{P}/members", json=dict(email="pf-view@x.de", role="view"), headers=H)
    ro = TestClient(main.app)
    ro.post("/api/auth/login", json={"email": "pf-view@x.de", "password": "passwort123"}, headers=H)
    assert ro.get(f"{P}/portforwards").json()["total"] == 2
    assert ro.post(f"{P}/portforwards/ack", json={}, headers=H).status_code == 403
    # Alle quittieren; Integration löschen räumt auf
    assert cl.post(f"{P}/portforwards/ack", json={}, headers=H).json()["new"] == 0
    cl.delete(f"{P}/integrations/{d['fiid']}", headers=H)
    with db() as c:
        pf = json.loads(c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()["settings"])["portfw"]
    assert pf["known"] == {} and pf["notes"] == {} and pf["base"] == []
    assert cl.get(f"{P}/portforwards").json() == dict(items=[], sources=[], problems=[], new=0, upnp=0, total=0)
