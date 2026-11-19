"""díktyo – Web-App (FastAPI + SQLite)."""
import pathlib
import re
import threading

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import catalog, mailer, routes_actions, routes_backup, routes_catalog, routes_integrations, routes_inventory, routes_scan, security, users
from .scan import ident
from .auth import (COOKIE, ROLES, client_ip, current_user, lang_of, profile_access, rate_limit, require_admin, require_user,
                   start_session, text, touch)
from .db import audit, db, get_setting, migrate, now, set_setting
from .version import REPO_URL, VERSION

BASE = pathlib.Path(__file__).resolve().parent
CSRF_HEADER = "diktyo"  # Wert des Headers X-Requested-With bei ändernden API-Aufrufen

migrate()
with db() as _c:
    catalog.merge_seed(_c)
    ident.merge_seed(_c)
app = FastAPI(title="díktyo", docs_url=None, redoc_url=None)
app.include_router(routes_inventory.router)
app.include_router(routes_catalog.router)
app.include_router(routes_catalog.rules_router)
app.include_router(routes_backup.router)
app.include_router(routes_scan.router)
app.include_router(routes_integrations.router)
app.include_router(routes_actions.router)


def owner_count(c, pid):
    return c.execute("SELECT COUNT(*) FROM profile_members WHERE profile_id=? AND role='owner'", (pid,)).fetchone()[0]


def members_of(c, pid):
    return [dict(user_id=r["user_id"], email=r["email"], role=r["role"]) for r in c.execute(
        "SELECT m.user_id, m.role, u.email FROM profile_members m JOIN users u ON u.id = m.user_id WHERE m.profile_id=? "
        "ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'edit' THEN 1 ELSE 2 END, u.email", (pid,))]


def profile_out(p, role, member):
    return dict(id=p["id"], name=p["name"], description=p["description"], created=p["created"], updated=p["updated"],
                role=role, member=member)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    # Browser senden eigene Header nie seitenübergreifend ohne CORS-Preflight, den wir nicht erlauben.
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS") \
            and request.headers.get("x-requested-with") != CSRF_HEADER:
        msg = "Fehlender Request-Header"
        return JSONResponse({"error": ERR_EN.get(msg, msg) if lang_of(request) == "en" else msg}, status_code=403)
    return await call_next(request)


# ------------------------------------------------------------------ Status
@app.get("/api/state")
def state(request: Request):
    with db() as c:
        first = users.count(c) == 0
        return dict(version=VERSION, repo=REPO_URL, first_run=first,
                    registration_open=first or bool(get_setting(c, "registration_open", False)),
                    mail_enabled=mailer.enabled(c), min_pw=users.MIN_PW, user=current_user(request))


# ------------------------------------------------------------------ Anmeldung
@app.post("/api/auth/register")
def register(request: Request, response: Response, body: dict = Body(...)):
    rate_limit(f"reg:{client_ip(request)}", 20)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")  # zwei gleichzeitige Erstanmeldungen dürfen nicht beide Admin werden
        first = users.count(c) == 0
        if not first and not get_setting(c, "registration_open", False):
            raise HTTPException(403, "Die Registrierung ist geschlossen. Bitte einen Administrator um ein Konto bitten.")
        u = users.create(c, body.get("email"), body.get("password"), is_admin=first)
        c.execute("UPDATE users SET lang=? WHERE id=?", (lang_of(request), u["id"]))
        start_session(c, response, u["id"])
        return dict(user=users.public(c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()))


@app.post("/api/auth/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    rate_limit(f"login:{client_ip(request)}")
    with db() as c:
        u = users.by_email(c, body.get("email"))
        ok = security.check_pw(body.get("password") or "", u["pw_hash"] if u else security.DUMMY_HASH)
        if not u or not ok:
            raise HTTPException(401, "E-Mail-Adresse oder Passwort ist falsch")
        start_session(c, response, u["id"])
        users.cleanup(c)
        return dict(user=users.public(u))


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get(COOKIE)
    if tok:
        with db() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (security.sha256(tok),))
    response.delete_cookie(COOKIE, path="/")
    return dict(ok=True)


