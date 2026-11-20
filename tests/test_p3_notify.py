"""Benachrichtigungen per ntfy und E-Mail: Einschalten ohne Altlasten, Bündeln, Filter, Token, neue Ereignisquellen."""
import json
import time

import httpx

from app import configbackup, integrations, mailer, notify, security
from app.db import db, now
from app.scan import runner
from tests.test_m6 import H, login


class Sent:
    def __init__(self, monkeypatch):
        self.ntfy, self.mails = [], []

        def post(url, json=None, headers=None, timeout=None):
            self.ntfy.append(dict(url=url, json=json, headers=headers or {}))
            return httpx.Response(200, json={"id": "x"})
        monkeypatch.setattr(notify.httpx, "post", post)
        monkeypatch.setattr(mailer, "enabled", lambda c: True)
        monkeypatch.setattr(mailer, "smtp_config", lambda c: {"host": "smtp.example.com"})
        monkeypatch.setattr(mailer, "send", lambda cfg, to, subject, text: self.mails.append((to, subject, text)))


def _profile(name):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]
    return cl, pid, f"/api/profiles/{pid}"


def test_enable_bundle_filter_and_token(monkeypatch):
    sent = Sent(monkeypatch)
    cl, pid, P = _profile("Benachrichtigung")
    tv = cl.post(f"{P}/devices", json=dict(name="Fernseher", type="tv"), headers=H).json()["id"]
    sw = cl.post(f"{P}/devices", json=dict(name="Switch", type="switch"), headers=H).json()["id"]
    with db() as c:
        runner.event(c, pid, "device_offline", tv, name="Fernseher")  # vor dem Einschalten: wird nicht gemeldet
    s = cl.put(f"{P}/notify", json=dict(ntfy=True, ntfy_url="https://ntfy.example.com", ntfy_topic="diktyo-test", ntfy_token="tk_geheim",
                                        email=True, kinds=["device_offline", "new_device", "speed_slow"]), headers=H).json()
    assert s["ntfy_token"] == security.MASK and s["kinds"] == ["device_offline", "new_device", "speed_slow"]
    with db() as c:
        assert "tk_geheim" not in c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()["settings"]  # verschlüsselt
    assert notify.deliver(pid, force=True) == 0 and not sent.ntfy
    with db() as c:
        runner.event(c, pid, "device_offline", sw, name="Switch")
        runner.event(c, pid, "new_device", None, name="Shelly", ip="192.0.2.50")
        runner.event(c, pid, "device_online", tv, name="Fernseher")  # nicht gewählt
    assert notify.deliver(pid, force=True) == 2
    m = sent.ntfy[-1]
    assert m["url"] == "https://ntfy.example.com/" and m["json"]["topic"] == "diktyo-test" and m["headers"]["Authorization"] == "Bearer tk_geheim"
    assert m["json"]["title"] == "díktyo · Benachrichtigung: 2 Meldungen" and m["json"]["priority"] == 4
    assert m["json"]["message"].splitlines() == ["Switch ist offline", "Neues Gerät: Shelly 192.0.2.50"]
    owner = cl.get("/api/state").json()["user"]["email"]
    assert [x[0] for x in sent.mails] == [owner] and sent.mails[0][1] == m["json"]["title"]
    # Bündeln: innerhalb einer Minute nichts Neues
    with db() as c:
        runner.event(c, pid, "device_offline", tv, name="Fernseher")
    assert notify.deliver(pid) == 0
    # Token bleibt beim Speichern mit Maske erhalten; nur Infrastruktur
    cl.put(f"{P}/notify", json=dict(ntfy_token=security.MASK, only_infra_offline=True), headers=H)
    with db() as c:
        assert notify.settings(c.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone(), reveal=True)["ntfy_token"] == "tk_geheim"
        c.execute("UPDATE notify_state SET last_sent=0 WHERE profile_id=?", (pid,))
    assert notify.deliver(pid) == 0  # Fernseher ist keine Infrastruktur
    assert cl.put(f"{P}/notify", json=dict(ntfy_url="ntfy.sh"), headers=H).status_code == 400


def test_test_endpoint_reports_per_channel(monkeypatch):
    sent = Sent(monkeypatch)
    monkeypatch.setattr(mailer, "enabled", lambda c: False)
    cl, pid, P = _profile("Testnachricht")
    r = cl.post(f"{P}/notify/test", json=dict(ntfy=True, email=True, ntfy_url="https://ntfy.sh", ntfy_topic="abc"), headers=H).json()
    assert r["ntfy"] == "ok" and "nicht eingerichtet" in r["email"] and sent.ntfy[0]["json"]["message"] == "Benachrichtigungen funktionieren."


def test_new_event_sources(monkeypatch):
    cl, pid, P = _profile("Ereignisse")
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, created) VALUES(?,?,?,?,?,?)",
                        (pid, "snmp", "Switch", "192.0.2.2", json.dumps({"ssh_user": "admin", "ssh_pass": ""}), now())).lastrowid
    kinds = lambda: [r["kind"] for r in db_rows("SELECT kind FROM events WHERE profile_id=? ORDER BY id", pid)]  # noqa: E731
    # Integration gestört: erst nach 15 Minuten, nur einmal; Erfolg setzt zurück
    integrations._fail(iid, "Keine Antwort")
    assert "integration_failed" not in kinds()
    with db() as c:
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()["state"])
        st["fail_since"] = time.time() - 1000
        c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st), iid))
    integrations._fail(iid, "Keine Antwort")
    integrations._fail(iid, "Keine Antwort")
    assert kinds().count("integration_failed") == 1
    # Backup fehlgeschlagen (automatisch) – beim Knopfdruck nicht
    configbackup.run(iid)
    assert kinds().count("backup_failed") == 1
    configbackup.run(iid, interactive=True)
    assert kinds().count("backup_failed") == 1
    # Internet langsam
    from app import speedtest
    with db() as c:
        c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, state, created) VALUES(?,?,?,?,?,?,?)",
                  (pid, "fritzbox", "FRITZ!Box", "192.0.2.1", "{}", json.dumps(dict(result=dict(wan=dict(max_down=1e9)))), now()))
        jid = speedtest.enqueue(c, pid, "internet")
    monkeypatch.setattr(speedtest, "internet", lambda **k: dict(down_bps=200e6, up_bps=40e6, ping_ms=9, jitter_ms=1, server="Cloudflare FRA", detail={}))
    speedtest.run_job(jid)
    with db() as c:
        e = c.execute("SELECT data FROM events WHERE profile_id=? AND kind='speed_slow'", (pid,)).fetchone()
    assert json.loads(e["data"]) == {"down": "200 Mbit/s", "line": "1000 Mbit/s"}
    assert notify.line("speed_slow", json.loads(e["data"])) == "Internet langsam: ↓ 200 Mbit/s (Leitung ↓ 1000 Mbit/s)"


def db_rows(q, *a):
    with db() as c:
        return c.execute(q, a).fetchall()
