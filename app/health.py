"""Erreichbarkeit und Firmware je Gerät.

- Verfügbarkeit, Ausfälle und längster Ausfall aus den Online/Offline-Wechseln (status_events) – gemessen wird nur
  der Zeitraum, seit dem díktyo das Gerät überwacht.
- Antwortzeit aus der Online-Überwachung (Zeitreihe „d<ID>:rtt“ in ms, Aufbewahrung wie die übrigen Messwerte).
- Firmware: Integrationen liefern installed/latest/update; apply() legt das am Gerät ab, trägt Versionswechsel in den
  Verlauf ein und meldet neue Updates als Ereignis „firmware_update“.
"""
import datetime as dt
import json
import time

from .db import now, parse_ts


def availability(c, did, hours=24, t=None):
    """-> dict(pct, outages, longest_s, covered_s) oder None, wenn das Gerät in diesem Zeitraum nicht überwacht wurde.
    Zerlegt den Zeitraum in Abschnitte zwischen den Online/Offline-Wechseln; vor dem ersten bekannten Zustand wird nicht gezählt."""
    t = t or dt.datetime.now().astimezone()
    t0 = t - dt.timedelta(hours=hours)
    evs = [(parse_ts(r["ts"]), r["online"]) for r in c.execute("SELECT ts, online FROM status_events WHERE device_id=? ORDER BY ts, id", (did,))]
    before = [on for ts, on in evs if ts <= t0]
    state = before[-1] if before else None
    cursor = t0
    online_s = offline_s = longest = cur_out = 0.0
    outages = 1 if state == 0 else 0
    for ts, on in [e for e in evs if t0 < e[0] <= t] + [(t, None)]:
        span = (ts - cursor).total_seconds()
        if state == 1:
            online_s += span
        elif state == 0:
            offline_s += span
            cur_out += span  # ein Ausfall kann aus mehreren Offline-Meldungen bestehen
            longest = max(longest, cur_out)
        if on is None:
            break
        if on == 0 and state != 0:
            outages += 1
        if on != 0:
            cur_out = 0.0
        state, cursor = on, ts
    covered = online_s + offline_s
    if covered < 60:  # weniger als eine Minute überwacht: noch keine Aussage
        return None
    return dict(pct=round(100 * online_s / covered, 2), outages=outages, longest_s=int(longest), covered_s=int(covered))


def rtt_avg(c, pid, did, since_s=86400):
    r = c.execute("""SELECT AVG(m.value) AS a, COUNT(*) AS n FROM metrics m JOIN series s ON s.id=m.series_id
                     WHERE s.profile_id=? AND s.key=? AND m.ts>=?""", (pid, f"d{did}:rtt", int(time.time()) - since_s)).fetchone()
    return round(r["a"], 1) if r and r["n"] else None


def device(c, pid, did):
    d = c.execute("SELECT data FROM devices WHERE id=? AND profile_id=?", (did, pid)).fetchone()
    fw = json.loads(d["data"] or "{}").get("firmware") if d else None
    from . import clienttraffic
    live, today = clienttraffic.device(*clienttraffic.collect(c, pid), clienttraffic.macs_of(c, did))
    web_ip = ((json.loads(d["data"] or "{}") if d else {}).get("smart") or {}).get("ip")
    return dict(availability={h: availability(c, did, h) for h in (24, 168, 720)}, rtt_24h=rtt_avg(c, pid, did), firmware=fw, web_ip=web_ip,
                today=today, live=live)


def overview(c, pid):
    """Bestätigte Geräte mit Überwachungsdaten oder Firmware-Angaben – die mit den meisten Problemen zuerst."""
    out = []
    for d in c.execute("SELECT id, name, type, online, data FROM devices WHERE profile_id=? AND status='confirmed'", (pid,)):
        fw = json.loads(d["data"] or "{}").get("firmware")
        a24, a7 = availability(c, d["id"], 24), availability(c, d["id"], 168)
        rtt = rtt_avg(c, pid, d["id"])
        if not (a24 or a7 or fw or rtt is not None or d["online"] is not None):
            continue  # weder überwacht noch Firmware bekannt
        out.append(dict(id=d["id"], name=d["name"], type=d["type"], online=d["online"], a24=a24, a7=a7, rtt=rtt, firmware=fw))
    out.sort(key=lambda x: (x["online"] != 0, not (x["firmware"] or {}).get("update"), (x["a7"] or {}).get("pct", 100), x["name"].lower()))
    return out


