"""Übersichtsseite und Durchsatz in der Topologie."""
import json

from app import actions, health
from app.db import db, now
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


def _traffic(d):
    with db() as c:
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (d["siid"],)).fetchone()["state"])
        for p in st["result"]["ports"]:
            p["in_bps"], p["out_bps"] = (2_000_000, 48_000_000) if p["port_no"] == 5 else (60_000_000, 9_000_000) if p["port_no"] == 1 else (None, None)
        c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st), d["siid"]))
        fst = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (d["fiid"],)).fetchone()["state"])
        fst["result"]["wan"] = {"connected": True, "rx_bps": 61_000_000, "tx_bps": 9_500_000}
        c.execute("UPDATE integrations SET state=?, last_ok=? WHERE id=?", (json.dumps(fst), now(), d["fiid"]))


def test_topology_traffic_on_edges(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Durchsatz")
    _traffic(d)
    plain = cl.get(f"{P}/topology").json()
    assert all("down_bps" not in e for e in plain["edges"])
    t = cl.get(f"{P}/topology?traffic=1").json()
    by = {n["id"]: n for n in t["nodes"]}
    edge = {by[e["target"]].get("name"): e for e in t["edges"] if e["source"] != "internet"}
    # Fernseher an Switch-Port 5: Download = Port sendet (out), Upload = Port empfängt (in)
    assert (edge["Fernseher"]["down_bps"], edge["Fernseher"]["up_bps"]) == (48_000_000, 2_000_000)
    # Switch hängt mit seinem Port 1 an der FRITZ!Box (deren Ports kennt díktyo nicht): Uplink-Port des Switches
    assert (edge["Switch"]["down_bps"], edge["Switch"]["up_bps"]) == (60_000_000, 9_000_000)


def test_dashboard(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Übersicht")
    _traffic(d)
    with db() as c:
        c.execute("UPDATE devices SET online=1 WHERE profile_id=?", (pid,))
        c.execute("UPDATE devices SET online=0 WHERE id=?", (d["tv"],))
        health.apply_firmware(c, pid, d["fb"], dict(installed="7.57", latest="8.02", update=True), "fritzbox")
        c.execute("INSERT INTO actions(profile_id, device_id, integration_id, kind, params, label, status, message, created) VALUES(?,?,?,?,?,?,?,?,?)",
                  (pid, d["tv"], d["fiid"], "internet", "{}", "Internetzugang sperren", "error", "zweiter Faktor nötig", now()))
        c.execute("UPDATE integrations SET last_error='Keine Antwort', last_ok=NULL WHERE id=?", (d["siid"],))
        c.execute("INSERT INTO devices(profile_id, name, type, status, created, updated) VALUES(?,?,?,?,?,?)", (pid, "Neu", "other", "discovered", now(), now()))
    r = cl.get(f"{P}/dashboard").json()
    assert r["counts"] == {**r["counts"], "devices": 3, "online": 2, "offline": 1, "inbox": 1, "firmware": 1}
    assert r["wan"]["rx_bps"] == 61_000_000 and r["wan"]["keys"] == [f"i{d['fiid']}:wan:rx", f"i{d['fiid']}:wan:tx"]
    assert [x["name"] for x in r["offline"]] == ["Fernseher"] and r["firmware"][0]["latest"] == "8.02"
    assert r["broken"][0]["error"] == "Keine Antwort" and r["failed"][0]["message"] == "zweiter Faktor nötig"
    assert [p["port_no"] for p in r["ports"]] == [1, 5] and r["ports"][0]["keys"][0] == f"i{d['siid']}:port:1:rx"
    # Übersicht nennt das Gerät hinter dem Port (Verbindungen) und den Switch einmal mit Gerätenamen
    assert [[x["name"] for x in p["peers"]] for p in r["ports"]] == [["FRITZ!Box"], ["Fernseher"]]
    assert {p["device"] for p in r["ports"]} == {"Switch"} and r["ports"][0]["device_id"] == d["sw"]
    assert {x["name"] for x in r["infra"]} == {"FRITZ!Box", "Switch"} and next(x for x in r["infra"] if x["name"] == "FRITZ!Box")["fw_update"]
