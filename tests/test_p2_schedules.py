"""Zeitpläne für Aktionen und Quarantäne für neue Geräte (FRITZ!Box-Aktionen nachgebildet)."""
import datetime as dt
import json

from app import actions, quarantine, schedules
from app.db import db, now
from app.drivers import fritzbox
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup

TZ = dt.datetime.now().astimezone().tzinfo


def at(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi, tzinfo=TZ)


def test_transitions_overnight_and_weekdays():
    s = {"days": "0,1,2,3,4", "start": "22:00", "end_time": "06:30"}  # Mo–Fr 22:00–06:30
    # Freitag 21:59 -> Samstag 07:00: Start Fr 22:00, Ende Sa 06:30 (gehört zum Freitag)
    ev = schedules.transitions(s, at(2026, 11, 20, 21, 59), at(2026, 11, 21, 7, 0))
    assert ev == [(at(2026, 11, 20, 22, 0), "start"), (at(2026, 11, 21, 6, 30), "end")]
    # Samstag 21:00 -> Sonntag 23:00: nichts
    assert schedules.transitions(s, at(2026, 11, 21, 21, 0), at(2026, 11, 22, 23, 0)) == []
    # Einmal-Aktion ohne Ende
    assert schedules.transitions({"days": "6", "start": "04:00", "end_time": None}, at(2026, 11, 22, 3, 0), at(2026, 11, 22, 5, 0)) == [
        (at(2026, 11, 22, 4, 0), "start")]


def test_schedule_runs_at_transitions_only(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    calls = []
    monkeypatch.setattr(fritzbox, "action", lambda conf, state, kind, params: calls.append((kind, dict(params))) or "ok")
    cl = login()
    pid, P, d = _setup(cl, "Zeitplan")
    a = next(x for x in cl.get(f"{P}/devices/{d['tv']}/actions").json()["actions"] if x["label"] == "Internetzugang sperren")
    r = cl.post(f"{P}/devices/{d['tv']}/schedules", json={"key": a["key"], "days": [0, 1, 2, 3, 4], "start": "22:00", "end": "6:30"}, headers=H)
    s = r.json()
    assert r.status_code == 200 and s["start"] == "22:00" and s["end"] == "06:30" and s["next_run"]
    with db() as c:
        c.execute("UPDATE schedules SET last_check=? WHERE id=?", (at(2026, 11, 20, 21, 0).isoformat(), s["id"]))  # Freitag
    schedules.run_due(lambda *x: None, t=at(2026, 11, 20, 22, 1))
    assert calls == [("internet", {"ip": "192.168.178.50", "block": True})]
    # zwischendurch: kein erneutes Schalten (manuelle Freigabe würde nicht überstimmt)
    schedules.run_due(lambda *x: None, t=at(2026, 11, 20, 23, 30))
    assert len(calls) == 1
    # IP geändert -> Ende gibt die aktuelle IP frei
    with db() as c:
        c.execute("UPDATE ip_addresses SET address='192.168.178.77' WHERE device_id=?", (d["tv"],))
    schedules.run_due(lambda *x: None, t=at(2026, 11, 21, 6, 31))
    assert calls[-1] == ("internet", {"ip": "192.168.178.77", "block": False})
    hist = cl.get(f"{P}/actions").json()["actions"]
    assert hist[0]["label"].startswith("Zeitplan: Ende: Internetzugang sperren")
    lst = cl.get(f"{P}/schedules?device_id={d['tv']}").json()["schedules"]
    assert lst[0]["last_result"].startswith("end: done")
    # ausschalten, löschen
    assert cl.put(f"{P}/schedules/{s['id']}", json={"enabled": False}, headers=H).json()["enabled"] is False
    assert cl.delete(f"{P}/schedules/{s['id']}", headers=H).json()["ok"]


def test_schedule_respects_lockout_protection(monkeypatch):
    """Ein Port-Zeitplan schaltet nicht, wenn der Port inzwischen der Verwaltungsweg ist."""
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    from app.drivers import snmp
    seen = []
    monkeypatch.setattr(snmp, "action", lambda conf, state, kind, params: seen.append(params) or "ok")
    cl = login()
    pid, P, d = _setup(cl, "Zeitplan-Schutz")
    a = next(x for x in cl.get(f"{P}/devices/{d['tv']}/actions").json()["actions"] if x["label"] == "Switch-Port 5 abschalten")
    s = cl.post(f"{P}/devices/{d['tv']}/schedules", json={"key": a["key"], "days": list(range(7)), "start": "01:00", "end": "05:00"}, headers=H).json()
    # Jetzt hängt plötzlich der Router an Port 5 -> geschützt
    with db() as c:
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (d["siid"],)).fetchone()["state"])
        st["result"]["ports"][4]["macs"] = ["AA:AA:AA:AA:AA:01"]
        c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st), d["siid"]))
        c.execute("UPDATE schedules SET last_check=? WHERE id=?", (at(2026, 11, 20, 0, 0).isoformat(), s["id"]))
    schedules.run_due(lambda *x: None, t=at(2026, 11, 20, 1, 5))
    assert seen == []
    with db() as c:
        assert "aussperren" in c.execute("SELECT last_result FROM schedules WHERE id=?", (s["id"],)).fetchone()["last_result"]
        assert c.execute("SELECT 1 FROM events WHERE profile_id=? AND kind='schedule_failed'", (pid,)).fetchone()


