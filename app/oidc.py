"""Anmeldung über OpenID Connect (Authentik, Keycloak, Logto, Zitadel, Authelia …).

Ablauf: Authorization Code Flow mit PKCE (S256), state und nonce. state ist einmalig, zehn Minuten gültig und an den
Browser gebunden (Cookie dk_oidc, nur der Hash liegt in oidc_states). Das ID-Token wird über die Schlüssel des Anbieters
(JWKS) geprüft – RS256/384/512, PS256/384/512, ES256/384/512 (Logto signiert mit ES384) und HS256/384/512 mit dem
Client-Secret –, dazu Aussteller, Empfänger (client_id), Ablauf und nonce.

Konten: verknüpft über „<issuer>|<sub>“ (users.oidc_sub). Beim ersten Mal wird ein bestehendes Konto mit gleicher
E-Mail-Adresse verknüpft – nur wenn der Anbieter sie als bestätigt meldet (email_verified) oder der Administrator
das ausdrücklich erlaubt hat; sonst könnte jemand mit einer fremden, unbestätigten Adresse ein Konto übernehmen.
Neue Konten nur, wenn „automatisch anlegen“ eingeschaltet ist. Optional: nur Mitglieder einer Gruppe, Administratoren
über eine Gruppe (nur hinzufügen, nie automatisch entziehen). Der zweite Faktor von díktyo entfällt bei OIDC – den
übernimmt der Anbieter. Einstellungen unter settings["oidc"], Client-Secret verschlüsselt.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse

import httpx

from . import security
from .db import get_setting, set_setting

DEFAULTS = dict(enabled=False, label="", issuer="", client_id="", client_secret="", scopes="openid email profile", auto_create=False,
                trust_email=False, require_group="", admin_group="", groups_claim="groups", verify_tls=True)
STATE_TTL = 600
LEEWAY = 120
_cache = {}  # (url) -> (expires, data)


class OIDCError(Exception):
    pass


# ------------------------------------------------------------ Einstellungen
def settings(c, reveal=False):
    s = {**DEFAULTS, **{k: v for k, v in (get_setting(c, "oidc", {}) or {}).items() if k in DEFAULTS}}
    if not reveal:
        s["client_secret"] = security.MASK if s["client_secret"] else ""
    elif s["client_secret"]:
        try:
            s["client_secret"] = security.decrypt(s["client_secret"])
        except Exception:
            s["client_secret"] = ""
    return s


def save_settings(c, body):
    old = get_setting(c, "oidc", {}) or {}
    s = settings(c)
    for k in ("enabled", "auto_create", "trust_email", "verify_tls"):
        if k in body:
            s[k] = bool(body[k])
    for k, n in (("label", 40), ("issuer", 300), ("client_id", 200), ("scopes", 200), ("require_group", 100), ("admin_group", 100), ("groups_claim", 60)):
        if k in body:
            s[k] = str(body[k] or "").strip()[:n]
    s["issuer"] = s["issuer"].removesuffix("/.well-known/openid-configuration")  # falls die Discovery-Adresse eingefügt wurde
    if s["issuer"] and not s["issuer"].startswith(("https://", "http://")):
        raise OIDCError("Aussteller (Issuer) bitte mit https:// angeben")
    if "openid" not in s["scopes"].split():
        s["scopes"] = ("openid " + s["scopes"]).strip()
    sec = body.get("client_secret")
    s["client_secret"] = old.get("client_secret", "") if sec in (None, security.MASK) else (security.encrypt(sec) if sec else "")
    if s["enabled"] and not (s["issuer"] and s["client_id"]):
        raise OIDCError("Zum Einschalten Aussteller (Issuer) und Client-ID angeben")
    set_setting(c, "oidc", s)
    _cache.clear()
    return settings(c)


def public(c):
    s = settings(c)
    return dict(enabled=bool(s["enabled"] and s["issuer"] and s["client_id"]), label=s["label"] or "SSO")


# ------------------------------------------------------------ Anbieter
def _get(url, s, **kw):
    try:
        r = httpx.get(url, timeout=10, verify=s["verify_tls"], follow_redirects=True, **kw)
    except httpx.HTTPError as ex:
        raise OIDCError(f"Anbieter nicht erreichbar: {ex}")
    if r.status_code >= 400:
        raise OIDCError(f"Anbieter meldet HTTP {r.status_code} für {url}")
    try:
        return r.json()
    except ValueError:
        raise OIDCError(f"Keine gültige Antwort von {url}")


def discovery(s, fresh=False):
    url = s["issuer"].rstrip("/") + "/.well-known/openid-configuration"
    hit = _cache.get(url)
    if hit and hit[0] > time.time() and not fresh:
        return hit[1]
    d = _get(url, s)
    for k in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not d.get(k):
            raise OIDCError(f"Discovery-Dokument ohne „{k}“")
    _cache[url] = (time.time() + 600, d)
    return d


def _jwks(s, uri, fresh=False):
    hit = _cache.get(uri)
    if hit and hit[0] > time.time() and not fresh:
        return hit[1]
    keys = _get(uri, s).get("keys") or []
    _cache[uri] = (time.time() + 600, keys)
    return keys


def test(c):
    s = settings(c, reveal=True)
    if not s["issuer"]:
        raise OIDCError("Aussteller (Issuer) fehlt")
    d = discovery(s, fresh=True)
    keys = _jwks(s, d["jwks_uri"], fresh=True)
    return dict(issuer=d["issuer"], authorization_endpoint=d["authorization_endpoint"], token_endpoint=d["token_endpoint"],
                userinfo_endpoint=d.get("userinfo_endpoint", ""), keys=len(keys),
                algs=d.get("id_token_signing_alg_values_supported") or [])


# ------------------------------------------------------------ JWT
def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _int(b):
    return int.from_bytes(_b64d(b), "big")


HASHES = {"256": "SHA256", "384": "SHA384", "512": "SHA512"}


def verify_jwt(token, s, jwks_uri):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
    try:
        h64, p64, s64 = token.split(".")
        head, claims, sig = json.loads(_b64d(h64)), json.loads(_b64d(p64)), _b64d(s64)
    except (ValueError, TypeError):
        raise OIDCError("ID-Token ist ungültig")
    alg = str(head.get("alg") or "")
    if alg[2:] not in HASHES or alg[:2] not in ("RS", "PS", "ES", "HS"):
        raise OIDCError(f"Signaturverfahren {alg or '–'} wird nicht unterstützt")
    data = f"{h64}.{p64}".encode()
    hsh = getattr(hashes, HASHES[alg[2:]])()
    if alg.startswith("HS"):
        if not s["client_secret"]:
            raise OIDCError("ID-Token ist mit dem Client-Secret signiert, aber keins eingetragen")
        if not hmac.compare_digest(hmac.new(s["client_secret"].encode(), data, getattr(hashlib, "sha" + alg[2:])).digest(), sig):
            raise OIDCError("Signatur des ID-Tokens stimmt nicht")
        return claims
    kty = "RSA" if alg[0] in "RP" else "EC"
    for fresh in (False, True):  # Schlüsselwechsel beim Anbieter: einmal neu laden
        keys = [k for k in _jwks(s, jwks_uri, fresh) if k.get("kty") == kty and k.get("use", "sig") == "sig"]
        cand = [k for k in keys if k.get("kid") == head.get("kid")] if head.get("kid") else keys
        if cand:
            break
    if not cand:
        raise OIDCError("Kein passender Schlüssel des Anbieters für das ID-Token")
    for k in cand:
        try:
            if kty == "RSA":
                pub = rsa.RSAPublicNumbers(_int(k["e"]), _int(k["n"])).public_key()
                pad = padding.PKCS1v15() if alg[0] == "R" else padding.PSS(mgf=padding.MGF1(hsh), salt_length=hsh.digest_size)
                pub.verify(sig, data, pad, hsh)
            else:
                curve = {"P-256": ec.SECP256R1(), "P-384": ec.SECP384R1(), "P-521": ec.SECP521R1()}[k["crv"]]
                pub = ec.EllipticCurvePublicNumbers(_int(k["x"]), _int(k["y"]), curve).public_key()
                n = len(sig) // 2
                pub.verify(utils.encode_dss_signature(int.from_bytes(sig[:n], "big"), int.from_bytes(sig[n:], "big")), data, ec.ECDSA(hsh))
            return claims
        except (InvalidSignature, KeyError, ValueError):
            continue
    raise OIDCError("Signatur des ID-Tokens stimmt nicht")


def check_claims(claims, s, issuer, nonce):
    now = time.time()
    if claims.get("iss") != issuer:
        raise OIDCError("ID-Token stammt von einem anderen Aussteller")
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if s["client_id"] not in auds or (len(auds) > 1 and claims.get("azp") not in (None, s["client_id"])):
        raise OIDCError("ID-Token ist nicht für díktyo ausgestellt")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < now - LEEWAY:
        raise OIDCError("ID-Token ist abgelaufen – Uhrzeit von díktyo und Anbieter prüfen")
    if isinstance(claims.get("iat"), (int, float)) and claims["iat"] > now + 300:
        raise OIDCError("ID-Token liegt in der Zukunft – Uhrzeit von díktyo und Anbieter prüfen")
    if not nonce or not hmac.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise OIDCError("ID-Token passt nicht zu dieser Anmeldung (nonce)")
    if not claims.get("sub"):
        raise OIDCError("ID-Token ohne Benutzerkennung (sub)")


# ------------------------------------------------------------ Ablauf
def _pkce():
    v = secrets.token_urlsafe(48)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def start(c, redirect_uri, next_hash="", link_user=None):
    """-> (URL beim Anbieter, Browser-Bindung für das Cookie)"""
    s = settings(c, reveal=True)
    if not public(c)["enabled"]:
        raise OIDCError("Anmeldung über OIDC ist nicht eingeschaltet")
    d = discovery(s)
    state, nonce, bind = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = _pkce()
    c.execute("DELETE FROM oidc_states WHERE created<?", (time.time() - STATE_TTL,))
    c.execute("INSERT INTO oidc_states(state_hash, nonce, verifier, redirect_uri, next, link_user, bind_hash, created) VALUES(?,?,?,?,?,?,?,?)",
              (security.sha256(state), nonce, verifier, redirect_uri, next_hash if str(next_hash).startswith("#/") else "", link_user,
               security.sha256(bind), time.time()))
    q = dict(response_type="code", client_id=s["client_id"], redirect_uri=redirect_uri, scope=s["scopes"], state=state, nonce=nonce,
             code_challenge=challenge, code_challenge_method="S256")
    sep = "&" if "?" in d["authorization_endpoint"] else "?"
    return d["authorization_endpoint"] + sep + urllib.parse.urlencode(q), bind


def callback(c, code, state, bind):
    """Code einlösen und prüfen. -> dict(claims, next, link_user)"""
    s = settings(c, reveal=True)
    row = c.execute("SELECT * FROM oidc_states WHERE state_hash=?", (security.sha256(state or ""),)).fetchone()
    if row:
        c.execute("DELETE FROM oidc_states WHERE state_hash=?", (row["state_hash"],))  # nur einmal verwendbar
    if not row or row["created"] < time.time() - STATE_TTL:
        raise OIDCError("Anmeldung abgelaufen oder ungültig – bitte erneut versuchen")
    if not bind or not hmac.compare_digest(security.sha256(bind), row["bind_hash"]):
        raise OIDCError("Anmeldung wurde in einem anderen Browser begonnen – bitte erneut versuchen")
    if not code:
        raise OIDCError("Anbieter hat keinen Code geliefert")
    d = discovery(s)
    data = dict(grant_type="authorization_code", code=code, redirect_uri=row["redirect_uri"], code_verifier=row["verifier"], client_id=s["client_id"])
    auth = (s["client_id"], s["client_secret"]) if s["client_secret"] else None
    try:
        r = httpx.post(d["token_endpoint"], data=data, auth=auth, timeout=10, verify=s["verify_tls"], headers={"Accept": "application/json"})
    except httpx.HTTPError as ex:
        raise OIDCError(f"Anbieter nicht erreichbar: {ex}")
    if r.status_code >= 400:
        try:
            err = r.json()
            msg = err.get("error_description") or err.get("error") or ""
        except ValueError:
            msg = r.text[:120]
        raise OIDCError(f"Anbieter lehnt den Code ab (HTTP {r.status_code}): {msg}")
    tok = r.json()
    if not tok.get("id_token"):
        raise OIDCError("Anbieter hat kein ID-Token geliefert (Scope „openid“ fehlt?)")
    claims = verify_jwt(tok["id_token"], s, d["jwks_uri"])
    check_claims(claims, s, d["issuer"], row["nonce"])
    if (not claims.get("email") or s["groups_claim"] not in claims) and d.get("userinfo_endpoint") and tok.get("access_token"):
        try:
            ui = _get(d["userinfo_endpoint"], s, headers={"Authorization": f"Bearer {tok['access_token']}"})
            if ui.get("sub") == claims["sub"]:
                claims = {**ui, **claims, **{k: ui[k] for k in ("email", "email_verified", s["groups_claim"]) if k in ui and k not in claims}}
        except OIDCError:
            pass
    return dict(claims=claims, next=row["next"], link_user=row["link_user"], issuer=d["issuer"])


def _groups(claims, s):
    g = claims.get(s["groups_claim"] or "groups") or []
    if isinstance(g, str):
        g = [g]
    return {str(x) for x in g if isinstance(x, (str, int))} | {str(x.get("name")) for x in g if isinstance(x, dict) and x.get("name")}


def resolve_user(c, res):
    """Konto zur Anmeldung finden, verknüpfen oder anlegen. -> Benutzerzeile"""
    from . import users
    s = settings(c)
    claims, key = res["claims"], f"{res['issuer']}|{res['claims']['sub']}"
    groups = _groups(claims, s)
    if s["require_group"] and s["require_group"] not in groups:
        raise OIDCError(f"Für díktyo ist die Gruppe „{s['require_group']}“ beim Anbieter nötig")
    try:
        email = users.norm_email(claims.get("email") or "")
    except users.UserError:
        email = ""  # Anbieter ohne (gültige) E-Mail-Adresse: Zuordnung nur über sub
    verified = claims.get("email_verified") in (True, "true", "True", 1)
    if res.get("link_user"):  # Verknüpfen aus den eigenen Einstellungen
        other = c.execute("SELECT id FROM users WHERE oidc_sub=? AND id<>?", (key, res["link_user"])).fetchone()
        if other:
            raise OIDCError("Dieses Konto beim Anbieter ist schon mit einem anderen díktyo-Konto verknüpft")
        c.execute("UPDATE users SET oidc_sub=? WHERE id=?", (key, res["link_user"]))
        u = c.execute("SELECT * FROM users WHERE id=?", (res["link_user"],)).fetchone()
    else:
        u = c.execute("SELECT * FROM users WHERE oidc_sub=?", (key,)).fetchone()
        if not u and email:
            bymail = users.by_email(c, email)
            if bymail:
                if bymail["oidc_sub"]:
                    raise OIDCError("Das díktyo-Konto mit dieser E-Mail-Adresse ist schon mit einem anderen Anbieter-Konto verknüpft")
                if not (verified or s["trust_email"]):
                    raise OIDCError("Der Anbieter meldet die E-Mail-Adresse nicht als bestätigt – das Konto wird nicht automatisch verknüpft. "
                                    "Mit Passwort anmelden und unter Einstellungen → Mein Konto verknüpfen.")
                c.execute("UPDATE users SET oidc_sub=? WHERE id=?", (key, bymail["id"]))
                u = c.execute("SELECT * FROM users WHERE id=?", (bymail["id"],)).fetchone()
        if not u:
            if not s["auto_create"]:
                raise OIDCError("Für dieses Konto gibt es in díktyo noch keinen Zugang – ein Administrator muss es anlegen "
                                "oder „Konten automatisch anlegen“ einschalten")
            if not email:
                raise OIDCError("Der Anbieter liefert keine E-Mail-Adresse (Scope „email“ fehlt?)")
            first = users.count(c) == 0
            from .db import now
            uid = c.execute("INSERT INTO users(email, pw_hash, is_admin, created, oidc_sub) VALUES(?,?,?,?,?)",
                            (email, security.hash_pw(secrets.token_urlsafe(32)), 1 if first else 0, now(), key)).lastrowid
            u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if s["admin_group"] and s["admin_group"] in groups and not u["is_admin"]:
        c.execute("UPDATE users SET is_admin=1 WHERE id=?", (u["id"],))
        u = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    return u


def unlink(c, uid):
    c.execute("UPDATE users SET oidc_sub='' WHERE id=?", (uid,))
