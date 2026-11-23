"""Prometheus-Endpunkt: Token je Profil (nur Besitzer), Textformat mit Geräten, WAN, Ports, Speedtest, Wachliste; Grafana-Dashboard."""
import json

from app import actions, metrics, watch
from app.db import db, now
from app.scan import runner
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


def _metric(text, name, **labels):
    for line in text.splitlines():
        if line.startswith(name + "{") or line.startswith(name + " "):
            if all(f'{k}="{v}"' in line for k, v in labels.items()):
                return float(line.rsplit(" ", 1)[1])
    return None


def test_prometheus(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Prometheus")
    with db() as c:
        runner._set_online(c, d["fb"], 1, now())
        runner._set_online(c, d["tv"], 0, now())
        metrics.put(c, pid, {f"i{d['fiid']}:wan:rx": 5e7, f"i{d['fiid']}:wan:tx": 1e7, f"i{d['siid']}:port:5:rx": 2e6, f"i{d['siid']}:port:5:tx": 3e6})
        metrics.put(c, pid, {f"d{d['fb']}:rtt": 1.5}, unit="ms")
        c.execute("INSERT INTO speedtests(profile_id, kind, ts, down_bps, up_bps, ping_ms, jitter_ms) VALUES(?,?,?,?,?,?,?)",
                  (pid, "internet", now(), 2.5e8, 4e7, 9.4, 1.2))
        watch.add(c, pid, d["tv"], "")
        c.execute("UPDATE integrations SET last_ok=?, last_poll=? WHERE profile_id=?", (now(), now(), pid))
    # ohne Token kein Zugriff; Token nur für Besitzer
    assert cl.get(f"{P}/prometheus").status_code == 401
    assert cl.get(f"{P}/prometheus/settings").json()["enabled"] is False
    tok = cl.post(f"{P}/prometheus/token", headers=H).json()["token"]
    assert len(tok) > 30 and cl.get(f"{P}/prometheus/settings").json()["enabled"]
    assert cl.get(f"{P}/prometheus", headers={"Authorization": "Bearer falsch"}).status_code == 401
    r = cl.get(f"{P}/prometheus", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    t = r.text
    assert "# TYPE diktyo_device_up gauge" in t
    assert _metric(t, "diktyo_device_up", device="FRITZ!Box", infra="1") == 1 and _metric(t, "diktyo_device_up", device="Fernseher") == 0
    assert _metric(t, "diktyo_device_rtt_milliseconds", device="FRITZ!Box") == 1.5
    assert _metric(t, "diktyo_wan_receive_bits_per_second", integration="FRITZ!Box") == 5e7
    assert _metric(t, "diktyo_port_transmit_bits_per_second", device="Switch", peer="Fernseher") == 3e6
    assert _metric(t, "diktyo_speedtest_download_bits_per_second") == 2.5e8
    assert _metric(t, "diktyo_watch_alarms") == 1 and _metric(t, "diktyo_watch_alarm", device="Fernseher", state="down") == 1
    assert _metric(t, "diktyo_integration_up", integration="Switch", driver="snmp") == 1
    assert cl.get(f"{P}/prometheus/settings").json()["last_scrape"]
    # Token gilt nur für dieses Profil
    other = cl.post("/api/profiles", json={"name": "Anderes"}, headers=H).json()["profile"]["id"]
    assert cl.get(f"/api/profiles/{other}/prometheus", headers={"Authorization": f"Bearer {tok}"}).status_code == 401
    # Grafana-Dashboard
    g = cl.get(f"{P}/prometheus/grafana.json")
    dash = json.loads(g.content)
    assert "attachment" in g.headers["content-disposition"] and dash["title"] == "díktyo · Prometheus"
    assert any("diktyo_wan_receive_bits_per_second" in tg["expr"] for p in dash["panels"] for tg in p["targets"])
    # Lesende: kein neues Token
    with db() as c:
        from app import users
        if not users.by_email(c, "leser@x.de"):
            users.create(c, "leser@x.de", "passwort123")
        c.execute("INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?,'view')", (pid, users.by_email(c, "leser@x.de")["id"]))
    rd = login("leser@x.de")
    assert rd.post(f"{P}/prometheus/token", headers=H).status_code == 403
    # neues Token macht das alte ungültig, Widerruf sperrt
    tok2 = cl.post(f"{P}/prometheus/token", headers=H).json()["token"]
    assert cl.get(f"{P}/prometheus", headers={"Authorization": f"Bearer {tok}"}).status_code == 401
    assert cl.get(f"{P}/prometheus", headers={"Authorization": f"Bearer {tok2}"}).status_code == 200
    cl.delete(f"{P}/prometheus/token", headers=H)
    assert cl.get(f"{P}/prometheus", headers={"Authorization": f"Bearer {tok2}"}).status_code == 401
