"""Leitungswerte der FRITZ!Box: DSL über TR-064, Kabel (DOCSIS-Kanäle) über die Weboberfläche, Richtwert-Hinweise,
Abfrage-Abstand und Sperre nach abgelehnter Anmeldung, Ereignis, Übersicht, Messwerte und anheftbare Diagramme."""
import json

from app import actions, dashlayout, integrations, notify, prometheus
from app.db import db
from app.drivers import fritzbox
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup

DOCINFO = {"pid": "docInfo", "data": {
    "channelDs": {
        "docsis30": [
            {"channelID": 1, "frequency": "114", "powerLevel": "3.9", "type": "256QAM", "mse": "-36.6", "latency": 0.32, "corrErrors": 12, "nonCorrErrors": 0},
            {"channelID": 2, "frequency": "122", "powerLevel": "16.4", "type": "256QAM", "mse": "-30.1", "latency": 0.32, "corrErrors": 40, "nonCorrErrors": 3},
        ],
        "docsis31": [{"channelID": 33, "frequency": "751", "powerLevel": "5.2", "type": "4K", "mer": "41", "plc": "754", "corrErrors": 5, "nonCorrErrors": 0}],
    },
    "channelUs": {
        "docsis30": [{"channelID": 1, "frequency": "51", "powerLevel": "43.0", "type": "64QAM", "multiplex": "ATDMA"},
                     {"channelID": 2, "frequency": "45", "powerLevel": "52.5", "type": "64QAM", "multiplex": "ATDMA"}],
        "docsis31": [],
    }}}


def test_parse_docinfo_and_hints():
    line = fritzbox.parse_docinfo(DOCINFO)
    assert (line["kind"], line["ds_30"], line["ds_31"], line["us_30"], line["us_31"]) == ("cable", 2, 1, 2, 0)
    assert (line["ds_pwr_min"], line["ds_pwr_max"], line["us_pwr_max"]) == (3.9, 16.4, 52.5)
    assert line["snr_min"] == 30.1 and line["corr"] == 57 and line["uncorr"] == 3
    assert next(c for c in line["ds"] if c["id"] == 33)["snr"] == 41.0
    codes = {h["code"]: h for h in fritzbox.line_hints(line)}
    assert set(codes) == {"ds_pwr", "us_pwr", "mse"}
    assert "16,4 dBmV" in codes["ds_pwr"]["de"] and "16.4 dBmV" in codes["ds_pwr"]["en"] and "channel 2" in codes["ds_pwr"]["en"]
    assert "30,1 dB" in codes["mse"]["de"] and "256QAM" in codes["mse"]["de"]
    # neue nicht korrigierbare Fehler gegenüber der letzten Messung
    later = dict(line, uncorr=line["uncorr"] + 80)
    assert "uncorr" in {h["code"] for h in fritzbox.line_hints(later, line)}
    assert fritzbox.line_metrics(later, line) == {"line:snr_min": 30.1, "line:us_pwr_max": 52.5, "line:err": 80}
    # Zähler nach Neustart kleiner -> kein Hinweis, Fehler 0
    assert "uncorr" not in {h["code"] for h in fritzbox.line_hints(dict(line, uncorr=0), later)}
    assert fritzbox.line_metrics(dict(line, uncorr=0), later)["line:err"] == 0
    assert fritzbox.parse_docinfo({"data": {}}) is None


class FakeFC:
    def __init__(self, info, stats=None, access="DSL"):
        self.info, self.stats, self.access = info, stats or {}, access

    def call_action(self, svc, act, **kw):
        if svc == "WANDSLInterfaceConfig1":
            if self.info is None:
                raise Exception("UPnPError: invalid action")
            return self.info if act == "GetInfo" else self.stats
        if svc == "WANCommonIFC1" and act == "GetCommonLinkProperties":
            return {"NewWANAccessType": self.access}
        raise Exception("unknown")


DSL_INFO = {"NewStatus": "Up", "NewDownstreamCurrRate": 109_000, "NewUpstreamCurrRate": 34_000, "NewDownstreamMaxRate": 118_500,
            "NewUpstreamMaxRate": 41_000, "NewDownstreamNoiseMargin": 52, "NewUpstreamNoiseMargin": 90,
            "NewDownstreamAttenuation": 140, "NewUpstreamAttenuation": 0}


def test_dsl_values_and_hints():
    st = {}
    line, m = fritzbox.poll_line(FakeFC(DSL_INFO, {"NewCRCErrors": 10, "NewFECErrors": 900, "NewLinkRetrain": 1}), {}, st, now=1000)
    assert (line["kind"], line["rate_down"], line["max_up"], line["snr_down"], line["att_down"]) == ("dsl", 109_000_000, 41_000_000, 5.2, 14.0)
    assert [h["code"] for h in line["hints"]] == ["snr_low"] and "5,2 dB" in line["hints"][0]["de"]
    assert m == {"line:snr_down": 5.2, "line:snr_up": 9.0, "line:rate_down": 109_000_000, "line:rate_up": 34_000_000}
    assert st["line_kind"] == "dsl" and "hints" not in st["line_last"]
    info = dict(DSL_INFO, NewDownstreamNoiseMargin=25)
    line, m = fritzbox.poll_line(FakeFC(info, {"NewCRCErrors": 200, "NewLinkRetrain": 2}), {}, st, now=1060)
    codes = [h["code"] for h in line["hints"]]
    assert codes == ["snr_bad", "crc", "retrain"] and line["hints"][0]["level"] == "bad"
    assert m["line:err"] == 190
    # ohne DSL-Schnittstelle und ohne Kabel: nichts, und das wird gemerkt
    st = {}
    assert fritzbox.poll_line(FakeFC(None, access="Ethernet"), {}, st) == (None, {}) and st["line_kind"] == "none"


