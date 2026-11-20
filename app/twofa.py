"""Zweiter Faktor für die Anmeldung an díktyo (TOTP nach RFC 6238) und Wiederherstellungscodes.

Ablauf: Passwort richtig -> bei eingeschaltetem zweiten Faktor statt einer Sitzung ein kurzlebiges Anmelde-Ticket
(5 Minuten, höchstens 5 Versuche) -> Code aus der Authenticator-App oder ein Wiederherstellungscode -> Sitzung.
Der Schlüssel liegt verschlüsselt in der Datenbank; ein Code gilt nur einmal (zuletzt benutzter Zeitschritt wird gemerkt).
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
import urllib.parse

from . import security

STEP, DIGITS, WINDOW = 30, 6, 1          # ±1 Zeitschritt Toleranz für ungenaue Uhren
TICKET_SECONDS, TICKET_TRIES = 300, 5
RECOVERY_COUNT = 10
ISSUER = "diktyo"  # ASCII: manche Authenticator-Apps zeigen Sonderzeichen im Aussteller falsch an


class TwoFAError(Exception):
    pass


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret):
    s = secret.replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret, counter):
    h = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS).zfill(DIGITS)


def check(secret, code, last=0, t=None):
    """-> benutzter Zeitschritt oder None. Schritte ≤ last (schon benutzt) zählen nicht."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    now = int((t or time.time()) // STEP)
    for c in range(now - WINDOW, now + WINDOW + 1):
        if c > (last or 0) and hmac.compare_digest(code_at(secret, c), code):
            return c
    return None


def uri(secret, account):
    label = urllib.parse.quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def qr_svg(text):
    """QR-Code als SVG (lokal erzeugt – der Schlüssel verlässt díktyo nicht)."""
    import io
    import segno
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=5, border=3, dark="#0b1d38", light="#ffffff", xmldecl=False, svgns=True, omitsize=True)
    return buf.getvalue().decode()


def new_recovery():
    """-> (Codes zum Anzeigen, Hashes zum Speichern)"""
    codes = ["-".join(secrets.token_hex(2) for _ in range(3)) for _ in range(RECOVERY_COUNT)]
    return codes, [security.sha256(c) for c in codes]


def _norm_recovery(code):
    s = "".join(ch for ch in str(code or "").lower() if ch in "0123456789abcdef")
    return "-".join(s[i:i + 4] for i in range(0, 12, 4)) if len(s) == 12 else ""


# ------------------------------------------------------------ Konto
def enabled(row):
    return bool(row and row["totp_secret"])


def verify_user(c, user_row, code):
    """Code (TOTP oder Wiederherstellungscode) für ein Konto prüfen und verbrauchen. -> 'totp' | 'recovery' | None"""
    secret = security.decrypt(user_row["totp_secret"]) if user_row["totp_secret"] else ""
    step = check(secret, code, user_row["totp_last"])
    if step:
        c.execute("UPDATE users SET totp_last=? WHERE id=?", (step, user_row["id"]))
        return "totp"
    rc = _norm_recovery(code)
    if rc:
        hashes = json.loads(user_row["recovery"] or "[]")
        h = security.sha256(rc)
        if h in hashes:
            hashes.remove(h)
            c.execute("UPDATE users SET recovery=? WHERE id=?", (json.dumps(hashes), user_row["id"]))
            return "recovery"
    return None


def start_setup(c, uid, email):
    secret = new_secret()
    c.execute("UPDATE users SET totp_pending=? WHERE id=?", (security.encrypt(secret), uid))
    u = uri(secret, email)
    return dict(secret=" ".join(secret[i:i + 4] for i in range(0, len(secret), 4)), uri=u, qr=qr_svg(u))


def finish_setup(c, user_row, code):
    if not user_row["totp_pending"]:
        raise TwoFAError("Bitte die Einrichtung neu starten")
    secret = security.decrypt(user_row["totp_pending"])
    step = check(secret, code)
    if not step:
        raise TwoFAError("Der Code passt nicht – Uhrzeit von Handy und Server prüfen und den aktuellen Code eingeben")
    codes, hashes = new_recovery()
    c.execute("UPDATE users SET totp_secret=?, totp_pending='', totp_last=?, recovery=? WHERE id=?",
              (security.encrypt(secret), step, json.dumps(hashes), user_row["id"]))
    return codes


def disable(c, uid):
    c.execute("UPDATE users SET totp_secret='', totp_pending='', totp_last=0, recovery='[]' WHERE id=?", (uid,))


def regenerate_recovery(c, uid):
    codes, hashes = new_recovery()
    c.execute("UPDATE users SET recovery=? WHERE id=?", (json.dumps(hashes), uid))
    return codes


def recovery_left(row):
    return len(json.loads(row["recovery"] or "[]")) if row and row["totp_secret"] else 0


# ------------------------------------------------------------ Anmelde-Ticket (zwischen Passwort und Code)
def new_ticket(c, uid):
    tok, th = security.new_token()
    c.execute("DELETE FROM login_tickets WHERE expires<?", (time.time(),))
    c.execute("INSERT INTO login_tickets(token_hash, user_id, expires, tries) VALUES(?,?,?,0)", (th, uid, time.time() + TICKET_SECONDS))
    return tok


def use_ticket(c, ticket, code):
    """-> (user_row, Art) oder TwoFAError. Zählt Fehlversuche; nach TICKET_TRIES ist das Ticket verbraucht."""
    th = security.sha256(ticket or "")
    t = c.execute("SELECT * FROM login_tickets WHERE token_hash=?", (th,)).fetchone()
    if not t or t["expires"] < time.time() or t["tries"] >= TICKET_TRIES:
        if t:
            c.execute("DELETE FROM login_tickets WHERE token_hash=?", (th,))
        raise TwoFAError("Anmeldung abgelaufen – bitte noch einmal mit Passwort anmelden")
    u = c.execute("SELECT * FROM users WHERE id=?", (t["user_id"],)).fetchone()
    kind = verify_user(c, u, code) if u else None
    if not kind:
        c.execute("UPDATE login_tickets SET tries=tries+1 WHERE token_hash=?", (th,))
        left = TICKET_TRIES - t["tries"] - 1
        raise TwoFAError("Code falsch" + (f" – noch {left} Versuche" if left > 0 else " – bitte noch einmal mit Passwort anmelden"))
    c.execute("DELETE FROM login_tickets WHERE token_hash=?", (th,))
    return u, kind
