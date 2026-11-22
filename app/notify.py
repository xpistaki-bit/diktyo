"""Benachrichtigungen per E-Mail und ntfy – unabhängig von Home Assistant.

Quelle sind die Ereignisse (Tabelle events). Der Hintergrunddienst bündelt neue Ereignisse eines Profils höchstens
einmal pro Minute (BATCH_S) zu einer Nachricht je Kanal. Was schon verschickt ist, merkt notify_state.last_id; beim
Einschalten zählen nur Ereignisse ab dann. Einstellungen je Profil unter settings["notify"], das ntfy-Token verschlüsselt.
"""
import json
import time

import httpx

from . import mailer, security
from .db import db

BATCH_S = 60
MAX_LINES = 25
KINDS = {  # Art -> (deutsch, englisch, ntfy-Priorität, ntfy-Tag)
    "device_offline": ("{name} ist offline", "{name} is offline", 4, "red_circle"),
    "device_online": ("{name} ist wieder online", "{name} is back online", 2, "green_circle"),
    "new_device": ("Neues Gerät: {name} {ip}", "New device: {name} {ip}", 3, "new"),
    "quarantined": ("In Quarantäne: {name} {ip}", "Quarantined: {name} {ip}", 4, "no_entry"),
    "firmware_update": ("Firmware-Update für {name}: {installed} → {latest}", "Firmware update for {name}: {installed} → {latest}", 2, "arrow_up"),
    "action_undo_failed": ("Zurückschalten fehlgeschlagen: {label} – {message}", "Undo failed: {label} – {message}", 5, "warning"),
    "schedule_failed": ("Zeitplan fehlgeschlagen: {label} – {message}", "Schedule failed: {label} – {message}", 4, "warning"),
    "speed_slow": ("Internet langsam: ↓ {down} (Leitung ↓ {line})", "Internet slow: ↓ {down} (line ↓ {line})", 3, "turtle"),
    "backup_failed": ("Konfigurations-Backup fehlgeschlagen: {name} – {message}", "Configuration backup failed: {name} – {message}", 3, "floppy_disk"),
    "integration_failed": ("Integration gestört: {name} – {message}", "Integration failing: {name} – {message}", 3, "warning"),
    "watch_change": ("Wachliste: {name} – {label_de} {old} → {new}", "Watchlist: {name} – {label_en} {old} → {new}", 5, "rotating_light"),
}
DEFAULT_KINDS = ["device_offline", "new_device", "quarantined", "action_undo_failed", "schedule_failed", "speed_slow", "backup_failed",
                 "integration_failed", "watch_change"]
DEFAULTS = dict(email=False, email_to="", ntfy=False, ntfy_url="https://ntfy.sh", ntfy_topic="", ntfy_token="", kinds=DEFAULT_KINDS,
                lang="de", only_infra_offline=False)


class NotifyError(Exception):
    pass


def settings(profile_row, reveal=False):
    s = json.loads(profile_row["settings"] or "{}").get("notify") or {}
    out = {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}
    out["kinds"] = [k for k in out["kinds"] if k in KINDS]
    if s and not s.get("seen_watch") and "watch_change" not in out["kinds"]:  # vor 0.27 gespeichert: Wachliste mit an
        out["kinds"].append("watch_change")
    if not reveal:
        out["ntfy_token"] = security.MASK if out["ntfy_token"] else ""
    elif out["ntfy_token"]:
        try:
            out["ntfy_token"] = security.decrypt(out["ntfy_token"])
        except Exception:
            out["ntfy_token"] = ""
    return out


