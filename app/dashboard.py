"""Übersichtsseite eines Profils: Kennzahlen, offene Probleme, WAN, Infrastruktur, aktivste Ports, letzte Änderungen."""
import datetime as dt
import json

from . import changes, health, watch
from .actions import INFRA

WAN_DRIVERS = ("fritzbox", "unifi", "mikrotik", "opnsense", "asuswrt", "openwrt")
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
                    ports.append(dict(integration=r["id"], device=r["name"], device_id=r["device_id"], port_no=p["port_no"],
                                      name=p.get("name") or str(p["port_no"]), in_bps=p.get("in_bps"), out_bps=p.get("out_bps"), total=total,
                                      speed=p.get("speed") or 0, keys=[f"i{r['id']}:port:{p['port_no']}:rx", f"i{r['id']}:port:{p['port_no']}:tx"]))
    ports.sort(key=lambda x: -x["total"])
    ports = ports[:6]
    for p in ports:  # Gerätename statt Integrationsname, und was am Port hängt
        p.update(_port_peer(c, p["device_id"], p["port_no"]))
        if p["device_id"]:
            n = c.execute("SELECT name FROM devices WHERE id=?", (p["device_id"],)).fetchone()
            if n:
                p["device"] = n["name"]
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
    # gerade aktiv: Live-Raten je Gerät aus den Integrationen
    from . import clienttraffic
    live, _ = clienttraffic.collect(c, pid)
    per = {}
    for m, x in live.items():
        did, name = by_mac.get(m, (None, m))
        k = did or m
        p = per.setdefault(k, dict(device_id=did, name=name, mac=m, down=0, up=0, source=x["source"]))
        p["down"] += x["down"]
        p["up"] += x["up"]
    top_now = sorted((x for x in per.values() if x["down"] + x["up"] > 0), key=lambda x: -(x["down"] + x["up"]))[:8]
    # DNS-Filter (Pi-hole / AdGuard Home): Zusammenfassung und Geräte mit den meisten Blockierungen
    dns = None
    by_ip = {r["address"]: (r["device_id"], r["name"]) for r in c.execute(
        "SELECT a.address, d.id AS device_id, d.name FROM ip_addresses a JOIN devices d ON d.id=a.device_id WHERE d.profile_id=?", (pid,))}
    for r in integ:
        if r["driver"] != "dnsfilter":
            continue
        res_ = json.loads(r["state"] or "{}").get("result") or {}
        if res_.get("summary"):
            top = sorted((x for x in res_.get("clients") or [] if x.get("blocked")), key=lambda x: -x["blocked"])[:8]
            for x in top:
                did, name = by_ip.get(x["ip"], (None, x.get("name") or x["ip"]))
                x.update(device_id=did, label=name)
            dns = dict(integration=r["id"], name=r["name"], info=res_.get("info"), summary=res_["summary"], top=top,
                       top_domains=(res_.get("top_domains") or [])[:5], keys=[f"i{r['id']}:dns:qpm", f"i{r['id']}:dns:bpm"])
            break
    # Internet-Geschwindigkeit: letzte Messungen; deutlich unter der Leitung (laut Router) -> Hinweis
    from . import speedtest
    hist = speedtest.history(c, pid, limit=120)
    speed = None
    if hist:
        last = hist[0]
        line = (wan or {}).get("max_down")
        slow = bool(line and last["down_bps"] and last["down_bps"] < 0.5 * line)
        speed = dict(last=last, line_down=line, line_up=(wan or {}).get("max_up"), slow=slow,
                     points=[[x["ts"], x["down_bps"], x["up_bps"], x["ping_ms"]] for x in reversed(hist)])
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
        infra.append(dict(id=d["id"], name=d["name"], type=d["type"], online=d["online"], a24=a24, a7=health.availability(c, d["id"], 168),
                          rtt=health.rtt_avg(c, pid, d["id"]),
                          fw_update=bool((json.loads(d["data"] or "{}").get("firmware") or {}).get("update"))))
    infra.sort(key=lambda x: (x["online"] != 0, (x["a24"] or {}).get("pct", 100), ["router", "firewall", "modem", "switch"].index(x["type"])
                              if x["type"] in ("router", "firewall", "modem", "switch") else 9, x["name"].lower()))
    avail = [x["a24"]["pct"] for x in infra if x["a24"]]
    rtt_keys = _rtt(c, pid, [x for x in infra if x["rtt"] is not None][:10])
    from . import dashlayout
    return dict(
        layout=dashlayout.get(c, pid),
        counts=dict(devices=len(confirmed), online=sum(1 for d in confirmed if d["online"] == 1), offline=len(offline),
                    inbox=sum(1 for d in devs if d["status"] == "discovered"), firmware=len(fw_up), quarantine=quarantine,
                    availability=round(sum(avail) / len(avail), 2) if avail else None),
        wan=wan, speed=speed, dns=dns, top_today=top_today, top_now=top_now, offline=offline[:12], firmware=fw_up[:12], broken=broken, failed=failed[:10], ports=ports, infra=infra[:16],
        rtt=rtt_keys, recent=[x for x in changes.timeline(c, pid, limit=12) if x["cat"] in ("change", "action", "quarantine")][:8],
        summary=changes.summary(c, pid), watch=watch.state(c, pid))


def _port_peer(c, did, port_no):
    """Welche Geräte hängen an diesem Port (Verbindungen in der Topologie)? -> dict(peers=[{id, name}])"""
    if not did:
        return dict(peers=[])
    r = c.execute("SELECT id FROM interfaces WHERE device_id=? AND role='port' AND port_no=?", (did, port_no)).fetchone()
    if not r:
        return dict(peers=[])
    rows = c.execute("""SELECT d.id, d.name FROM links l JOIN interfaces i ON i.id = CASE WHEN l.b_if=? THEN l.a_if ELSE l.b_if END
                        JOIN devices d ON d.id=i.device_id WHERE (l.a_if=? OR l.b_if=?) AND d.id<>? ORDER BY d.name""",
                     (r["id"], r["id"], r["id"], did)).fetchall()
    return dict(peers=[dict(id=x["id"], name=x["name"]) for x in rows])


def _rtt(c, pid, infra):
    """Antwortzeiten der Infrastruktur: Mittel, Höchstwert und Verlauf der letzten 24 Stunden je Gerät."""
    from . import metrics
    keys = [f"d{x['id']}:rtt" for x in infra]
    q = metrics.query(c, pid, keys, 86400, points=72)["series"] if keys else {}
    out = []
    for x, k in zip(infra, keys):
        pts = q.get(k) or []
        vals = [v for _, v in pts]
        out.append(dict(id=x["id"], name=x["name"], type=x["type"], online=x["online"], key=k, avg=x["rtt"],
                        max=max(vals) if vals else None, last=vals[-1] if vals else None, spark=vals))
    return out
