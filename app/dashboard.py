"""Übersichtsseite eines Profils: Kennzahlen, offene Probleme, WAN, Infrastruktur, aktivste Ports, letzte Änderungen."""
import datetime as dt
import json

from . import changes, health
from .actions import INFRA

WAN_DRIVERS = ("fritzbox", "unifi", "mikrotik", "opnsense", "asuswrt")
PORT_DRIVERS = ("snmp", "mikrotik", "opnsense")


def build(c, pid):
    devs = c.execute("SELECT id, name, type, status, online, data FROM devices WHERE profile_id=?", (pid,)).fetchall()
    confirmed = [d for d in devs if d["status"] == "confirmed"]
    fw_up = []
    for d in confirmed:
        fw = (json.loads(d["data"] or "{}").get("firmware") or {})
        if fw.get("update"):
            fw_up.append(dict(id=d["id"], name=d["name"], installed=fw.get("installed"), latest=fw.get("latest")))
    offline = [dict(id=d["id"], name=d["name"], type=d["type"]) for d in confirmed if d["online"] == 0]
    offline.sort(key=lambda x: (x["type"] not in INFRA, x["name"].lower()))
    # Integrationen: WAN, Fehler, aktivste Ports
    integ = c.execute("SELECT * FROM integrations WHERE profile_id=? AND enabled=1 ORDER BY id", (pid,)).fetchall()
    wan, broken, ports = None, [], []
    for r in integ:
        st = json.loads(r["state"] or "{}")
        res = st.get("result") or {}
        if r["last_error"] and not r["last_ok"]:
            broken.append(dict(id=r["id"], name=r["name"], driver=r["driver"], error=r["last_error"]))
        elif r["last_error"] and r["last_ok"] and r["last_poll"] and r["last_poll"] > r["last_ok"]:
            broken.append(dict(id=r["id"], name=r["name"], driver=r["driver"], error=r["last_error"]))
        w = res.get("wan") or {}
        if wan is None and r["driver"] in WAN_DRIVERS and (w.get("rx_bps") is not None or w.get("connected") is not None):
            wan = dict(integration=r["id"], name=r["name"], connected=w.get("connected"), rx_bps=w.get("rx_bps"), tx_bps=w.get("tx_bps"),
                       max_down=w.get("max_down"), max_up=w.get("max_up"), keys=[f"i{r['id']}:wan:rx", f"i{r['id']}:wan:tx"])
        if r["driver"] in PORT_DRIVERS:
            for p in res.get("ports") or []:
                total = (p.get("in_bps") or 0) + (p.get("out_bps") or 0)
                wan_if = (res.get("wan") or {}).get("iface")
                if total > 0 and not (wan_if and p.get("iface") == wan_if):  # WAN-Port steht schon oben
                    ports.append(dict(integration=r["id"], device=r["name"], port_no=p["port_no"], name=p.get("name") or str(p["port_no"]),
                                      in_bps=p.get("in_bps"), out_bps=p.get("out_bps"), total=total,
                                      keys=[f"i{r['id']}:port:{p['port_no']}:rx", f"i{r['id']}:port:{p['port_no']}:tx"]))
    ports.sort(key=lambda x: -x["total"])
    top_today = []
    by_mac = {r["mac"]: (r["device_id"], r["name"]) for r in c.execute(
        "SELECT i.mac, d.id AS device_id, d.name FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND i.mac<>''", (pid,))}
    for r in integ:
        ta = ((json.loads(r["state"] or "{}").get("result") or {}).get("analyzer") or {})
        for x in (ta.get("clients") or [])[:8]:
            did, name = by_mac.get(x["mac"], (None, x["mac"]))
            top_today.append(dict(device_id=did, name=name, mac=x["mac"], rx=x["rx"], tx=x["tx"]))
        if top_today:
            break
    # Aktionen/Zeitpläne der letzten 24 Stunden, die nicht geklappt haben
    since = (dt.datetime.now().astimezone() - dt.timedelta(hours=24)).isoformat(timespec="seconds")
    failed = [dict(ts=r["created"], label=r["label"], message=r["message"]) for r in c.execute(
        "SELECT * FROM actions WHERE profile_id=? AND created>=? AND status<>'done' ORDER BY id DESC LIMIT 10", (pid, since))]
    failed += [dict(ts=r["undone"], label=f"Zurückschalten: {r['label']}", message=r["undo_result"]) for r in c.execute(
        "SELECT * FROM actions WHERE profile_id=? AND undone>=? AND undo_result NOT LIKE 'done%'", (pid, since))]
    quarantine = c.execute("SELECT COUNT(*) FROM quarantine WHERE profile_id=? AND status='active'", (pid,)).fetchone()[0]
    # Infrastruktur: Verfügbarkeit und Antwortzeit
    infra = []
    for d in confirmed:
        if d["type"] not in INFRA:
            continue
        a24 = health.availability(c, d["id"], 24)
        infra.append(dict(id=d["id"], name=d["name"], type=d["type"], online=d["online"], a24=a24, rtt=health.rtt_avg(c, pid, d["id"]),
                          fw_update=bool((json.loads(d["data"] or "{}").get("firmware") or {}).get("update"))))
    infra.sort(key=lambda x: (x["online"] != 0, (x["a24"] or {}).get("pct", 100), ["router", "firewall", "modem", "switch"].index(x["type"])
                              if x["type"] in ("router", "firewall", "modem", "switch") else 9, x["name"].lower()))
    avail = [x["a24"]["pct"] for x in infra if x["a24"]]
    rtt_keys = [dict(id=x["id"], name=x["name"], key=f"d{x['id']}:rtt") for x in infra if x["rtt"] is not None][:4]
    return dict(
        counts=dict(devices=len(confirmed), online=sum(1 for d in confirmed if d["online"] == 1), offline=len(offline),
                    inbox=sum(1 for d in devs if d["status"] == "discovered"), firmware=len(fw_up), quarantine=quarantine,
                    availability=round(sum(avail) / len(avail), 2) if avail else None),
        wan=wan, top_today=top_today, offline=offline[:12], firmware=fw_up[:12], broken=broken, failed=failed[:10], ports=ports[:4], infra=infra[:12],
        rtt=rtt_keys, recent=[x for x in changes.timeline(c, pid, limit=12) if x["cat"] in ("change", "action", "quarantine")][:8],
        summary=changes.summary(c, pid))
