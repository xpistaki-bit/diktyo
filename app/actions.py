"""Schaltaktionen über die Integrationen: WLAN und Internetzugang (FRITZ!Box), Switch-Ports und PoE (SNMP), VMs (Proxmox).

Regeln:
- Angeboten wird nur, was zum Gerät passt (available); ausgeführt wird nur, was angeboten wird (run prüft erneut).
- Vor Änderungen an der Konfiguration eine Konfigurationssicherung, wenn die letzte älter als eine Stunde ist.
- Schutz vor dem Aussperren: kein Abschalten des Switch-Ports, über den díktyo bzw. der Router den Switch erreicht;
  kein Internet-Sperren für Infrastruktur oder díktyo selbst; díktyos eigene VM wird nicht heruntergefahren.
- Optional automatisch zurückschalten (undo_at); erledigt der Hintergrunddienst.
- Jede Aktion landet im Protokoll (Tabelle actions + Audit).
"""
import datetime as dt
import ipaddress
import json
import time

from . import configbackup
from .db import audit, db, now, parse_ts
from .drivers import DRIVERS, ERRORS

INFRA = ("router", "modem", "firewall", "switch", "ap", "mesh", "repeater", "powerline", "hypervisor")
CONFIG_CHANGING = {"wlan", "internet", "port", "reboot"}
BACKUP_MAX_AGE = 3600


class ActionError(Exception):
    pass


def _own_addresses():
    """IPv4- und MAC-Adressen des Rechners, auf dem díktyo läuft."""
    from .scan import netinfo
    ips = {i["ip"] for i in netinfo.interfaces()}
    macs = set()
    try:
        import pathlib
        for p in pathlib.Path("/sys/class/net").iterdir():
            m = (p / "address").read_text().strip().upper()
            if m and m != "00:00:00:00:00:00":
                macs.add(m)
    except OSError:
        pass
    return ips, macs


def _integrations(c, pid, driver):
    return [r for r in c.execute("SELECT * FROM integrations WHERE profile_id=? AND driver=? AND enabled=1 ORDER BY id", (pid, driver))]


def _state(row):
    return json.loads(row["state"] or "{}")


def _ipv4(ips):
    out = []
    for a in ips:
        try:
            if ipaddress.ip_address(a).version == 4:
                out.append(a)
        except ValueError:
            pass
    return out


def _same_lan(ip, host, c, pid):
    """Liegt ip im Netz der FRITZ!Box (Subnetz aus dem IPAM, sonst /24)?"""
    try:
        a, b = ipaddress.ip_address(ip), ipaddress.ip_address(host)
    except ValueError:
        return False
    for r in c.execute("SELECT cidr FROM subnets WHERE profile_id=?", (pid,)):
        try:
            net = ipaddress.ip_network(r["cidr"], strict=False)
        except ValueError:
            continue
        if b in net:
            return a in net
    return a in ipaddress.ip_network(f"{host}/24", strict=False)


def _undo_options(kind):
    return kind in ("wlan", "internet", "port")


def _act(kind, iid, params, label, detail="", danger=False, blocked=""):
    return dict(kind=kind, integration_id=iid, params=params, label=label, detail=detail, danger=danger, undo=_undo_options(kind),
                blocked=blocked, key=f"{kind}:{iid}:{json.dumps(params, sort_keys=True)}")


def _blocked_internet(c, pid, d, ip, own_ips):
    if ip in own_ips:
        return "Das ist der Rechner, auf dem díktyo läuft."
    return ""


def _uplink(c, did):
    """-> (Gerät darüber, Port-Nr. am Gerät darüber oder None)"""
    r = c.execute("""SELECT bi.device_id, bi.port_no, bi.role FROM links l JOIN interfaces ai ON ai.id=l.a_if JOIN interfaces bi ON bi.id=l.b_if
                     WHERE ai.device_id=? AND l.uplink=1 LIMIT 1""", (did,)).fetchone()
    return (r["device_id"], r["port_no"] if r["role"] == "port" else None) if r else (None, None)


