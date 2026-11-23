"""Prometheus-Endpunkt für Grafana: aktuelle Messwerte eines Profils im Prometheus-Textformat.

Abgerufen unter /api/profiles/<id>/prometheus mit „Authorization: Bearer <token>“. Das Token gilt nur für dieses
Profil und nur zum Lesen der Messwerte; gespeichert ist nur sein Hash (profiles.settings["prometheus"]). Prometheus
fragt regelmäßig ab und hält den Verlauf selbst – díktyo liefert jeweils den aktuellen Stand:
Geräte online/offline, Antwortzeit, Verfügbarkeit, Leistung, WAN, Switch-Ports, DNS-Filter, Speedtest, Integrationen,
Firmware-Updates, Wachliste, offene VLAN-Umstellungen. Dazu ein fertiges Grafana-Dashboard (grafana_dashboard).
"""
import datetime as dt
import hmac
import json
import time

from . import security
from .db import now, parse_ts

FRESH_S = 900  # Messwerte älter als 15 Minuten gelten als veraltet und werden nicht ausgegeben
INFRA = ("router", "switch", "ap", "mesh", "firewall", "modem", "hypervisor", "server", "nas", "repeater", "powerline")


# ------------------------------------------------------------ Token
def _settings(c, pid):
    r = c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()
    return json.loads(r["settings"] or "{}") if r else None


def info(c, pid):
    p = (_settings(c, pid) or {}).get("prometheus") or {}
    return dict(enabled=bool(p.get("token_hash")), created=p.get("created"), last_scrape=p.get("last_scrape"))


def new_token(c, pid):
    """Neues Token (das alte wird ungültig). -> Klartext, nur jetzt sichtbar"""
    st = _settings(c, pid)
    tok, th = security.new_token()
    st["prometheus"] = dict(token_hash=th, created=now())
    c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
    return tok


def revoke(c, pid):
    st = _settings(c, pid)
    st.pop("prometheus", None)
    c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))


def check(c, pid, auth_header):
    """True, wenn der Bearer-Token zum Profil passt. Merkt sich den Zeitpunkt der letzten Abfrage (höchstens minütlich)."""
    st = _settings(c, pid)
    p = (st or {}).get("prometheus") or {}
    tok = (auth_header or "").removeprefix("Bearer ").strip() if (auth_header or "").startswith("Bearer ") else ""
    ok = bool(p.get("token_hash")) and bool(tok) and hmac.compare_digest(security.sha256(tok), p["token_hash"])
    if ok and (not p.get("last_scrape") or time.time() - parse_ts(p["last_scrape"]).timestamp() > 60):
        p["last_scrape"] = now()
        st["prometheus"] = p
        c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
    return ok


