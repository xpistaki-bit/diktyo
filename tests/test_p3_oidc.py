"""Anmeldung über OIDC gegen einen nachgebauten Anbieter: echte Signaturen (ES384 wie Logto, RS256 wie Keycloak/Authentik,
HS256), PKCE/state/nonce, Browser-Bindung, Verknüpfen über bestätigte E-Mail, automatisch anlegen, Gruppen, Verknüpfen
aus der Sitzung."""
import base64
import hashlib
import hmac
import json
import time
import urllib.parse

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
from fastapi.testclient import TestClient

from app import main, oidc, users
from app.db import db
from tests.test_m6 import H, login

ISS = "https://idp.example.com/oidc"
CID = "diktyo-client"
SECRET = "geheim-fuer-tests"


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def ib64(n, size=None):
    return b64(n.to_bytes(size or (n.bit_length() + 7) // 8, "big"))


class FakeIdP:
    def __init__(self, monkeypatch):
        self.ec = ec.generate_private_key(ec.SECP384R1())
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.alg, self.claims, self.codes, self.last_auth = "ES384", {}, {}, None
        en, rn = self.ec.public_key().public_numbers(), self.rsa.public_key().public_numbers()
        self.jwks = {"keys": [dict(kty="EC", crv="P-384", kid="ec1", use="sig", x=ib64(en.x, 48), y=ib64(en.y, 48)),
                              dict(kty="RSA", kid="rsa1", use="sig", n=ib64(rn.n), e=ib64(rn.e))]}
        monkeypatch.setattr(oidc.httpx, "get", self.get)
        monkeypatch.setattr(oidc.httpx, "post", self.post)
        oidc._cache.clear()

    def get(self, url, **kw):
        if url == ISS + "/.well-known/openid-configuration":
            return httpx.Response(200, json=dict(issuer=ISS, authorization_endpoint=ISS + "/auth", token_endpoint=ISS + "/token",
                                                 jwks_uri=ISS + "/jwks", userinfo_endpoint=ISS + "/me"))
        if url == ISS + "/jwks":
            return httpx.Response(200, json=self.jwks)
        return httpx.Response(404)

    def sign(self, claims):
        head = {"alg": self.alg, "typ": "JWT", "kid": {"ES384": "ec1", "RS256": "rsa1"}.get(self.alg)}
        data = f"{b64(json.dumps(head).encode())}.{b64(json.dumps(claims).encode())}".encode()
        if self.alg == "ES384":
            r, s = utils.decode_dss_signature(self.ec.sign(data, ec.ECDSA(hashes.SHA384())))
            sig = r.to_bytes(48, "big") + s.to_bytes(48, "big")
        elif self.alg == "RS256":
            sig = self.rsa.sign(data, padding.PKCS1v15(), hashes.SHA256())
        else:
            sig = hmac.new(SECRET.encode(), data, hashlib.sha256).digest()
        return data.decode() + "." + b64(sig)

    def post(self, url, data=None, auth=None, **kw):
        assert url == ISS + "/token" and auth == (CID, SECRET)
        a = self.codes.pop(data["code"], None)
        if not a:
            return httpx.Response(400, json={"error": "invalid_grant"})
        # PKCE: code_verifier muss zur code_challenge passen
        assert b64(hashlib.sha256(data["code_verifier"].encode()).digest()) == a["code_challenge"]
        now = int(time.time())
        claims = dict(iss=ISS, aud=CID, exp=now + 300, iat=now, nonce=a["nonce"], **self.claims)
        return httpx.Response(200, json=dict(id_token=self.sign(claims), access_token="at", token_type="Bearer"))

    def authorize(self, location, **claims):
        """Was der Anbieter nach der Anmeldung tut: Code ausstellen, zurück zu redirect_uri."""
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query))
        assert q["response_type"] == "code" and q["client_id"] == CID and q["code_challenge_method"] == "S256" and "openid" in q["scope"]
        code = "c" + q["state"][:8]
        self.codes[code] = q
        self.claims = claims
        return f"/api/auth/oidc/callback?code={code}&state={q['state']}", q


def enable(admin, **kw):
    body = dict(enabled=True, label="Authentik", issuer=ISS, client_id=CID, client_secret=SECRET, **kw)
    r = admin.put("/api/settings/oidc", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def flow(idp, cl=None, start="/api/auth/oidc/start", **claims):
    cl = cl or TestClient(main.app)
    r = cl.get(start, follow_redirects=False)
    assert r.status_code == 302, r.text
    if not r.headers["location"].startswith(ISS):
        return cl, r
    cb, _ = idp.authorize(r.headers["location"], **claims)
    return cl, cl.get(cb, follow_redirects=False)


def err_of(r):
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r.headers["location"]).query))
    return q.get("oidc_error", "")


