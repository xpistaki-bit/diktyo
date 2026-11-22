"""Wachliste: ausgewählte Systeme (z. B. einen Proxmox-Quorum-Knoten) gezielt beobachten.

Ein Gerät auf der Wachliste schlägt Alarm, wenn es offline ist oder seit dem letzten Quittieren ausgefallen war, seine
IP-Adresse, MAC, seinen Namen oder Anschluss gewechselt hat. Quelle sind der Änderungsverlauf (changes) und die
Online-/Offline-Wechsel (status_events); eigene Bearbeitungen in díktyo (Quelle „user“) zählen nicht. Der Alarm bleibt
stehen, bis jemand quittiert (ack_change/ack_status = höchste schon gesehene ID; nur Ereignisse danach zählen). Für Benachrichtigungen schreibt
changes.sync bei Änderungen an beobachteten Geräten ein Ereignis „watch_change“; Ausfälle laufen über device_offline.
"""
import json

from .db import now

FIELDS = ("ips", "mac", "name", "uplink")
LABEL = {"ips": ("IP-Adresse", "IP address"), "mac": ("MAC", "MAC"), "name": ("Name", "Name"), "uplink": ("Anschluss", "Connection")}
MAX_EVENTS = 12
MAX_WATCH = 50


class WatchError(Exception):
    pass


def watched_ids(c, pid):
    return {r["device_id"] for r in c.execute("SELECT device_id FROM watch WHERE profile_id=?", (pid,))}


def is_watched(c, did):
    return c.execute("SELECT 1 FROM watch WHERE device_id=?", (did,)).fetchone() is not None


def add(c, pid, did, note=""):
    if not c.execute("SELECT 1 FROM devices WHERE id=? AND profile_id=?", (did, pid)).fetchone():
        raise WatchError("Gerät nicht gefunden")
    if c.execute("SELECT COUNT(*) FROM watch WHERE profile_id=?", (pid,)).fetchone()[0] >= MAX_WATCH:
        raise WatchError(f"Höchstens {MAX_WATCH} Geräte auf der Wachliste")
    ts = now()
    c.execute("INSERT INTO watch(device_id, profile_id, created, ack, ack_change, ack_status, note) VALUES(?,?,?,?,?,?,?) "
              "ON CONFLICT(device_id) DO UPDATE SET note=excluded.note", (did, pid, ts, ts, *_marks(c), str(note or "").strip()[:200]))


def _marks(c):
    return (c.execute("SELECT COALESCE(MAX(id), 0) FROM changes").fetchone()[0],
            c.execute("SELECT COALESCE(MAX(id), 0) FROM status_events").fetchone()[0])


def remove(c, pid, did):
    c.execute("DELETE FROM watch WHERE device_id=? AND profile_id=?", (did, pid))


def ack(c, pid, did=None):
    """Alarm quittieren – für ein Gerät oder alle. Ein Gerät, das gerade offline ist, bleibt rot, bis es zurück ist."""
    sql = "UPDATE watch SET ack=?, ack_change=?, ack_status=? WHERE profile_id=?"
    c.execute(sql + (" AND device_id=?" if did else ""), (now(), *_marks(c), pid) + ((did,) if did else ()))


def _events(c, did, after_change, after_status):
    out = []
    marks = ",".join("?" * len(FIELDS))
    for r in c.execute(f"""SELECT ts, field, old, new, source FROM changes WHERE device_id=? AND kind='changed' AND id>?
                           AND field IN ({marks}) AND source<>'user' ORDER BY id DESC LIMIT ?""", (did, after_change, *FIELDS, MAX_EVENTS)):
        out.append(dict(ts=r["ts"], kind="changed", field=r["field"], old=r["old"], new=r["new"], source=r["source"]))
    for r in c.execute("SELECT ts, online, source FROM status_events WHERE device_id=? AND id>? ORDER BY id DESC LIMIT ?",
                       (did, after_status, MAX_EVENTS)):
        out.append(dict(ts=r["ts"], kind="online" if r["online"] else "offline", source=r["source"] or ""))
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:MAX_EVENTS]


def state(c, pid, did=None):
    """-> dict(items=[...], alarms=n). state je Gerät: down (gerade offline), changed (Ereignisse seit dem Quittieren), ok."""
    q = """SELECT w.*, d.name, d.type, d.online, d.last_seen FROM watch w JOIN devices d ON d.id=w.device_id
           WHERE w.profile_id=?""" + (" AND w.device_id=?" if did else "")
    items = []
    for r in c.execute(q, (pid, did) if did else (pid,)).fetchall():
        evs = _events(c, r["device_id"], r["ack_change"], r["ack_status"])
        ips = [x["address"] for x in c.execute("SELECT address FROM ip_addresses WHERE device_id=? ORDER BY id", (r["device_id"],))]
        st = "down" if r["online"] == 0 else "changed" if evs else "ok"
        items.append(dict(id=r["device_id"], name=r["name"], type=r["type"], online=r["online"], last_seen=r["last_seen"], ip=ips[0] if ips else "",
                          note=r["note"], since=r["created"], ack=r["ack"], state=st, events=evs))
    order = {"down": 0, "changed": 1, "ok": 2}
    items.sort(key=lambda x: (order[x["state"]], x["name"].lower()))
    return dict(items=items, alarms=sum(1 for x in items if x["state"] != "ok"))


def on_changes(c, pid, did, name, diffs, source):
    """Von changes.sync: Ereignis für Benachrichtigungen, wenn sich ein beobachtetes Gerät geändert hat."""
    if source == "user" or not is_watched(c, did):
        return
    for f, a, b in diffs:
        if f in FIELDS:
            de, en = LABEL[f]
            c.execute("INSERT INTO events(profile_id, ts, kind, device_id, data) VALUES(?,?,?,?,?)",
                      (pid, now(), "watch_change", did, json.dumps(dict(name=name, label_de=de, label_en=en, old=a, new=b), ensure_ascii=False)))