def _same_version(a, b):
    """Gleiche Version in anderer Schreibweise (z. B. „161.08.25“ und „8.25“, „3006_102_46475-g…“ und „3.0.0.6.102_46475“)?"""
    import re
    da, db_ = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    short, long_ = sorted((da, db_), key=len)
    return bool(short) and (long_.startswith(short) or long_.endswith(short))


def apply_firmware(c, pid, did, fw, source):
    """Firmware-Angaben am Gerät ablegen; Versionswechsel in den Verlauf, neues Update als Ereignis."""
    if not did or not fw or not (fw.get("installed") or fw.get("update") is not None):
        return
    from . import changes
    from .scan import runner
    r = c.execute("SELECT data, name FROM devices WHERE id=?", (did,)).fetchone()
    if not r:
        return
    data = json.loads(r["data"] or "{}")
    old = data.get("firmware") or {}
    new = dict(installed=str(fw.get("installed") or "")[:60], latest=str(fw.get("latest") or "")[:60], update=bool(fw.get("update")),
               info=str(fw.get("info") or "")[:200], source=source, checked=now())
    if old.get("installed") and new["installed"] and old["installed"] != new["installed"] and not _same_version(old["installed"], new["installed"]):
        changes.record(c, pid, did, "changed", "firmware", old["installed"], new["installed"], source)
    if new["update"] and (not old.get("update") or old.get("latest") != new["latest"]):
        runner.event(c, pid, "firmware_update", did, name=r["name"], installed=new["installed"], latest=new["latest"], source=source)
    req = data.get("fw_requested")
    if req:  # von díktyo angestoßenes Update: angekommen? sonst nach 20 Minuten deutlicher Hinweis
        if new["installed"] and new["installed"] != req.get("installed") and not _same_version(new["installed"], req.get("installed") or "x"):
            data.pop("fw_requested", None)
            old = {}  # Speichern erzwingen
        elif time.time() - req.get("ts", 0) > 20 * 60:
            new["stuck"] = dict(since=req["ts"], installed=req.get("installed", ""), target=req.get("target", ""))
            if time.time() - req["ts"] > 7 * 86400:
                data.pop("fw_requested", None)
    if {k: v for k, v in old.items() if k != "checked"} != {k: v for k, v in new.items() if k != "checked"} or \
            not old.get("checked") or time.time() - parse_ts(old["checked"]).timestamp() > 3600:
        data["firmware"] = new
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), did))


def apply_result(c, row, res, summary):
    """Nach einer Integrationsabfrage: Firmware des eigenen Geräts bzw. der vom Controller verwalteten Geräte übernehmen."""
    pid, src = row["profile_id"], row["driver"]
    if res.get("firmware"):
        apply_firmware(c, pid, (summary or {}).get("device_id") or row["device_id"], res["firmware"], src)
    for d in res.get("devices") or []:
        if d.get("firmware_info") and d.get("mac"):
            m = c.execute("SELECT i.device_id FROM interfaces i JOIN devices dv ON dv.id=i.device_id WHERE dv.profile_id=? AND i.mac=?",
                          (pid, d["mac"])).fetchone()
            if m:
                apply_firmware(c, pid, m["device_id"], d["firmware_info"], src)
    for n in res.get("nodes_fw") or []:  # Proxmox: je Knoten
        m = c.execute("SELECT id FROM devices WHERE profile_id=? AND json_extract(data,'$.proxmox.node')=? AND type='hypervisor'",
                      (pid, n["node"])).fetchone()
        if m:
            apply_firmware(c, pid, m["id"], n, src)