def test_quarantine_flow(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: ({"192.168.178.2"}, set()))
    calls = []
    monkeypatch.setattr(fritzbox, "action", lambda conf, state, kind, params: calls.append(dict(params)) or "ok")
    cl = login()
    pid, P, d = _setup(cl, "Quarantäne")
    # schon vorhandenes Gerät im Posteingang bleibt unberührt
    old = cl.post(f"{P}/devices", json={"name": "alt", "type": "other", "status": "discovered", "ips": [{"address": "192.168.178.60"}]}, headers=H).json()["id"]
    assert cl.put(f"{P}/quarantine", json={"enabled": True}, headers=H).json()["enabled"] is True
    q = cl.get(f"{P}/quarantine").json()
    assert q["available"] and q["settings"]["since"]
    mk = lambda name, ip, typ="phone", mac="": cl.post(f"{P}/devices", json={"name": name, "type": typ, "status": "discovered",  # noqa: E731
                                                                              "ips": [{"address": ip}], "mac": mac}, headers=H).json()["id"]
    new = mk("Neues Handy", "192.168.178.61", mac="12:34:56:78:9A:BC")
    gast = mk("Gast", "192.168.179.20")             # Gastnetz der FRITZ!Box
    ap = mk("Neuer AP", "192.168.178.62", typ="ap")  # Infrastruktur
    me = mk("díktyo", "192.168.178.2")              # díktyo selbst
    quarantine.process(pid, lambda *x: None)
    assert calls == [{"ip": "192.168.178.61", "block": True}]
    lst = cl.get(f"{P}/quarantine").json()["devices"]
    assert [(x["device"], x["status"]) for x in lst] == [("Neues Handy", "active")]
    with db() as c:
        assert c.execute("SELECT 1 FROM events WHERE profile_id=? AND kind='quarantined'", (pid,)).fetchone()
    # zweiter Lauf: nichts doppelt
    quarantine.process(pid, lambda *x: None)
    assert len(calls) == 1
    # IP-Wechsel: neue sperren, alte freigeben
    with db() as c:
        c.execute("UPDATE ip_addresses SET address='192.168.178.63' WHERE device_id=?", (new,))
    quarantine.process(pid, lambda *x: None)
    assert calls[-2:] == [{"ip": "192.168.178.63", "block": True}, {"ip": "192.168.178.61", "block": False}]
    # übernehmen -> freigeben
    cl.post(f"{P}/inbox", json={"action": "confirm", "ids": [new]}, headers=H)
    quarantine.process(pid, lambda *x: None)
    assert calls[-1] == {"ip": "192.168.178.63", "block": False}
    assert cl.get(f"{P}/quarantine").json()["devices"][0]["status"] == "released"
    # weiteres Gerät: von Hand freigeben, danach nicht wieder gesperrt
    other = mk("Laptop", "192.168.178.70")
    quarantine.process(pid, lambda *x: None)
    qid = next(x["id"] for x in cl.get(f"{P}/quarantine").json()["devices"] if x["device"] == "Laptop")
    assert cl.post(f"{P}/quarantine/{qid}/release", headers=H).json()["status"] == "done"
    n = len(calls)
    quarantine.process(pid, lambda *x: None)
    assert len(calls) == n
    # gelöschtes Gerät in Quarantäne -> freigeben
    third = mk("Tablet", "192.168.178.71")
    quarantine.process(pid, lambda *x: None)
    cl.post(f"{P}/inbox", json={"action": "delete", "ids": [third]}, headers=H)
    quarantine.process(pid, lambda *x: None)
    assert calls[-1] == {"ip": "192.168.178.71", "block": False}
    assert old and gast and ap and me and other
