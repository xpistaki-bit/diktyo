"""Konten: Anlegen, Passwort, Admin-Recht, Löschen. Gemeinsam genutzt von Web-App und CLI."""
import re
import time

from . import security
from .db import audit, now

MIN_PW = 8
RESET_VALID_S = 3600
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")  # eindeutig zerlegbar (kein Rückverfolgen über Punkte)


class UserError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status
        self.msg = msg


def norm_email(email):
    e = str(email or "").strip().lower()
    if len(e) > 254 or not EMAIL_RE.match(e):
        raise UserError(400, "Bitte eine gültige E-Mail-Adresse angeben")
    return e


def check_new_pw(pw):
    pw = str(pw or "")
    if len(pw) < MIN_PW:
        raise UserError(400, "Das Passwort muss mindestens 8 Zeichen haben")
    return pw


def public(r):
    if r is None:
        return None
    keys = r.keys()
    return dict(id=r["id"], email=r["email"], is_admin=bool(r["is_admin"]), lang=r["lang"], created=r["created"], last_login=r["last_login"],
                totp=bool(r["totp_secret"]) if "totp_secret" in keys else False)


def by_email(c, email):
    return c.execute("SELECT * FROM users WHERE email=?", (str(email or "").strip().lower(),)).fetchone()


def count(c):
    return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def admin_count(c):
    return c.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0]


def create(c, email, pw, is_admin=False, actor=None):
    email = norm_email(email)
    pw = check_new_pw(pw)
    if by_email(c, email):
        raise UserError(409, "Für diese E-Mail-Adresse gibt es schon ein Konto")
    cur = c.execute("INSERT INTO users(email, pw_hash, is_admin, created) VALUES(?,?,?,?)",
                    (email, security.hash_pw(pw), 1 if is_admin else 0, now()))
    audit(c, "user.create", actor, detail=dict(email=email, admin=bool(is_admin)))
    return public(c.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone())


def set_password(c, uid, pw, actor=None):
    """Setzt ein neues Passwort und meldet alle Sitzungen des Kontos ab."""
    pw = check_new_pw(pw)
    c.execute("UPDATE users SET pw_hash=? WHERE id=?", (security.hash_pw(pw), uid))
    c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    c.execute("UPDATE password_resets SET used=1 WHERE user_id=?", (uid,))
    audit(c, "user.password", actor, detail=dict(user=uid))


def set_admin(c, uid, on, actor=None):
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise UserError(404, "Konto nicht gefunden")
    if u["is_admin"] and not on and admin_count(c) <= 1:
        raise UserError(400, "Es muss mindestens ein Administrator bleiben")
    c.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if on else 0, uid))
    audit(c, "user.admin", actor, detail=dict(user=uid, admin=bool(on)))


def delete(c, uid, heir_id, actor=None):
    """Löscht ein Konto. Profile, deren einziger Besitzer es war, gehen an heir_id über."""
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise UserError(404, "Konto nicht gefunden")
    if u["is_admin"] and admin_count(c) <= 1:
        raise UserError(400, "Es muss mindestens ein Administrator bleiben")
    orphans = [r["profile_id"] for r in c.execute(
        """SELECT m.profile_id FROM profile_members m WHERE m.user_id=? AND m.role='owner'
           AND (SELECT COUNT(*) FROM profile_members o WHERE o.profile_id=m.profile_id AND o.role='owner') = 1""", (uid,))]
    for pid in orphans:
        if heir_id:
            c.execute("""INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?,'owner')
                         ON CONFLICT(profile_id, user_id) DO UPDATE SET role='owner'""", (pid, heir_id))
    c.execute("DELETE FROM users WHERE id=?", (uid,))
    audit(c, "user.delete", actor, detail=dict(email=u["email"], transferred=orphans))


def create_reset_token(c, uid):
    tok, th = security.new_token()
    c.execute("INSERT INTO password_resets(token_hash, user_id, expires) VALUES(?,?,?)", (th, uid, time.time() + RESET_VALID_S))
    return tok


def reset_with_token(c, token, pw):
    r = c.execute("SELECT * FROM password_resets WHERE token_hash=? AND used=0 AND expires>?",
                  (security.sha256(token or ""), time.time())).fetchone()
    if not r:
        raise UserError(400, "Der Link ist ungültig oder abgelaufen. Bitte einen neuen anfordern.")
    set_password(c, r["user_id"], pw, actor=r["user_id"])


def cleanup(c):
    t = time.time()
    c.execute("DELETE FROM sessions WHERE expires<?", (t,))
    c.execute("DELETE FROM password_resets WHERE expires<? OR used=1", (t,))