@app.post("/api/auth/forgot")
def forgot(request: Request, body: dict = Body(...)):
    # Antwortet immer gleich, damit niemand ausprobieren kann, welche Adressen ein Konto haben.
    rate_limit(f"forgot:{client_ip(request)}", 5)
    with db() as c:
        cfg = mailer.smtp_config(c)
        enabled = mailer.enabled(c)
        u = users.by_email(c, body.get("email")) if enabled else None
        tok = users.create_reset_token(c, u["id"]) if u else None
    if u:
        base = (cfg.get("app_url") or str(request.base_url)).rstrip("/")
        link = f"{base}/#/reset/{tok}"
        lang = u["lang"] or lang_of(request)

        def _send():
            try:
                mailer.send_reset(cfg, u["email"], link, lang)
            except Exception as ex:
                print("mail: Versand der Reset-Mail fehlgeschlagen:", ex)

        threading.Thread(target=_send, daemon=True).start()
    return dict(mail_enabled=enabled)


@app.post("/api/auth/reset")
def reset(request: Request, body: dict = Body(...)):
    rate_limit(f"reset:{client_ip(request)}")
    with db() as c:
        users.reset_with_token(c, body.get("token"), body.get("password"))
    return dict(ok=True)


@app.post("/api/auth/password")
def change_password(response: Response, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        r = c.execute("SELECT pw_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not security.check_pw(body.get("current") or "", r["pw_hash"]):
            raise HTTPException(400, "Das aktuelle Passwort stimmt nicht")
        users.set_password(c, user["id"], body.get("password"), actor=user["id"])
        start_session(c, response, user["id"])  # alle anderen Sitzungen wurden abgemeldet
    return dict(ok=True)


@app.put("/api/auth/me")
def update_me(body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        if body.get("lang") in ("de", "en"):
            c.execute("UPDATE users SET lang=? WHERE id=?", (body["lang"], user["id"]))
        return dict(user=users.public(c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()))


# ------------------------------------------------------------------ Benutzerverwaltung (Admin)
def _user_list(c):
    out = []
    for r in c.execute("SELECT u.*, (SELECT COUNT(*) FROM profile_members m WHERE m.user_id=u.id) AS profiles FROM users u ORDER BY u.email"):
        out.append(dict(users.public(r), profiles=r["profiles"]))
    return out


@app.get("/api/users")
def user_list(admin=Depends(require_admin)):
    with db() as c:
        return dict(users=_user_list(c))


@app.post("/api/users")
def user_create(body: dict = Body(...), admin=Depends(require_admin)):
    pw = body.get("password") or security.generate_password()
    with db() as c:
        u = users.create(c, body.get("email"), pw, is_admin=bool(body.get("is_admin")), actor=admin["id"])
    return dict(user=u, password=None if body.get("password") else pw)


@app.put("/api/users/{uid}")
def user_update(uid: int, body: dict = Body(...), admin=Depends(require_admin)):
    pw = None
    with db() as c:
        if not c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            raise HTTPException(404, "Konto nicht gefunden")
        if "is_admin" in body:
            users.set_admin(c, uid, bool(body["is_admin"]), actor=admin["id"])
        if body.get("new_password"):
            pw = security.generate_password()
            users.set_password(c, uid, pw, actor=admin["id"])
        return dict(users=_user_list(c), password=pw)


@app.delete("/api/users/{uid}")
def user_delete(uid: int, admin=Depends(require_admin)):
    if uid == admin["id"]:
        raise HTTPException(400, "Das eigene Konto kann hier nicht gelöscht werden")
    with db() as c:
        users.delete(c, uid, heir_id=admin["id"], actor=admin["id"])
        return dict(users=_user_list(c))


# ------------------------------------------------------------------ Profile (Netz / Standort)
@app.get("/api/profiles")
def profile_list(user=Depends(require_user)):
    with db() as c:
        rows = c.execute(
            """SELECT p.*, m.role AS myrole,
                      (SELECT COUNT(*) FROM profile_members x WHERE x.profile_id = p.id) AS members,
                      (SELECT GROUP_CONCAT(u.email, ', ') FROM profile_members o JOIN users u ON u.id = o.user_id
                        WHERE o.profile_id = p.id AND o.role = 'owner') AS owners
               FROM profiles p LEFT JOIN profile_members m ON m.profile_id = p.id AND m.user_id = ?
               WHERE m.role IS NOT NULL OR ? = 1
               ORDER BY p.name COLLATE NOCASE""", (user["id"], 1 if user["is_admin"] else 0)).fetchall()
        return dict(profiles=[dict(profile_out(r, r["myrole"] or "owner", r["myrole"] is not None),
                                   members=r["members"], owners=r["owners"] or "") for r in rows])


@app.post("/api/profiles")
def profile_create(body: dict = Body(...), user=Depends(require_user)):
    name = text(body, "name", 120)
    if not name:
        raise HTTPException(400, "Name fehlt")
    with db() as c:
        cur = c.execute("INSERT INTO profiles(name, description, created, updated) VALUES(?,?,?,?)",
                        (name, text(body, "description", 2000), now(), now()))
        pid = cur.lastrowid
        c.execute("INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?,'owner')", (pid, user["id"]))
        audit(c, "profile.create", user["id"], pid, dict(name=name))
        touch(c, pid, user)
        p, role = profile_access(c, user, pid)
        return dict(profile=profile_out(p, role, True), members=members_of(c, pid))


@app.get("/api/profiles/{pid}")
def profile_get(pid: int, user=Depends(require_user)):
    with db() as c:
        p, role = profile_access(c, user, pid)
        member = c.execute("SELECT 1 FROM profile_members WHERE profile_id=? AND user_id=?", (pid, user["id"])).fetchone() is not None
        inbox = c.execute("SELECT COUNT(*) FROM devices WHERE profile_id=? AND status='discovered'", (pid,)).fetchone()[0]
        return dict(profile=profile_out(p, role, member), members=members_of(c, pid), inbox=inbox)


@app.put("/api/profiles/{pid}")
def profile_update(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        p, role = profile_access(c, user, pid, "edit")
        name = text(body, "name", 120) if "name" in body else p["name"]
        if not name:
            raise HTTPException(400, "Name fehlt")
        desc = text(body, "description", 2000) if "description" in body else p["description"]
        c.execute("UPDATE profiles SET name=?, description=?, updated=? WHERE id=?", (name, desc, now(), pid))
        audit(c, "profile.update", user["id"], pid, dict(name=name))
        touch(c, pid, user)
        p, role = profile_access(c, user, pid)
        return dict(profile=profile_out(p, role, True), members=members_of(c, pid))


@app.delete("/api/profiles/{pid}")
def profile_delete(pid: int, user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid, "owner")
        c.execute("DELETE FROM profiles WHERE id=?", (pid,))
        audit(c, "profile.delete", user["id"], pid, dict(name=p["name"]))
        touch(c)
    return dict(ok=True)


@app.post("/api/profiles/{pid}/members")
def member_add(pid: int, body: dict = Body(...), user=Depends(require_user)):
    role = body.get("role") or "view"
    if role not in ROLES:
        raise HTTPException(400, "Unbekannte Rolle")
    with db() as c:
        profile_access(c, user, pid, "owner")
        u = users.by_email(c, body.get("email"))
        if not u:
            raise HTTPException(404, "Kein Konto mit dieser E-Mail-Adresse")
        old = c.execute("SELECT role FROM profile_members WHERE profile_id=? AND user_id=?", (pid, u["id"])).fetchone()
        c.execute("""INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?,?)
                     ON CONFLICT(profile_id, user_id) DO UPDATE SET role=excluded.role""", (pid, u["id"], role))
        if old and old["role"] == "owner" and owner_count(c, pid) == 0:
            raise HTTPException(400, "Ein Profil braucht mindestens einen Besitzer")
        audit(c, "profile.share", user["id"], pid, dict(email=u["email"], role=role))
        touch(c, pid, user)
        return dict(members=members_of(c, pid))


@app.put("/api/profiles/{pid}/members/{uid}")
def member_update(pid: int, uid: int, body: dict = Body(...), user=Depends(require_user)):
    role = body.get("role")
    if role not in ROLES:
        raise HTTPException(400, "Unbekannte Rolle")
    with db() as c:
        profile_access(c, user, pid, "owner")
        if not c.execute("UPDATE profile_members SET role=? WHERE profile_id=? AND user_id=?", (role, pid, uid)).rowcount:
            raise HTTPException(404, "Mitglied nicht gefunden")
        if owner_count(c, pid) == 0:
            raise HTTPException(400, "Ein Profil braucht mindestens einen Besitzer")
        audit(c, "profile.role", user["id"], pid, dict(user=uid, role=role))
        touch(c, pid, user)
        return dict(members=members_of(c, pid))


@app.delete("/api/profiles/{pid}/members/{uid}")
def member_remove(pid: int, uid: int, user=Depends(require_user)):
    with db() as c:
        # Besitzer dürfen Mitglieder entfernen, jedes Mitglied darf sich selbst austragen.
        profile_access(c, user, pid, "view" if uid == user["id"] else "owner")
        if not c.execute("DELETE FROM profile_members WHERE profile_id=? AND user_id=?", (pid, uid)).rowcount:
            raise HTTPException(404, "Mitglied nicht gefunden")
        if owner_count(c, pid) == 0:
            raise HTTPException(400, "Ein Profil braucht mindestens einen Besitzer")
        audit(c, "profile.unshare", user["id"], pid, dict(user=uid))
        touch(c, pid, user)
        return dict(members=members_of(c, pid))


# ------------------------------------------------------------------ Einstellungen (Admin)
SMTP_FIELDS = ("host", "port", "security", "user", "sender", "app_url")


def _settings_out(c):
    smtp = dict(mailer.smtp_config(c))
    if smtp.get("password"):
        smtp["password"] = security.MASK
    return dict(registration_open=bool(get_setting(c, "registration_open", False)), smtp=smtp)


@app.get("/api/settings")
def settings_get(admin=Depends(require_admin)):
    with db() as c:
        return _settings_out(c)


@app.put("/api/settings")
def settings_put(body: dict = Body(...), admin=Depends(require_admin)):
    with db() as c:
        if "registration_open" in body:
            set_setting(c, "registration_open", bool(body["registration_open"]))
        if isinstance(body.get("smtp"), dict):
            new, old = body["smtp"], mailer.smtp_config(c)
            smtp = {k: str(new.get(k) or "").strip() for k in SMTP_FIELDS}
            if smtp["security"] not in ("starttls", "ssl", "none"):
                smtp["security"] = "starttls"
            pw = new.get("password") or ""
            if pw == security.MASK:
                smtp["password"] = old.get("password", "")
            elif pw:
                smtp["password"] = security.encrypt(pw)
            set_setting(c, "smtp", smtp)
        audit(c, "settings.update", admin["id"], detail=sorted(k for k in body if k in ("registration_open", "smtp")))
        touch(c)
        return _settings_out(c)


@app.post("/api/settings/smtp/test")
def smtp_test(request: Request, admin=Depends(require_admin)):
    with db() as c:
        cfg = mailer.smtp_config(c)
    try:
        mailer.send_test(cfg, admin["email"], admin["lang"] or lang_of(request))
    except Exception as ex:
        raise HTTPException(400, f"Versand fehlgeschlagen: {ex}")
    return dict(ok=True, to=admin["email"])


# ------------------------------------------------------------------ Fehlertexte, Oberfläche
ERR_EN = {
    "Bitte anmelden": "Please sign in", "Nur für Administratoren": "Administrators only",
    "Zu viele Versuche. Bitte einige Minuten warten.": "Too many attempts. Please wait a few minutes.",
    "Fehlender Request-Header": "Missing request header",
    "Die Registrierung ist geschlossen. Bitte einen Administrator um ein Konto bitten.": "Registration is closed. Please ask an administrator for an account.",
    "E-Mail-Adresse oder Passwort ist falsch": "E-mail or password is wrong",
    "Bitte eine gültige E-Mail-Adresse angeben": "Please enter a valid e-mail address",
    "Das Passwort muss mindestens 8 Zeichen haben": "The password must be at least 8 characters long",
    "Für diese E-Mail-Adresse gibt es schon ein Konto": "An account with this e-mail address already exists",
    "Der Link ist ungültig oder abgelaufen. Bitte einen neuen anfordern.": "This link is invalid or has expired. Please request a new one.",
    "Das aktuelle Passwort stimmt nicht": "The current password is wrong",
    "Konto nicht gefunden": "Account not found", "Es muss mindestens ein Administrator bleiben": "At least one administrator must remain",
    "Das eigene Konto kann hier nicht gelöscht werden": "You cannot delete your own account here",
    "Profil nicht gefunden": "Profile not found", "Dafür fehlen dir in diesem Profil die Rechte": "You do not have the rights for this in this profile",
    "Name fehlt": "Name missing", "Unbekannte Rolle": "Unknown role", "Kein Konto mit dieser E-Mail-Adresse": "No account with this e-mail address",
    "Ein Profil braucht mindestens einen Besitzer": "A profile needs at least one owner", "Mitglied nicht gefunden": "Member not found",
    "E-Mail-Versand ist nicht eingerichtet": "Sending e-mail is not set up",
    "Gerät nicht gefunden": "Device not found", "Standort nicht gefunden": "Location not found", "VLAN nicht gefunden": "VLAN not found",
    "Subnetz nicht gefunden": "Subnet not found", "Katalogeintrag nicht gefunden": "Catalog entry not found", "Port nicht gefunden": "Port not found",
    "Standort gehört nicht zu diesem Profil": "Location does not belong to this profile",
    "Gegenstelle gehört nicht zu diesem Profil": "Connected device does not belong to this profile",
    "VLAN gehört nicht zu diesem Profil": "VLAN does not belong to this profile",
    "Ein Gerät kann nicht mit sich selbst verbunden werden": "A device cannot be connected to itself",
    "Diese Verbindung würde einen Ring ergeben": "This connection would create a loop",
    "Ein Standort kann nicht in sich selbst liegen": "A location cannot be inside itself",
    "Ungültiges Netz, Beispiel: 192.168.178.0/24": "Invalid network, example: 192.168.178.0/24",
    "Das Gateway liegt nicht im Netz": "The gateway is not inside the network",
    "Für den DHCP-Bereich Anfang und Ende angeben": "Enter start and end of the DHCP range",
    "Der DHCP-Bereich muss im Netz liegen und mit der kleineren Adresse beginnen": "The DHCP range must be inside the network and start with the lower address",
    "Die VLAN-ID muss zwischen 1 und 4094 liegen": "The VLAN ID must be between 1 and 4094",
    "Hersteller und Modell sind erforderlich": "Manufacturer and model are required",
    "Diesen Katalogeintrag gibt es schon": "This catalog entry already exists",
    "Kein Sicherungsziel eingerichtet": "No backup target configured", "Keine gültige Sicherungsdatei": "Not a valid backup file",
    "Wiederherstellen ist nur in einer leeren Installation möglich": "Restoring is only possible in an empty installation",
    "Die Backup-Passphrase ist falsch": "The backup passphrase is wrong",
    "Die Backup-Passphrase muss mindestens 8 Zeichen haben": "The backup passphrase must be at least 8 characters long",
    "Gescannt werden IPv4-Netze": "Only IPv4 networks are scanned", "Für dieses Profil läuft schon ein Scan": "A scan is already running for this profile",
    "Auftrag nicht gefunden": "Job not found", "Unbekannte Aktion": "Unknown action", "Regel nicht gefunden": "Rule not found",
    "Bezeichnung und mindestens eine Bedingung sind erforderlich": "Label and at least one condition are required",
    "Unbekannter Treiber": "Unknown driver", "Adresse fehlt": "Address missing", "Integration nicht gefunden": "Integration not found",
    "Gerät gehört nicht zu diesem Profil": "Device does not belong to this profile", "Ungültige Angabe": "Invalid value",
    "Keine Antwort (Adresse, Community oder SNMP am Gerät prüfen)": "No answer (check address, community or SNMP on the device)",
    "Die FRITZ!Box verlangt eine Anmeldung. Benutzer und Passwort angeben.": "The FRITZ!Box requires a sign-in. Enter user and password.",
    "MQTT-Anmeldung abgelehnt (Benutzer oder Passwort prüfen)": "MQTT sign-in rejected (check user and password)",
    "Token abgelehnt (Long-Lived Access Token prüfen)": "Token rejected (check the long-lived access token)",
    "Token oder MQTT-Broker angeben": "Enter a token or an MQTT broker",
    "Konfigurations-Backup nicht gefunden": "Configuration backup not found",
    "Ungültige Positionen": "Invalid positions",
    "Zeitplan nicht gefunden": "Schedule not found",
    "Für die Quarantäne wird eine FRITZ!Box-Integration mit Benutzer gebraucht": "Quarantine needs a FRITZ!Box integration with a user",
    "Eintrag nicht gefunden": "Entry not found",
    "Uhrzeit im Format HH:MM angeben": "Enter the time as HH:MM",
    "Mindestens einen Wochentag wählen": "Choose at least one weekday",
    "Start und Ende dürfen nicht gleich sein": "Start and end must differ",
    "Diese Aktion ist für das Gerät nicht (mehr) verfügbar – Ansicht neu laden": "This action is not (or no longer) available for the device – reload the view",
    "Ungültige Zeit für das Zurückschalten": "Invalid time for switching back",
    "Kein geplantes Zurückschalten": "No scheduled switch-back",
    "Für Schaltaktionen Benutzer und Passwort der FRITZ!Box angeben (Recht „FRITZ!Box Einstellungen“)": "Enter the FRITZ!Box user and password for actions (permission “FRITZ!Box settings”)",
    "Kein Claude-API-Schlüssel hinterlegt (Einstellungen → KI)": "No Claude API key stored (Settings → AI)",
    "Hersteller und Modell werden für die KI-Suche gebraucht": "Manufacturer and model are needed for the AI lookup",
    "Die KI hat die Anfrage abgelehnt": "The AI declined the request",
    "Claude-API-Schlüssel ungültig": "Claude API key invalid",
    "Der API-Schlüssel darf dieses Modell oder die Websuche nicht nutzen (Websuche in der Console freigeben)": "The API key may not use this model or web search (enable web search in the Console)",
    "Claude API: Anfragelimit erreicht – kurz warten": "Claude API: rate limit reached – wait a moment",
    "Claude API: kein Guthaben auf dem Konto": "Claude API: no credit on the account",
    "Claude API nicht erreichbar (Internetzugang des Containers prüfen)": "Claude API not reachable (check the container's internet access)",
    "Die KI hat keinen Katalogeintrag geliefert – später erneut versuchen": "The AI did not return a catalog entry – try again later",
    "Authenticator-Schlüssel ungültig (Base32 aus der FRITZ!Box, z. B. „WI5M JOGQ …“)": "Authenticator key invalid (Base32 from the FRITZ!Box, e.g. “WI5M JOGQ …”)",
    "Bitte Systeminformationen einfügen": "Please paste system information",
    "Hersteller und Modell nicht erkannt – z. B. die Ausgabe von „dmidecode -t system“ einfügen": "Manufacturer and model not recognised – paste e.g. the output of “dmidecode -t system”",
    "Der Code aus der App hat 6 Ziffern": "The code from the app has 6 digits",
    "FRITZ!Box hat den Code nicht angenommen": "The FRITZ!Box did not accept the code",
    "Export abgelehnt – Code falsch oder abgelaufen? Neuen Code aus der App nehmen.": "Export rejected – wrong or expired code? Use a new code from the app.",
    "Anmeldung an der Weboberfläche der FRITZ!Box abgelehnt (Benutzer/Passwort prüfen)": "Sign-in to the FRITZ!Box web interface rejected (check user/password)",
    "Weboberfläche der FRITZ!Box nicht erreichbar": "FRITZ!Box web interface not reachable",
    "Für diese Integration gibt es keine Diagnose": "There is no diagnosis for this integration",
    "Das Gerät hat keine IPv4-Adresse": "The device has no IPv4 address",
    "nmap ist nicht installiert": "nmap is not installed",
    "Zeitlimit erreicht – „Schnell“ wählen oder später erneut versuchen": "Time limit reached – choose “Quick” or try again later",
    "Die FRITZ!Box verlangt für den Export eine Bestätigung (zweiter Faktor). Automatisch geht das nicht – bitte „Konfiguration sichern“ von Hand auslösen und an der FRITZ!Box bestätigen.": "The FRITZ!Box requires a confirmation (second factor) for the export. This cannot be done automatically – please start “Back up configuration” by hand and confirm on the FRITZ!Box.",
    "Bestätigung an der FRITZ!Box gesperrt (zu viele Versuche) – bis zu 60 Minuten warten": "Confirmation on the FRITZ!Box blocked (too many attempts) – wait up to 60 minutes",
    "Die FRITZ!Box wartet gerade auf eine andere Bestätigung – in zwei Minuten erneut versuchen": "The FRITZ!Box is waiting for another confirmation – try again in two minutes",
    "Diese Integration kennt keinen zweiten Faktor": "This integration has no second factor",
    "API-Schlüssel abgelehnt (in UniFi Network unter Integrationen einen lokalen Schlüssel erstellen, nicht den Site-Manager-Schlüssel)": "API key rejected (create a local key under Integrations in UniFi Network, not the Site Manager key)",
    "Integration API nicht gefunden": "Integration API not found",
    "Unerwartete Antwort (ist das eine UniFi-Konsole mit Network 9.0 oder neuer?)": "Unexpected response (is this a UniFi console with Network 9.0 or newer?)",
    "Nur Text-Konfigurationen lassen sich vergleichen": "Only text configurations can be compared",
    "Diese Integration unterstützt kein Konfigurations-Backup": "This integration does not support configuration backups",
    "Für das Konfigurations-Backup Benutzer und Passwort der FRITZ!Box angeben": "Enter the FRITZ!Box user and password for the configuration backup",
    "Benutzer hat nicht das Recht „FRITZ!Box Einstellungen“": "The user lacks the permission “FRITZ!Box settings”",
    "Router hat keine Einstellungsdatei geliefert": "The router did not provide a settings file",
    "Für das Konfigurations-Backup SSH-Benutzer und -Passwort des Switches angeben": "Enter the switch’s SSH user and password for the configuration backup",
    "SSH-Anmeldung abgelehnt (Benutzer oder Passwort prüfen)": "SSH sign-in rejected (check user and password)",
    "Gerät hat keine Konfiguration geliefert (Befehl prüfen)": "The device did not provide a configuration (check the command)",
}
# Meldungen mit Werten: Präfix übersetzen, Rest übernehmen
ERR_EN_PREFIX = {"Ungültige MAC-Adresse: ": "Invalid MAC address: ", "Ungültige IP-Adresse: ": "Invalid IP address: ",
                 "Ungültiges Netz: ": "Invalid network: ", "Ungültige Adresse: ": "Invalid address: ",
                 "Herstellerliste konnte nicht geladen werden: ": "Vendor list could not be loaded: ", "Ungültiger Ausdruck: ": "Invalid expression: ",
                 "FRITZ!Box nicht erreichbar: ": "FRITZ!Box not reachable: ", "Home Assistant nicht erreichbar: ": "Home Assistant not reachable: ",
                 "Proxmox nicht erreichbar: ": "Proxmox not reachable: ",
                 "Versand fehlgeschlagen: ": "Sending failed: "}
ERR_EN_RE = [(r"^Port (.+) ist schon mit (.+) belegt$", r"Port \1 is already connected to \2"),
             (r"^Das Subnetz (.+) gibt es schon$", r"The subnet \1 already exists"),
             (r"^MQTT-Broker „(.+)“ unbekannt: .*$", r"MQTT broker “\1” unknown: this name only exists inside Home Assistant. Enter the IP address of Home Assistant (port 1883)."),
             (r"^MQTT-Broker (.+) nicht erreichbar: (.*)$", r"MQTT broker \1 not reachable: \2"),
             (r"^VLAN (\d+) gibt es schon$", r"VLAN \1 already exists"),
             (r"^Netz (.+) ist zu groß zum Scannen \(höchstens /20\)$", r"Network \1 is too large to scan (at most /20)")]


def err_response(request, status, detail):
    if lang_of(request) == "en" and isinstance(detail, str):
        en = ERR_EN.get(detail)
        if en is None:
            for de_p, en_p in ERR_EN_PREFIX.items():
                if detail.startswith(de_p):
                    rest = detail[len(de_p):]
                    en = en_p + ERR_EN.get(rest, rest)
                    break
        if en is None:
            for pat, rep in ERR_EN_RE:
                if re.match(pat, detail):
                    en = re.sub(pat, rep, detail)
                    break
        detail = en or detail
    return JSONResponse({"error": detail}, status_code=status)


@app.exception_handler(HTTPException)
async def http_err(request, exc):
    return err_response(request, exc.status_code, exc.detail)


@app.exception_handler(users.UserError)
async def user_err(request, exc):
    return err_response(request, exc.status, exc.msg)


@app.get("/")
def index():
    # Versionsnummer an CSS/JS hängen: nach einem Update lädt der Browser die neuen Dateien statt der zwischengespeicherten.
    html = (BASE / "static" / "index.html").read_text(encoding="utf-8")
    for f in ("style.css", "i18n.js", "app.js", "inventory.js", "scan.js", "integrations.js", "topology.js", "history.js", "catalog.js"):
        html = html.replace(f'"/{f}"', f'"/{f}?v={VERSION}"')
    return Response(html, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


routes_backup.start_auto_backup()


class NoCacheStatic(StaticFiles):
    """Statische Dateien: Browser muss vor Verwendung nachfragen (ETag), sonst zeigt er nach Updates alte Dateien."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/", NoCacheStatic(directory=BASE / "static"), name="static")
