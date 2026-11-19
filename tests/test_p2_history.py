"""Änderungsverlauf: Schnappschüsse, Quellen, Roaming, Löschen, Zeitleiste, Kurzfassung, CSV."""
import json

from app import changes, integrations
from app.db import db, now
from app.scan import runner
from tests.test_m6 import H, login


def test_history_records_changes_with_source():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Verlauf"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    mk = lambda **kw: cl.post(f"{P}/devices", json={"status": "confirmed", **kw}, headers=H).json()["id"]  # noqa: E731
    sw = mk(name="Switch", type="switch", ports=[{"count": 8, "kind": "rj45", "speed": "1G"}])
    ap1, ap2 = mk(name="AP Flur", type="ap"), mk(name="AP Garten", type="ap")
    nas = mk(name="NAS", type="nas", ips=[{"address": "192.168.1.10"}], mac="11:22:33:44:55:66")
    phone = mk(name="Handy", type="phone", ips=[{"address": "192.168.1.50"}])
    # Bearbeitung von Hand: Name und IP
    d = cl.get(f"{P}/devices/{nas}").json()
    cl.put(f"{P}/devices/{nas}", json={**d, "name": "NAS Keller", "ips": [{"address": "192.168.1.11"}]}, headers=H)
    # Integration: Port-Wechsel des NAS, Roaming des Handys
    with db() as c:
        ports = {r["port_no"]: r["id"] for r in c.execute("SELECT id, port_no FROM interfaces WHERE device_id=? AND role='port'", (sw,))}
        integrations.set_auto_uplink(c, pid, nas, sw, "lan", port_id=ports[3], source="snmp")
        integrations.set_auto_uplink(c, pid, phone, ap1, "wlan", source="asuswrt")
        changes.sync(c, pid, "snmp")
        integrations.set_auto_uplink(c, pid, nas, sw, "lan", port_id=ports[5], source="snmp")
        integrations.set_auto_uplink(c, pid, phone, ap2, "wlan", source="asuswrt")  # Roaming -> nicht erfassen
        changes.sync(c, pid, "snmp")
        runner._set_online(c, nas, 0, now(), "monitor")
    items = cl.get(f"{P}/history?device_id={nas}").json()["items"]
    by = [(x["cat"], x.get("field"), x.get("old"), x.get("new"), x.get("source")) for x in items]
    assert ("change", "name", "NAS", "NAS Keller", "user") in by
    assert ("change", "ips", "192.168.1.10", "192.168.1.11", "user") in by
    assert ("change", "uplink", "Switch · Port 3 (lan)", "Switch · Port 5 (lan)", "snmp") in by
    assert any(x["cat"] == "created" or x.get("kind") == "created" for x in items)
    assert next(x for x in items if x.get("field") == "name")["user"] == "m6@x.de"  # wer hat geändert
    ph = cl.get(f"{P}/history?device_id={phone}").json()["items"]
    uplinks = [x for x in ph if x.get("field") == "uplink"]
    assert len(uplinks) == 1 and uplinks[0]["new"] == "AP Flur (wlan)"  # erster Anschluss ja, Roaming nein
    # Löschen
    cl.delete(f"{P}/devices/{phone}", headers=H)
    all_ = cl.get(f"{P}/history").json()
    dele = [x for x in all_["items"] if x.get("kind") == "deleted"]
    assert dele and dele[0]["device"] == "Handy" and dele[0]["source"] == "user"
    s = all_["summary"]
    assert s["created"] == 5 and s["deleted"] == 1 and s["moved"] >= 1 and s["ip"] == 1 and s["offline"] == 1
    # Filter und Suche
    assert all(x["cat"] == "status" for x in cl.get(f"{P}/history?kinds=status").json()["items"])
    assert {x["device"] for x in cl.get(f"{P}/history?q=Keller").json()["items"]} == {"NAS Keller"}
    csv = cl.get(f"{P}/history.csv").text
    assert csv.startswith("﻿Zeit;Art;Gerät") and "NAS Keller" in csv


def test_first_sync_is_silent_and_ports_from_service_scan():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Verlauf-Alt"}, headers=H).json()["profile"]["id"]
    with db() as c:  # Geräte von vor dem Update (ohne Verlauf)
        did = c.execute("INSERT INTO devices(profile_id, name, type, status, created, updated) VALUES(?,?,?,?,?,?)",
                        (pid, "Altgerät", "server", "confirmed", now(), now())).lastrowid
        st = json.loads(c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()["settings"] or "{}")
        st.pop("history_since", None)
        c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st), pid))
        c.execute("DELETE FROM changes WHERE profile_id=?", (pid,))
        c.execute("DELETE FROM device_snapshots WHERE profile_id=?", (pid,))
        assert changes.sync(c, pid, "") == 0  # still übernommen
        c.execute("UPDATE devices SET name='Server' WHERE id=?", (did,))
        assert changes.sync(c, pid, "") == 1
        changes.record(c, pid, did, "changed", "ports", "22, 443", "22, 23, 443", "nmap", None, dict(opened=[23], closed=[]))
    items = cl.get(f"/api/profiles/{pid}/history").json()["items"]
    assert [x["field"] for x in items if x["cat"] == "change"] == ["ports", "name"]
    assert cl.get(f"/api/profiles/{pid}/history").json()["summary"]["ports"] == 1


def test_history_survives_backup_restore(monkeypatch, tmp_path):
    from app import backup as bk
    from app import db as dbmod
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Verlauf-Backup"}, headers=H).json()["profile"]["id"]
    did = cl.post(f"/api/profiles/{pid}/devices", json={"name": "Drucker", "type": "printer", "status": "confirmed"}, headers=H).json()["id"]
    d = cl.get(f"/api/profiles/{pid}/devices/{did}").json()
    cl.put(f"/api/profiles/{pid}/devices/{did}", json={**d, "name": "Drucker Büro"}, headers=H)
    with db() as c:
        exp = bk.export_data(c)
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "neu.db")
    dbmod.migrate()
    with db() as c:
        bk.restore_all(c, json.loads(json.dumps(exp)), None)
        npid = c.execute("SELECT id FROM profiles WHERE name='Verlauf-Backup'").fetchone()["id"]
        rows = c.execute("SELECT field, old, new FROM changes WHERE profile_id=? AND kind='changed'", (npid,)).fetchall()
        assert ("name", "Drucker", "Drucker Büro") in [tuple(r) for r in rows]
        before = c.execute("SELECT COUNT(*) FROM changes WHERE profile_id=?", (npid,)).fetchone()[0]
        changes.sync(c, npid, "")  # stiller Abgleich nach dem Import
        assert c.execute("SELECT COUNT(*) FROM changes WHERE profile_id=?", (npid,)).fetchone()[0] == before
