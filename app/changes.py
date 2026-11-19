"""Änderungsverlauf: Was hat sich wann an welchem Gerät geändert – und wodurch?

Erfasst wird über Schnappschüsse: je Gerät der Stand von Name, Typ, Status, Hersteller/Modell, Standort, IP-Adressen,
MAC und Anschluss. sync() vergleicht mit dem letzten Stand und schreibt die Unterschiede mit Quelle (user, scan,
fritzbox, snmp, …) in die Tabelle changes. Aufgerufen wird es nach Bearbeitungen (auth.touch), nach jedem Scan und
jeder Integrationsabfrage; der Hintergrunddienst gleicht zusätzlich regelmäßig ab.

Roaming zwischen WLAN-/Mesh-Zugangspunkten wird nicht erfasst (sonst würde jedes Handy den Verlauf fluten).
Die Zeitleiste (timeline) mischt dazu Online/Offline, Aktionen, neue Konfigurationsstände, Quarantäne und Ports aus
dem Dienste-Scan.
"""
import datetime as dt
import json

from .db import now, parse_ts

FIELDS = ("name", "type", "status", "model", "location", "ips", "mac", "uplink")
KEEP_DAYS = 365
ROAMING = ("wlan", "mesh")


def snapshot(d):
    up = d.get("uplink") or {}
    model = " ".join(x for x in (d.get("manufacturer"), d.get("model")) if x)
    return dict(name=d["name"], type=d["type"], status=d["status"], model=model, location=d.get("location") or "",
                ips=sorted(x["address"] for x in d.get("ips") or []), mac=d.get("mac") or "",
                uplink=dict(device=up.get("device_name") or "", device_id=up.get("device_id"), port=up.get("port_name") or "",
                            medium=up.get("medium") or "") if up else None)


def _uplink_text(u):
    if not u:
        return "–"
    return f"{u['device']}{' · Port ' + u['port'] if u.get('port') else ''} ({u['medium']})"


def _diff(old, new):
    """-> [(feld, alt, neu)] als Text"""
    out = []
    for f in FIELDS:
        a, b = old.get(f), new.get(f)
        if f == "uplink":
            if (a or {}).get("device_id") == (b or {}).get("device_id") and (a or {}).get("port") == (b or {}).get("port") \
                    and (a or {}).get("medium") == (b or {}).get("medium"):
                continue
            if a and b and a.get("medium") in ROAMING and b.get("medium") in ROAMING:
                continue  # Roaming zwischen Zugangspunkten
            out.append((f, _uplink_text(a), _uplink_text(b)))
        elif f == "ips":
            a, b = a or [], b or []
            if a != b:
                out.append((f, ", ".join(a) or "–", ", ".join(b) or "–"))
        elif (a or "") != (b or ""):
            out.append((f, a or "–", b or "–"))
    return out


def record(c, pid, did, kind, field="", old="", new="", source="", user_id=None, detail=None):
    c.execute("""INSERT INTO changes(profile_id, device_id, ts, kind, field, old, new, source, user_id, detail)
                 VALUES(?,?,?,?,?,?,?,?,?,?)""", (pid, did, now(), kind, field, str(old)[:300], str(new)[:300], source, user_id,
                                                  json.dumps(detail or {}, ensure_ascii=False)))


def sync(c, pid, source="", user_id=None):
    """Aktuellen Stand mit den Schnappschüssen vergleichen und Unterschiede eintragen. -> Anzahl Änderungen"""
    from .inventory import list_devices
    devs = {d["id"]: d for d in list_devices(c, pid)}
    snaps = {r["device_id"]: json.loads(r["data"]) for r in c.execute("SELECT * FROM device_snapshots WHERE profile_id=?", (pid,))}
    prow = c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()
    if not prow:
        return 0
    pset = json.loads(prow["settings"] or "{}")
    baseline = bool(pset.get("history_since"))  # erster Abgleich (z. B. nach dem Update): Stand still übernehmen
    if not baseline:
        pset["history_since"] = now()
        c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(pset, ensure_ascii=False), pid))
    n = 0
    for did, d in devs.items():
        snap = snapshot(d)
        old = snaps.get(did)
        if old is None:
            if baseline:  # erster Stand eines Profils wird still übernommen
                record(c, pid, did, "created", "", "", d["name"], source, user_id,
                       dict(ip=(snap["ips"] or [""])[0], mac=snap["mac"], status=snap["status"]))
                n += 1
            c.execute("INSERT INTO device_snapshots(device_id, profile_id, data) VALUES(?,?,?)", (did, pid, json.dumps(snap, ensure_ascii=False)))
            continue
        diffs = _diff(old, snap)
        for f, a, b in diffs:
            record(c, pid, did, "changed", f, a, b, source, user_id)
            n += 1
        if diffs or old != snap:
            c.execute("UPDATE device_snapshots SET data=? WHERE device_id=?", (json.dumps(snap, ensure_ascii=False), did))
    for did, old in snaps.items():
        if did not in devs:
            record(c, pid, None, "deleted", "", old.get("name", ""), "", source, user_id,
                   dict(name=old.get("name"), ip=(old.get("ips") or [""])[0], mac=old.get("mac", ""), device_id=did))
            c.execute("DELETE FROM device_snapshots WHERE device_id=?", (did,))
            n += 1
    return n


