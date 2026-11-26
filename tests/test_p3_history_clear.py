"""Verlauf löschen (nur Besitzer, wählbar nach Art und Alter; letzter Online-Stand je Gerät, offene Zurückschaltungen und
aktive Quarantäne bleiben) und Verlauf speichern als CSV mit dem aktuellen Filter."""
import datetime as dt

from app.db import db, now
from tests.test_m6 import H, login


def _ago(days):
    return (dt.datetime.now().astimezone() - dt.timedelta(days=days)).isoformat(timespec="seconds")


def test_history_clear_and_csv():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Verlauf"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    did = cl.post(f"{P}/devices", json=dict(name="NAS", type="nas", status="confirmed"), headers=H).json()["id"]
    with db() as c:
        for days in (100, 40, 1):
            c.execute("INSERT INTO changes(profile_id, device_id, ts, kind, field, old, new, source) VALUES(?,?,?,?,?,?,?,?)",
                      (pid, did, _ago(days), "changed", "name", "alt", f"neu{days}", "user"))
            c.execute("INSERT INTO status_events(device_id, ts, online, source) VALUES(?,?,?,?)", (did, _ago(days), days % 2, "monitor"))
        c.execute("INSERT INTO actions(profile_id, device_id, kind, params, label, status, message, created) VALUES(?,?,?,?,?,?,?,?)",
                  (pid, did, "wlan", "{}", "WLAN aus", "done", "", _ago(50)))
        c.execute("INSERT INTO actions(profile_id, device_id, kind, params, label, status, message, created, undo_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (pid, did, "wlan", "{}", "WLAN aus (zurück später)", "done", "", _ago(50), now()))
        c.execute("INSERT INTO quarantine(profile_id, device_id, ip, mac, name, status, since) VALUES(?,?,?,?,?,?,?)",
                  (pid, did, "192.0.2.5", "AA:BB:CC:00:00:05", "x", "released", _ago(60)))
        c.execute("INSERT INTO quarantine(profile_id, device_id, ip, mac, name, status, since) VALUES(?,?,?,?,?,?,?)",
                  (pid, did, "192.0.2.6", "AA:BB:CC:00:00:06", "y", "active", _ago(60)))
    # CSV mit Filter: nur Änderungen, Suche „neu40“
    r = cl.get(f"{P}/history.csv?days=365&kinds=change&q=neu40")
    assert r.status_code == 200 and "neu40" in r.text and "neu100" not in r.text and "status:" not in r.text
    assert "diktyo-verlauf-" in r.headers["content-disposition"]
    # ungültig: nichts gewählt, Zeitraum
    assert cl.delete(f"{P}/history?kinds=", headers=H).status_code == 400
    assert cl.delete(f"{P}/history?kinds=change&older_than_days=-1", headers=H).status_code == 400
    # älter als 30 Tage: Änderungen und Status
    r = cl.delete(f"{P}/history?kinds=change,status&older_than_days=30", headers=H).json()
    assert r["deleted"] == {"change": 2, "status": 2}
    with db() as c:
        assert sorted(x["new"] for x in c.execute("SELECT new FROM changes WHERE profile_id=?", (pid,))) == ["NAS", "neu1"]  # „NAS“: Anlegen
    # alles: Status behält den letzten Stand, offene Zurückschaltung und aktive Quarantäne bleiben
    r = cl.delete(f"{P}/history?kinds=change,status,action,quarantine", headers=H).json()
    assert r["deleted"] == {"change": 2, "status": 0, "action": 1, "quarantine": 1}
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM status_events WHERE device_id=?", (did,)).fetchone()[0] == 1
        assert [x["label"] for x in c.execute("SELECT label FROM actions WHERE profile_id=?", (pid,))] == ["WLAN aus (zurück später)"]
        assert [x["status"] for x in c.execute("SELECT status FROM quarantine WHERE profile_id=?", (pid,))] == ["active"]
        assert c.execute("SELECT 1 FROM audit_log WHERE action='history.clear' AND profile_id=?", (pid,)).fetchone()
    # nur Besitzer: ein Mitglied mit „Bearbeiten“ darf nicht löschen
    from fastapi.testclient import TestClient
    from app import main, users
    with db() as c:
        if not users.by_email(c, "hc-edit@x.de"):
            users.create(c, "hc-edit@x.de", "passwort123", is_admin=False)
    assert cl.post(f"{P}/members", json=dict(email="hc-edit@x.de", role="edit"), headers=H).status_code == 200
    ed = TestClient(main.app)
    ed.post("/api/auth/login", json={"email": "hc-edit@x.de", "password": "passwort123"}, headers=H)
    assert ed.get(f"{P}/history?days=7").status_code == 200
    assert ed.delete(f"{P}/history?kinds=change", headers=H).status_code == 403
