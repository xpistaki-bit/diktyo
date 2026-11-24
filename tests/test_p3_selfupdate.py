"""Updates aus der Oberfläche: neue Version auf GitHub erkennen (mit Änderungsliste), Anfrage-Datei für den Update-Dienst,
Status, nur für Administratoren, Hinweis in /api/state; Update-Skript nimmt nichts aus der Anfrage."""
import json
import pathlib

import httpx

from app import selfupdate
from app.db import db
from tests.test_m6 import H, login

ROOT = pathlib.Path(__file__).resolve().parent.parent


def fake_github(monkeypatch, latest="9.9.0"):
    def get(url, **kw):
        if url.endswith("/app/version.py"):
            return httpx.Response(200, text=f'"""x"""\nVERSION = "{latest}"\n', request=httpx.Request("GET", url))
        if "/commits" in url:
            return httpx.Response(200, json=[{"commit": {"message": f"v{latest}: Neue Funktion\n\nDetails"}},
                                             {"commit": {"message": "v9.8.1: Fehler behoben"}},
                                             {"commit": {"message": "Aufräumen ohne Version"}},
                                             {"commit": {"message": "v0.1.0: uralt"}}], request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))
    monkeypatch.setattr(selfupdate.httpx, "get", get)


def test_check_and_request(monkeypatch, tmp_path):
    fake_github(monkeypatch)
    with db() as c:
        r = selfupdate.check(c, force=True)
    assert r["available"] and r["latest"] == "9.9.0" and [n["version"] for n in r["notes"]] == ["9.9.0", "9.8.1"]
    with db() as c:  # innerhalb von 12 Stunden keine neue Abfrage
        monkeypatch.setattr(selfupdate.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("keine Abfrage erwartet")))
        assert selfupdate.check(c)["latest"] == "9.9.0"
    # Update-Dienst eingerichtet (Pfad-Einheit vorhanden, Verzeichnis beschreibbar)
    unit = tmp_path / "diktyo-update.path"
    unit.write_text("[Path]")
    monkeypatch.setattr(selfupdate, "PATH_UNIT", unit)
    monkeypatch.setattr(selfupdate, "UPDATE_DIR", tmp_path / "update")
    (tmp_path / "update").mkdir()
    admin = login("upd-admin@x.de")
    r = admin.get("/api/update").json()
    assert r["kind"] == "systemd" and r["check"]["available"] and r["installed"]
    assert admin.get("/api/state").json()["update"] == {"available": True, "latest": "9.9.0"}
    r = admin.post("/api/update/start", headers=H).json()
    req = json.loads((tmp_path / "update" / "request.json").read_text())
    assert req["user"] == "upd-admin@x.de" and r["status"]["state"] == "queued"
    assert admin.post("/api/update/start", headers=H).status_code == 400  # läuft schon
    # Update-Skript meldet Fortschritt
    (tmp_path / "update" / "status.json").write_text(json.dumps({"state": "running", "message": "Installiere Version 9.9.0", "ts": 9e12}))
    assert admin.get("/api/update", headers={"X-Lang": "en"}).json()["status"]["message"] == "Installiere Version 9.9.0"
    # nur Administratoren
    with db() as c:
        from app import users
        if not users.by_email(c, "upd-user@x.de"):
            users.create(c, "upd-user@x.de", "passwort123")
    u = login("upd-user@x.de")
    assert u.get("/api/update").status_code == 403 and u.post("/api/update/start", headers=H).status_code == 403
    assert u.get("/api/state").json()["update"] is None


def test_not_updatable_and_unreachable(monkeypatch, tmp_path):
    monkeypatch.setattr(selfupdate, "PATH_UNIT", tmp_path / "fehlt.path")
    admin = login("upd-admin@x.de")
    assert admin.get("/api/update").json()["kind"] in ("manual", "docker")
    assert admin.post("/api/update/start", headers=H).status_code == 400
    monkeypatch.setattr(selfupdate.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    with db() as c:
        r = selfupdate.check(c, force=True)
    assert r["error"].startswith("GitHub nicht erreichbar")


def test_update_script_takes_nothing_from_request():
    """Quelle nur aus /opt/diktyo/update.conf; Anfrage wird gelöscht, nicht gelesen; Status als Benutzer diktyo."""
    s = (ROOT / "install" / "self-update.sh").read_text()
    assert 'rm -f "$DIR/request.json"' in s and "request.json" not in s.replace('rm -f "$DIR/request.json"', "").replace("/var/lib/diktyo/update/request.json", "")
    assert "runuser -u diktyo" in s and 'REPO" =~' in s
    setup = (ROOT / "install" / "setup.sh").read_text()
    assert "PathExists=/var/lib/diktyo/update/request.json" in setup and "install -m 755 -o root -g root" in setup