def prune(c):
    cut = (dt.datetime.now().astimezone() - dt.timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    c.execute("DELETE FROM changes WHERE ts<?", (cut,))


def timeline(c, pid, did=None, since=None, kinds=None, q="", limit=300):
    """Gemischte Zeitleiste, neueste zuerst. kinds: Teilmenge von change, status, action, config, quarantine."""
    since = since or (dt.datetime.now().astimezone() - dt.timedelta(days=7)).isoformat(timespec="seconds")
    kinds = set(kinds or ("change", "status", "action", "config", "quarantine"))
    names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM devices WHERE profile_id=?", (pid,))}
    users = {r["id"]: r["email"] for r in c.execute("SELECT id, email FROM users")}
    dev = " AND device_id=?" if did else ""
    args = (pid, since) + ((did,) if did else ())
    out = []
    if "change" in kinds:
        for r in c.execute(f"SELECT * FROM changes WHERE profile_id=? AND ts>=?{dev} ORDER BY id DESC LIMIT ?", args + (limit,)):
            det = json.loads(r["detail"] or "{}")
            out.append(dict(ts=r["ts"], cat="change", kind=r["kind"], field=r["field"], old=r["old"], new=r["new"], source=r["source"],
                            user=users.get(r["user_id"], ""), device_id=r["device_id"], device=names.get(r["device_id"]) or det.get("name") or r["old"],
                            detail=det))
    if "status" in kinds:
        q2 = f"""SELECT s.*, d.name FROM status_events s JOIN devices d ON d.id=s.device_id WHERE d.profile_id=? AND s.ts>=?
                 {'AND s.device_id=?' if did else ''} ORDER BY s.id DESC LIMIT ?"""
        for r in c.execute(q2, args + (limit,)):
            out.append(dict(ts=r["ts"], cat="status", kind="online" if r["online"] else "offline", source=r["source"] or "", device_id=r["device_id"],
                            device=r["name"]))
    if "action" in kinds:
        for r in c.execute(f"SELECT * FROM actions WHERE profile_id=? AND created>=?{dev} ORDER BY id DESC LIMIT ?", args + (limit,)):
            out.append(dict(ts=r["created"], cat="action", kind=r["status"], new=r["label"], old=r["message"], user=users.get(r["user_id"], "díktyo"),
                            device_id=r["device_id"], device=names.get(r["device_id"], "")))
    if "config" in kinds:
        for r in c.execute(f"SELECT * FROM config_backups WHERE profile_id=? AND created>=?{dev} ORDER BY id DESC LIMIT ?", args + (limit,)):
            out.append(dict(ts=r["created"], cat="config", kind="config", new=r["filename"], device_id=r["device_id"],
                            device=names.get(r["device_id"], ""), detail=dict(id=r["id"], is_text=bool(r["is_text"]))))
    if "quarantine" in kinds:
        for r in c.execute(f"SELECT * FROM quarantine WHERE profile_id=? AND since>=?{dev} ORDER BY id DESC LIMIT ?", args + (limit,)):
            out.append(dict(ts=r["since"], cat="quarantine", kind=r["status"], new=r["ip"], device_id=r["device_id"],
                            device=names.get(r["device_id"]) or r["name"], old=r["message"]))
    if q:
        ql = q.lower()
        out = [x for x in out if ql in " ".join(str(x.get(k) or "") for k in ("device", "old", "new", "field")).lower()]
    out.sort(key=lambda x: parse_ts(x["ts"]), reverse=True)
    return out[:limit]


def summary(c, pid, hours=24):
    """Kurzfassung „seit gestern“: neue, gelöschte, geänderte Geräte, Ausfälle, Konfigurationsänderungen."""
    since = (dt.datetime.now().astimezone() - dt.timedelta(hours=hours)).isoformat(timespec="seconds")
    r = lambda sql, *a: c.execute(sql, (pid, since) + a).fetchone()[0]  # noqa: E731
    return dict(
        hours=hours,
        created=r("SELECT COUNT(*) FROM changes WHERE profile_id=? AND ts>=? AND kind='created'"),
        deleted=r("SELECT COUNT(*) FROM changes WHERE profile_id=? AND ts>=? AND kind='deleted'"),
        changed=r("SELECT COUNT(DISTINCT device_id) FROM changes WHERE profile_id=? AND ts>=? AND kind='changed'"),
        ip=r("SELECT COUNT(*) FROM changes WHERE profile_id=? AND ts>=? AND field='ips'"),
        moved=r("SELECT COUNT(*) FROM changes WHERE profile_id=? AND ts>=? AND field='uplink'"),
        offline=c.execute("""SELECT COUNT(DISTINCT s.device_id) FROM status_events s JOIN devices d ON d.id=s.device_id
                             WHERE d.profile_id=? AND s.ts>=? AND s.online=0""", (pid, since)).fetchone()[0],
        configs=r("SELECT COUNT(*) FROM config_backups WHERE profile_id=? AND created>=?"),
        ports=r("SELECT COUNT(*) FROM changes WHERE profile_id=? AND ts>=? AND field='ports'"),
    )
