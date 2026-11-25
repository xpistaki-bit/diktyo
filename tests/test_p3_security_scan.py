"""Korrekturen aus dem Code-Scanning (CodeQL): SSH-Host-Schlüssel vor der Anmeldung prüfen, Ausdrücke ohne
exponentielles Rückverfolgen, keine internen Ausnahmen im Wortlaut, Dateinamen nur aus Zahlen, TLS ab 1.2."""
import ssl
import time

import paramiko
import pytest

from app import backup, configbackup, sshcfg, sysinfo, users
from app.drivers import routeros_api


class FakeKey:
    def get_name(self):
        return "ssh-ed25519"

    fingerprint = "SHA256:abc"

    def get_base64(self):
        return "AAAA"


def test_ssh_host_key_checked_before_login():
    fp = sshcfg.fingerprint(FakeKey())
    assert fp == "ssh-ed25519 SHA256:abc"
    sshcfg._policy(paramiko, None).missing_host_key(None, "h", FakeKey())  # erste Verbindung: annehmen
    sshcfg._policy(paramiko, fp).missing_host_key(None, "h", FakeKey())  # bekannter Schlüssel: annehmen
    with pytest.raises(paramiko.SSHException, match="hostkey-changed"):
        sshcfg._policy(paramiko, "ssh-ed25519 SHA256:anders").missing_host_key(None, "h", FakeKey())
    src = open(sshcfg.__file__).read()
    assert "AutoAddPolicy" not in src


def test_ssh_changed_key_aborts_without_sending_password(monkeypatch):
    """Weicht der Schlüssel ab, kommt paramiko gar nicht bis zur Anmeldung – die Meldung nennt den neuen Schlüssel."""
    sent = []

    class Client:
        def set_missing_host_key_policy(self, p):
            self.p = p

        def connect(self, host, password=None, **kw):
            self.p.missing_host_key(self, host, FakeKey())  # wie paramiko: Prüfung vor _auth
            sent.append(password)

        def close(self):
            pass
    monkeypatch.setattr(paramiko, "SSHClient", Client)
    with pytest.raises(sshcfg.SSHError, match="Host-Schlüssel des Geräts hat sich geändert"):
        sshcfg.run("192.0.2.5", 22, "admin", "geheim", "show running-config", known="ssh-ed25519 SHA256:alt")
    assert sent == []


@pytest.mark.parametrize("fn,arg", [
    (lambda s: users.EMAIL_RE.match(s), "a@" + "b." * 30000 + "!"),
    (sysinfo._fields, "a" * 40 + " " * 20000 + ":" + " \t" * 20000 + "x"),
    (sysinfo.parse, "ethernet controller" + " " * 50000 + "x"),
])
def test_regexes_stay_fast(fn, arg):
    t = time.time()
    fn(arg)
    assert time.time() - t < 0.5


def test_email_still_valid():
    assert users.norm_email(" Anna@Example.COM ") == "anna@example.com" and users.norm_email("a.b@sub.example.de")
    for bad in ("a@b", "a@@b.de", "a b@c.de", "x@" + "y" * 260 + ".de"):
        with pytest.raises(users.UserError):
            users.norm_email(bad)


def test_rclone_token_and_paths(monkeypatch):
    monkeypatch.setattr(backup.shutil, "which", lambda x: None)  # Abbruch vor rclone, Token-Teil wird nicht erreicht
    assert configbackup.path(17).name == "17.bin"
    with pytest.raises(ValueError):
        configbackup.path("../../etc/passwd")


def test_routeros_tls_minimum(monkeypatch):
    seen = {}

    class Ctx:
        check_hostname, verify_mode, minimum_version = True, None, None

        def wrap_socket(self, raw, server_hostname=None):
            seen["min"] = self.minimum_version
            raise ssl.SSLError("stop")
    monkeypatch.setattr(routeros_api.ssl, "create_default_context", lambda: Ctx())
    monkeypatch.setattr(routeros_api.socket, "create_connection", lambda *a, **k: type("S", (), {"close": lambda self: None})())
    with pytest.raises(routeros_api.APIError):
        routeros_api.Client("192.0.2.1", 8729, use_ssl=True)
    assert seen["min"] == ssl.TLSVersion.TLSv1_2
