"""díktyo – Web-App (FastAPI + SQLite)."""
import pathlib
import re
import threading
import time

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import catalog, mailer, msg_en, oidc, selfupdate, twofa, routes_actions, routes_backup, routes_catalog, routes_integrations, routes_inventory, routes_scan, routes_speed, routes_cabling, routes_vlans, routes_prometheus, routes_oidc, security, users
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
app.include_router(routes_speed.router)
app.include_router(routes_cabling.router)
app.include_router(routes_vlans.router)
app.include_router(routes_prometheus.router)
app.include_router(routes_oidc.router)


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
        return JSONResponse({"error": msg_en.en(msg) if lang_of(request) == "en" else msg}, status_code=403)
    return await call_next(request)


# ------------------------------------------------------------------ Übersetzung der Server-Meldungen (für gespeicherte Texte)
@app.get("/api/i18n/messages")
def i18n_messages():
    return JSONResponse(msg_en.table(), headers={"Cache-Control": "public, max-age=3600"})


# ------------------------------------------------------------------ Status
@app.get("/api/state")
def state(request: Request):
    with db() as c:
        first = users.count(c) == 0
        user = current_user(request)
        upd = None
        if user and user.get("is_admin"):  # Hinweis in der Kopfzeile, ohne Netzabfrage (prüft der Hintergrunddienst)
            chk = selfupdate.info(c)["check"]
            upd = dict(available=bool(chk.get("available")), latest=chk.get("latest"))
        return dict(version=VERSION, repo=REPO_URL, first_run=first,
                    registration_open=first or bool(get_setting(c, "registration_open", False)),
                    mail_enabled=mailer.enabled(c), min_pw=users.MIN_PW, user=user, oidc=oidc.public(c), update=upd)


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
        start_session(c, response, u["id"], request)
        return dict(user=users.public(c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()))


