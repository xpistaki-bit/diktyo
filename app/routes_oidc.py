"""API: Anmeldung über OpenID Connect – Start, Rückkehr vom Anbieter, Verknüpfen, Einstellungen (Admin)."""
import urllib.parse

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import mailer, oidc, users
from .auth import client_ip, current_user, lang_of, rate_limit, require_admin, require_user, start_session, touch
from .db import audit, db

router = APIRouter()
BIND_COOKIE = "dk_oidc"


def _redirect_uri(c, request):
    """Fest eingetragene Adresse der Weboberfläche (hinter einem Reverse-Proxy nötig) oder die aufgerufene."""
    base = (mailer.smtp_config(c).get("app_url") or str(request.base_url)).rstrip("/")
    return f"{base}/api/auth/oidc/callback"


def _fail(msg):
    r = RedirectResponse("/?oidc_error=" + urllib.parse.quote(str(msg)[:300]) + "#/", status_code=302)
    r.delete_cookie(BIND_COOKIE, path="/api/auth/oidc")
    return r


@router.get("/api/auth/oidc/start")
def oidc_start(request: Request, next: str = "", link: int = 0):
    rate_limit(f"oidc:{client_ip(request)}", 60)
    user = current_user(request) if link else None
    if link and not user:
        return _fail("Zum Verknüpfen zuerst anmelden")
    with db() as c:
        try:
            url, bind = oidc.start(c, _redirect_uri(c, request), next, user["id"] if user else None)
        except oidc.OIDCError as ex:
            return _fail(ex)
    r = RedirectResponse(url, status_code=302)
    r.set_cookie(BIND_COOKIE, bind, httponly=True, samesite="lax", max_age=oidc.STATE_TTL, path="/api/auth/oidc",
                 secure=request.url.scheme == "https")
    return r


@router.get("/api/auth/oidc/callback")
def oidc_callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    rate_limit(f"oidc:{client_ip(request)}", 60)
    if error:
        return _fail(f"Anbieter: {error_description or error}")
    with db() as c:
        try:
            res = oidc.callback(c, code, state, request.cookies.get(BIND_COOKIE))
            if res["link_user"]:
                me = current_user(request)
                if not me or me["id"] != res["link_user"]:
                    raise oidc.OIDCError("Verknüpfen nur in der Sitzung, in der es begonnen wurde")
            u = oidc.resolve_user(c, res)
        except oidc.OIDCError as ex:
            audit(c, "auth.oidc_failed", None, None, dict(ip=client_ip(request), error=str(ex)[:200]))
            err = str(ex)
        else:
            err = None
            target = "/#/einstellungen" if res["link_user"] else "/" + (res["next"] or "#/")
            r = RedirectResponse(target, status_code=302)
            r.delete_cookie(BIND_COOKIE, path="/api/auth/oidc")
            if res["link_user"]:
                audit(c, "auth.oidc_link", u["id"], None, dict(ip=client_ip(request)))
            else:
                start_session(c, r, u["id"], request)
                users.cleanup(c)
                audit(c, "auth.login", u["id"], None, dict(ip=client_ip(request), method="oidc"))
            return r
    return _fail(err)


@router.delete("/api/auth/oidc/link")
def oidc_unlink(user=Depends(require_user)):
    with db() as c:
        oidc.unlink(c, user["id"])
        audit(c, "auth.oidc_unlink", user["id"])
        return dict(ok=True)


@router.get("/api/auth/oidc/me")
def oidc_me(user=Depends(require_user)):
    with db() as c:
        r = c.execute("SELECT oidc_sub FROM users WHERE id=?", (user["id"],)).fetchone()
        return dict(oidc.public(c), linked=bool(r and r["oidc_sub"]))


@router.get("/api/settings/oidc")
def oidc_settings(request: Request, admin=Depends(require_admin)):
    with db() as c:
        return dict(oidc.settings(c), redirect_uri=_redirect_uri(c, request), app_url_set=bool(mailer.smtp_config(c).get("app_url")))


@router.put("/api/settings/oidc")
def oidc_settings_put(request: Request, body: dict = Body(...), admin=Depends(require_admin)):
    with db() as c:
        try:
            s = oidc.save_settings(c, body)
        except oidc.OIDCError as ex:
            raise HTTPException(400, str(ex))
        audit(c, "settings.oidc", admin["id"], detail=dict(enabled=s["enabled"]))
        touch(c)
        return dict(s, redirect_uri=_redirect_uri(c, request), app_url_set=bool(mailer.smtp_config(c).get("app_url")))


@router.post("/api/settings/oidc/test")
def oidc_settings_test(admin=Depends(require_admin)):
    with db() as c:
        try:
            return oidc.test(c)
        except oidc.OIDCError as ex:
            raise HTTPException(400, str(ex))