# ------------------------------------------------------------ Ausgabe
def _esc(v):
    return str(v if v is not None else "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class Out:
    def __init__(self):
        self.fam, self.order = {}, []

    def add(self, name, help_, typ, value, **labels):
        if value is None:
            return
        if name not in self.fam:
            self.fam[name] = (help_, typ, [])
            self.order.append(name)
        lab = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
        self.fam[name][2].append(f"{name}{{{lab}}} {float(value):.6g}" if lab else f"{name} {float(value):.6g}")

    def text(self):
        out = []
        for n in self.order:
            h, t, lines = self.fam[n]
            out += [f"# HELP {n} {h}", f"# TYPE {n} {t}", *lines]
        return "\n".join(out) + "\n"


def _latest(c, pid):
    """-> {key: (value, unit)} – jüngster Wert je Messreihe der letzten FRESH_S Sekunden."""
    rows = c.execute("""SELECT s.key, s.unit, m.value, MAX(m.ts) AS ts FROM series s JOIN metrics m ON m.series_id=s.id
                        WHERE s.profile_id=? AND m.ts>=? GROUP BY s.id""", (pid, int(time.time()) - FRESH_S))
    return {r["key"]: (r["value"], r["unit"]) for r in rows}


def render(c, pid):
    from . import health, vlanplan, watch
    from .version import VERSION
    o = Out()
    prof = c.execute("SELECT name FROM profiles WHERE id=?", (pid,)).fetchone()
    o.add("diktyo_info", "díktyo-Version und Profil", "gauge", 1, version=VERSION, profile=prof["name"] if prof else "")
    devs = c.execute("""SELECT d.id, d.name, d.type, d.status, d.online, d.data, l.name AS loc,
                               (SELECT address FROM ip_addresses WHERE device_id=d.id ORDER BY id LIMIT 1) AS ip
                        FROM devices d LEFT JOIN locations l ON l.id=d.location_id WHERE d.profile_id=?""", (pid,)).fetchall()
    names = {d["id"]: d["name"] for d in devs}
    conf = [d for d in devs if d["status"] == "confirmed"]
    o.add("diktyo_devices", "Bestätigte Geräte", "gauge", len(conf))
    o.add("diktyo_devices_online", "Bestätigte Geräte, die gerade online sind", "gauge", sum(1 for d in conf if d["online"] == 1))
    o.add("diktyo_devices_offline", "Bestätigte überwachte Geräte, die gerade offline sind", "gauge", sum(1 for d in conf if d["online"] == 0))
    o.add("diktyo_inbox_devices", "Gefundene, noch nicht übernommene Geräte (Posteingang)", "gauge", sum(1 for d in devs if d["status"] == "discovered"))
    lat = _latest(c, pid)
    for d in conf:
        did = str(d["id"])  # id-Label: eindeutig, auch wenn zwei Geräte gleich heißen
        lab = dict(id=did, device=d["name"], type=d["type"], ip=d["ip"] or "", location=d["loc"] or "", infra="1" if d["type"] in INFRA else "0")
        if d["online"] is not None:
            o.add("diktyo_device_up", "Gerät erreichbar (1) oder nicht (0) laut Online-Überwachung", "gauge", d["online"], **lab)
        if f"d{d['id']}:rtt" in lat:
            o.add("diktyo_device_rtt_milliseconds", "Antwortzeit des Geräts (letzte Messung)", "gauge", lat[f"d{d['id']}:rtt"][0], id=did, device=d["name"])
        if f"d{d['id']}:power" in lat:
            o.add("diktyo_device_power_watts", "Leistung (Shelly/Tasmota/Home Assistant)", "gauge", lat[f"d{d['id']}:power"][0], id=did, device=d["name"])
        if d["type"] in INFRA and d["online"] is not None:
            a = health.availability(c, d["id"], 24)
            if a:
                o.add("diktyo_device_availability_ratio", "Verfügbarkeit der letzten 24 Stunden (0–1)", "gauge", a["pct"] / 100, id=did, device=d["name"], window="24h")
        fw = (json.loads(d["data"] or "{}").get("firmware") or {})
        if fw.get("installed"):
            o.add("diktyo_device_firmware_update_available", "Firmware-Update verfügbar (1) oder nicht (0)", "gauge", 1 if fw.get("update") else 0,
                  id=did, device=d["name"], installed=fw.get("installed") or "", latest=fw.get("latest") or "")
    # Integrationen und ihre Messreihen
    integ = c.execute("SELECT * FROM integrations WHERE profile_id=?", (pid,)).fetchall()
    inames = {r["id"]: r["name"] for r in integ}
    t_now = dt.datetime.now().astimezone()
    for r in integ:
        ok = 1 if r["enabled"] and r["last_ok"] and (not r["last_error"] or (r["last_poll"] and r["last_ok"] >= r["last_poll"])) else 0
        o.add("diktyo_integration_up", "Integration antwortet (1) oder ist gestört/pausiert (0)", "gauge", ok, integration=r["name"], driver=r["driver"])
        if r["last_ok"]:
            o.add("diktyo_integration_last_success_seconds", "Sekunden seit der letzten erfolgreichen Abfrage", "gauge",
                  max(0, (t_now - parse_ts(r["last_ok"])).total_seconds()), integration=r["name"], driver=r["driver"])
    port_names, peers = {}, {}
    for r in c.execute("""SELECT g.id AS iid, i.port_no, i.name FROM integrations g JOIN interfaces i ON i.device_id=g.device_id AND i.role='port'
                          WHERE g.profile_id=?""", (pid,)):
        port_names[(r["iid"], r["port_no"])] = r["name"] or str(r["port_no"])
    from .dashboard import _port_peer
    devof = {r["id"]: r["device_id"] for r in integ}
    for key, (val, unit) in lat.items():
        p = key.split(":")
        if not p[0].startswith("i") or not p[0][1:].isdigit():
            continue
        iid = int(p[0][1:])
        src = inames.get(iid, "")
        dev = names.get(devof.get(iid), src)
        if p[1] == "wan" and len(p) == 3:
            o.add(f"diktyo_wan_{'receive' if p[2] == 'rx' else 'transmit'}_bits_per_second", "WAN-Traffic (Download = receive, Upload = transmit)",
                  "gauge", val, integration=src)
        elif p[1] == "port" and len(p) == 4:
            no = int(p[2])
            if (iid, no) not in peers:
                peers[(iid, no)] = ", ".join(x["name"] for x in _port_peer(c, devof.get(iid), no)["peers"]) if devof.get(iid) else ""
            # rx = vom Switch empfangen (= Upload des angeschlossenen Geräts)
            o.add(f"diktyo_port_{'receive' if p[3] == 'rx' else 'transmit'}_bits_per_second", "Traffic je Switch-Port (aus Sicht des Switches)",
                  "gauge", val, device=dev, port=port_names.get((iid, no), str(no)), peer=peers[(iid, no)])
        elif p[1] == "if" and len(p) == 4:
            o.add(f"diktyo_interface_{'receive' if p[3] == 'rx' else 'transmit'}_bits_per_second", "Traffic je Schnittstelle (z. B. ASUS LAN/WLAN)",
                  "gauge", val, device=dev, interface=p[2])
        elif p[1] == "dns" and len(p) == 3:
            m = {"qpm": ("diktyo_dns_queries_per_minute", "DNS-Anfragen pro Minute"), "bpm": ("diktyo_dns_blocked_per_minute", "Blockierte DNS-Anfragen pro Minute"),
                 "blocked_pct": ("diktyo_dns_blocked_ratio", "Anteil blockierter DNS-Anfragen (0–1)")}.get(p[2])
            if m:
                o.add(m[0], m[1], "gauge", val / 100 if p[2] == "blocked_pct" else val, integration=src)
    # Speedtest
    st = c.execute("SELECT * FROM speedtests WHERE profile_id=? AND kind='internet' AND down_bps IS NOT NULL ORDER BY ts DESC LIMIT 1", (pid,)).fetchone()
    if st:
        o.add("diktyo_speedtest_download_bits_per_second", "Letzter Internet-Speedtest: Download", "gauge", st["down_bps"])
        o.add("diktyo_speedtest_upload_bits_per_second", "Letzter Internet-Speedtest: Upload", "gauge", st["up_bps"])
        o.add("diktyo_speedtest_ping_milliseconds", "Letzter Internet-Speedtest: Ping", "gauge", st["ping_ms"])
        o.add("diktyo_speedtest_jitter_milliseconds", "Letzter Internet-Speedtest: Jitter", "gauge", st["jitter_ms"])
        o.add("diktyo_speedtest_timestamp_seconds", "Zeitpunkt des letzten Speedtests (Unix-Zeit)", "gauge", parse_ts(st["ts"]).timestamp())
    # Wachliste und VLAN-Plan
    w = watch.state(c, pid)
    o.add("diktyo_watch_alarms", "Systeme auf der Wachliste mit Alarm", "gauge", w["alarms"])
    for x in w["items"]:
        o.add("diktyo_watch_alarm", "Wachliste: 1 = Alarm (offline oder geändert), 0 = ruhig", "gauge", 0 if x["state"] == "ok" else 1,
              id=str(x["id"]), device=x["name"], state=x["state"])
    if vlanplan.plan_info(c, pid):
        o.add("diktyo_vlan_plan_open_changes", "Ports, die laut VLAN-Plan noch umzustellen sind", "gauge", len(vlanplan.diff(c, pid)))
    return o.text()


# ------------------------------------------------------------ Grafana
def grafana_dashboard(profile_name):
    """Fertiges Dashboard zum Importieren (Grafana → Dashboards → Import). Datenquelle wird beim Import gewählt."""
    ds = {"type": "prometheus", "uid": "${DS_PROMETHEUS}"}
    pid = [0]

    def panel(title, typ, exprs, x, y, w, h, unit="", legend="", **extra):
        pid[0] += 1
        p = dict(id=pid[0], title=title, type=typ, datasource=ds, gridPos=dict(x=x, y=y, w=w, h=h),
                 targets=[dict(refId=chr(65 + i), expr=e, legendFormat=legend if isinstance(legend, str) else legend[i], datasource=ds)
                          for i, e in enumerate(exprs)],
                 fieldConfig=dict(defaults=dict(unit=unit), overrides=[]), options={})
        p.update(extra)
        return p

    stat_opts = dict(options=dict(reduceOptions=dict(calcs=["lastNotNull"]), colorMode="background", graphMode="none", textMode="value"))
    panels = [
        panel("Geräte online", "stat", ["diktyo_devices_online"], 0, 0, 4, 4, **stat_opts),
        panel("Offline", "stat", ["diktyo_devices_offline"], 4, 0, 4, 4, **stat_opts),
        panel("Wachliste: Alarme", "stat", ["diktyo_watch_alarms"], 8, 0, 4, 4, **stat_opts),
        panel("Integrationen gestört", "stat", ["count(diktyo_integration_up == 0) or vector(0)"], 12, 0, 4, 4, **stat_opts),
        panel("Firmware-Updates", "stat", ["sum(diktyo_device_firmware_update_available) or vector(0)"], 16, 0, 4, 4, **stat_opts),
        panel("Posteingang", "stat", ["diktyo_inbox_devices"], 20, 0, 4, 4, **stat_opts),
        panel("WAN-Traffic", "timeseries", ["diktyo_wan_receive_bits_per_second", "-diktyo_wan_transmit_bits_per_second"], 0, 4, 16, 9, "bps",
              ["↓ {{integration}}", "↑ {{integration}}"]),
        panel("Letzter Speedtest", "stat", ["diktyo_speedtest_download_bits_per_second", "diktyo_speedtest_upload_bits_per_second"], 16, 4, 8, 5, "bps",
              ["Download", "Upload"], options=dict(reduceOptions=dict(calcs=["lastNotNull"]), colorMode="value", graphMode="area", textMode="value_and_name")),
        panel("Ping / Jitter", "stat", ["diktyo_speedtest_ping_milliseconds", "diktyo_speedtest_jitter_milliseconds"], 16, 9, 8, 4, "ms", ["Ping", "Jitter"],
              options=dict(reduceOptions=dict(calcs=["lastNotNull"]), colorMode="value", graphMode="none", textMode="value_and_name")),
        panel("Antwortzeit Infrastruktur", "timeseries", ['diktyo_device_rtt_milliseconds * on(id) group_left() max by (id) (diktyo_device_up{infra="1"} >= 0)'],
              0, 13, 12, 9, "ms", "{{device}}"),
        panel("Verfügbarkeit (24 h)", "bargauge", ["diktyo_device_availability_ratio"], 12, 13, 12, 9, "percentunit", "{{device}}",
              options=dict(orientation="horizontal", displayMode="gradient", reduceOptions=dict(calcs=["lastNotNull"]))),
        panel("Aktivste Switch-Ports", "timeseries", ["topk(8, diktyo_port_receive_bits_per_second + diktyo_port_transmit_bits_per_second)"], 0, 22, 12, 9, "bps",
              "{{device}} · {{port}} → {{peer}}"),
        panel("DNS-Anfragen", "timeseries", ["diktyo_dns_queries_per_minute", "diktyo_dns_blocked_per_minute"], 12, 22, 12, 9, "short",
              ["Anfragen/min {{integration}}", "blockiert/min {{integration}}"]),
        panel("Geräte offline", "table", ["diktyo_device_up == 0"], 0, 31, 12, 8, "", "",
              options=dict(showHeader=True), transformations=[dict(id="labelsToFields", options={}),
                                                               dict(id="organize", options=dict(excludeByName={"Time": True, "Value": True, "__name__": True, "infra": True, "id": True,
                                                                                                   "instance": True, "job": True}))]),
        panel("Leistung", "timeseries", ["diktyo_device_power_watts"], 12, 31, 12, 8, "watt", "{{device}}"),
    ]
    return {
        "__inputs": [dict(name="DS_PROMETHEUS", label="Prometheus", type="datasource", pluginId="prometheus", pluginName="Prometheus")],
        "title": f"díktyo · {profile_name}", "uid": None, "tags": ["diktyo", "network"], "timezone": "browser", "schemaVersion": 39,
        "refresh": "1m", "time": dict(**{"from": "now-24h", "to": "now"}), "panels": panels, "templating": dict(list=[]), "annotations": dict(list=[]),
    }
