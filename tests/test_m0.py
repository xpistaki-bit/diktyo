"""M0: Konten, Sitzungen, Passwort-Reset, Profile mit Teilen, Einstellungen."""
from fastapi.testclient import TestClient

from app import main, security, users
from app.db import db

H = {"X-Requested-With": "diktyo"}


def client():
    return TestClient(main.app)


def test_flow():
    admin = client()
    st = admin.get("/api/state").json()
    assert st["first_run"] and st["registration_open"] and st["user"] is None

    # ändernde Aufrufe ohne CSRF-Header werden abgewiesen
    assert admin.post("/api/auth/register", json={"email": "a@x.de", "password": "geheim123"}).status_code == 403
    # zu kurzes Passwort
    r = admin.post("/api/auth/register", json={"email": "a@x.de", "password": "kurz"}, headers=H)
    assert r.status_code == 400
    r = admin.post("/api/auth/register", json={"email": "A@X.de", "password": "geheim123"}, headers=H)
    assert r.status_code == 200 and r.json()["user"]["is_admin"] and r.json()["user"]["email"] == "a@x.de"

    # zweite Selbstregistrierung ist geschlossen
    other = client()
    assert other.post("/api/auth/register", json={"email": "b@x.de", "password": "geheim123"}, headers=H).status_code == 403

    # Admin legt Konto an, Passwort wird erzeugt
    r = admin.post("/api/users", json={"email": "b@x.de"}, headers=H).json()
    pw_b = r["password"]
    assert pw_b and not r["user"]["is_admin"]
    assert admin.post("/api/users", json={"email": "b@x.de"}, headers=H).status_code == 409

    # Anmeldung
    assert other.post("/api/auth/login", json={"email": "b@x.de", "password": "falsch!!"}, headers=H).status_code == 401
    assert other.post("/api/auth/login", json={"email": "b@x.de", "password": pw_b}, headers=H).status_code == 200
    assert other.get("/api/users").status_code == 403

    # englische Fehlermeldung
    r = other.get("/api/users", headers={"X-Lang": "en"})
    assert r.json()["error"] == "Administrators only"

    # Profil anlegen und teilen
    p = admin.post("/api/profiles", json={"name": "Zuhause", "description": "Heimnetz"}, headers=H).json()["profile"]
    assert p["role"] == "owner"
    assert other.get(f"/api/profiles/{p['id']}").status_code == 404
    assert other.get("/api/profiles").json()["profiles"] == []
    r = admin.post(f"/api/profiles/{p['id']}/members", json={"email": "b@x.de", "role": "view"}, headers=H)
    assert r.status_code == 200 and len(r.json()["members"]) == 2
    assert other.get(f"/api/profiles/{p['id']}").json()["profile"]["role"] == "view"
    assert other.put(f"/api/profiles/{p['id']}", json={"name": "X"}, headers=H).status_code == 403
    uid_b = users_id("b@x.de")
    admin.put(f"/api/profiles/{p['id']}/members/{uid_b}", json={"role": "edit"}, headers=H)
    assert other.put(f"/api/profiles/{p['id']}", json={"name": "Daheim"}, headers=H).json()["profile"]["name"] == "Daheim"
    assert other.delete(f"/api/profiles/{p['id']}", headers=H).status_code == 403

    # letzter Besitzer kann nicht herabgestuft werden
    uid_a = users_id("a@x.de")
    assert admin.put(f"/api/profiles/{p['id']}/members/{uid_a}", json={"role": "view"}, headers=H).status_code == 400

    # Konto b löschen, sein eigenes Profil geht an den Admin
    q = other.post("/api/profiles", json={"name": "Eltern"}, headers=H).json()["profile"]
    admin.delete(f"/api/users/{uid_b}", headers=H)
    r = admin.get(f"/api/profiles/{q['id']}").json()
    assert [m["email"] for m in r["members"]] == ["a@x.de"] and r["members"][0]["role"] == "owner"
    assert other.get("/api/state").json()["user"] is None  # Sitzung ist mit dem Konto weg


def test_password_reset_and_change():
    c = client()
    with db() as con:
        if not users.by_email(con, "c@x.de"):
            users.create(con, "c@x.de", "anfang123")
        uid = users.by_email(con, "c@x.de")["id"]
    assert c.post("/api/auth/login", json={"email": "c@x.de", "password": "anfang123"}, headers=H).status_code == 200

    # ohne SMTP: gleiche Antwort, kein Versand
    assert c.post("/api/auth/forgot", json={"email": "c@x.de"}, headers=H).json() == {"mail_enabled": False}

    with db() as con:
        tok = users.create_reset_token(con, uid)
    assert c.post("/api/auth/reset", json={"token": "falsch", "password": "neuneu123"}, headers=H).status_code == 400
    assert c.post("/api/auth/reset", json={"token": tok, "password": "neuneu123"}, headers=H).status_code == 200
    assert c.post("/api/auth/reset", json={"token": tok, "password": "nochmal123"}, headers=H).status_code == 400
    assert c.get("/api/state").json()["user"] is None  # Reset meldet alle Sitzungen ab

    assert c.post("/api/auth/login", json={"email": "c@x.de", "password": "neuneu123"}, headers=H).status_code == 200
    assert c.post("/api/auth/password", json={"current": "falsch", "password": "x" * 9}, headers=H).status_code == 400
    assert c.post("/api/auth/password", json={"current": "neuneu123", "password": "y" * 9}, headers=H).status_code == 200
    assert c.get("/api/state").json()["user"]["email"] == "c@x.de"  # neue Sitzung nach Passwortwechsel


def test_settings_secret_is_encrypted():
    a = client()
    a.post("/api/auth/login", json={"email": "a@x.de", "password": "geheim123"}, headers=H)
    r = a.put("/api/settings", json={"registration_open": True, "smtp": {"host": "mail.example", "port": "587", "password": "s3cret"}}, headers=H).json()
    assert r["smtp"]["password"] == security.MASK and r["registration_open"]
    with db() as con:
        from app.db import get_setting
        stored = get_setting(con, "smtp")["password"]
    assert stored != "s3cret" and security.decrypt(stored) == "s3cret"
    # Maske beim Speichern behält das alte Passwort
    a.put("/api/settings", json={"smtp": {"host": "mail.example", "password": security.MASK}}, headers=H)
    with db() as con:
        from app.db import get_setting
        assert security.decrypt(get_setting(con, "smtp")["password"]) == "s3cret"
    assert a.get("/api/state").json()["mail_enabled"]


def test_cli(capsys):
    from app import cli
    cli.main(["create-user", "d@x.de", "passwort1"])
    cli.main(["reset-password", "d@x.de", "passwort2"])
    with db() as con:
        assert security.check_pw("passwort2", users.by_email(con, "d@x.de")["pw_hash"])
    cli.main(["list-users"])
    assert "d@x.de" in capsys.readouterr().out


def users_id(email):
    with db() as con:
        return users.by_email(con, email)["id"]
