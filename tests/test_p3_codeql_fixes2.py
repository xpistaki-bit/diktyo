"""Code-Scanning: Sicherung zeigt nur feste Fehlertexte, die Kommandozeile gibt keine Passwörter aus, sysinfo-Parser
ohne polynomielles Regex."""
import errno
import time

import httpx

from app import backup, cli, msg_en, sysinfo
from app.db import db


def test_backup_errors_without_exception_text(tmp_path, monkeypatch, capsys):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    monkeypatch.setattr(backup.httpx, "put", lambda url, **k: httpx.Response(401))
    with db() as c:
        res, size = backup.run(c, [dict(type="local", path=str(ro / "sub")), dict(type="webdav", url="http://192.0.2.1/dav"),
                                   dict(type="local", path=str(tmp_path / "ok")), dict(type="ftp")])
    ro.chmod(0o700)
    assert size > 0
    assert res[0]["ok"] is False and res[0]["detail"] in ("Keine Schreibrechte – Rechte des díktyo-Dienstes am Ziel prüfen",
                                                          "Fehler beim Sichern – Details im Protokoll des Dienstes") or res[0]["ok"]  # als root beschreibbar
    assert res[1] == dict(target="WebDAV http://192.0.2.1/dav", ok=False, detail="Anmeldung abgelehnt – Benutzer und Passwort prüfen")
    assert res[2]["ok"] is True and res[3]["detail"] == "unbekannter Zieltyp"
    assert backup.failure_text(OSError(errno.ENOSPC, "voll")) == "Kein Speicherplatz mehr am Ziel"
    assert backup.failure_text(httpx.ConnectTimeout("x")) == "WebDAV-Server antwortet nicht (Zeitüberschreitung)"
    assert backup.failure_text(KeyError("geheim")) == "Fehler beim Sichern – Details im Protokoll des Dienstes"
    assert msg_en.en("WebDAV-Server meldet HTTP 507") == "WebDAV server returns HTTP 507"


def test_cli_never_prints_passwords(monkeypatch, capsys):
    cli.main(["create-user", "cq@x.de", "Passwort-123"])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    answers = iter(["kurz", "kurz", "Neues-Passwort-1", "Neues-Passwort-1"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    cli.main(["reset-password", "cq@x.de"])
    out = capsys.readouterr().out
    assert "Passwort-123" not in out and "Neues-Passwort-1" not in out and "mindestens 8 Zeichen" in out and "gesetzt" in out
    from app import security, users
    with db() as c:
        assert security.check_pw("Neues-Passwort-1", users.by_email(c, "cq@x.de")["pw_hash"])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    try:
        cli.main(["reset-password", "cq@x.de"])
        raise AssertionError
    except SystemExit as ex:
        assert "Terminal" in str(ex.code)


def test_sysinfo_fields_linear():
    f = sysinfo._fields("Manufacturer: Dell Inc.\n  Product Name = OptiPlex 7070\nx: kurz\nSKU_Number:  X1 \nnur Text\nA" + " " * 900 + "b")
    assert f == {"manufacturer": "Dell Inc.", "product name": "OptiPlex 7070", "sku number": "X1"}
    t0 = time.time()
    sysinfo._fields(("a" + " " * 998 + "\n") * 200)
    assert time.time() - t0 < 0.5
