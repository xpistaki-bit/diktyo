"""M6: Konfigurations-Backups (FRITZ!Box, ASUS, SSH), Vergleich, Zeitplan, Aufnahme ins díktyo-Backup."""
import io
import json
import socket
import threading
import time
import zipfile

import paramiko
from fastapi.testclient import TestClient

from app import backup as bk
from app import configbackup, integrations, main, sshcfg, users
from app.db import db, now
from app.drivers import asuswrt, fritzbox

H = {"X-Requested-With": "diktyo"}


def login(email="m6@x.de"):
    with db() as c:
        if not users.by_email(c, email):
            users.create(c, email, "passwort123", is_admin=True)
    cl = TestClient(main.app)
    cl.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H)
    return cl


def setup(cl, name, driver):
    pid = cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]
    did = cl.post(f"/api/profiles/{pid}/devices", json={"name": "Gerät", "type": "router"}, headers=H).json()["id"]
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, secret, options, device_id, created) VALUES(?,?,?,?,?,?,?,?)",
                        (pid, driver, driver, "192.0.2.1", integrations.security.encrypt(json.dumps({"password": "x"})), json.dumps({"cfg_schedule": "daily"}),
                         did, now())).lastrowid
    return pid, f"/api/profiles/{pid}", did, iid


def test_fritz_backup_versions_and_diff(monkeypatch):
    cl = login()
    pid, P, did, iid = setup(cl, "FB-Backup", "fritzbox")
    content = {"v": "**** FRITZ!Box 6591 Cable CONFIGURATION EXPORT\nwlan ssid = Zuhause\nportfw = none\n"}
    monkeypatch.setattr(fritzbox, "backup", lambda conf, state: ("FRITZ.Box_6591_Cable.export", content["v"].encode(), True))
    r1 = cl.post(f"{P}/integrations/{iid}/config-backup", headers=H).json()
    assert r1["status"] == "new" and r1["filename"].startswith("FRITZ.Box_6591_Cable_") and r1["filename"].endswith(".export")
    assert cl.post(f"{P}/integrations/{iid}/config-backup", headers=H).json()["status"] == "unchanged"
    content["v"] = content["v"].replace("portfw = none", "portfw = 443 -> nas")
    r3 = cl.post(f"{P}/integrations/{iid}/config-backup", headers=H).json()
    assert r3["status"] == "new"
    cfgs = cl.get(f"{P}/configs?device_id={did}").json()["configs"]
    assert [x["id"] for x in cfgs] == [r3["id"], r1["id"]] and cfgs[0]["prev_id"] == r1["id"]
    d = cl.get(f"{P}/configs/{r3['id']}/diff?other={r1['id']}").json()
    assert d["changed"] == 2 and "-portfw = none" in d["lines"] and "+portfw = 443 -> nas" in d["lines"]
    dl = cl.get(f"{P}/configs/{r3['id']}/download")
    assert dl.text == content["v"] and "attachment" in dl.headers["content-disposition"]
    # verschlüsselt auf der Platte
    assert b"portfw" not in configbackup.path(r3["id"]).read_bytes()
    # Gerätedialog zeigt die Stände
    assert len(cl.get(f"{P}/devices/{did}").json()["configs"]) == 2
    # Fehler wird gemeldet und vermerkt
    monkeypatch.setattr(fritzbox, "backup", lambda conf, state: (_ for _ in ()).throw(fritzbox.DriverError("Benutzer hat nicht das Recht „FRITZ!Box Einstellungen“")))
    r = cl.post(f"{P}/integrations/{iid}/config-backup", headers=H)
    assert r.status_code == 400 and "FRITZ!Box Einstellungen" in r.json()["error"]
    i = next(x for x in cl.get(f"{P}/integrations").json()["integrations"] if x["id"] == iid)
    assert i["can_backup"] and i["cfg_result"]["status"] == "error" and i["cfg_ok"]
    # Zeitplan: gerade versucht -> nicht fällig, einen Tag später fällig
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
        assert not configbackup.due(row) and configbackup.due(row, time.time() + 86401)
    assert cl.delete(f"{P}/configs/{r1['id']}", headers=H).json()["ok"] and not configbackup.path(r1["id"]).exists()