def save_settings(c, profile_row, body):
    st = json.loads(profile_row["settings"] or "{}")
    old = settings(profile_row, reveal=False)
    raw_old = (st.get("notify") or {}).get("ntfy_token", "")
    s = dict(old)
    for k in ("email", "ntfy", "only_infra_offline"):
        if k in body:
            s[k] = bool(body[k])
    for k, n in (("email_to", 300), ("ntfy_url", 200), ("ntfy_topic", 120)):
        if k in body:
            s[k] = str(body[k] or "").strip()[:n]
    if body.get("lang") in ("de", "en"):
        s["lang"] = body["lang"]
    if "kinds" in body and isinstance(body["kinds"], list):
        s["kinds"] = [k for k in body["kinds"] if k in KINDS]
    tok = body.get("ntfy_token")
    s["ntfy_token"] = raw_old if tok in (None, security.MASK) else (security.encrypt(tok) if tok else "")
    if s["ntfy_url"] and not s["ntfy_url"].startswith(("http://", "https://")):
        raise NotifyError("ntfy-Server bitte mit http:// oder https:// angeben")
    was_on = old["email"] or old["ntfy"]
    st["notify"] = dict(s, seen_watch=True)
    c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), profile_row["id"]))
    if (s["email"] or s["ntfy"]) and not was_on:  # ab jetzt melden, nicht rückwirkend
        last = c.execute("SELECT COALESCE(MAX(id), 0) FROM events WHERE profile_id=?", (profile_row["id"],)).fetchone()[0]
        c.execute("INSERT INTO notify_state(profile_id, last_id, last_sent) VALUES(?,?,0) "
                  "ON CONFLICT(profile_id) DO UPDATE SET last_id=excluded.last_id", (profile_row["id"], last))
    return settings(c.execute("SELECT * FROM profiles WHERE id=?", (profile_row["id"],)).fetchone())


def _recipients(c, pid, s):
    if s["email_to"].strip():
        return [x.strip() for x in s["email_to"].replace(";", ",").split(",") if "@" in x][:10]
    return [r["email"] for r in c.execute("""SELECT u.email FROM profile_members m JOIN users u ON u.id=m.user_id
                                             WHERE m.profile_id=? AND m.role='owner'""", (pid,))]


def line(kind, data, lang="de"):
    tpl = KINDS[kind][1 if lang == "en" else 0]

    class D(dict):
        def __missing__(self, k):
            return ""
    return " ".join(tpl.format_map(D({k: (str(v) if v is not None else "") for k, v in data.items()})).split())


def compose(profile_name, events, lang="de"):
    """-> (Titel, Text, Priorität, Tags)"""
    lines = [line(e["kind"], json.loads(e["data"] or "{}"), lang) for e in events[:MAX_LINES]]
    if len(events) > MAX_LINES:
        lines.append(f"… und {len(events) - MAX_LINES} weitere" if lang != "en" else f"… and {len(events) - MAX_LINES} more")
    prio = max(KINDS[e["kind"]][2] for e in events)
    tags = sorted({KINDS[e["kind"]][3] for e in events})[:5]
    title = f"díktyo · {profile_name}: " + (lines[0] if len(events) == 1 else
                                            (f"{len(events)} Meldungen" if lang != "en" else f"{len(events)} notifications"))
    return title, "\n".join(lines), prio, tags


def send_ntfy(s, title, text, prio=3, tags=()):
    if not s["ntfy_topic"]:
        raise NotifyError("ntfy-Thema fehlt")
    headers = {"Authorization": f"Bearer {s['ntfy_token']}"} if s.get("ntfy_token") else {}
    try:
        # als JSON an die Server-Adresse: Umlaute im Titel kommen so sicher an (HTTP-Header wären nur Latin-1)
        r = httpx.post(s["ntfy_url"].rstrip("/") + "/", json=dict(topic=s["ntfy_topic"], title=title, message=text, priority=prio, tags=list(tags)),
                       headers=headers, timeout=10)
    except httpx.HTTPError as ex:
        raise NotifyError(f"ntfy nicht erreichbar: {ex}")
    if r.status_code >= 400:
        raise NotifyError(f"ntfy meldet HTTP {r.status_code}: {r.text[:120]}")


def send_email(c, pid, s, title, text):
    if not mailer.enabled(c):
        raise NotifyError("E-Mail-Versand ist nicht eingerichtet (Einstellungen → E-Mail-Versand)")
    to = _recipients(c, pid, s)
    if not to:
        raise NotifyError("Keine Empfänger")
    cfg = mailer.smtp_config(c)
    for addr in to:
        mailer.send(cfg, addr, title, text + "\n\n— díktyo")