def _path_targets(c, pid, sw_did):
    """Geräte, über die díktyo seine Verbindung hat: díktyo selbst, sein Gateway und ein Router mit Adressen in díktyos Netz
    und im Netz des Switches (NAT-Router dazwischen, z. B. ein ASUS hinter der FRITZ!Box)."""
    from .scan import netinfo
    local = []
    for i in netinfo.interfaces():
        try:
            local.append(ipaddress.ip_network(i["cidr"]))
        except ValueError:
            pass
    own_ips = {i["ip"] for i in netinfo.interfaces()}
    gw = netinfo.default_gateway()
    host = c.execute("SELECT host FROM integrations WHERE device_id=? AND driver IN ('snmp','mikrotik') LIMIT 1", (sw_did,)).fetchone()
    try:
        sw_net = ipaddress.ip_network(f"{host['host']}/24", strict=False) if host else None
    except ValueError:
        sw_net = None
    by_dev = {}
    for r in c.execute("SELECT device_id, address FROM ip_addresses WHERE profile_id=? AND device_id IS NOT NULL", (pid,)):
        by_dev.setdefault(r["device_id"], []).append(r["address"])
    out = set()
    for did, addrs in by_dev.items():
        ips = []
        for a in addrs:
            try:
                ips.append(ipaddress.ip_address(a))
            except ValueError:
                pass
        if set(addrs) & own_ips or (gw and gw in addrs):
            out.add(did)
        elif sw_net and any(ip in sw_net for ip in ips) and any(ip in n for ip in ips for n in local):
            out.add(did)
    return out


def _protected_ports(c, pid, sw_did, st):
    """Ports des Switches, über die díktyo oder ein Router erreichbar ist (abschalten würde die Verwaltung aussperren)."""
    keep = set()
    for t in _path_targets(c, pid, sw_did):  # Weg von díktyo/Gateway/NAT-Router nach oben bis zu diesem Switch
        x, seen = t, set()
        while x and x not in seen:
            seen.add(x)
            parent, port = _uplink(c, x)
            if parent == sw_did:
                if port:
                    keep.add(port)
                break
            x = parent
    own_ips, own_macs = _own_addresses()
    routers = {r["mac"] for r in c.execute("""SELECT i.mac FROM interfaces i JOIN devices d ON d.id=i.device_id
                                              WHERE d.profile_id=? AND d.type IN ('router','firewall','modem') AND i.mac<>''""", (pid,))}
    # (Wege oben bereits eingetragen)
    for p in (st.get("result") or {}).get("ports") or []:
        macs = {m.upper() for m in p.get("macs") or []}
        if macs & (routers | own_macs):
            keep.add(p["port_no"])
    up = c.execute("""SELECT ai.port_no FROM links l JOIN interfaces ai ON ai.id=l.a_if WHERE ai.device_id=? AND l.uplink=1 AND ai.role='port'""",
                   (sw_did,)).fetchone()
    if up and up["port_no"]:
        keep.add(up["port_no"])
    return keep


def _port_actions(c, pid, row, port_no):
    st = _state(row)
    port = next((p for p in (st.get("result") or {}).get("ports") or [] if p["port_no"] == port_no), None)
    if not port:
        return []
    protected = port_no in _protected_ports(c, pid, row["device_id"], st)
    reason = "Über diesen Port erreicht díktyo bzw. der Router den Switch – abschalten würde die Verwaltung aussperren." if protected else ""
    name = port.get("name") or f"Port {port_no}"
    ref = dict(iface=port["iface"], id=port["id"]) if row["driver"] == "mikrotik" else dict(ifindex=port["ifindex"])
    what = "Port" if row["driver"] == "mikrotik" else "Switch-Port"
    out = []
    if port.get("admin") == "down":
        out.append(_act("port", row["id"], dict(port_no=port_no, up=True, **ref), f"{what} {port_no} einschalten", name))
    else:
        out.append(_act("port", row["id"], dict(port_no=port_no, up=False, **ref), f"{what} {port_no} abschalten",
                        f"{name} – das angeschlossene Gerät verliert die Verbindung.", danger=True, blocked=reason))
    if port.get("poe"):
        poe_ref = dict(iface=port["iface"]) if row["driver"] == "mikrotik" else {}
        out.append(_act("poe_cycle", row["id"], dict(port_no=port_no, **poe_ref), f"PoE an Port {port_no} neu starten",
                        "Strom am Port 5 Sekunden aus und wieder an (startet z. B. Access Point oder Kamera neu).", danger=True, blocked=reason))
    return out