def test_asus_settings_file(monkeypatch):
    calls = {}

    class Resp:
        status_code = 200
        content = b"HDR2" + bytes(range(256)) * 4

    class Cl:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url, **kw):
            calls["url"], calls["cookie"] = url, kw["cookies"]["asus_token"]
            return Resp()

    monkeypatch.setattr(asuswrt, "_fetch", lambda conf, state: ({"productid": "EBM68"}, "tok"))
    monkeypatch.setattr(asuswrt, "_client", lambda conf: Cl())
    name, data, is_text = asuswrt.backup(dict(host="h"), {})
    assert name == "Settings_EBM68.CFG" and calls == {"url": "/Settings_EBM68.CFG", "cookie": "tok"} and not is_text and data.startswith(b"HDR2")


# ------------------------------------------------------------ kleiner SSH-Server für den Test
CONFIG = "hostname XGS1935\nvlan 10\n name IoT\nexit\ninterface port-channel 1\n"


class _Srv(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if (username, password) == ("admin", "geheim") else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_exec_request(self, channel, command):
        def answer():
            time.sleep(0.1)  # erst nach der Bestätigung des Befehls antworten
            channel.sendall((CONFIG if command == b"show running-config" else "% Invalid input\n").encode())
            channel.send_exit_status(0)
            channel.close()
        threading.Thread(target=answer, daemon=True).start()
        return True


def ssh_server(key):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(5)

    def loop():
        while True:
            conn, _ = s.accept()
            t = paramiko.Transport(conn)
            t.add_server_key(key)
            try:
                t.start_server(server=_Srv())
            except Exception:
                continue

    threading.Thread(target=loop, daemon=True).start()
    return s.getsockname()[1]


def test_ssh_running_config():
    key = paramiko.RSAKey.generate(2048)
    port = ssh_server(key)
    out, fp = sshcfg.run("127.0.0.1", port, "admin", "geheim", "show running-config")
    assert out.strip() == CONFIG.strip() and fp.startswith("ssh-rsa")
    try:
        sshcfg.run("127.0.0.1", port, "admin", "falsch", "show running-config")
        raise AssertionError
    except sshcfg.SSHError as ex:
        assert "abgelehnt" in str(ex)
    try:  # anderer Host-Schlüssel als beim ersten Mal -> abbrechen
        sshcfg.run("127.0.0.1", port, "admin", "geheim", "show running-config", known="ssh-rsa SHA256:anders")
        raise AssertionError
    except sshcfg.SSHError as ex:
        assert "geändert" in str(ex)


def test_config_in_diktyo_backup(monkeypatch, tmp_path):
    cl = login()
    pid, P, did, iid = setup(cl, "Backup-Konfig", "fritzbox")
    monkeypatch.setattr(fritzbox, "backup", lambda conf, state: ("FRITZ.Box.export", b"geheime fritz konfiguration", True))
    cl.post(f"{P}/integrations/{iid}/config-backup", headers=H)
    # ohne Passphrase bleibt die Konfiguration draußen
    cl.put("/api/backup", json={"targets": [], "passphrase": ""}, headers=H)
    with db() as c:
        c.execute("UPDATE settings SET value=? WHERE key='backup'", (json.dumps({"targets": []}),))
        raw = bk.build_zip(c, with_documents=False)
    assert not [n for n in zipfile.ZipFile(io.BytesIO(raw)).namelist() if n.startswith("geraete-konfiguration/")]
    # mit Passphrase verschlüsselt drin
    cl.put("/api/backup", json={"targets": [], "passphrase": "backup-pass"}, headers=H)
    with db() as c:
        raw = bk.build_zip(c, with_documents=False)
    z = zipfile.ZipFile(io.BytesIO(raw))
    enc = [n for n in z.namelist() if n.startswith("geraete-konfiguration/")]
    assert enc and all(b"geheime" not in z.read(n) for n in enc)
    exp = bk.read_zip(raw)
    assert any(m["filename"].startswith("FRITZ.Box_") for m in exp["config_backups"])
    # Wiederherstellung in leere Installation bringt die Datei zurück
    from app import db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "neu.db")
    dbmod.migrate()
    with db() as c:
        bk.restore_all(c, exp, "backup-pass")
        r = c.execute("SELECT id FROM config_backups WHERE filename LIKE 'FRITZ.Box_%' ORDER BY id DESC").fetchone()
    assert configbackup.read(r["id"]) == b"geheime fritz konfiguration"
