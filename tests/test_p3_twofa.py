"""Anmeldung mit zweitem Faktor (TOTP), Wiederherstellungscodes, Sitzungsverwaltung, Zurücksetzen durch Admin und CLI."""
import time

from fastapi.testclient import TestClient

from app import cli, main, twofa, users
from app.db import db

H = {"X-Requested-With": "diktyo"}


def client(email, pw="passwort123", admin=False):
    with db() as c:
        if not users.by_email(c, email):
            users.create(c, email, pw, is_admin=admin)
    cl = TestClient(main.app, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"})
    r = cl.post("/api/auth/login", json={"email": email, "password": pw}, headers=H)
    return cl, r


def now_code(secret, offset=0):
    return twofa.code_at(secret.replace(" ", ""), int(time.time() // twofa.STEP) + offset)


def test_totp_algorithm_rfc6238():
    # Testvektor aus RFC 6238 (SHA-1, Schlüssel „12345678901234567890“, T=59 -> 94287082, 6 Stellen: 287082)
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert twofa.code_at(secret, 59 // 30) == "287082"
    assert twofa.check(secret, "287082", 0, t=59) == 1 and twofa.check(secret, "287082", 1, t=59) is None  # schon benutzt


def test_setup_login_recovery_disable():
    email = "zwei@x.de"
    cl, r = client(email)
    assert r.json()["user"]["totp"] is False
    assert cl.post("/api/auth/2fa/setup", json={"password": "falsch"}, headers=H).status_code == 400
    s = cl.post("/api/auth/2fa/setup", json={"password": "passwort123"}, headers=H).json()
    assert s["uri"].startswith("otpauth://totp/") and "<svg" in s["qr"] and len(s["secret"].replace(" ", "")) == 32
    assert cl.post("/api/auth/2fa/enable", json={"code": "000000"}, headers=H).status_code == 400
    codes = cl.post("/api/auth/2fa/enable", json={"code": now_code(s["secret"])}, headers=H).json()["recovery"]
    assert len(codes) == 10 and cl.get("/api/auth/2fa").json() == {"enabled": True, "recovery_left": 10}

    # Anmeldung: Passwort allein gibt keine Sitzung
    cl2 = TestClient(main.app)
    r = cl2.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H).json()
    assert r["totp_required"] and "user" not in r
    assert cl2.get("/api/auth/sessions").status_code == 401
    bad = cl2.post("/api/auth/login/totp", json={"ticket": r["ticket"], "code": "123456"}, headers=H)
    assert bad.status_code == 401 and "noch 4 Versuche" in bad.json()["error"]  # Fehlversuch wurde gespeichert
    # der beim Einschalten benutzte Code gilt kein zweites Mal
    assert cl2.post("/api/auth/login/totp", json={"ticket": r["ticket"], "code": now_code(s["secret"])}, headers=H).status_code == 401
    ok = cl2.post("/api/auth/login/totp", json={"ticket": r["ticket"], "code": now_code(s["secret"], 1)}, headers=H)
    assert ok.status_code == 200 and ok.json()["user"]["email"] == email
    assert cl2.post("/api/auth/login/totp", json={"ticket": r["ticket"], "code": now_code(s["secret"], 1)}, headers=H).status_code == 401  # Ticket verbraucht

    # Wiederherstellungscode: einmal
    cl3 = TestClient(main.app)
    t3 = cl3.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H).json()["ticket"]
    r3 = cl3.post("/api/auth/login/totp", json={"ticket": t3, "code": codes[0].upper().replace("-", " ")}, headers=H).json()
    assert r3["recovery_used"] and r3["recovery_left"] == 9
    t4 = cl3.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H).json()["ticket"]
    assert cl3.post("/api/auth/login/totp", json={"ticket": t4, "code": codes[0]}, headers=H).status_code == 401

    # nach 5 Fehlversuchen ist das Ticket verbraucht
    t5 = cl3.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H).json()["ticket"]
    for _ in range(5):
        cl3.post("/api/auth/login/totp", json={"ticket": t5, "code": "111111"}, headers=H)
    assert "abgelaufen" in cl3.post("/api/auth/login/totp", json={"ticket": t5, "code": codes[1]}, headers=H).json()["error"]

    # Ausschalten braucht Passwort und Code
    assert cl.post("/api/auth/2fa/disable", json={"password": "passwort123", "code": "000000"}, headers=H).status_code == 400
    assert cl.post("/api/auth/2fa/disable", json={"password": "passwort123", "code": codes[2]}, headers=H).json() == {"enabled": False}
    r = TestClient(main.app).post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H).json()
    assert r["user"]["totp"] is False


def test_sessions_list_and_revoke():
    email = "sitzung@x.de"
    a, _ = client(email)
    b, _ = client(email)
    c_, _ = client(email)
    s = a.get("/api/auth/sessions").json()["sessions"]
    assert len(s) == 3 and sum(x["current"] for x in s) == 1 and s[0]["user_agent"].startswith("Mozilla")
    other = next(x for x in s if not x["current"])["id"]
    assert a.delete(f"/api/auth/sessions/{next(x for x in s if x['current'])['id']}", headers=H).status_code == 400
    assert a.delete(f"/api/auth/sessions/{other}", headers=H).json()["removed"] == 1
    assert a.delete("/api/auth/sessions/others", headers=H).json()["removed"] == 1
    assert b.get("/api/auth/sessions").status_code == 401 and c_.get("/api/auth/sessions").status_code == 401
    assert len(a.get("/api/auth/sessions").json()["sessions"]) == 1


def test_admin_and_cli_reset(capsys):
    email = "verloren@x.de"
    u, _ = client(email)
    s = u.post("/api/auth/2fa/setup", json={"password": "passwort123"}, headers=H).json()
    u.post("/api/auth/2fa/enable", json={"code": now_code(s["secret"])}, headers=H)
    admin, _ = client("chef2fa@x.de", admin=True)
    uid = next(x["id"] for x in admin.get("/api/users").json()["users"] if x["email"] == email)
    assert next(x for x in admin.get("/api/users").json()["users"] if x["email"] == email)["totp"] is True
    r = admin.put(f"/api/users/{uid}", json={"reset_2fa": True}, headers=H).json()
    assert next(x for x in r["users"] if x["email"] == email)["totp"] is False
    assert u.get("/api/auth/sessions").status_code == 401  # abgemeldet
    # per Kommandozeile
    u2, _ = client(email)
    s = u2.post("/api/auth/2fa/setup", json={"password": "passwort123"}, headers=H).json()
    u2.post("/api/auth/2fa/enable", json={"code": now_code(s["secret"])}, headers=H)
    cli.main(["reset-2fa", email])
    assert "ausgeschaltet" in capsys.readouterr().out
    with db() as c:
        assert not twofa.enabled(users.by_email(c, email))
