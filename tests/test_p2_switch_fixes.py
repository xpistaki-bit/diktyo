"""Switch: nur echte Frontports, SSH-Anmeldung mit Schlüssel; Online-Überwachung mit Toleranz gegen einzelne verlorene Pings."""
import io
import json

import paramiko

from app import integrations, monitor, sshcfg
from app.db import db, now
from app.drivers import snmp
from app.scan import discover
from tests.test_m6 import H, login


def test_physical_ports_filters_logical_bridge_and_catalog():
    types = {str(i): 6 for i in range(1, 33)}
    types["33"] = 24  # softwareLoopback
    names = {str(i): f"port{i}" for i in range(1, 29)}
    names.update({"29": "trunk1", "30": "port30", "31": "port31", "32": "port32"})
    phys, skipped = snmp.physical_ports(types, names, {}, bridge_ifs=set(range(1, 32)))
    assert phys == list(range(1, 29)) + [30, 31]
    assert (29, "trunk1", "logische Schnittstelle") in skipped and any(i == 32 and g == "kein Bridge-Port" for i, _, g in skipped)
    phys, skipped = snmp.physical_ports(types, names, {}, expected=28)
    assert phys == list(range(1, 29)) and any("28 Ports des Katalogmodells" in g for _, _, g in skipped)
    # unplausible Bridge-Tabelle (zu wenige Einträge) wird ignoriert
    assert len(snmp.physical_ports(types, names, {}, bridge_ifs={1})[0]) == 31


def test_poll_passes_catalog_port_count(monkeypatch):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Switch-Ports"}, headers=H).json()["profile"]["id"]
    sw = cl.post(f"/api/profiles/{pid}/devices", json=dict(name="SW", type="switch", ports=[dict(count=28, kind="rj45", speed="1G")]), headers=H).json()
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, device_id, created) VALUES(?,?,?,?,?,?,?)",
                        (pid, "snmp", "SW", "192.0.2.2", "{}", sw["id"], now())).lastrowid
    seen = {}

    def fake(conf, state):
        seen.update(conf)
        return dict(info={}, ports=[], fdb_size=0), {}, state
    monkeypatch.setattr(snmp, "poll", fake)
    integrations.poll(iid)
    assert seen["expected_ports"] == 28


def test_monitor_tolerates_single_missed_ping(monkeypatch):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Shelly"}, headers=H).json()["profile"]["id"]
    d = cl.post(f"/api/profiles/{pid}/devices", json=dict(name="Shelly", type="iot", ips=[{"address": "192.0.2.31"}]), headers=H).json()
    with db() as c:
        c.execute("UPDATE devices SET status='confirmed', online=1 WHERE id=?", (d["id"],))
    calls = []

    async def no_ping(ip, timeout=1.0):
        calls.append(("ping", timeout))
        return None

    async def no_tcp(ip, port, timeout=0.8):
        calls.append(("tcp", port))
        return False
    monkeypatch.setattr(discover, "ping_rtt", no_ping)
    monkeypatch.setattr(discover, "tcp", no_tcp)
    monitor._misses.clear()
    monitor.run(pid)
    assert ("tcp", 80) in calls and ("ping", 2.0) in calls  # zweiter Versuch und Port-Prüfung
    online = lambda: db_one("SELECT online FROM devices WHERE id=?", d["id"])  # noqa: E731
    assert online() == 1  # eine verpasste Runde reicht nicht
    monitor.run(pid)
    assert online() == 0

    async def pong(ip, timeout=1.0):
        return 3.2
    monkeypatch.setattr(discover, "ping_rtt", pong)
    monitor.run(pid)
    assert online() == 1 and d["id"] not in monitor._misses


def db_one(q, *a):
    with db() as c:
        return c.execute(q, a).fetchone()[0]


def _pem(key):
    buf = io.StringIO()
    key.write_private_key(buf)
    return buf.getvalue()


def test_ssh_keys_and_switch_backup(monkeypatch):
    k = paramiko.RSAKey.generate(1024)
    assert sshcfg.load_key(_pem(k)).get_base64() == k.get_base64()
    for bad, msg in (("", "Kein privater"), (f"ssh-rsa {k.get_base64()} x", "öffentlicher Schlüssel"), ("Unsinn", "nicht lesbar")):
        try:
            sshcfg.load_key(bad)
            raise AssertionError(bad)
        except sshcfg.SSHError as ex:
            assert msg in str(ex)
    # díktyos eigener Schlüssel: einmal erzeugt, danach derselbe
    real_gen = paramiko.RSAKey.generate
    monkeypatch.setattr(paramiko.RSAKey, "generate", staticmethod(lambda bits: real_gen(1024)))
    cl = login()
    pub1 = cl.get("/api/ssh-key").json()["public"]
    pub2 = cl.get("/api/ssh-key").json()["public"]
    assert pub1 == pub2 and pub1.startswith("ssh-rsa ")

    got = {}

    def fake_run(host, port, user, password, command, known=None, timeout=15, pkey=None, mode="auto"):
        got.update(user=user, password=password, pkey=pkey, mode=mode)
        return "hostname sw\n" * 5, "ssh-rsa aa:bb"
    monkeypatch.setattr(sshcfg, "run", fake_run)
    base = dict(host="192.0.2.2", ssh_user="admin", ssh_command="show running-config")
    snmp.backup({**base, "ssh_auth": "key_diktyo", "ssh_mode": "shell"}, {})
    assert got["password"] is None and f"{got['pkey'].get_name()} {got['pkey'].get_base64()} diktyo" == pub1 and got["mode"] == "shell"
    snmp.backup({**base, "ssh_auth": "key_own", "ssh_key": _pem(k)}, {})
    assert got["pkey"].get_base64() == k.get_base64()
    snmp.backup({**base, "ssh_pass": "geheim"}, {})  # ältere Integrationen ohne ssh_auth: Passwort
    assert got["password"] == "geheim" and got["pkey"] is None
    try:
        snmp.backup({**base, "ssh_auth": "password"}, {})
        raise AssertionError
    except snmp.DriverError as ex:
        assert "Passwort" in str(ex)


def test_sshpub_field_not_stored():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "SSH-Felder"}, headers=H).json()["profile"]["id"]
    r = cl.post(f"/api/profiles/{pid}/integrations", json=dict(driver="snmp", host="192.0.2.2", version="v2c", password="public",
                                                                ssh_auth="key_diktyo", ssh_user="admin", ssh_pub="egal"), headers=H)
    assert r.status_code == 200, r.text
    with db() as c:
        opts = json.loads(c.execute("SELECT options FROM integrations WHERE profile_id=?", (pid,)).fetchone()["options"])
    assert opts["ssh_auth"] == "key_diktyo" and "ssh_pub" not in opts
