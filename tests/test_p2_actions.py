"""Schaltaktionen: Angebot je Gerät, Schutzregeln, Sicherung vorher, zweiter Faktor, automatisches Zurückschalten, SNMP-SET."""
import json
import socket
import threading

from app import actions, integrations, users
from app.db import db, now
from app.drivers import fritzbox, snmp, snmplib
from tests.test_m6 import H, login


def _setup(cl, name):
    pid = cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    mk = lambda **kw: cl.post(f"{P}/devices", json={"status": "confirmed", **kw}, headers=H).json()["id"]  # noqa: E731
    fb = mk(name="FRITZ!Box", type="router", ips=[{"address": "192.168.178.1"}], mac="AA:AA:AA:AA:AA:01")
    sw = mk(name="Switch", type="switch", ips=[{"address": "192.168.178.20"}], ports=[{"count": 8, "kind": "rj45", "speed": "1G"}])
    tv = mk(name="Fernseher", type="tv", ips=[{"address": "192.168.178.50"}], mac="BB:BB:BB:BB:BB:50")
    with db() as c:
        sw_ports = {r["port_no"]: r["id"] for r in c.execute("SELECT id, port_no FROM interfaces WHERE device_id=? AND role='port'", (sw,))}
        integrations.set_auto_uplink(c, pid, tv, sw, "lan", port_id=sw_ports[5])
        integrations.set_auto_uplink(c, pid, sw, fb, "lan", local_port_id=sw_ports[1])
        fstate = {"result": {"wlan": [dict(index=1, ssid="Zuhause", channel=6, enabled=True), dict(index=3, ssid="Gäste", channel=36, enabled=False)]}}
        fiid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, username, secret, options, device_id, state, created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (pid, "fritzbox", "FRITZ!Box", "192.168.178.1", "diktyo", integrations.security.encrypt(json.dumps({"password": "pw"})),
                          json.dumps({"cfg_schedule": "weekly"}), fb, json.dumps(fstate), now())).lastrowid
        ports = [dict(port_no=n, ifindex=100 + n, name=f"Port{n}", oper="up", admin="up", poe=(n == 5), macs=[]) for n in range(1, 9)]
        ports[0]["macs"] = ["AA:AA:AA:AA:AA:01"]  # Router hängt an Port 1
        siid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, secret, options, device_id, state, created) VALUES(?,?,?,?,?,?,?,?,?)",
                         (pid, "snmp", "Switch", "192.168.178.20", "", json.dumps({"cfg_schedule": "no"}), sw,
                          json.dumps({"result": {"ports": ports}}), now())).lastrowid
    return pid, P, dict(fb=fb, sw=sw, tv=tv, fiid=fiid, siid=siid)


def test_offer_and_protection(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: ({"192.168.178.50"} - {"192.168.178.50"} | {"192.168.50.223"}, set()))
    cl = login()
    pid, P, d = _setup(cl, "Aktionen-Angebot")
    fb = {a["label"]: a for a in cl.get(f"{P}/devices/{d['fb']}/actions").json()["actions"]}
    assert "WLAN „Zuhause“ (2,4 GHz) ausschalten" in fb and "WLAN „Gäste“ (5 GHz) einschalten" in fb and "FRITZ!Box neu starten" in fb
    assert fb["WLAN „Zuhause“ (2,4 GHz) ausschalten"]["undo"] and not fb["FRITZ!Box neu starten"]["undo"]
    tv = {a["label"]: a for a in cl.get(f"{P}/devices/{d['tv']}/actions").json()["actions"]}
    assert {"Internetzugang sperren", "Internetzugang freigeben", "Aufwecken (Wake-on-LAN)", "Switch-Port 5 abschalten", "PoE an Port 5 neu starten"} <= set(tv)
    assert not tv["Internetzugang sperren"]["blocked"] and not tv["Switch-Port 5 abschalten"]["blocked"]
    # Infrastruktur nicht sperren; Port zum Router nicht abschalten
    sw = {a["label"]: a for a in cl.get(f"{P}/devices/{d['sw']}/actions").json()["actions"]}
    assert "Internetzugang sperren" not in sw  # Infrastruktur wird nicht gesperrt
    p1 = {a["label"]: a for a in cl.get(f"{P}/devices/{d['sw']}/actions?port=1").json()["actions"]}
    assert set(p1) == {"Switch-Port 1 abschalten"}
    assert "aussperren" in p1["Switch-Port 1 abschalten"]["blocked"]
    r = cl.post(f"{P}/devices/{d['sw']}/actions", json={"key": p1["Switch-Port 1 abschalten"]["key"], "port": 1}, headers=H)
    assert r.status_code == 400 and "aussperren" in r.json()["error"]
    # erfundene Aktion wird abgelehnt
    r = cl.post(f"{P}/devices/{d['tv']}/actions", json={"key": 'port:1:{"ifindex": 101, "port_no": 1, "up": false}'}, headers=H)
    assert r.status_code == 400 and "nicht (mehr) verfügbar" in r.json()["error"]
    # Bearbeiter (nicht Besitzer) sehen nichts und dürfen nichts
    with db() as c:
        u = users.create(c, "bearbeiter-akt@x.de", "passwort123")
        c.execute("INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?, 'edit')", (pid, u["id"] if isinstance(u, dict) else u))
    cl2 = login("bearbeiter-akt@x.de")
    assert cl2.get(f"{P}/devices/{d['tv']}/actions").json() == {"actions": [], "allowed": False}
    assert cl2.post(f"{P}/devices/{d['tv']}/actions", json={"key": tv["Internetzugang sperren"]["key"]}, headers=H).status_code == 403


