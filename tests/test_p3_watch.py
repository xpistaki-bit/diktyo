"""Wachliste: beobachten, Alarm bei Ausfall und IP-Wechsel, Quittieren, eigene Bearbeitungen zählen nicht, Benachrichtigung."""
from app import changes, notify
from app.db import db, now
from app.scan import runner
from tests.test_m6 import H, login
from tests.test_p3_notify import Sent


def test_watchlist(monkeypatch):
    sent = Sent(monkeypatch)
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Wachliste"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    mk = lambda **kw: cl.post(f"{P}/devices", json={"status": "confirmed", **kw}, headers=H).json()["id"]  # noqa: E731
    pve = mk(name="pve-quorum", type="hypervisor", ips=[{"address": "192.0.2.30"}])
    tv = mk(name="Fernseher", type="tv", ips=[{"address": "192.0.2.50"}])
    with db() as c:
        changes.sync(c, pid, "scan")
        runner._set_online(c, pve, 1, now())
        runner._set_online(c, tv, 1, now())
    assert cl.get(f"{P}/watch").json() == {"items": [], "alarms": 0}
    assert cl.put(f"{P}/devices/99999/watch", json={"watch": True}, headers=H).status_code == 400
    r = cl.put(f"{P}/devices/{pve}/watch", json={"watch": True, "note": "Quorum-Knoten"}, headers=H).json()
    assert [(x["name"], x["state"], x["ip"], x["note"]) for x in r["items"]] == [("pve-quorum", "ok", "192.0.2.30", "Quorum-Knoten")]
    assert "watch" in [x["id"] for x in cl.get(f"{P}/dashboard/layout").json()["items"]]
    cl.put(f"{P}/notify", json=dict(ntfy=True, ntfy_url="https://ntfy.example.com", ntfy_topic="t", kinds=["watch_change"]), headers=H)
    # eigene Bearbeitung in díktyo: kein Alarm
    cl.put(f"{P}/devices/{pve}", json={"name": "pve-quorum", "type": "hypervisor", "status": "confirmed", "notes": "neu"}, headers=H)
    assert cl.get(f"{P}/watch").json()["alarms"] == 0
    # IP-Wechsel durch eine Integration und Ausfall: Alarm
    with db() as c:
        c.execute("UPDATE ip_addresses SET address='192.0.2.31' WHERE device_id=?", (pve,))
        c.execute("UPDATE ip_addresses SET address='192.0.2.51' WHERE device_id=?", (tv,))  # nicht beobachtet
        changes.sync(c, pid, "proxmox")
    w = cl.get(f"{P}/dashboard").json()["watch"]
    assert w["alarms"] == 1 and w["items"][0]["state"] == "changed"
    ev = w["items"][0]["events"][0]
    assert (ev["field"], ev["old"], ev["new"]) == ("ips", "192.0.2.30", "192.0.2.31")
    with db() as c:
        runner._set_online(c, pve, 0, now())
        runner._set_online(c, tv, 0, now())
    w = cl.get(f"{P}/watch").json()
    assert w["items"][0]["state"] == "down" and "offline" in [e["kind"] for e in w["items"][0]["events"]]
    # Benachrichtigung: IP-Wechsel und Ausfall des beobachteten Geräts, obwohl „Gerät offline“ nicht gewählt ist; der Fernseher nicht
    assert notify.deliver(pid, log=lambda *a: None, force=True) == 2
    text = sent.ntfy[-1]["json"]["message"]
    assert "Wachliste: pve-quorum – IP-Adresse 192.0.2.30 → 192.0.2.31" in text and "pve-quorum ist offline" in text and "Fernseher" not in text
    # Quittieren: offline bleibt rot, bis es zurück ist; danach ruhig
    assert cl.post(f"{P}/watch/ack", json={}, headers=H).json()["items"][0]["state"] == "down"
    with db() as c:
        runner._set_online(c, pve, 1, now())
    assert cl.get(f"{P}/watch").json()["items"][0]["state"] == "changed"
    assert cl.post(f"{P}/watch/ack", json={"device_id": pve}, headers=H).json()["alarms"] == 0
    # Lesende sehen die Wachliste, dürfen aber nichts ändern
    with db() as c:
        from app import users
        if not users.by_email(c, "leser@x.de"):
            users.create(c, "leser@x.de", "passwort123")
        uid = users.by_email(c, "leser@x.de")["id"]
        c.execute("INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?,'view')", (pid, uid))
    rd = login("leser@x.de")
    assert rd.get(f"{P}/watch").status_code == 200
    assert rd.post(f"{P}/watch/ack", json={}, headers=H).status_code == 403
    assert rd.put(f"{P}/devices/{pve}/watch", json={"watch": False}, headers=H).status_code == 403
    # entfernen
    assert cl.put(f"{P}/devices/{pve}/watch", json={"watch": False}, headers=H).json()["items"] == []


def test_old_notify_settings_get_watch():
    s = notify.settings({"settings": '{"notify": {"ntfy": true, "kinds": ["device_offline"]}}'})
    assert s["kinds"] == ["device_offline", "watch_change"]
    s = notify.settings({"settings": '{"notify": {"ntfy": true, "kinds": ["device_offline"], "seen_watch": true}}'})
    assert s["kinds"] == ["device_offline"]


def test_new_builtin_lands_behind_predecessor():
    from app import dashlayout
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Altes Layout"}, headers=H).json()["profile"]["id"]
    old = [{"id": k, "size": s} for k, s in dashlayout.BUILTINS if k != "watch"][::-1]  # vor 0.27 gespeichert, umsortiert
    cl.put(f"/api/profiles/{pid}/dashboard/layout", json={"items": old}, headers=H)
    with db() as c:
        import json
        st = json.loads(c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()["settings"])
        st["dashboard"]["items"] = [x for x in st["dashboard"]["items"] if x["id"] != "watch"]
        c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st), pid))
        ids = [x["id"] for x in dashlayout.get(c, pid)["items"]]
    assert ids.index("watch") == ids.index("issues") + 1
