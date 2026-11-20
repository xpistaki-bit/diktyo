"""Geschwindigkeitsmessungen: Internet (nachgebildetes speed.cloudflare.com), iperf3 (nachgebildete Ausgabe), Aufträge, Übersicht."""
import json
import subprocess

import httpx

from app import speedtest, worker
from app.db import db
from tests.test_m6 import H, login


def cf_handler(req):
    p = req.url.path
    if p == "/__down":
        n = int(req.url.params.get("bytes", 0))
        return httpx.Response(200, content=b"x" * n, headers={"server-timing": "cfSpeedEdge;dur=0.2, cfSpeedWorker;dur=0.5", "cf-ray": "8e0000000000abcd-FRA"})
    if p == "/__up":
        req.read()
        return httpx.Response(200, text="ok")
    return httpx.Response(404)


def mock_cf(monkeypatch):
    monkeypatch.setattr(speedtest, "_client", lambda: httpx.Client(base_url=speedtest.BASE, transport=httpx.MockTransport(cf_handler)))
    monkeypatch.setattr(speedtest, "CHUNK_DOWN", 300_000)
    monkeypatch.setattr(speedtest, "CHUNK_UP", 200_000)


def test_internet_measurement(monkeypatch):
    mock_cf(monkeypatch)
    steps = []
    r = speedtest.internet(streams=2, seconds=1, progress=lambda p, m: steps.append(m))
    assert r["down_bps"] > 0 and r["up_bps"] > 0 and r["ping_ms"] >= 0.1 and r["jitter_ms"] >= 0
    assert r["server"] == "Cloudflare FRA"
    assert speedtest._server_ms(httpx.Response(200, headers={"server-timing": "cfSpeedEdge;dur=7, cfSpeedWorker;dur=30, cfL4;desc=\"x\""})) == 30
    assert steps == ["Antwortzeit", "Download", "Upload"]
    assert r["detail"]["bytes_down"] <= speedtest.MAX_DOWN + 2 * speedtest.CHUNK_DOWN


def _iperf_json(bps, rtt_us=1500, err=None):
    if err:
        return json.dumps({"error": err})
    return json.dumps({"end": {"sum_received": {"bits_per_second": bps}, "sum_sent": {"retransmits": 3},
                               "streams": [{"sender": {"mean_rtt": rtt_us}}]}})


def test_iperf(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=_iperf_json(410e6 if "-R" in cmd else 930e6), stderr="")
    monkeypatch.setattr(speedtest.subprocess, "run", fake_run)
    r = speedtest.iperf("192.0.2.11", 5201, seconds=2, streams=2)
    assert r["up_bps"] == 930e6 and r["down_bps"] == 410e6 and r["ping_ms"] == 1.5 and r["detail"]["retransmits_up"] == 3
    assert calls[0][:3] == ["iperf3", "-c", "192.0.2.11"] and "-R" in calls[1] and "-J" in calls[0]
    monkeypatch.setattr(speedtest.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout=_iperf_json(0, err="unable to connect to server: Connection refused"), stderr=""))
    try:
        speedtest.iperf("192.0.2.11")
        raise AssertionError
    except speedtest.SpeedError as ex:
        assert "iperf3 -s" in str(ex)


def test_jobs_api_schedule_and_dashboard(monkeypatch):
    mock_cf(monkeypatch)
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Speed"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    s = cl.put(f"{P}/speedtest", json={"schedule_hours": 6, "streams": "2", "seconds": "3"}, headers=H).json()
    assert s == {"schedule_hours": 6, "streams": 2, "seconds": 3}
    # geplante Messung wird eingereiht, eine zweite nicht doppelt
    worker.enqueue_scheduled()
    worker.enqueue_scheduled()
    with db() as c:
        jobs = c.execute("SELECT * FROM jobs WHERE profile_id=? AND kind='speedtest'", (pid,)).fetchall()
    assert len(jobs) == 1 and json.loads(jobs[0]["params"]) == {"kind": "internet", "scheduled": True}
    # von Hand: derselbe wartende Auftrag
    assert cl.post(f"{P}/speedtest/run", headers=H).json()["job"]["id"] == jobs[0]["id"]
    monkeypatch.setattr(speedtest, "DEFAULTS", dict(speedtest.DEFAULTS))
    with db() as c:
        c.execute("UPDATE profiles SET settings=json_set(settings, '$.speedtest.seconds', 3) WHERE id=?", (pid,))
    res = speedtest.run_job(jobs[0]["id"])
    assert res["down_bps"] > 0
    o = cl.get(f"{P}/speedtest").json()
    assert len(o["history"]) == 1 and o["history"][0]["scheduled"] is True and o["job"] is None or o["job"]["id"] == jobs[0]["id"]
    # Übersicht: deutlich unter der Leitung -> Hinweis
    with db() as c:
        c.execute("UPDATE speedtests SET down_bps=? WHERE profile_id=?", (100e6, pid))
        c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, state, created) VALUES(?,?,?,?,?,?,datetime('now'))",
                  (pid, "fritzbox", "FRITZ!Box", "192.0.2.1", "{}", json.dumps(dict(result=dict(wan=dict(connected=True, rx_bps=1e6, tx_bps=1e5, max_down=1e9, max_up=5e7))))))
    d = cl.get(f"{P}/dashboard").json()
    assert d["speed"]["slow"] is True and d["speed"]["line_down"] == 1e9 and d["speed"]["last"]["down_bps"] == 100e6


def test_iperf_api(monkeypatch):
    monkeypatch.setattr(speedtest.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, stdout=_iperf_json(5e8), stderr=""))
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "iperf"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    nas = cl.post(f"{P}/devices", json=dict(name="NAS", type="nas", ips=[{"address": "192.0.2.11"}]), headers=H).json()["id"]
    none = cl.post(f"{P}/devices", json=dict(name="ohne IP", type="other"), headers=H).json()["id"]
    assert cl.post(f"{P}/devices/{none}/iperf", json={}, headers=H).status_code == 400
    assert cl.post(f"{P}/devices/{nas}/iperf", json={"port": 70000}, headers=H).status_code == 400
    job = cl.post(f"{P}/devices/{nas}/iperf", json={"port": 5202}, headers=H).json()["job"]
    assert job["params"] == {"kind": "iperf", "device_id": nas, "host": "192.0.2.11", "port": 5202}
    speedtest.run_job(job["id"])
    h = cl.get(f"{P}/devices/{nas}/iperf").json()["history"]
    assert h[0]["up_bps"] == 5e8 and h[0]["server"] == "192.0.2.11:5202"