def test_wlan_off_with_backup_2fa_and_undo(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    calls, backups = [], []
    need_2fa = {"on": True}

    def fake_action(conf, state, kind, params):
        token = state.pop("sf_token", None)
        if need_2fa["on"] and not token:
            raise fritzbox.SecondFactorRequired("866")
        calls.append((kind, params, token))
        return "ok"
    monkeypatch.setattr(fritzbox, "action", fake_action)
    monkeypatch.setattr(fritzbox, "second_factor_start", lambda conf, state: state.update(sf_token="TOK") or dict(state="waitingforauth", button=True, dtmf=""))
    monkeypatch.setattr(fritzbox, "backup", lambda conf, state: backups.append(1) or ("FRITZ.export", b"cfg", True))
    cl = login()
    pid, P, d = _setup(cl, "Aktionen-WLAN")
    a = next(x for x in cl.get(f"{P}/devices/{d['fb']}/actions").json()["actions"] if x["label"].startswith("WLAN „Zuhause“"))
    r = cl.post(f"{P}/devices/{d['fb']}/actions", json={"key": a["key"], "undo": "15"}, headers=H).json()
    assert r["status"] == "second_factor" and r["backup"] == "Konfiguration vorher gesichert." and len(backups) == 1
    # nach der Bestätigung erneut: mit Token, ohne zweite Sicherung
    r = cl.post(f"{P}/devices/{d['fb']}/actions", json={"key": a["key"], "undo": "15"}, headers=H).json()
    assert r["status"] == "done" and calls[-1] == ("wlan", {"index": 1, "on": False, "ssid": "Zuhause"}, "TOK") and len(backups) == 1
    assert r["undo_at"]
    hist = cl.get(f"{P}/actions").json()["actions"]
    assert hist[0]["label"].startswith("WLAN „Zuhause“") and hist[0]["status"] == "done" and hist[0]["undo_at"]
    # Zeit abgelaufen: Hintergrunddienst schaltet zurück (ohne zweiten Faktor möglich)
    need_2fa["on"] = False
    with db() as c:
        c.execute("UPDATE actions SET undo_at='2000-01-01T00:00:00+00:00' WHERE id=?", (r["id"],))
    actions.run_due_undos(lambda *a: None)
    assert calls[-1][:2] == ("wlan", {"index": 1, "on": True, "ssid": "Zuhause"})
    hist = cl.get(f"{P}/actions").json()["actions"]
    assert hist[0]["label"].startswith("Automatisch zurück") and hist[1]["undone"] and hist[1]["undo_result"].startswith("done")
    # geplantes Zurückschalten lässt sich abbrechen
    r2 = cl.post(f"{P}/devices/{d['fb']}/actions", json={"key": a["key"], "undo": "60"}, headers=H).json()
    assert cl.delete(f"{P}/actions/{r2['id']}/undo", headers=H).json()["ok"]


def test_undo_needing_2fa_reports_event(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    monkeypatch.setattr(fritzbox, "backup", lambda conf, state: ("FRITZ.export", b"cfg", True))
    cl = login()
    pid, P, d = _setup(cl, "Aktionen-Undo-2FA")
    monkeypatch.setattr(fritzbox, "action", lambda conf, state, kind, params: "ok")
    a = next(x for x in cl.get(f"{P}/devices/{d['tv']}/actions").json()["actions"] if x["label"] == "Internetzugang sperren")
    r = cl.post(f"{P}/devices/{d['tv']}/actions", json={"key": a["key"], "undo": "morning"}, headers=H).json()
    assert r["status"] == "done" and "T06:00:00" in r["undo_at"]
    monkeypatch.setattr(fritzbox, "action", lambda conf, state, kind, params: (_ for _ in ()).throw(fritzbox.SecondFactorRequired("866")))
    with db() as c:
        c.execute("UPDATE actions SET undo_at='2000-01-01T00:00:00+00:00' WHERE id=?", (r["id"],))
    actions.run_due_undos(lambda *a: None)
    with db() as c:
        ev = c.execute("SELECT * FROM events WHERE profile_id=? AND kind='action_undo_failed'", (pid,)).fetchone()
    assert ev and "Internetzugang sperren" in ev["data"]


def test_switch_port_action(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    seen = []
    monkeypatch.setattr(snmp, "action", lambda conf, state, kind, params: seen.append((kind, params)) or "Port 5 abgeschaltet")
    cl = login()
    pid, P, d = _setup(cl, "Aktionen-Port")
    a = next(x for x in cl.get(f"{P}/devices/{d['tv']}/actions").json()["actions"] if x["label"] == "Switch-Port 5 abschalten")
    r = cl.post(f"{P}/devices/{d['tv']}/actions", json={"key": a["key"]}, headers=H).json()
    assert r["status"] == "done" and seen == [("port", {"port_no": 5, "ifindex": 105, "up": False})] and r["backup"] == ""


def test_snmp_v2c_set_on_wire():
    """SET-PDU mit INTEGER-Wert gegen einen kleinen v2c-Agenten."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    got = {}

    def agent():
        data, addr = sock.recvfrom(65535)
        _, msg, _ = snmplib._read(data, 0)
        i = 0
        _, _, i = snmplib._read(msg, i)
        _, comm, i = snmplib._read(msg, i)
        tag, _, _ = snmplib._read(msg, i)
        rid, _, vbs = snmplib._parse(data)
        got.update(tag=tag, community=bytes(comm), vbs=vbs)
        sock.sendto(snmplib._message("rw", snmplib.RESPONSE, [vbs[0][0]], rid, values=[vbs[0][2]]), addr)
    threading.Thread(target=agent, daemon=True).start()
    snmplib.Client("127.0.0.1", "rw", port=sock.getsockname()[1]).set_int("1.3.6.1.2.1.2.2.1.7.105", 2)
    assert got["tag"] == snmplib.SET and got["community"] == b"rw" and got["vbs"] == [("1.3.6.1.2.1.2.2.1.7.105", snmplib.INT, 2)]


def test_lockout_protection_via_nat_router(monkeypatch):
    """díktyo im ASUS-Netz (192.168.50.x), ASUS hängt an Switch-Port 2: Port 2 darf nicht abgeschaltet werden."""
    from app.scan import netinfo
    monkeypatch.setattr(netinfo, "interfaces", lambda: [dict(ifname="eth0", ip="192.168.50.223", prefix=24, cidr="192.168.50.0/24")])
    monkeypatch.setattr(netinfo, "default_gateway", lambda: "192.168.50.1")
    monkeypatch.setattr(actions, "_own_addresses", lambda: ({"192.168.50.223"}, {"DE:AD:00:00:00:01"}))
    cl = login()
    pid, P, d = _setup(cl, "Aktionen-NAT")
    asus = cl.post(f"{P}/devices", json={"name": "ASUS EBM68", "type": "mesh", "status": "confirmed",
                                          "ips": [{"address": "192.168.50.1"}, {"address": "192.168.178.3"}]}, headers=H).json()["id"]
    with db() as c:
        p2 = c.execute("SELECT id FROM interfaces WHERE device_id=? AND role='port' AND port_no=2", (d["sw"],)).fetchone()["id"]
        integrations.set_auto_uplink(c, pid, asus, d["sw"], "lan", port_id=p2)
    a = {x["label"]: x for x in cl.get(f"{P}/devices/{asus}/actions").json()["actions"]}
    assert "aussperren" in a["Switch-Port 2 abschalten"]["blocked"]
    # Fernseher an Port 5 bleibt schaltbar; Port-Auswahl am Switch liefert alle Ports
    tv = {x["label"]: x for x in cl.get(f"{P}/devices/{d['tv']}/actions").json()["actions"]}
    assert not tv["Switch-Port 5 abschalten"]["blocked"]
    r = cl.get(f"{P}/devices/{d['sw']}/actions").json()
    assert [p["port_no"] for p in r["ports"]] == list(range(1, 9)) and r["ports"][4]["poe"] is True


def test_proxmox_host_lists_guests(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: ({"192.168.50.223"}, set()))
    cl = login()
    pid, P, d = _setup(cl, "Aktionen-PVE")
    mk = lambda **kw: cl.post(f"{P}/devices", json={"status": "confirmed", **kw}, headers=H).json()["id"]  # noqa: E731
    host = mk(name="pve", type="hypervisor")
    vm = mk(name="HomeAssistant", type="vm", ips=[{"address": "192.168.50.9"}])
    me = mk(name="diktyo", type="container", ips=[{"address": "192.168.50.223"}])
    with db() as c:
        for did, meta in ((host, {"node": "pve"}), (vm, {"node": "pve", "vmid": 100, "kind": "qemu"}), (me, {"node": "pve", "vmid": 103, "kind": "lxc"})):
            c.execute("UPDATE devices SET data=?, online=1 WHERE id=?", (json.dumps({"proxmox": meta}), did))
        c.execute("INSERT INTO integrations(profile_id, driver, name, host, secret, options, device_id, created) VALUES(?,?,?,?,?,?,?,?)",
                  (pid, "proxmox", "Proxmox", "192.0.2.12", "", "{}", host, now()))
    acts = {x["label"]: x for x in cl.get(f"{P}/devices/{host}/actions").json()["actions"]}
    assert not acts["„HomeAssistant“ herunterfahren"]["blocked"] and "díktyo läuft" in acts["„diktyo“ herunterfahren"]["blocked"]
    vm_acts = {x["label"] for x in cl.get(f"{P}/devices/{vm}/actions").json()["actions"]}
    assert vm_acts == {"Herunterfahren", "Neu starten"}