def available(c, pid, did, port_no=None):
    d = c.execute("SELECT * FROM devices WHERE id=? AND profile_id=?", (did, pid)).fetchone()
    if not d:
        return []
    data = json.loads(d["data"] or "{}")
    ips = _ipv4([r["address"] for r in c.execute("SELECT address FROM ip_addresses WHERE device_id=?", (did,))])
    mac = next((r["mac"] for r in c.execute("SELECT mac FROM interfaces WHERE device_id=? AND mac<>'' AND role<>'port' ORDER BY id", (did,))), "")
    own_ips, _ = _own_addresses()
    out = []
    if port_no:  # Frontplatte bzw. Port-Auswahl: nur die Aktionen dieses Switch-Ports
        for row in _integrations(c, pid, "snmp") + _integrations(c, pid, "mikrotik"):
            if row["device_id"] == did:
                return _port_actions(c, pid, row, port_no)
        return []
    # FRITZ!Box
    for row in _integrations(c, pid, "fritzbox"):
        st = _state(row)
        if row["device_id"] == did:
            for w in (st.get("result") or {}).get("wlan") or []:
                if "index" not in w:
                    continue
                band = "2,4 GHz" if str(w.get("channel") or "").isdigit() and int(w["channel"]) <= 14 else "5 GHz"
                out.append(_act("wlan", row["id"], dict(index=w["index"], on=not w["enabled"], ssid=w["ssid"]),
                                f"WLAN „{w['ssid']}“ ({band}) {'einschalten' if not w['enabled'] else 'ausschalten'}",
                                "" if not w["enabled"] else "Geräte in diesem WLAN verlieren die Verbindung.", danger=w["enabled"]))
            out.append(_act("reboot", row["id"], {}, "FRITZ!Box neu starten",
                            "Internet, WLAN und Telefonie sind 2–3 Minuten weg.", danger=True))
        elif ips and d["type"] not in INFRA and _same_lan(ips[0], row["host"], c, pid):
            reason = _blocked_internet(c, pid, d, ips[0], own_ips)
            out.append(_act("internet", row["id"], dict(ip=ips[0], block=True), "Internetzugang sperren",
                            f"Die FRITZ!Box sperrt den Internetzugang für {ips[0]}; das Heimnetz bleibt erreichbar.", blocked=reason))
            out.append(_act("internet", row["id"], dict(ip=ips[0], block=False), "Internetzugang freigeben", f"für {ips[0]}"))
            if mac:
                out.append(_act("wol", row["id"], dict(mac=mac), "Aufwecken (Wake-on-LAN)", f"Weckruf an {mac} über die FRITZ!Box"))
    # MikroTik: WLAN, Neustart, Wake-on-LAN für direkt angeschlossene Geräte
    for row in _integrations(c, pid, "mikrotik"):
        st = (_state(row).get("result") or {})
        if row["device_id"] == did:
            for w in st.get("wifi") or []:
                if not w.get("id"):
                    continue
                label = f"WLAN „{w['ssid'] or w['iface']}“{' (' + w['band'] + ')' if w.get('band') else ''} {'ausschalten' if w['enabled'] else 'einschalten'}"
                out.append(_act("wlan", row["id"], dict(iface=w["iface"], id=w["id"], menu=st.get("wifi_menu") or "interface/wifi", on=not w["enabled"], ssid=w["ssid"]),
                                label, "Geräte in diesem WLAN verlieren die Verbindung." if w["enabled"] else "", danger=w["enabled"]))
            out.append(_act("reboot", row["id"], {}, "MikroTik neu starten", "Alle Verbindungen über dieses Gerät sind etwa eine Minute weg.", danger=True))
        elif mac and _uplink(c, did)[0] == row["device_id"]:
            out.append(_act("wol", row["id"], dict(mac=mac), "Aufwecken (Wake-on-LAN)", f"Weckruf an {mac} über den MikroTik"))
    # Switch-Ports (SNMP) und MikroTik-Ports
    for row in _integrations(c, pid, "snmp") + _integrations(c, pid, "mikrotik"):
        if row["device_id"] == did and port_no:
            out += _port_actions(c, pid, row, port_no)
        elif row["device_id"] and row["device_id"] != did:
            link = c.execute("""SELECT bi.port_no FROM links l JOIN interfaces ai ON ai.id=l.a_if JOIN interfaces bi ON bi.id=l.b_if
                                WHERE ai.device_id=? AND l.uplink=1 AND bi.device_id=? AND bi.role='port'""", (did, row["device_id"])).fetchone()
            if link and link["port_no"]:
                out += _port_actions(c, pid, row, link["port_no"])
    # Proxmox-Host: seine Gäste schalten
    px = data.get("proxmox") or {}
    if px.get("node") and not px.get("vmid"):
        rows = _integrations(c, pid, "proxmox")
        if rows:
            for g in c.execute("""SELECT d.id, d.name, d.online, d.data FROM devices d WHERE d.profile_id=? AND json_extract(d.data,'$.proxmox.node')=?
                                  AND json_extract(d.data,'$.proxmox.vmid') IS NOT NULL ORDER BY d.name COLLATE NOCASE""", (pid, px["node"])):
                gp = json.loads(g["data"])["proxmox"]
                if gp.get("kind") not in ("qemu", "lxc"):
                    continue
                gips = _ipv4([r["address"] for r in c.execute("SELECT address FROM ip_addresses WHERE device_id=?", (g["id"],))])
                base = dict(node=gp["node"], kind=gp["kind"], vmid=gp["vmid"])
                tag = f"{gp['kind'].upper()} {gp['vmid']}"
                if g["online"] != 1:
                    out.append(_act("vm", rows[0]["id"], dict(base, op="start"), f"„{g['name']}“ starten", tag))
                else:
                    out.append(_act("vm", rows[0]["id"], dict(base, op="shutdown"), f"„{g['name']}“ herunterfahren", tag, danger=True,
                                    blocked="díktyo läuft in dieser VM bzw. diesem Container." if set(gips) & own_ips else ""))
    # Proxmox-Gast
    if px.get("vmid") and px.get("kind") in ("qemu", "lxc"):
        for row in _integrations(c, pid, "proxmox"):
            base = dict(node=px["node"], kind=px["kind"], vmid=px["vmid"])
            mine = "díktyo läuft in dieser VM bzw. diesem Container." if set(ips) & own_ips else ""
            if d["online"] != 1:
                out.append(_act("vm", row["id"], dict(base, op="start"), "Starten", f"{px['kind'].upper()} {px['vmid']} auf {px['node']}"))
            else:
                out.append(_act("vm", row["id"], dict(base, op="shutdown"), "Herunterfahren", f"{px['kind'].upper()} {px['vmid']} sauber beenden",
                                danger=True, blocked=mine))
                out.append(_act("vm", row["id"], dict(base, op="reboot"), "Neu starten", f"{px['kind'].upper()} {px['vmid']}", danger=True, blocked=mine))
            break
    return out


