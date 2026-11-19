"""Quarantäne für neue Geräte.

Ist sie im Profil eingeschaltet, sperrt díktyo neuen Geräten (die danach im Posteingang auftauchen) über die FRITZ!Box
den Internetzugang. Übernimmt man das Gerät im Posteingang, wird es automatisch freigegeben; „Freigeben“ geht auch
ohne Übernehmen. Infrastruktur, díktyo selbst und Geräte außerhalb des FRITZ!Box-Netzes (z. B. Gastnetz) bleiben
unberührt. Wechselt ein Gerät in Quarantäne die IP, wird die neue gesperrt und die alte freigegeben; wird es gelöscht,
wird die Sperre aufgehoben.
"""
import json

from . import actions
from .db import db, now


def settings(profile_row):
    s = json.loads(profile_row["settings"] or "{}").get("quarantine") or {}
    return dict(enabled=bool(s.get("enabled")), since=s.get("since"), since_id=s.get("since_id"), random=s.get("random", True))


def save(c, pid, enabled, random=True):
    p = c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()
    st = json.loads(p["settings"] or "{}")
    old = st.get("quarantine") or {}
    keep = old.get("enabled") and enabled
    last_id = c.execute("SELECT MAX(id) FROM devices").fetchone()[0] or 0  # Geräte bis hier gelten als „schon da“
    q = dict(enabled=bool(enabled), random=bool(random), since=old.get("since") if keep else (now() if enabled else None),
             since_id=old.get("since_id", 0) if keep else (last_id if enabled else None))
    st["quarantine"] = q
    c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
    return q


def _fritz(c, pid):
    return c.execute("SELECT * FROM integrations WHERE profile_id=? AND driver='fritzbox' AND enabled=1 ORDER BY id LIMIT 1", (pid,)).fetchone()


def _block(pid, iid, did, ip, block, label):
    return actions.execute(None, pid, None, "internet", iid, dict(ip=ip, block=block), interactive=False, device_id=did, label=label)


def process(pid, log=print):
    """Vom Hintergrunddienst: neue Geräte sperren, übernommene/gelöschte freigeben, IP-Wechsel nachziehen.
    Gelesen und geschrieben wird in kurzen Abschnitten – die Aktionen selbst schreiben in eigene Verbindungen."""
    from .scan import oui, runner
    own_ips, _ = actions._own_addresses()
    with db() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
        fritz = _fritz(c, pid)
        if not p or not fritz:
            return
        fritz = dict(fritz)
        qs = settings(p)
        rows = [dict(r) for r in c.execute("SELECT * FROM quarantine WHERE profile_id=? AND status='active'", (pid,))]
        todo = []
        if qs["enabled"] and qs["since_id"] is not None:
            known = {r["device_id"] for r in c.execute("SELECT device_id FROM quarantine WHERE profile_id=? AND device_id IS NOT NULL", (pid,))}
            for d in c.execute("SELECT * FROM devices WHERE profile_id=? AND status='discovered'", (pid,)).fetchall():
                if d["id"] in known or d["type"] in actions.INFRA or d["id"] <= qs["since_id"]:
                    continue
                ips = actions._ipv4([r["address"] for r in c.execute("SELECT address FROM ip_addresses WHERE device_id=? ORDER BY id", (d["id"],))])
                mac = next((r["mac"] for r in c.execute("SELECT mac FROM interfaces WHERE device_id=? AND mac<>'' ORDER BY id", (d["id"],))), "")
                if not ips or ips[0] in own_ips or not actions._same_lan(ips[0], fritz["host"], c, pid):
                    continue
                if mac and not qs["random"] and oui.is_random(mac):
                    continue
                todo.append((d["id"], d["name"], ips[0], mac))
        checks = []
        for r in rows:
            d = c.execute("SELECT * FROM devices WHERE id=?", (r["device_id"],)).fetchone() if r["device_id"] else None
            ips = actions._ipv4([x["address"] for x in c.execute("SELECT address FROM ip_addresses WHERE device_id=? ORDER BY id", (d["id"],))]) if d else []
            same = bool(ips) and actions._same_lan(ips[0], fritz["host"], c, pid)
            checks.append((r, d["status"] if d else None, ips[0] if ips and same else None))
    # neue Geräte sperren
    for did, name, ip, mac in todo:
        res = _block(pid, fritz["id"], did, ip, True, "Quarantäne: Internet gesperrt")
        with db() as c:
            c.execute("INSERT INTO quarantine(profile_id, device_id, integration_id, ip, mac, name, status, since, message) VALUES(?,?,?,?,?,?,?,?,?)",
                      (pid, did, fritz["id"], ip, mac, name, "active" if res["status"] == "done" else "error", now(), res.get("message", "")))
            runner.event(c, pid, "quarantined", did, name=name, ip=ip, mac=mac, ok=res["status"] == "done", message=res.get("message", ""))
        log(f"Quarantäne {name} ({ip}): {res['status']} {res.get('message', '')}")
    # übernommene oder gelöschte freigeben, IP-Wechsel nachziehen
    for r, status, ip in checks:
        if status is None or status == "confirmed":
            res = _block(pid, r["integration_id"], r["device_id"], r["ip"], False,
                         "Quarantäne beendet: übernommen" if status else "Quarantäne beendet: Gerät gelöscht")
            with db() as c:
                c.execute("UPDATE quarantine SET status=?, released=?, message=? WHERE id=?",
                          ("released" if res["status"] == "done" else "release_failed", now(), res.get("message", ""), r["id"]))
        elif ip and ip != r["ip"]:
            res = _block(pid, r["integration_id"], r["device_id"], ip, True, "Quarantäne: neue IP gesperrt")
            if res["status"] == "done":
                _block(pid, r["integration_id"], r["device_id"], r["ip"], False, "Quarantäne: alte IP freigegeben")
                with db() as c:
                    c.execute("UPDATE quarantine SET ip=? WHERE id=?", (ip, r["id"]))


def release(pid, qid, interactive=True):
    """Ohne Übernehmen freigeben (das Gerät wird danach nicht erneut gesperrt). -> Ergebnis der Aktion oder None"""
    with db() as c:
        r = c.execute("SELECT * FROM quarantine WHERE id=? AND profile_id=?", (qid, pid)).fetchone()
    if not r:
        return None
    res = actions.execute(None, pid, None, "internet", r["integration_id"], dict(ip=r["ip"], block=False), interactive=interactive,
                          device_id=r["device_id"], label="Quarantäne von Hand beendet")
    if res["status"] == "done" or r["status"] == "error":
        with db() as c:
            c.execute("UPDATE quarantine SET status='released', released=?, message=? WHERE id=?", (now(), res.get("message", ""), qid))
    return res


def listing(c, pid):
    rows = c.execute("""SELECT q.*, d.name AS device, d.status AS dstatus FROM quarantine q LEFT JOIN devices d ON d.id=q.device_id
                        WHERE q.profile_id=? ORDER BY q.id DESC LIMIT 50""", (pid,)).fetchall()
    return [dict(id=r["id"], device_id=r["device_id"], integration_id=r["integration_id"], device=r["device"] or r["name"], ip=r["ip"], mac=r["mac"], status=r["status"],
                 since=r["since"], released=r["released"], message=r["message"]) for r in rows]