def test_oidc_login(monkeypatch):
    idp = FakeIdP(monkeypatch)
    admin = login("oidc-admin@x.de")
    assert TestClient(main.app).get("/api/state").json()["oidc"]["enabled"] is False
    s = enable(admin)
    assert s["client_secret"] == "••••••" or s["client_secret"] != SECRET
    assert s["redirect_uri"].endswith("/api/auth/oidc/callback")
    assert admin.post("/api/settings/oidc/test", headers=H).json()["keys"] == 2
    assert TestClient(main.app).get("/api/state").json()["oidc"] == {"enabled": True, "label": "Authentik"}

    # unbekanntes Konto, automatisch anlegen aus -> abgelehnt
    _, r = flow(idp, sub="u-1", email="neu@x.de", email_verified=True)
    assert "noch keinen Zugang" in err_of(r)
    # bestehendes Konto mit bestätigter E-Mail -> verknüpft und angemeldet (ES384)
    with db() as c:
        if not users.by_email(c, "anna@x.de"):
            users.create(c, "anna@x.de", "passwort123")
    cl, r = flow(idp, sub="anna-sub", email="anna@x.de", email_verified=True)
    assert r.headers["location"] == "/#/" and cl.get("/api/state").json()["user"]["email"] == "anna@x.de"
    # nächstes Mal über sub, auch mit anderer E-Mail beim Anbieter (RS256)
    idp.alg = "RS256"
    cl, r = flow(idp, sub="anna-sub", email="anna.neu@x.de")
    assert cl.get("/api/state").json()["user"]["email"] == "anna@x.de"
    # Direktlink bleibt erhalten
    cl, r = flow(idp, start="/api/auth/oidc/start?next=%23/p/1/geraete/5", sub="anna-sub")
    assert r.status_code == 302, (r.status_code, r.text[:300])
    assert r.headers["location"] == "/#/p/1/geraete/5"
    # unbestätigte E-Mail verknüpft kein bestehendes Konto (Übernahme verhindern)
    with db() as c:
        if not users.by_email(c, "bob@x.de"):
            users.create(c, "bob@x.de", "passwort123")
    _, r = flow(idp, sub="fremd", email="bob@x.de", email_verified=False)
    assert "nicht als bestätigt" in err_of(r)
    # automatisch anlegen, HS256, Gruppe nötig, Admin über Gruppe
    idp.alg = "HS256"
    enable(admin, auto_create=True, require_group="diktyo", admin_group="diktyo-admins")
    _, r = flow(idp, sub="c-1", email="carla@x.de", groups=["andere"])
    assert "Gruppe „diktyo“" in err_of(r)
    cl, r = flow(idp, sub="c-1", email="carla@x.de", groups=["diktyo", "diktyo-admins"])
    me = cl.get("/api/state").json()["user"]
    assert me["email"] == "carla@x.de" and me["is_admin"]


def test_oidc_security(monkeypatch):
    idp = FakeIdP(monkeypatch)
    admin = login("oidc-admin@x.de")
    enable(admin, auto_create=True)
    # state nur einmal verwendbar
    cl = TestClient(main.app)
    r = cl.get("/api/auth/oidc/start", follow_redirects=False)
    cb, q = idp.authorize(r.headers["location"], sub="d-1", email="dora@x.de", email_verified=True)
    assert cl.get(cb, follow_redirects=False).headers["location"] == "/#/"
    idp.codes["c" + q["state"][:8]] = q
    assert "abgelaufen oder ungültig" in err_of(cl.get(cb, follow_redirects=False))
    # anderer Browser (ohne Bindungs-Cookie) kann den Rücksprung nicht verwenden
    r = cl.get("/api/auth/oidc/start", follow_redirects=False)
    cb, _ = idp.authorize(r.headers["location"], sub="d-1", email="dora@x.de")
    assert "anderen Browser" in err_of(TestClient(main.app).get(cb, follow_redirects=False))
    # falsche Signatur, falscher Empfänger, falsche nonce
    for bad in ("sig", "aud", "nonce", "iss"):
        cl = TestClient(main.app)
        r = cl.get("/api/auth/oidc/start", follow_redirects=False)
        cb, q = idp.authorize(r.headers["location"], sub="d-1", email="dora@x.de")
        orig = idp.sign
        if bad == "sig":
            idp.sign = lambda claims: orig(claims)[:-6] + "AAAAAA"
        elif bad == "aud":
            idp.sign = lambda claims: orig(dict(claims, aud="anderer-client"))
        elif bad == "nonce":
            idp.sign = lambda claims: orig(dict(claims, nonce="falsch"))
        else:
            idp.sign = lambda claims: orig(dict(claims, iss="https://boese.example.com"))
        msg = err_of(cl.get(cb, follow_redirects=False))
        idp.sign = orig
        assert msg and "/#/" not in msg, (bad, msg)
        assert cl.get("/api/state").json()["user"] is None
    # Fehler vom Anbieter wird angezeigt
    assert "access_denied" in err_of(TestClient(main.app).get("/api/auth/oidc/callback?error=access_denied", follow_redirects=False))


def test_oidc_link_from_settings(monkeypatch):
    idp = FakeIdP(monkeypatch)
    admin = login("oidc-admin@x.de")
    enable(admin)
    with db() as c:
        if not users.by_email(c, "eva@x.de"):
            users.create(c, "eva@x.de", "passwort123")
    eva = login("eva@x.de")
    assert eva.get("/api/auth/oidc/me").json()["linked"] is False
    _, r = flow(idp, cl=eva, start="/api/auth/oidc/start?link=1", sub="eva-anbieter", email="eva@firma.example", email_verified=False)
    assert r.headers["location"] == "/#/einstellungen"
    assert eva.get("/api/auth/oidc/me").json()["linked"] is True
    # jetzt Anmeldung ohne Passwort möglich
    cl, r = flow(idp, sub="eva-anbieter", email="eva@firma.example")
    assert cl.get("/api/state").json()["user"]["email"] == "eva@x.de"
    # lösen
    eva.delete("/api/auth/oidc/link", headers=H)
    _, r = flow(idp, sub="eva-anbieter", email="eva@firma.example")
    assert "noch keinen Zugang" in err_of(r)
    # Verknüpfen ohne Anmeldung nicht möglich; Einstellungen nur für Admins
    _, r = flow(idp, start="/api/auth/oidc/start?link=1")
    assert "zuerst anmelden" in err_of(r)
    assert eva.get("/api/settings/oidc").status_code == 403


@pytest.fixture(autouse=True)
def _reset_oidc():
    yield
    with db() as c:
        c.execute("DELETE FROM settings WHERE key='oidc'")
