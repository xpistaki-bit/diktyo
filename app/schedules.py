"""Zeitpläne für Schaltaktionen.

Ein Zeitplan entsteht aus einer angebotenen Aktion (actions.available). Umkehrbare Aktionen (WLAN, Internetsperre,
Switch-Port) haben ein Zeitfenster: zu Beginn die Aktion, am Ende die Umkehrung (z. B. Mo–Fr 22:00–06:30 Internet
gesperrt). Andere Aktionen (Neustart, PoE, Wake-on-LAN, VM) laufen einmal zur Startzeit.

Geschaltet wird nur an den Übergängen – wer zwischendurch von Hand umschaltet, wird bis zum nächsten Übergang nicht
überstimmt. Vor jedem Lauf wird erneut geprüft, ob die Aktion noch angeboten und nicht gesperrt ist (Aussperr-Schutz).
"""
import datetime as dt
import json
import re

from . import actions
from .db import db, now, parse_ts

DAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
DIRECTION = {"wlan": "on", "internet": "block", "port": "up"}
CATCH_UP = dt.timedelta(hours=6)


class ScheduleError(Exception):
    pass


def _hm(v):
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(v or "").strip())
    if not m:
        raise ScheduleError("Uhrzeit im Format HH:MM angeben")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _identity(kind, params):
    """Parameter ohne Richtung (und ohne IP, die sich ändern darf) – zum Wiederfinden der Aktion."""
    return {k: v for k, v in params.items() if k not in ("on", "block", "up", "ip", "ssid")}


def create(c, pid, user_id, did, key, days, start, end=None, port=0):
    acts = {a["key"]: a for a in actions.available(c, pid, did, port or None)}
    a = acts.get(key)
    if not a:
        raise ScheduleError("Diese Aktion ist für das Gerät nicht (mehr) verfügbar – Ansicht neu laden")
    if a["blocked"]:
        raise ScheduleError(a["blocked"])
    days = sorted({int(d) for d in days or [] if str(d).isdigit() and 0 <= int(d) <= 6})
    if not days:
        raise ScheduleError("Mindestens einen Wochentag wählen")
    start = _hm(start)
    end = _hm(end) if end and a["kind"] in DIRECTION else None
    if end == start:
        raise ScheduleError("Start und Ende dürfen nicht gleich sein")
    sid = c.execute("""INSERT INTO schedules(profile_id, device_id, integration_id, kind, params, label, port, days, start, end_time, enabled,
                       created, created_by, last_check) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,?)""",
                    (pid, did, a["integration_id"], a["kind"], json.dumps(a["params"], ensure_ascii=False), a["label"], port or 0,
                     ",".join(map(str, days)), start, end, now(), user_id, now())).lastrowid
    return sid


def _at(day, hm):
    h, m = map(int, hm.split(":"))
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def transitions(s, a, b):
    """Übergänge des Zeitplans s im Zeitraum (a, b] -> [(zeitpunkt, 'start'|'end')]"""
    days = {int(x) for x in s["days"].split(",") if x}
    out = []
    d = (a - dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while d <= b:
        if d.weekday() in days:
            st = _at(d, s["start"])
            if a < st <= b:
                out.append((st, "start"))
            if s["end_time"]:
                en = _at(d, s["end_time"])
                if en <= st:
                    en += dt.timedelta(days=1)  # über Mitternacht
                if a < en <= b:
                    out.append((en, "end"))
        d += dt.timedelta(days=1)
    return sorted(out)


def next_run(s, t=None):
    t = t or dt.datetime.now().astimezone()
    ev = transitions(s, t, t + dt.timedelta(days=8))
    return ev[0][0].isoformat(timespec="minutes") if ev else None


def _params_for(c, s, phase):
    params = json.loads(s["params"])
    if phase == "end":
        params = actions.inverse(s["kind"], params)
    if s["kind"] == "internet" and s["device_id"]:  # aktuelle IP des Geräts
        ip = actions._ipv4([r["address"] for r in c.execute("SELECT address FROM ip_addresses WHERE device_id=? ORDER BY id", (s["device_id"],))])
        if ip:
            params["ip"] = ip[0]
    return params


def _allowed(c, s):
    """Wird die Aktion noch angeboten und ist sie nicht gesperrt? -> Fehlertext oder ''"""
    want = _identity(s["kind"], json.loads(s["params"]))
    for a in actions.available(c, s["profile_id"], s["device_id"], s["port"] or None):
        if a["kind"] == s["kind"] and a["integration_id"] == s["integration_id"] and _identity(a["kind"], a["params"]) == want:
            return a["blocked"]
    return "Aktion für das Gerät nicht mehr verfügbar"


def run_due(log=print, t=None):
    """Vom Hintergrunddienst (etwa jede Minute): fällige Übergänge ausführen."""
    t = t or dt.datetime.now().astimezone()
    with db() as c:
        rows = c.execute("SELECT * FROM schedules WHERE enabled=1").fetchall()
    for s in rows:
        last = parse_ts(s["last_check"]) if s["last_check"] else t
        ev = transitions(s, max(last, t - CATCH_UP), t)
        with db() as c:
            c.execute("UPDATE schedules SET last_check=? WHERE id=?", (t.isoformat(timespec="seconds"), s["id"]))
        if not ev:
            continue
        phase = ev[-1][1]  # bei mehreren verpassten Übergängen gilt der letzte
        with db() as c:
            if not s["device_id"] or not c.execute("SELECT 1 FROM devices WHERE id=?", (s["device_id"],)).fetchone():
                reason = "Gerät gelöscht"
            else:
                reason = _allowed(c, s)
            params = _params_for(c, s, phase)
        if reason:
            res = dict(status="error", message=reason)
        else:
            label = s["label"] if phase == "start" else f"Ende: {s['label']}"
            res = actions.execute(None, s["profile_id"], None, s["kind"], s["integration_id"], params, interactive=False,
                                  device_id=s["device_id"], label=f"Zeitplan: {label}")
        with db() as c:
            c.execute("UPDATE schedules SET last_run=?, last_result=? WHERE id=?",
                      (now(), f"{phase}: {res['status']}" + (f" – {res.get('message')}" if res.get("message") else ""), s["id"]))
            if res["status"] != "done":
                from .scan import runner
                runner.event(c, s["profile_id"], "schedule_failed", s["device_id"], label=s["label"], message=res.get("message", ""))
        log(f"Zeitplan {s['id']} ({phase}): {res['status']} {res.get('message', '')}")


def listing(c, pid, did=None):
    q = "SELECT s.*, d.name AS device FROM schedules s LEFT JOIN devices d ON d.id=s.device_id WHERE s.profile_id=?"
    args = [pid]
    if did:
        q += " AND s.device_id=?"
        args.append(did)
    out = []
    for s in c.execute(q + " ORDER BY s.id", args):
        out.append(dict(id=s["id"], device_id=s["device_id"], device=s["device"], label=s["label"], kind=s["kind"],
                        days=[int(x) for x in s["days"].split(",") if x], start=s["start"], end=s["end_time"], enabled=bool(s["enabled"]),
                        next_run=next_run(s) if s["enabled"] else None, last_run=s["last_run"], last_result=s["last_result"]))
    return out