@app.post("/api/auth/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    rate_limit(f"login:{client_ip(request)}")
    with db() as c:
        u = users.by_email(c, body.get("email"))
        ok = security.check_pw(body.get("password") or "", u["pw_hash"] if u else security.DUMMY_HASH)
        if not u or not ok:
            raise HTTPException(401, "E-Mail-Adresse oder Passwort ist falsch")
        if twofa.enabled(u):  # zweiter Schritt: Code aus der Authenticator-App
            return dict(totp_required=True, ticket=twofa.new_ticket(c, u["id"]))
        start_session(c, response, u["id"], request)
        users.cleanup(c)
        audit(c, "auth.login", u["id"], None, dict(ip=client_ip(request)))
        return dict(user=users.public(u))


@app.post("/api/auth/login/totp")
def login_totp(request: Request, response: Response, body: dict = Body(...)):
    rate_limit(f"totp:{client_ip(request)}", 20)
    err = None
    with db() as c:
        try:
            u, kind = twofa.use_ticket(c, body.get("ticket"), body.get("code"))
        except twofa.TwoFAError as ex:
            err = str(ex)  # Fehlversuch zählt: erst nach dem Speichern melden
        else:
            start_session(c, response, u["id"], request)
            users.cleanup(c)
            audit(c, "auth.login", u["id"], None, dict(ip=client_ip(request), factor=kind))
            left = twofa.recovery_left(c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone())
            return dict(user=users.public(u), recovery_used=kind == "recovery", recovery_left=left)
    raise HTTPException(401, err)


# ------------------------------------------------------------------ Zweiter Faktor und Sitzungen (eigenes Konto)
def _me(c, user):
    return c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()


def _check_pw(row, pw):
    if not security.check_pw(pw or "", row["pw_hash"]):
        raise HTTPException(400, "Das Passwort stimmt nicht")


@app.get("/api/auth/2fa")
def twofa_state(user=Depends(require_user)):
    with db() as c:
        r = _me(c, user)
        return dict(enabled=twofa.enabled(r), recovery_left=twofa.recovery_left(r))


@app.post("/api/auth/2fa/setup")
def twofa_setup(body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        r = _me(c, user)
        _check_pw(r, body.get("password"))
        if twofa.enabled(r):
            raise HTTPException(400, "Der zweite Faktor ist schon eingeschaltet")
        return twofa.start_setup(c, user["id"], user["email"])


@app.post("/api/auth/2fa/enable")
def twofa_enable(request: Request, body: dict = Body(...), user=Depends(require_user)):
    rate_limit(f"totp-setup:{user['id']}", 10)
    with db() as c:
        try:
            codes = twofa.finish_setup(c, _me(c, user), body.get("code"))
        except twofa.TwoFAError as ex:
            raise HTTPException(400, str(ex))
        audit(c, "auth.2fa_on", user["id"], None, dict(ip=client_ip(request)))
        return dict(enabled=True, recovery=codes)


@app.post("/api/auth/2fa/disable")
def twofa_disable(request: Request, body: dict = Body(...), user=Depends(require_user)):
    rate_limit(f"totp-off:{user['id']}", 10)
    err = None
    with db() as c:
        r = _me(c, user)
        _check_pw(r, body.get("password"))
        if not twofa.verify_user(c, r, body.get("code")):
            err = "Code falsch"
        else:
            twofa.disable(c, user["id"])
            audit(c, "auth.2fa_off", user["id"], None, dict(ip=client_ip(request)))
            return dict(enabled=False)
    raise HTTPException(400, err)


@app.post("/api/auth/2fa/recovery")
def twofa_recovery(body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        r = _me(c, user)
        _check_pw(r, body.get("password"))
        if not twofa.enabled(r):
            raise HTTPException(400, "Der zweite Faktor ist nicht eingeschaltet")
        return dict(recovery=twofa.regenerate_recovery(c, user["id"]))


@app.get("/api/auth/sessions")
def sessions_list(user=Depends(require_user)):
    with db() as c:
        rows = c.execute("SELECT * FROM sessions WHERE user_id=? AND expires>? ORDER BY last_seen DESC, created DESC", (user["id"], time.time())).fetchall()
    return dict(sessions=[dict(id=r["token_hash"][:16], created=r["created"], last_seen=r["last_seen"] or r["created"], ip=r["ip"],
                               user_agent=r["user_agent"], current=r["token_hash"][:16] == user["sid"]) for r in rows])


@app.delete("/api/auth/sessions/{sid}")
def sessions_delete(sid: str, user=Depends(require_user)):
    """sid = Sitzung abmelden; „others“ = alle außer der aktuellen."""
    with db() as c:
        if sid == "others":
            n = c.execute("DELETE FROM sessions WHERE user_id=? AND substr(token_hash, 1, 16)<>?", (user["id"], user["sid"])).rowcount
        else:
            if len(sid) != 16 or sid == user["sid"]:
                raise HTTPException(400, "Die aktuelle Sitzung bitte über „Abmelden“ beenden")
            n = c.execute("DELETE FROM sessions WHERE user_id=? AND substr(token_hash, 1, 16)=?", (user["id"], sid)).rowcount
        audit(c, "auth.sessions_revoked", user["id"], None, dict(count=n))
    return dict(removed=n)


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
def change_password(request: Request, response: Response, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        r = c.execute("SELECT pw_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not security.check_pw(body.get("current") or "", r["pw_hash"]):
            raise HTTPException(400, "Das aktuelle Passwort stimmt nicht")
        users.set_password(c, user["id"], body.get("password"), actor=user["id"])
        start_session(c, response, user["id"], request)  # alle anderen Sitzungen wurden abgemeldet
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
        if body.get("reset_2fa") and uid != admin["id"]:  # ausgesperrt (Handy verloren): zweiten Faktor zurücksetzen
            twofa.disable(c, uid)
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            audit(c, "auth.2fa_reset", admin["id"], None, dict(user=uid))
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


# ------------------------------------------------------------------ Updates aus der Oberfläche (Admin)
@app.get("/api/update")
def update_get(admin=Depends(require_admin)):
    with db() as c:
        return dict(selfupdate.info(c), log=selfupdate.log_tail())


@app.post("/api/update/check")
def update_check(admin=Depends(require_admin)):
    with db() as c:
        selfupdate.check(c, force=True)
        return dict(selfupdate.info(c), log=selfupdate.log_tail())


@app.post("/api/update/start")
def update_start(admin=Depends(require_admin)):
    with db() as c:
        try:
            selfupdate.request(c, admin)
        except selfupdate.UpdateError as ex:
            raise HTTPException(400, str(ex))
        audit(c, "update.start", admin["id"], detail=dict(from_version=VERSION, to=(selfupdate.info(c)["check"] or {}).get("latest")))
        return dict(selfupdate.info(c), log=selfupdate.log_tail())


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
def err_response(request, status, detail):
    if lang_of(request) == "en" and isinstance(detail, str):
        detail = msg_en.en(detail)
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
    html = re.sub(r'"/([\w.-]+\.(?:js|css))"', lambda m: f'"/{m.group(1)}?v={VERSION}"', html)
    return Response(html, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


routes_backup.start_auto_backup()


class NoCacheStatic(StaticFiles):
    """Statische Dateien: Browser muss vor Verwendung nachfragen (ETag), sonst zeigt er nach Updates alte Dateien."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/", NoCacheStatic(directory=BASE / "static"), name="static")