def _undo_at(choice):
    if not choice:
        return None
    t = dt.datetime.now().astimezone()
    if choice == "morning":
        nxt = (t + dt.timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        return nxt.isoformat(timespec="seconds")
    minutes = int(choice)
    if not 1 <= minutes <= 7 * 24 * 60:
        raise ActionError("Ungültige Zeit für das Zurückschalten")
    return (t + dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")


def inverse(kind, params):
    if kind == "wlan":
        return dict(params, on=not params["on"])
    if kind == "internet":
        return dict(params, block=not params["block"])
    if kind == "port":
        return dict(params, up=not params["up"])
    return None


def _preflight_backup(iid):
    """Konfigurationssicherung vor der Änderung, wenn die letzte älter als eine Stunde ist. -> Hinweistext"""
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
    if not configbackup.can_backup(row):
        return ""
    from .integrations import conf_of
    conf = conf_of(row)
    if conf.get("cfg_schedule") == "no" or (row["driver"] == "snmp" and not conf.get("ssh_user")):
        return ""  # Sicherung für diese Integration nicht eingerichtet
    st = _state(row)
    if st.get("sf_token"):
        return ""  # zweiter Anlauf nach der Bestätigung: Token gehört der Aktion
    if st.get("cfg_ok") and time.time() - parse_ts(st["cfg_ok"]).timestamp() < BACKUP_MAX_AGE:
        return "Konfiguration wurde in der letzten Stunde gesichert."
    res = configbackup.run(iid)
    if res["status"] == "new":
        return "Konfiguration vorher gesichert."
    if res["status"] == "unchanged":
        return "Konfiguration vorher gesichert (unverändert)."
    return f"Keine Sicherung vorher möglich: {res.get('message', '')}"


def execute(c_unused, pid, user_id, kind, iid, params, interactive=True, undo=None, device_id=None, label=""):
    """Aktion ausführen (ohne Prüfung gegen available – das macht run). -> dict(status=done|second_factor|error, …)"""
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=? AND profile_id=?", (iid, pid)).fetchone()
    if not row:
        raise ActionError("Integration nicht gefunden")
    drv = DRIVERS[row["driver"]]
    from .integrations import conf_of
    note = _preflight_backup(iid) if kind in CONFIG_CHANGING and interactive else ""
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
    state = _state(row)
    try:
        msg = drv.action(conf_of(row), state, kind, params)
        res = dict(status="done", message=msg, backup=note)
    except ERRORS as ex:
        if type(ex).__name__ == "SecondFactorRequired" and interactive and hasattr(drv, "second_factor_start"):
            sf = drv.second_factor_start(conf_of(row), state)
            res = dict(status="second_factor", backup=note, **sf)
        else:
            res = dict(status="error", message=str(ex), backup=note, second_factor=type(ex).__name__ == "SecondFactorRequired")
    with db() as c:
        st = _state(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone())
        if state.get("sf_token"):
            st["sf_token"] = state["sf_token"]
        else:
            st.pop("sf_token", None)
        c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st, ensure_ascii=False), iid))
        if res["status"] != "second_factor":
            undo_at = _undo_at(undo) if res["status"] == "done" and inverse(kind, params) else None
            aid = c.execute("""INSERT INTO actions(profile_id, device_id, integration_id, user_id, kind, params, label, status, message, created, undo_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (pid, device_id, iid, user_id, kind, json.dumps(params, ensure_ascii=False), label, res["status"], res.get("message", ""),
                             now(), undo_at)).lastrowid
            audit(c, f"action.{kind}", user_id, pid, dict(id=aid, params=params, status=res["status"]))
            res.update(id=aid, undo_at=undo_at)
    return res


def run(pid, user_id, did, key, undo=None, port_no=None):
    """Angebotene Aktion (über ihren Schlüssel) ausführen."""
    with db() as c:
        acts = {a["key"]: a for a in available(c, pid, did, port_no)}
    a = acts.get(key)
    if not a:
        raise ActionError("Diese Aktion ist für das Gerät nicht (mehr) verfügbar – Ansicht neu laden")
    if a["blocked"]:
        raise ActionError(a["blocked"])
    if undo and not a["undo"]:
        undo = None
    return execute(None, pid, user_id, a["kind"], a["integration_id"], a["params"], undo=undo, device_id=did, label=a["label"])


def run_due_undos(log=print):
    """Vom Hintergrunddienst: fällige automatische Rückschaltungen ausführen."""
    with db() as c:
        due = [r for r in c.execute("SELECT * FROM actions WHERE status='done' AND undo_at IS NOT NULL AND undone IS NULL").fetchall()
               if parse_ts(r["undo_at"]).timestamp() <= time.time()]
    for r in due:
        params = inverse(r["kind"], json.loads(r["params"]))
        res = execute(None, r["profile_id"], None, r["kind"], r["integration_id"], params, interactive=False, device_id=r["device_id"],
                      label=f"Automatisch zurück: {r['label']}")
        with db() as c:
            c.execute("UPDATE actions SET undone=?, undo_result=? WHERE id=?", (now(), res["status"] + (": " + res.get("message", "") if res.get("message") else ""), r["id"]))
            if res["status"] != "done":
                from .scan import runner
                runner.event(c, r["profile_id"], "action_undo_failed", r["device_id"], label=r["label"], message=res.get("message", ""))
        log(f"Aktion {r['id']} zurückgeschaltet: {res['status']} {res.get('message', '')}")


def recent(c, pid, limit=20):
    rows = c.execute("""SELECT a.*, d.name AS device, u.email AS user FROM actions a LEFT JOIN devices d ON d.id=a.device_id
                        LEFT JOIN users u ON u.id=a.user_id WHERE a.profile_id=? ORDER BY a.id DESC LIMIT ?""", (pid, limit)).fetchall()
    return [dict(id=r["id"], created=r["created"], kind=r["kind"], label=r["label"], device=r["device"], device_id=r["device_id"],
                 user=r["user"] or "díktyo", status=r["status"], message=r["message"], undo_at=r["undo_at"], undone=r["undone"],
                 undo_result=r["undo_result"]) for r in rows]


def cancel_undo(c, pid, aid):
    return c.execute("UPDATE actions SET undo_at=NULL WHERE id=? AND profile_id=? AND undone IS NULL", (aid, pid)).rowcount


def switch_ports(c, pid, did):
    """Ports eines per SNMP angebundenen Switches für die Port-Auswahl im Gerätedialog (sonst None)."""
    for row in _integrations(c, pid, "snmp") + _integrations(c, pid, "mikrotik"):
        if row["device_id"] == did:
            ports = (_state(row).get("result") or {}).get("ports") or []
            return [dict(port_no=p["port_no"], name=p.get("name") or "", oper=p.get("oper"), admin=p.get("admin", "up"), poe=p.get("poe")) for p in ports]
    return None