def test_cable_interval_and_block(monkeypatch):
    calls = []

    def fake(conf):
        calls.append(1)
        return fritzbox.parse_docinfo(DOCINFO)
    monkeypatch.setattr(fritzbox, "docsis_values", fake)
    fc, conf, st = FakeFC(None, access="X_AVM-DE_Cable"), {"host": "192.0.2.1", "username": "u", "password": "pw"}, {}
    line, m = fritzbox.poll_line(fc, conf, st, now=10_000)
    assert line["kind"] == "cable" and not line.get("cached") and m["line:snr_min"] == 30.1 and st["line_kind"] == "cable"
    # innerhalb von 15 Minuten keine neue Anmeldung, die letzte Messung samt Hinweisen bleibt sichtbar
    line, m = fritzbox.poll_line(fc, conf, st, now=10_300)
    assert line["cached"] and m == {} and len(calls) == 1 and {h["code"] for h in line["hints"]} == {"ds_pwr", "us_pwr", "mse"}
    fritzbox.poll_line(fc, conf, st, now=10_000 + fritzbox.LINE_WEB_S)
    assert len(calls) == 2
    # ohne Passwort: Hinweis statt Anmeldung; abgeschaltet: gar nichts
    assert "Passwort" in fritzbox.poll_line(fc, {"host": "192.0.2.1"}, {"line_kind": "cable"})[0]["error"]
    assert fritzbox.poll_line(fc, dict(conf, line="no"), {"line_kind": "cable"}) == (None, {})
    # abgelehnte Anmeldung: eine Stunde Pause (die FRITZ!Box sperrt sonst immer länger)
    rejected = []

    def deny(conf):
        rejected.append(1)
        raise fritzbox.DriverError("Anmeldung an der Weboberfläche der FRITZ!Box abgelehnt (Benutzer/Passwort prüfen)")
    monkeypatch.setattr(fritzbox, "docsis_values", deny)
    st = {"line_kind": "cable"}
    assert "abgelehnt" in fritzbox.poll_line(fc, conf, st, now=50_000)[0]["error"]
    assert "Stunde" in fritzbox.poll_line(fc, conf, st, now=50_000 + 1000)[0]["error"]
    assert len(rejected) == 1
    fritzbox.poll_line(fc, conf, st, now=50_000 + fritzbox.LINE_BLOCK_S + 1)
    assert len(rejected) == 2


def test_line_event_dashboard_and_pins(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Leitung")
    line = fritzbox.parse_docinfo(DOCINFO)
    hints = fritzbox.line_hints(line)
    out = {"line": dict(line, hints=hints, ts=1), "metrics": fritzbox.line_metrics(line)}

    def fake_poll(conf, state):
        res = dict(info=dict(model="FRITZ!Box 6591 Cable"), wan={}, hosts=[], mesh={}, auth=True, wlan=[], line=out["line"])
        return res, dict(out["metrics"]), state
    monkeypatch.setattr(fritzbox, "poll", fake_poll)

    def events():
        with db() as c:
            return [json.loads(r["data"]) for r in c.execute("SELECT data FROM events WHERE profile_id=? AND kind='line_degraded'", (pid,))]
    integrations.poll(d["fiid"])
    ev = events()
    assert len(ev) == 1 and "Downstream-Pegel" in ev[0]["msg_de"] and "Downstream power" in ev[0]["msg_en"]
    assert "Line: FRITZ!Box – Downstream power" in notify.line("line_degraded", dict(ev[0], name="FRITZ!Box"), "en")
    # gleiche Hinweise: keine neue Meldung; zwischengespeicherte Messung: ebenfalls nicht
    integrations.poll(d["fiid"])
    out["line"] = dict(out["line"], cached=True)
    integrations.poll(d["fiid"])
    assert len(events()) == 1
    out["line"] = dict(out["line"], hints=hints + [fritzbox._hint("uncorr", n=99)], cached=False)
    integrations.poll(d["fiid"])
    assert len(events()) == 2 and "99" in events()[1]["msg_de"]
    r = cl.get(f"{P}/dashboard").json()
    assert {x["en"].split(":")[0] for x in r["line"]} >= {"Downstream power outside the usual range"}
    integ = next(i for i in cl.get(f"{P}/integrations").json()["integrations"] if i["id"] == d["fiid"])
    assert integ["result"]["line"]["ds_31"] == 1
    with db() as c:
        cands = dashlayout.candidates(c, pid, "en")
        prom = prometheus.render(c, pid)
    assert 'diktyo_line_weakest_channel_db{integration="FRITZ!Box"} 30.1' in prom and "diktyo_line_upstream_power_max_dbmv" in prom
    snr = next(x for x in cands if x["keys"] == [f"i{d['fiid']}:line:snr_min"])
    assert (snr["unit"], snr["group"]) == ("dB", "Line (DSL/cable)")
    r = cl.post(f"{P}/dashboard/pins", json=dict(pin=dict(title="Leitung", keys=snr["keys"], names=["schwächster Kanal"], unit="dB", style="line"), size=6), headers=H)
    assert r.status_code == 200, r.text
    assert any((x.get("pin") or {}).get("unit") == "dB" for x in r.json()["items"])
