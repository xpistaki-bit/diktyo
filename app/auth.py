"""Anmeldung, Sitzungen und Rechte – gemeinsam genutzt von allen API-Bereichen."""
import threading
import time

from fastapi import Depends, HTTPException, Request

from . import security, users
from .db import db, now, set_setting

COOKIE = "dk_session"
SESSION_DAYS = 30
ROLES = {"view": 1, "edit": 2, "owner": 3}


def lang_of(request):
    v = (request.headers.get("x-lang") or request.query_params.get("lang") or "de").lower()
    return "en" if v.startswith("en") else "de"


def client_ip(request):
    return request.client.host if request.client else "?"


_attempts = {}
_attempts_lock = threading.Lock()


def rate_limit(key, limit=10, window=900):
    t = time.time()
    with _attempts_lock:
        for k in [k for k, v in _attempts.items() if v[1] < t]:
            del _attempts[k]
        n, reset = _attempts.get(key, (0, t + window))
        _attempts[key] = (n + 1, reset)
    if n + 1 > limit:
        raise HTTPException(429, "Zu viele Versuche. Bitte einige Minuten warten.")


def start_session(c, response, uid, request=None):
    tok, th = security.new_token()
    ip = client_ip(request) if request is not None else ""
    ua = (request.headers.get("user-agent", "") if request is not None else "")[:200]
    c.execute("INSERT INTO sessions(token_hash, user_id, created, expires, ip, user_agent, last_seen) VALUES(?,?,?,?,?,?,?)",
              (th, uid, time.time(), time.time() + SESSION_DAYS * 86400, ip, ua, time.time()))
    c.execute("UPDATE users SET last_login=? WHERE id=?", (now(), uid))
    response.set_cookie(COOKIE, tok, httponly=True, samesite="lax", max_age=SESSION_DAYS * 86400, path="/")


def current_user(request: Request):
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    th = security.sha256(tok)
    with db() as c:
        r = c.execute("SELECT u.*, s.last_seen AS s_seen FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=? AND s.expires>?",
                      (th, time.time())).fetchone()
        if r and time.time() - (r["s_seen"] or 0) > 300:  # „zuletzt aktiv“ der Sitzung, höchstens alle 5 Minuten schreiben
            c.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (time.time(), th))
    u = users.public(r)
    if u:
        u["sid"] = th[:16]
    return u


def require_user(request: Request):
    u = current_user(request)
    if not u:
        raise HTTPException(401, "Bitte anmelden")
    return u


def require_admin(user=Depends(require_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "Nur für Administratoren")
    return user


def profile_access(c, user, pid, need="view"):
    """-> (Profilzeile, Rolle). Administratoren haben in allen Profilen Besitzerrechte."""
    p = c.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
    m = p and c.execute("SELECT role FROM profile_members WHERE profile_id=? AND user_id=?", (pid, user["id"])).fetchone()
    role = m["role"] if m else ("owner" if p and user["is_admin"] else None)
    if not p or not role:
        raise HTTPException(404, "Profil nicht gefunden")
    if ROLES[role] < ROLES[need]:
        raise HTTPException(403, "Dafür fehlen dir in diesem Profil die Rechte")
    return p, role


def touch(c, pid=None, user=None):
    """Merkt sich eine Änderung (für die automatische Sicherung und die Änderungszeit des Profils) und trägt
    Geräteänderungen in den Änderungsverlauf ein."""
    set_setting(c, "last_change", time.time())
    if pid:
        c.execute("UPDATE profiles SET updated=? WHERE id=?", (now(), pid))
        from . import changes
        changes.sync(c, pid, "user", (user or {}).get("id"))


def text(body, key, maxlen=200):
    return str(body.get(key) or "").strip()[:maxlen]