def deliver(pid, log=print, force=False):
    """Neue Ereignisse eines Profils verschicken. -> Anzahl Ereignisse"""
    with db() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
        if not p:
            return 0
        s = settings(p, reveal=True)
        if not (s["email"] or s["ntfy"]):
            return 0
        st = c.execute("SELECT * FROM notify_state WHERE profile_id=?", (pid,)).fetchone()
        last_id = st["last_id"] if st else c.execute("SELECT COALESCE(MAX(id), 0) FROM events WHERE profile_id=?", (pid,)).fetchone()[0]
        if not st:
            c.execute("INSERT INTO notify_state(profile_id, last_id, last_sent) VALUES(?,?,0)", (pid, last_id))
            return 0
        if not force and time.time() - (st["last_sent"] or 0) < BATCH_S:
            return 0
        evs = c.execute("SELECT * FROM events WHERE profile_id=? AND id>? ORDER BY id LIMIT 500", (pid, last_id)).fetchall()
        if not evs:
            return 0
        new_last = evs[-1]["id"]
        wanted = [e for e in evs if _wanted(c, e, s)]
        c.execute("UPDATE notify_state SET last_id=?, last_sent=? WHERE profile_id=?", (new_last, time.time(), pid))
        name = p["name"]
    if not wanted:
        return 0
    title, text, prio, tags = compose(name, wanted, s["lang"])
    errors = []
    if s["ntfy"]:
        try:
            send_ntfy(s, title, text, prio, tags)
        except NotifyError as ex:
            errors.append(f"ntfy: {ex}")
    if s["email"]:
        try:
            with db() as c:
                send_email(c, pid, s, title, text)
        except Exception as ex:
            errors.append(f"E-Mail: {ex}")
    with db() as c:
        c.execute("UPDATE notify_state SET last_error=? WHERE profile_id=?", ("; ".join(errors)[:300], pid))
    for e in errors:
        log(f"Benachrichtigung Profil {pid}: {e}")
    return len(wanted)


INFRA = ("router", "switch", "ap", "mesh", "firewall", "modem", "hypervisor", "server", "nas")


def _wanted(c, e, s):
    """Gewählte Arten; Ausfälle beobachteter Geräte (Wachliste) kommen immer mit, wenn „Wachliste“ gewählt ist."""
    if e["kind"] in ("device_offline", "device_online") and e["device_id"] and "watch_change" in s["kinds"]:
        from . import watch
        if watch.is_watched(c, e["device_id"]):
            return True
    return e["kind"] in s["kinds"] and _relevant(c, e, s)


def _relevant(c, e, s):
    if s["only_infra_offline"] and e["kind"] in ("device_offline", "device_online") and e["device_id"]:
        r = c.execute("SELECT type FROM devices WHERE id=?", (e["device_id"],)).fetchone()
        return bool(r and r["type"] in INFRA)
    return True


def test(c, pid, body):
    """Testnachricht mit den (noch ungespeicherten) Einstellungen aus dem Formular."""
    p = c.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
    s = settings(p, reveal=True)
    for k in ("ntfy_url", "ntfy_topic", "email_to"):
        if k in body:
            s[k] = str(body[k] or "").strip()
    if body.get("ntfy_token") not in (None, security.MASK):
        s["ntfy_token"] = body["ntfy_token"]
    title = f"díktyo · {p['name']}: " + ("Testnachricht" if s["lang"] != "en" else "test message")
    text = "Benachrichtigungen funktionieren." if s["lang"] != "en" else "Notifications work."
    out = {}
    for ch in ("ntfy", "email"):
        if not body.get(ch):
            continue
        try:
            send_ntfy(s, title, text, 3, ("white_check_mark",)) if ch == "ntfy" else send_email(c, pid, s, title, text)
            out[ch] = "ok"
        except Exception as ex:
            out[ch] = str(ex)
    return out


def state(c, pid):
    st = c.execute("SELECT * FROM notify_state WHERE profile_id=?", (pid,)).fetchone()
    return dict(last_error=st["last_error"] if st else "", last_sent=st["last_sent"] if st else 0)
