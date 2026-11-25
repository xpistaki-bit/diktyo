"""Integrationen abfragen und die Ergebnisse auf den Bestand übertragen (FRITZ!Box, SNMP, ASUS, Proxmox, HA, Omada, UniFi)."""
import json
import time

from . import catalog, inventory, metrics, security
from .db import db, now
from .drivers import controller as ctl
from .drivers import DRIVERS, ERRORS
from .scan import ident, oui, runner

INFRA = ("switch", "ap", "mesh", "router", "repeater", "powerline", "firewall")
# Hängen mehrere Geräte hinter einem Port, ist das ranghöchste Infrastruktur-Gerät der direkte Nachbar
INFRA_RANK = (("switch",), ("ap", "mesh", "repeater", "powerline"), ("router", "firewall"))


def pick_neighbour(macs, by_mac):
    for group in INFRA_RANK:
        hit = [m for m in macs if by_mac[m]["type"] in group]
        if len(hit) == 1:
            return hit[0]
        if len(hit) > 1:
            return None
    return None


def secrets_of(row):
    """Gespeicherte Geheimnisse -> dict. Ältere Einträge enthalten nur ein Passwort als Text."""
    if not row["secret"]:
        return {}
    raw = security.decrypt(row["secret"])
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return d
    except ValueError:
        pass
    return {"password": raw}


def conf_of(row):
    opts = json.loads(row["options"] or "{}")
    return {**opts, **secrets_of(row), "host": row["host"], "port": row["port"], "username": row["username"]}


def poll(iid, log=print):
    """Fragt eine Integration ab. Fehler werden an der Integration vermerkt, nicht geworfen."""
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
        if not row:
            return None
        c.execute("UPDATE integrations SET last_poll=? WHERE id=?", (now(), iid))
    drv = DRIVERS.get(row["driver"])
    state = json.loads(row["state"] or "{}")
    before = json.loads(row["state"] or "{}")
    conf = conf_of(row)
    if row["driver"] == "shelly":
        with db() as c:
            conf["targets"] = smart_targets(c, row["profile_id"], conf)
    if row["driver"] == "snmp" and row["device_id"]:
        with db() as c:  # Portzahl des Katalogmodells: begrenzt die Frontports (Switches melden oft zusätzliche logische Schnittstellen)
            n = c.execute("SELECT COUNT(*) FROM interfaces WHERE device_id=? AND port_no IS NOT NULL", (row["device_id"],)).fetchone()[0]
        if n:
            conf["expected_ports"] = n
    try:
        res, values, new_state = drv.poll(conf, state)
    except ERRORS as ex:
        return _fail(iid, str(ex))
    except Exception as ex:  # unerwartete Antworten des Geräts
        log(f"Integration {iid}: {type(ex).__name__}: {ex}")
        return _fail(iid, f"{type(ex).__name__}: {ex}")
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
        if not row:
            return None
        summary = APPLY[row["driver"]](c, row, res)
        from . import changes, health
        health.apply_result(c, row, res, summary)
        changes.sync(c, row["profile_id"], row["driver"])
        if summary.get("device_id"):
            runner._set_online(c, summary["device_id"], 1, now(), row["driver"])
        metrics.put(c, row["profile_id"], {f"i{iid}:{k}": v for k, v in values.items()})
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()  # apply_ha schreibt eigenen Zustand
        changed = {k: v for k, v in new_state.items() if before.get(k, object()) != v}  # nur Änderungen des Treibers
        new_state = {**json.loads(row["state"] or "{}"), **changed}
        new_state.update(summary=summary, result=_slim(row["driver"], res), ts=time.time())
        new_state.pop("fail_since", None)
        new_state.pop("fail_notified", None)
        c.execute("UPDATE integrations SET state=?, last_ok=?, last_error=? WHERE id=?",
                  (json.dumps(new_state, ensure_ascii=False), now(), res.get("warning", ""), iid))
    return summary


FAIL_NOTIFY_S = 900  # so lange muss eine Integration gestört sein, bevor eine Meldung rausgeht


def _fail(iid, msg):
    with db() as c:
        c.execute("UPDATE integrations SET last_error=? WHERE id=?", (msg[:500], iid))
        r = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
        st = json.loads(r["state"] or "{}")
        since = st.get("fail_since") or time.time()
        if not st.get("fail_since"):
            st["fail_since"] = since
        if not st.get("fail_notified") and time.time() - since >= FAIL_NOTIFY_S:
            runner.event(c, r["profile_id"], "integration_failed", r["device_id"], name=r["name"], message=msg[:160])
            st["fail_notified"] = True
        c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st, ensure_ascii=False), iid))
    return None


def client_rates(res):
    """Live-Raten je MAC aus clients/guests: {MAC: [down_bps, up_bps]} (Sicht des Clients)."""
    out = {}
    for x in res.get("clients") or []:
        if isinstance(x, dict) and x.get("down_bps") is not None and x.get("mac"):
            out[x["mac"].upper()] = [x["down_bps"], x.get("up_bps") or 0]
    for g in res.get("guests") or []:
        if isinstance(g, dict) and g.get("down_bps") is not None:
            for n in g.get("nets") or []:
                if n.get("mac"):
                    out[n["mac"].upper()] = [g["down_bps"], g.get("up_bps") or 0]
                    break  # eine Netzwerkkarte reicht – die Zähler gelten für den ganzen Gast
    return out


def smart_targets(c, pid, conf):
    """Shelly/Tasmota: bei „auto“ die IPv4-Adressen aller Geräte, die nach Shelly oder Tasmota aussehen (Name, Hersteller,
    Modell, Erkennung) oder ein ESP-Modul von Espressif sind (tragen oft Tasmota)."""
    import ipaddress
    if "auto" not in str(conf.get("host") or "").lower():
        return []
    out = []
    for r in c.execute("""SELECT d.id, d.name, d.manufacturer, d.model, d.hostname, d.data, a.address FROM devices d
                          JOIN ip_addresses a ON a.device_id=d.id WHERE d.profile_id=? AND d.status<>'ignored'""", (pid,)):
        data = json.loads(r["data"] or "{}")
        seen = data.get("seen") or {}
        text = " ".join(str(x or "") for x in (r["name"], r["manufacturer"], r["model"], r["hostname"], (data.get("ident") or {}).get("label"),
                                                seen.get("vendor"), seen.get("hostname"), seen.get("http_title"))).lower()
        if any(k in text for k in ("shelly", "tasmota", "espressif")) or data.get("smart"):
            try:
                if ipaddress.ip_address(r["address"]).version == 4 and r["address"] not in out:
                    out.append(r["address"])
            except ValueError:
                pass
    return out[:200]


def _slim(driver, res):
    """Was die Oberfläche anzeigen soll (ohne die vollständige Hostliste), plus Live-Raten je Client."""
    out = _slim_view(driver, res)
    rates = client_rates(res)
    if rates:
        out["rates"] = rates
    return out


def _slim_view(driver, res):
    if driver == "asuswrt":
        return dict(info=res.get("info"), traffic=res.get("traffic"), wan=res.get("wan"), analyzer=res.get("analyzer"),
                    nodes=[{k: n[k] for k in ("name", "model", "ip", "online", "wired_backhaul")} for n in res.get("nodes", [])],
                    clients=len(res.get("clients", [])), online=sum(1 for x in res.get("clients", []) if x["online"]),
                    wlan=sum(1 for x in res.get("clients", []) if x["online"] and x["medium"] == "wlan"))
    if driver == "proxmox":
        return dict(info=res.get("info"), nodes=res.get("nodes"), guests=len(res.get("guests", [])),
                    running=sum(1 for g in res.get("guests", []) if g["running"]))
    if driver == "homeassistant":
        return dict(info=res.get("info"))
    if driver == "dnsfilter":
        return dict(info=res.get("info"), summary=res.get("summary"), top_domains=res.get("top_domains"),
                    clients=[c for c in res.get("clients", []) if c["queries"]][:30])
    if driver == "shelly":
        return dict(info=res.get("info"), devices=[{k: d.get(k) for k in ("ip", "mac", "kind", "gen", "model", "name", "channels", "power_w", "energy_kwh",
                                                                          "rssi", "voltage", "firmware")} for d in res.get("devices", [])])
    if driver == "docker":
        return dict(info=res.get("info"), containers=[{k: x[k] for k in ("name", "image", "state", "status", "ports", "ips")} for x in res.get("containers", [])])
    if driver in ("mikrotik", "opnsense"):
        return dict(info=res.get("info"), wan=res.get("wan"), ports=res.get("ports"), wifi=res.get("wifi"), wifi_menu=res.get("wifi_menu"),
                    clients=len(res.get("clients", [])), online=sum(1 for x in res.get("clients", []) if x["online"]),
                    wlan=sum(1 for x in res.get("clients", []) if x["medium"] == "wlan"), fdb_size=res.get("fdb_size"))
    if driver in CONTROLLERS:
        return dict(info=res.get("info"), wan=res.get("wan"),
                    devices=[dict({k: d[k] for k in ("name", "model", "type", "ip", "online", "clients")}, mac=d.get("mac", ""), ref=d.get("ref") or {})
                             for d in res.get("devices", [])],
                    clients=len(res.get("clients", [])), wlan=sum(1 for x in res.get("clients", []) if x["medium"] == "wlan"),
                    port_status={d["mac"]: d["ports"] for d in res.get("devices", []) if d.get("ports")})
    if driver == "devolo":
        return dict(info=res.get("info"), rates=res.get("rates"),
                    adapters=[{k: a.get(k) for k in ("mac", "ip", "name", "product", "firmware", "technology", "router", "local", "serial")}
                              | dict(clients=len(a.get("clients", [])), bridged=len(set(a.get("bridged", [])) - {x["mac"] for x in a.get("clients", [])}),
                                     update=(a.get("firmware_info") or {}).get("update"), latest=(a.get("firmware_info") or {}).get("latest", ""))
                              for a in res.get("adapters", [])])
    if driver == "fritzbox":
        return dict(info=res.get("info"), wan=res.get("wan"), auth=res.get("auth"), wlan=res.get("wlan"),
                    hosts=len(res.get("hosts", [])), active=sum(1 for h in res.get("hosts", []) if h["active"]))
    return dict(info=res.get("info"), ports=res.get("ports"), fdb_size=res.get("fdb_size"))


# ------------------------------------------------------------ Gerät der Integration
ENTERPRISE = {"890": "Zyxel", "11863": "TP-Link", "4526": "Netgear", "41112": "Ubiquiti", "9": "Cisco", "14988": "MikroTik",
              "6574": "Synology", "24681": "QNAP", "2011": "Huawei", "25506": "H3C", "171": "D-Link", "2636": "Juniper", "11": "HP"}


def _own_device(c, row, name, model_text="", mac="", typ="other", vendor=""):
    """Das Gerät, das die Integration darstellt (FRITZ!Box, Switch). Wird bei Bedarf angelegt und verknüpft."""
    pid = row["profile_id"]
    if row["device_id"] and c.execute("SELECT 1 FROM devices WHERE id=?", (row["device_id"],)).fetchone():
        return row["device_id"]
    r = c.execute("SELECT device_id FROM ip_addresses WHERE profile_id=? AND address=? AND device_id IS NOT NULL", (pid, row["host"])).fetchone()
    did = r["device_id"] if r else None
    if not did and mac:
        r = c.execute("SELECT i.device_id FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND i.mac=?", (pid, mac)).fetchone()
        did = r["device_id"] if r else None
    if not did:
        m = None
        if model_text:
            idx = ident.catalog_index(c)
            m = ident.match_catalog(idx, {}, dict(ssdp=model_text, http="", mdns="", hostname=name, vendor=vendor or model_text))
        ports = []
        if m:
            ports = json.loads(c.execute("SELECT data FROM device_models WHERE id=?", (m["id"],)).fetchone()["data"]).get("ports", [])
        did = inventory.save_device(c, pid, dict(
            name=name, type=m["type"] if m else typ, model_id=m["id"] if m else None, manufacturer=m["manufacturer"] if m else "",
            model=m["model"] if m else model_text, mac=mac, status="discovered", ports=ports,
            ips=[dict(address=row["host"], kind="static", source=row["driver"])]))
    c.execute("UPDATE integrations SET device_id=? WHERE id=?", (did, row["id"]))
    return did


STALE_LINK = 1800  # so lange (s) hat eine genauere Verbindung Vorrang, nachdem ihre Quelle sie zuletzt bestätigt hat


def _link_rank(medium, has_port):
    """Wie genau eine Verbindung ist: läuft auf Host / bestimmter Port (3) > WLAN/Mesh am Access Point (2) > irgendwo im LAN (1)."""
    return 3 if medium == "virtual" or has_port else 2 if medium in ("wlan", "mesh", "powerline") else 1


def set_auto_uplink(c, pid, did, target, medium="lan", port_name=None, port_id=None, local_port_id=None, source="auto"):
    """Verbindung aus einer Integration setzen. Von Hand gesetzte Verbindungen haben immer Vorrang; eine ungenauere Quelle
    (z. B. Router: „VM hängt im LAN“) überschreibt keine genauere (Proxmox: „VM läuft auf Host“), solange diese sie bestätigt."""
    import time as _t
    cur = c.execute("""SELECT l.*, bi.device_id AS target, ai.role AS a_role, bi.role AS b_role FROM links l
                       JOIN interfaces ai ON ai.id=l.a_if JOIN interfaces bi ON bi.id=l.b_if
                       WHERE ai.device_id=? AND l.uplink=1""", (did,)).fetchone()
    if cur and cur["source"] == "manual":
        return False
    if port_name and not port_id:
        r = c.execute("SELECT id FROM interfaces WHERE device_id=? AND role='port' AND lower(name)=lower(?)", (target, port_name)).fetchone()
        port_id = r["id"] if r else None
    if medium == "lan" and not port_id and not local_port_id and inventory.wireless_only(c, did):
        medium = "wlan"  # Router meldet „kabelgebunden“, das Gerät hat aber keine Buchse (z. B. Client hinter einem Mesh-Knoten)
    b_if = port_id or inventory.nic_of(c, target)["id"]
    a_if = local_port_id or inventory.nic_of(c, did)["id"]
    ts = _t.time()
    if cur and cur["b_if"] == b_if and cur["a_if"] == a_if and cur["medium"] == medium:
        if cur["source"] == source or _link_rank(medium, bool(port_id or local_port_id)) >= _link_rank(cur["medium"], "port" in (cur["a_role"], cur["b_role"])):
            c.execute("UPDATE links SET confirmed=? WHERE id=?", (ts, cur["id"]))  # bestätigt
        return False
    if cur and cur["source"] != source and ts - (cur["confirmed"] or 0) < STALE_LINK \
            and _link_rank(cur["medium"], "port" in (cur["a_role"], cur["b_role"])) > _link_rank(medium, bool(port_id or local_port_id)):
        return False  # genauere Angabe einer anderen Quelle ist noch aktuell
    for iface in {x for x in (port_id, local_port_id) if x}:
        used = c.execute("SELECT 1 FROM links WHERE (a_if=? OR b_if=?) AND NOT (a_if IN (SELECT id FROM interfaces WHERE device_id=?))",
                         (iface, iface, did)).fetchone()
        if used:
            return False
    # keine Ringe
    seen, x = set(), target
    while x and x not in seen:
        if x == did:
            return False
        seen.add(x)
        x = inventory._uplink_parent(c, x)
    c.execute("DELETE FROM links WHERE uplink=1 AND a_if IN (SELECT id FROM interfaces WHERE device_id=?)", (did,))
    c.execute("INSERT INTO links(profile_id, a_if, b_if, medium, uplink, source, confirmed) VALUES(?,?,?,?,1,?,?)", (pid, a_if, b_if, medium, source, ts))
    return True


def _device_by_mac(c, pid):
    return {r["mac"]: dict(id=r["device_id"], type=r["type"], status=r["status"]) for r in c.execute(
        "SELECT i.mac, i.device_id, d.type, d.status FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND i.mac<>''", (pid,))}


# ------------------------------------------------------------ FRITZ!Box
def apply_fritz(c, row, res):
    pid = row["profile_id"]
    oui.ensure(lambda *a: None)
    master_mac = next((m["node"] for m in res.get("mesh", {}).values() if m.get("master")), "")
    fritz = _own_device(c, row, res["info"].get("model") or "FRITZ!Box", res["info"].get("model", ""), master_mac, "router", "AVM")
    if master_mac:
        nic = inventory.nic_of(c, fritz)
        if not nic["mac"]:
            c.execute("UPDATE interfaces SET mac=? WHERE id=?", (master_mac, nic["id"]))
    rules, index = ident.load_rules(c), ident.catalog_index(c)
    hosts, inactive = [], set()
    for h in res.get("hosts", []):
        if not h["ip"] or h["ip"] == row["host"]:
            continue
        if not h["active"]:
            inactive.add(h["ip"])
            continue
        mac = h["mac"]
        x = dict(ip=h["ip"], mac=mac, vendor=oui.vendor(mac) if mac else "", random=oui.is_random(mac) if mac else False, hostname=h["name"],
                 netbios="", mdns=None, ssdp=None, http=None, ports=[], services={}, os="")
        x["ident"] = ident.identify(rules, index, x)
        hosts.append(x)
    stats = runner.merge(c, pid, None, hosts, probed=inactive, source="fritzbox", record=False)
    # Verbindungen aus der Mesh-Topologie
    links = 0
    by_mac = _device_by_mac(c, pid)
    groups = {}
    for cmac, m in res.get("mesh", {}).items():
        if cmac in by_mac:
            groups.setdefault((m["node"], m["iface"], m["medium"]), []).append(cmac)
    for (node, iface, medium), macs in groups.items():
        target = fritz if node == master_mac or not node else (by_mac.get(node) or {}).get("id")
        if not target:
            continue
        if medium == "lan" and len(macs) > 1:
            # mehrere Geräte am selben LAN-Port: direkt angeschlossen ist der Switch (bzw. Access Point) davor
            n = pick_neighbour(macs, by_mac)
            macs = [n] if n else []
        for cmac in macs:
            d = by_mac[cmac]
            if d["id"] != target and set_auto_uplink(c, pid, d["id"], target, medium, port_name=iface if medium == "lan" else None, source="fritzbox"):
                links += 1
    return dict(device_id=fritz, hosts=stats["hosts"], new=stats["new"], known=stats["known"], offline=stats["offline"], links=links,
                mesh=bool(res.get("mesh")))


# ------------------------------------------------------------ SNMP-Switch
def apply_snmp(c, row, res):
    pid = row["profile_id"]
    info = res.get("info") or {}
    oid = info.get("object_id", "")
    ent = oid.split(".")[6] if oid.startswith("1.3.6.1.4.1.") and len(oid.split(".")) > 6 else ""
    vendor = info.get("vendor") or ENTERPRISE.get(ent, "")
    sw = _own_device(c, row, info.get("name") or f"Switch {row['host']}", info.get("model") or info.get("descr", "")[:80], "", "switch", vendor)
    _auto_set(c, sw, manufacturer=vendor, model=info.get("model", ""))
    # Ports anlegen, wenn das Gerät noch keine hat
    have = c.execute("SELECT COUNT(*) FROM interfaces WHERE device_id=? AND role='port'", (sw,)).fetchone()[0]
    if not have and res.get("ports"):
        d = c.execute("SELECT data FROM devices WHERE id=?", (sw,)).fetchone()
        data = json.loads(d["data"] or "{}")
        data["ports"] = [dict(count=len(res["ports"]), kind="rj45", speed="")]
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), sw))
        inventory.sync_ports(c, sw, data["ports"])
    ports = {r["port_no"]: r["id"] for r in c.execute("SELECT id, port_no FROM interfaces WHERE device_id=? AND role='port'", (sw,))}
    by_mac = _device_by_mac(c, pid)
    own_macs = {m for m, d in by_mac.items() if d["id"] == sw}
    routers = {m for m, d in by_mac.items() if d["type"] in ("router", "firewall")}
    links = 0
    for p in res.get("ports", []):
        pid_port = ports.get(p["port_no"])
        if not pid_port:
            continue
        macs = [m for m in p["macs"] if m not in own_macs]
        known = [m for m in macs if m in by_mac]
        target = None
        if p.get("lldp") and p["lldp"].get("chassis") in by_mac:
            target = p["lldp"]["chassis"]
        elif len(macs) == 1 and known:
            target = known[0]
        elif known:
            target = pick_neighbour(known, by_mac)
        if target and target in routers and len(macs) > 2:
            # Port, an dem der Router mit vielen weiteren Adressen gelernt wird: Uplink des Switches
            if set_auto_uplink(c, pid, sw, by_mac[target]["id"], "lan", local_port_id=pid_port, source="snmp"):
                links += 1
        elif target and by_mac[target]["id"] != sw:
            if set_auto_uplink(c, pid, by_mac[target]["id"], sw, "lan", port_id=pid_port, source="snmp"):
                links += 1
    up = sum(1 for p in res.get("ports", []) if p["oper"] == "up")
    vlans = 0
    if res.get("vlans"):
        from . import vlanplan
        vlans = vlanplan.apply_switch(c, pid, sw, res["vlans"])
    return dict(device_id=sw, ports=len(res.get("ports", [])), up=up, links=links, macs=res.get("fdb_size", 0), vlan_ports=vlans)


def live_ports(c, did):
    """Port-Status aus der letzten SNMP-Abfrage eines Geräts bzw. vom Controller (UniFi) -> {port_no: {...}}"""
    r = c.execute("SELECT state FROM integrations WHERE device_id=? AND driver IN ('snmp','mikrotik','opnsense') ORDER BY id LIMIT 1", (did,)).fetchone()
    if r:
        st = json.loads(r["state"] or "{}")
        return {p["port_no"]: p for p in (st.get("result") or {}).get("ports") or []}
    macs = {x["mac"] for x in c.execute("SELECT mac FROM interfaces WHERE device_id=? AND mac<>''", (did,))}
    pid = c.execute("SELECT profile_id FROM devices WHERE id=?", (did,)).fetchone()
    if not macs or not pid:
        return {}
    for r in c.execute(f"SELECT state FROM integrations WHERE profile_id=? AND driver IN ({','.join('?' * len(CONTROLLERS))})", (pid[0], *CONTROLLERS)):
        ps = (json.loads(r["state"] or "{}").get("result") or {}).get("port_status") or {}
        for m in macs:
            if m in ps:
                return {p["port_no"]: p for p in ps[m]}
    return {}


def type_name(t, lang="de"):
    return catalog.type_name(t, lang)


# ------------------------------------------------------------ ASUS AiMesh
def _find_device(c, pid, mac="", ip="", name=""):
    if mac:
        r = c.execute("SELECT i.device_id FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND i.mac=?", (pid, mac)).fetchone()
        if r:
            return r["device_id"]
    if ip:
        r = c.execute("SELECT device_id FROM ip_addresses WHERE profile_id=? AND address=? AND device_id IS NOT NULL", (pid, ip)).fetchone()
        if r:
            return r["device_id"]
    if name:
        r = c.execute("SELECT id FROM devices WHERE profile_id=? AND lower(name)=lower(?)", (pid, name)).fetchone()
        if r:
            return r["id"]
    return None


def _catalog_ports(c, model_text, vendor):
    m = ident.match_catalog(ident.catalog_index(c), {}, dict(ssdp=model_text, http="", mdns="", hostname="", vendor=vendor)) if model_text else None
    if not m:
        return None, []
    return m, json.loads(c.execute("SELECT data FROM device_models WHERE id=?", (m["id"],)).fetchone()["data"]).get("ports", [])


def _new_device(c, pid, name, typ, mac="", ips=(), source="auto", model_text="", vendor="", data=None):
    m, ports = _catalog_ports(c, model_text, vendor)
    did = inventory.save_device(c, pid, dict(
        name=name, type=m["type"] if m and typ == "other" else typ, model_id=m["id"] if m else None,
        manufacturer=m["manufacturer"] if m else vendor, model=m["model"] if m else model_text, mac=mac, status="discovered", ports=ports,
        ips=[dict(address=ip, kind=runner._ip_kind(c, pid, ip), source=source) for ip in ips if ip]))
    if data:
        d = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()["data"] or "{}")
        d.update(data)
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(d, ensure_ascii=False), did))
    runner.event(c, pid, "new_device", did, name=name, ip=(list(ips) or [""])[0], mac=mac, label=typ, source=source)
    return did


def apply_asus(c, row, res):
    pid, info = row["profile_id"], res.get("info") or {}
    oui.ensure(lambda *a: None)
    main = _own_device(c, row, info.get("model") or "ASUS-Router", info.get("model", ""), info.get("mac", ""), "mesh", "ASUS")
    ap_owner, links, new_nodes = {}, 0, 0
    for mac in [info.get("mac", "")]:
        if mac:
            ap_owner[mac] = main
    node_dev = []
    for n in res.get("nodes", []):
        if n["mac"] == info.get("mac") or n["level"] == 0 or n["ip"] == row["host"]:
            did = main
        else:
            did = _find_device(c, pid, n["mac"], n["ip"])
            if not did:
                did = _new_device(c, pid, n["name"] or n["model"] or "AiMesh-Knoten", "mesh", n["mac"], [n["ip"]], "asuswrt", n["model"], "ASUS")
                new_nodes += 1
            runner._set_online(c, did, 1 if n["online"] else 0, now(), "asuswrt")
            if n.get("firmware"):  # AiMesh aktualisiert Knoten gleichen Modells mit dem Hauptrouter
                from . import health
                from .drivers.asuswrt import fw_version
                mfw = res.get("firmware") or {}
                same = (n.get("model") or "").replace("ExpertWiFi ", "") == (info.get("model") or "").replace("ExpertWiFi ", "")
                health.apply_firmware(c, pid, did, dict(installed=fw_version(n["firmware"]), latest=mfw.get("latest", "") if same else "",
                                                        update=mfw.get("update") if same else None), "asuswrt")
        for m in n["aps"] + [n["mac"]]:
            ap_owner[m] = did
        node_dev.append((n, did))
    for n, did in node_dev:
        if did == main:
            continue
        parent = ap_owner.get(n["parent_ap"], main)
        if parent != did and set_auto_uplink(c, pid, did, parent, "lan" if n["wired_backhaul"] else "mesh", source="asuswrt"):
            links += 1
    rules, index = ident.load_rules(c), ident.catalog_index(c)
    hosts, offline = [], set()
    for cl in res.get("clients", []):
        if not cl["ip"]:
            continue
        if not cl["online"]:
            offline.add(cl["ip"])
            continue
        x = dict(ip=cl["ip"], mac=cl["mac"], vendor=oui.vendor(cl["mac"]) if cl["mac"] else "", random=oui.is_random(cl["mac"]) if cl["mac"] else False,
                 hostname=cl["name"], netbios="", mdns=None, ssdp=None, http=None, ports=[], services={}, os="")
        x["ident"] = ident.identify(rules, index, x)
        hosts.append(x)
    stats = runner.merge(c, pid, None, hosts, probed=offline, source="asuswrt", record=False)
    by_mac = _device_by_mac(c, pid)
    for cl in res.get("clients", []):
        d = by_mac.get(cl["mac"])
        if not d or not cl["online"]:
            continue
        parent = ap_owner.get(cl["parent_ap"], main)
        if d["id"] != parent and set_auto_uplink(c, pid, d["id"], parent, cl["medium"], source="asuswrt"):
            links += 1
    return dict(device_id=main, clients=len(res.get("clients", [])), new=stats["new"] + new_nodes, nodes=len(node_dev), links=links)


# ------------------------------------------------------------ Proxmox
def _auto_set(c, did, software="", manufacturer="", model="", inherit_from=None):
    """Angaben aus einer Integration setzen, ohne Eingaben von Hand zu überschreiben: Software nur, wenn sie leer ist oder
    selbst automatisch kam; Hersteller/Modell nur, wenn leer; Standort vom Host, wenn keiner gesetzt ist."""
    d = c.execute("SELECT manufacturer, model, location_id, data FROM devices WHERE id=?", (did,)).fetchone()
    if not d:
        return
    data = json.loads(d["data"] or "{}")
    sets = {}
    if software and (not data.get("software") or data.get("software_auto", False)) and data.get("software") != software:
        data["software"], data["software_auto"] = software, True
        sets["data"] = json.dumps(data, ensure_ascii=False)
    if manufacturer and not d["manufacturer"]:
        sets["manufacturer"] = manufacturer
    if model and not d["model"]:
        sets["model"] = model
    if inherit_from and not d["location_id"]:
        loc = c.execute("SELECT location_id FROM devices WHERE id=?", (inherit_from,)).fetchone()
        if loc and loc["location_id"]:
            sets["location_id"] = loc["location_id"]
    if sets:
        c.execute(f"UPDATE devices SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), did))


def apply_proxmox(c, row, res):
    pid, ts = row["profile_id"], now()
    node_dev, new, links, own = {}, 0, 0, None
    for n in res.get("nodes", []):
        did = _find_device(c, pid, ip=n["ip"], name=n["name"])
        if not did:
            did = _new_device(c, pid, n["name"], "hypervisor", "", [n["ip"]], "proxmox", data=dict(proxmox=dict(node=n["name"])))
            new += 1
        node_dev[n["name"]] = did
        runner._set_online(c, did, 1 if n["online"] else 0, ts, "proxmox")
        ver = (res.get("info") or {}).get("version")
        if ver:
            _auto_set(c, did, software=f"Proxmox VE {ver}")
        if n["ip"] == row["host"] or own is None:
            own = did if n["ip"] == row["host"] else own
    if own is None and node_dev:
        own = next(iter(node_dev.values()))
    if own:
        c.execute("UPDATE integrations SET device_id=? WHERE id=?", (own, row["id"]))
    for g in res.get("guests", []):
        net = (g["nets"] or [{}])[0]
        mac = net.get("mac", "")
        typ = "vm" if g["kind"] == "qemu" else "container"
        meta = dict(proxmox=dict(vmid=g["vmid"], node=g["node"], kind=g["kind"], bridge=net.get("bridge", ""), tag=net.get("tag", ""),
                                 running=g["running"]))
        did = _find_device(c, pid, mac, (g["ips"] or [""])[0])
        if not did:
            did = _new_device(c, pid, g["name"], typ, mac, g["ips"], "proxmox", data=meta)
            new += 1
        else:
            d = c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()
            data = json.loads(d["data"] or "{}")
            data.update(meta)
            c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), did))
            nic = inventory.nic_of(c, did)
            if mac and not nic["mac"]:
                c.execute("UPDATE interfaces SET mac=? WHERE id=?", (mac, nic["id"]))
            if g["ips"] and not c.execute("SELECT 1 FROM ip_addresses WHERE device_id=?", (did,)).fetchone():
                for ip in g["ips"]:
                    c.execute("INSERT INTO ip_addresses(profile_id, device_id, interface_id, address, kind, source) VALUES(?,?,?,?,?,?)",
                              (pid, did, nic["id"], ip, runner._ip_kind(c, pid, ip), "proxmox"))
        runner._set_online(c, did, 1 if g["running"] else 0, ts, "proxmox")
        host = node_dev.get(g["node"])
        # vom Hypervisor übernehmen: Software, „Hardware“ (virtuell), Standort – nur wo nichts von Hand eingetragen ist
        _auto_set(c, did, software=g.get("os") or "", manufacturer="Proxmox", model="QEMU-VM" if g["kind"] == "qemu" else "LXC-Container", inherit_from=host)
        if host and host != did and set_auto_uplink(c, pid, did, host, "virtual", source="proxmox"):
            links += 1
    return dict(device_id=own, nodes=len(node_dev), guests=len(res.get("guests", [])), running=sum(1 for g in res.get("guests", []) if g["running"]),
                new=new, links=links)


# ------------------------------------------------------------ Home Assistant
def _auto_name(d):
    """Name, den díktyo selbst vergeben hat (Hostname, Vermutung mit Adresse), darf durch den HA-Namen ersetzt werden."""
    import re
    name = d["name"]
    return (d["status"] == "discovered" or name == d["hostname"] or bool(re.search(r" \.\d{1,3}$", name))
            or bool(re.fullmatch(r"[0-9a-z]+[-_][0-9a-f]{6,}", name, re.I)))


def _location_id(c, pid, area):
    r = c.execute("SELECT id FROM locations WHERE profile_id=? AND lower(name)=lower(?)", (pid, area)).fetchone()
    if r:
        return r["id"]
    return c.execute("INSERT INTO locations(profile_id, name) VALUES(?,?)", (pid, area)).lastrowid


def apply_ha(c, row, res):
    from . import mqtt
    pid, conf = row["profile_id"], conf_of(row)
    out = dict(device_id=None, matched=0, renamed=0, located=0, published=0, events=0)
    devs = res.get("ha_devices")
    if devs:
        by_mac = _device_by_mac(c, pid)
        for hd in devs:
            hit = next((by_mac[m.upper()] for m in hd.get("macs", []) if m.upper() in by_mac), None)
            if not hit:
                continue
            out["matched"] += 1
            d = c.execute("SELECT * FROM devices WHERE id=?", (hit["id"],)).fetchone()
            data = json.loads(d["data"] or "{}")
            data["ha"] = {k: hd.get(k) for k in ("name", "area", "manufacturer", "model")}
            sets = dict(data=json.dumps(data, ensure_ascii=False))
            mode = conf.get("import_names") or "new"
            if hd.get("name") and hd["name"] != d["name"] and (mode == "all" or (mode == "new" and _auto_name(d))) \
                    and not inventory.name_locked(c, d["id"], data):  # selbst vergebene Namen bleiben
                sets["name"] = hd["name"][:120]
                out["renamed"] += 1
            if conf.get("import_areas", "yes") == "yes" and hd.get("area") and not d["location_id"]:
                sets["location_id"] = _location_id(c, pid, hd["area"][:80])
                out["located"] += 1
            c.execute(f"UPDATE devices SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), d["id"]))
    if conf.get("mqtt_host"):
        try:
            out.update(_publish_ha(c, row, conf))
        except mqtt.MQTTError as ex:
            out["warning"] = str(ex)
            res["warning"] = str(ex)
    return out


def _publish_ha(c, row, conf):
    from . import mqtt
    from .version import VERSION
    pid = row["profile_id"]
    p = c.execute("SELECT name FROM profiles WHERE id=?", (pid,)).fetchone()
    base, disc = f"{mqtt.TOPIC}/{pid}", "homeassistant"
    hub = dict(identifiers=[f"diktyo_profile_{pid}"], name=f"díktyo {p['name']}", manufacturer="díktyo", model="Netzwerk-Dokumentation", sw_version=VERSION)
    expire = max(180, row["interval_s"] * 3)
    msgs = []
    st = json.loads(row["state"] or "{}")
    scope = conf.get("publish") or "infra"
    rows = c.execute("""SELECT d.id, d.name, d.type, d.online, d.manufacturer, d.model, i.mac FROM devices d
                        LEFT JOIN interfaces i ON i.device_id=d.id AND i.role='nic' WHERE d.profile_id=? AND d.status='confirmed'""", (pid,)).fetchall()
    sel = [r for r in rows if scope == "all" or (scope == "infra" and r["type"] in INFRA + ("server", "hypervisor", "nas"))]
    published = set()
    for r in sel:
        uid = f"diktyo_{pid}_{r['id']}"
        dev = dict(identifiers=[f"diktyo_device_{r['id']}"], name=r["name"], manufacturer=r["manufacturer"] or None, model=r["model"] or None,
                   via_device=f"diktyo_profile_{pid}")
        if r["mac"]:
            dev["connections"] = [["mac", r["mac"].lower()]]
        msgs.append((f"{disc}/binary_sensor/{uid}/config", dict(
            name="Netzwerk", unique_id=uid, object_id=f"diktyo_{r['name']}", device_class="connectivity",
            state_topic=f"{base}/device/{r['id']}", payload_on="ON", payload_off="OFF", expire_after=expire, device=dev), True))
        if r["online"] is not None:
            msgs.append((f"{base}/device/{r['id']}", "ON" if r["online"] else "OFF", True))
        published.add(uid)
    for uid in set(st.get("published", [])) - published:  # nicht mehr gemeldete Geräte aus HA entfernen
        msgs.append((f"{disc}/binary_sensor/{uid}/config", "", True))
    # Zähler und WAN-Traffic des Profils
    inbox = c.execute("SELECT COUNT(*) FROM devices WHERE profile_id=? AND status='discovered'", (pid,)).fetchone()[0]
    online = sum(1 for r in rows if r["online"] == 1)
    sensors = [("inbox", "Neue Geräte im Posteingang", inbox, None, "mdi:inbox-arrow-down"), ("online", "Geräte online", online, None, "mdi:lan-connect")]
    for k, name, unit in (("rx", "WAN Download", "Mbit/s"), ("tx", "WAN Upload", "Mbit/s")):
        r = c.execute("""SELECT m.value FROM metrics m JOIN series s ON s.id=m.series_id WHERE s.profile_id=? AND s.key LIKE ?
                         ORDER BY m.ts DESC LIMIT 1""", (pid, f"%:wan:{k}")).fetchone()
        if r:
            sensors.append((f"wan_{k}", name, round(r["value"] / 1e6, 2), unit, "mdi:download" if k == "rx" else "mdi:upload"))
    for key, name, val, unit, icon in sensors:
        uid = f"diktyo_{pid}_{key}"
        cfg = dict(name=name, unique_id=uid, state_topic=f"{base}/{key}", icon=icon, device=hub, expire_after=expire)
        if unit:
            cfg.update(unit_of_measurement=unit, device_class="data_rate", state_class="measurement")
        else:
            cfg["state_class"] = "measurement"
        msgs.append((f"{disc}/sensor/{uid}/config", cfg, True))
        msgs.append((f"{base}/{key}", str(val), True))
    # Ereignisse
    msgs.append((f"{disc}/event/diktyo_{pid}_events/config", dict(
        name="Ereignis", unique_id=f"diktyo_{pid}_events", state_topic=f"{base}/event", device=hub, icon="mdi:bell-ring",
        event_types=["device_offline", "device_online", "new_device", "action_undo_failed", "quarantined", "schedule_failed",
                     "firmware_update", "speed_slow", "backup_failed", "integration_failed"]), True))
    evs = c.execute("SELECT * FROM events WHERE profile_id=? AND delivered='' ORDER BY id LIMIT 200", (pid,)).fetchall()
    for e in evs:
        d = json.loads(e["data"] or "{}")
        msgs.append((f"{base}/event", dict(event_type=e["kind"], device=d.get("name", ""), ip=d.get("ip", ""), mac=d.get("mac", ""),
                                           label=d.get("label", ""), device_id=e["device_id"], profile=p["name"], ts=e["ts"]), False))
    n = mqtt.publish(dict(conf, profile_id=pid), msgs)
    if evs:
        c.execute(f"UPDATE events SET delivered=? WHERE id IN ({','.join('?' * len(evs))})", (now(), *[e["id"] for e in evs]))
    st["published"] = sorted(published)
    c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st, ensure_ascii=False), row["id"]))
    return dict(published=len(published), events=len(evs), messages=n)


# ------------------------------------------------------------ Controller (Omada, UniFi)
CONTROLLERS = ("omada", "unifi")
VENDOR = {"omada": "TP-Link", "unifi": "Ubiquiti"}


def _port_by_no(c, did, no):
    if no is None:
        return None
    r = c.execute("SELECT id FROM interfaces WHERE device_id=? AND role='port' AND port_no=?", (did, no)).fetchone()
    return r["id"] if r else None


def apply_controller(c, row, res):
    """Infrastruktur (Gateway, Switches, APs) anlegen und verbinden, Clients einsortieren und an AP bzw. Switch-Port hängen."""
    pid, src, vendor = row["profile_id"], row["driver"], VENDOR.get(row["driver"], "")
    oui.ensure(lambda *a: None)
    dev_of, new, links, own = {}, 0, 0, None
    for d in res.get("devices", []):
        did = _find_device(c, pid, d["mac"], d["ip"])
        if not did:
            did = _new_device(c, pid, d["name"] or d["model"] or d["type"], d["type"], d["mac"], [d["ip"]], src, d["model"], vendor)
            new += 1
        # Ports aus dem Controller anlegen, wenn das Gerät noch keine hat (z. B. Modell nicht im Katalog)
        if d.get("ports") and not c.execute("SELECT 1 FROM interfaces WHERE device_id=? AND role='port'", (did,)).fetchone():
            data = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()["data"] or "{}")
            data["ports"] = ctl.port_groups(d["ports"])
            c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), did))
            inventory.sync_ports(c, did, data["ports"])
        runner._set_online(c, did, 1 if d["online"] else 0, now(), src)
        dev_of[d["mac"]] = did
        if d["ip"] and d["ip"] == row["host"]:
            own = did
    for d in res.get("devices", []):
        parent = dev_of.get(d["uplink_mac"])
        if parent and parent != dev_of[d["mac"]]:
            medium = "mesh" if d["type"] == "ap" and not d["uplink_port"] and c.execute(
                "SELECT type FROM devices WHERE id=?", (parent,)).fetchone()["type"] == "ap" else "lan"
            if set_auto_uplink(c, pid, dev_of[d["mac"]], parent, medium, port_id=_port_by_no(c, parent, d["uplink_port"]), source=src):
                links += 1
    rules, index = ident.load_rules(c), ident.catalog_index(c)
    hosts = []
    for x in res.get("clients", []):
        if not x["ip"] or not x["online"]:
            continue
        h = dict(ip=x["ip"], mac=x["mac"], vendor=x.get("vendor") or (oui.vendor(x["mac"]) if x["mac"] else ""),
                 random=oui.is_random(x["mac"]) if x["mac"] else False, hostname=x["name"], netbios="", mdns=None, ssdp=None, http=None,
                 ports=[], services={}, os="")
        h["ident"] = ident.identify(rules, index, h)
        hosts.append(h)
    stats = runner.merge(c, pid, None, hosts, source=src, record=False)
    by_mac = _device_by_mac(c, pid)
    for x in res.get("clients", []):
        d, parent = by_mac.get(x["mac"]), dev_of.get(x["parent_mac"])
        if not d or not parent or d["id"] == parent:
            continue
        if set_auto_uplink(c, pid, d["id"], parent, x["medium"], port_id=_port_by_no(c, parent, x["port"]) if x["medium"] == "lan" else None, source=src):
            links += 1
    if own:
        c.execute("UPDATE integrations SET device_id=? WHERE id=? AND device_id IS NULL", (own, row["id"]))
    return dict(device_id=own, devices=len(dev_of), clients=len(res.get("clients", [])), new=stats["new"] + new, links=links)


# ------------------------------------------------------------ MikroTik
def apply_mikrotik(c, row, res):
    """Router mit Ports, Clients und Nachbarn (MikroTik, OPNsense)."""
    pid, info = row["profile_id"], res.get("info") or {}
    src = row["driver"]
    vendor = info.get("vendor") or "MikroTik"
    oui.ensure(lambda *a: None)
    own = _own_device(c, row, info.get("name") or info.get("model") or vendor, info.get("model", ""), "", "firewall" if src == "opnsense" else "router", vendor)
    if res.get("ports") and not c.execute("SELECT 1 FROM interfaces WHERE device_id=? AND role='port'", (own,)).fetchone():
        data = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (own,)).fetchone()["data"] or "{}")
        data["ports"] = ctl.port_groups([dict(p, max_speed=ctl.speed_text(p.get("speed") or 0)) for p in res["ports"]])
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), own))
        inventory.sync_ports(c, own, data["ports"])
    port_id = {r["port_no"]: r["id"] for r in c.execute("SELECT id, port_no FROM interfaces WHERE device_id=? AND role='port'", (own,))}
    rules, index = ident.load_rules(c), ident.catalog_index(c)
    hosts, offline = [], set()
    for x in res.get("clients", []):
        if not x["online"]:
            offline.add(x["ip"])
            continue
        h = dict(ip=x["ip"], mac=x["mac"], vendor=oui.vendor(x["mac"]), random=oui.is_random(x["mac"]), hostname=x["name"], netbios="",
                 mdns=None, ssdp=None, http=None, ports=[], services={}, os="")
        h["ident"] = ident.identify(rules, index, h)
        hosts.append(h)
    stats = runner.merge(c, pid, None, hosts, probed=offline, source=src, record=False)
    by_mac = _device_by_mac(c, pid)
    links = 0
    wan_if = (res.get("wan") or {}).get("iface")
    for p in res.get("ports", []):  # Nachbarn per MNDP/LLDP: am WAN-Port der Uplink, sonst ein Gerät dahinter
        n = p.get("lldp") or {}
        d = by_mac.get(n.get("mac") or "")
        if not d or d["id"] == own:
            continue
        if p["iface"] == wan_if:
            if set_auto_uplink(c, pid, own, d["id"], "lan", local_port_id=port_id.get(p["port_no"]), source=src):
                links += 1
        elif set_auto_uplink(c, pid, d["id"], own, "lan", port_id=port_id.get(p["port_no"]), source=src):
            links += 1
    for x in res.get("clients", []):
        d = by_mac.get(x["mac"])
        if not d or not x["online"] or d["id"] == own or d["type"] in INFRA and x["medium"] == "lan" and not x["port"]:
            continue
        if x["medium"] == "lan" and not x["port"]:
            continue  # Port unbekannt (z. B. hinter einem weiteren Switch) – nicht raten
        pid_port = port_id.get(x["port"]) if x["port"] else None
        if pid_port and len(next((p["macs"] for p in res["ports"] if p["port_no"] == x["port"]), [])) > 1:
            continue  # mehrere Geräte am Port: dahinter steckt ein Switch/AP – SNMP bzw. Nachbarn klären das
        if set_auto_uplink(c, pid, d["id"], own, x["medium"], port_id=pid_port, source=src):
            links += 1
    return dict(device_id=own, clients=len(res.get("clients", [])), new=stats["new"], links=links, ports=len(res.get("ports", [])))


# ------------------------------------------------------------ Docker
def apply_docker(c, row, res):
    """Docker-Host als Gerät der Integration, Container als virtuelle Geräte daran."""
    pid, info = row["profile_id"], res.get("info") or {}
    host = _own_device(c, row, info.get("name") or row["host"], "", "", "server", "")
    new, links, seen = 0, 0, set()
    for ct in res.get("containers", []):
        meta = dict(docker=dict(integration=row["id"], id=ct["id"], name=ct["name"], image=ct["image"], ports=ct["ports"], network=ct["network"],
                                compose=ct["compose"], status=ct["status"]))
        r = c.execute("""SELECT id FROM devices WHERE profile_id=? AND json_extract(data,'$.docker.integration')=? AND json_extract(data,'$.docker.name')=?""",
                      (pid, row["id"], ct["name"])).fetchone()
        did = r["id"] if r else (_find_device(c, pid, ct["mac"], (ct["ips"] or [""])[0]) if ct["mac"] or ct["ips"] else None)
        if did == host:
            did = None
        if not did:
            did = _new_device(c, pid, ct["name"], "container", ct["mac"], ct["ips"], "docker", ct["image"].split("@")[0][:120], "Docker", data=meta)
            new += 1
        else:
            d = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()["data"] or "{}")
            d.update(meta)
            c.execute("UPDATE devices SET data=?, model=CASE WHEN model='' THEN ? ELSE model END WHERE id=?",
                      (json.dumps(d, ensure_ascii=False), ct["image"].split("@")[0][:120], did))
        seen.add(did)
        runner._set_online(c, did, 1 if ct["running"] else 0, now(), "docker")
        if set_auto_uplink(c, pid, did, host, "virtual", source="docker"):
            links += 1
    # verschwundene Container (gelöscht/neu angelegt unter anderem Namen): als offline markieren
    for r in c.execute("SELECT id FROM devices WHERE profile_id=? AND json_extract(data,'$.docker.integration')=?", (pid, row["id"])).fetchall():
        if r["id"] not in seen:
            runner._set_online(c, r["id"], 0, now(), "docker")
    return dict(device_id=host, containers=len(res.get("containers", [])), running=sum(1 for x in res.get("containers", []) if x["running"]),
                new=new, links=links)


GENERIC_NAME = __import__("re").compile(r"^(Unbekanntes Gerät|Unknown device|.*\s\.\d{1,3}|\d{1,3}(\.\d{1,3}){3})$")


def apply_dnsfilter(c, row, res):
    """Pi-hole / AdGuard Home: Hostnamen übernehmen (nur leere Hostnamen; Platzhalternamen im Posteingang), Anfragen und
    Blockierte je Gerät ablegen. Legt keine Geräte an – das machen Scan und Router-Integrationen."""
    pid, info = row["profile_id"], res.get("info") or {}
    own = row["device_id"] or _find_device(c, pid, "", row["host"])
    if own and not row["device_id"]:  # Gerät der Integration merken (für die Aktion „Werbeblocker ausschalten“)
        c.execute("UPDATE integrations SET device_id=? WHERE id=?", (own, row["id"]))
    named = matched = 0
    src = "Pi-hole" if info.get("kind") == "pihole" else "AdGuard Home"
    for x in res.get("clients", []):
        did = _find_device(c, pid, x.get("mac", ""), x["ip"])
        if not did:
            continue
        matched += 1
        d = c.execute("SELECT name, hostname, status, data FROM devices WHERE id=?", (did,)).fetchone()
        host = (x.get("name") or "").strip()
        short = host.split(".")[0] if host and not host.replace(".", "").isdigit() else ""
        sets = {}
        if short and not d["hostname"]:
            sets["hostname"] = short[:120]
        if short and d["status"] == "discovered" and GENERIC_NAME.match(d["name"] or "") and not inventory.name_locked(c, did):
            sets["name"] = short[:80]
        data = json.loads(d["data"] or "{}")
        data["dns"] = dict(integration=row["id"], source=src, queries=x["queries"], blocked=x["blocked"], pct=x["pct"], name=host,
                           window=info.get("window", ""), ts=now())
        sets["data"] = json.dumps(data, ensure_ascii=False)
        c.execute(f"UPDATE devices SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), did))
        named += 1 if ("hostname" in sets or "name" in sets) else 0
    return dict(device_id=own, clients=len(res.get("clients", [])), matched=matched, named=named)


def apply_shelly(c, row, res):
    """Shelly/Tasmota: Geräte zuordnen (MAC, IP) oder neu in den Posteingang, Messwerte, Firmware, Online-Status."""
    from . import health
    pid, new = row["profile_id"], 0
    for x in res.get("devices", []):
        did = _find_device(c, pid, x.get("mac"), x.get("ip"))
        vendor = "Shelly" if x["kind"] == "shelly" else "Tasmota"
        if not did:
            did = _new_device(c, pid, x.get("name") or f"{vendor} {x.get('model') or ''}".strip(), "iot", x.get("mac", ""), [x["ip"]], "shelly",
                              x.get("model", ""), vendor)
            new += 1
        d = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()["data"] or "{}")
        d["smart"] = dict(integration=row["id"], ip=x["ip"], kind=x["kind"], gen=x.get("gen"), model=x.get("model", ""), channels=x.get("channels") or [],
                          device_name=x.get("name", ""),
                          power_w=x.get("power_w"), energy_kwh=x.get("energy_kwh"), rssi=x.get("rssi"), voltage=x.get("voltage"), ts=now())
        c.execute("UPDATE devices SET data=?, manufacturer=CASE WHEN manufacturer='' THEN ? ELSE manufacturer END, "
                  "model=CASE WHEN model='' THEN ? ELSE model END WHERE id=?", (json.dumps(d, ensure_ascii=False), vendor, x.get("model", ""), did))
        runner._set_online(c, did, 1, now(), "shelly")
        if x.get("firmware"):
            health.apply_firmware(c, pid, did, x["firmware"], "shelly")
        if x.get("power_w") is not None:
            metrics.put(c, pid, {f"d{did}:power": x["power_w"]}, unit="W")
    return dict(devices=len(res.get("devices", [])), new=new, power_w=round(sum(x.get("power_w") or 0 for x in res.get("devices", [])), 1))


# ------------------------------------------------------------ devolo Powerline
def apply_devolo(c, row, res):
    """Adapter anlegen und als Powerline-Netz verbinden (am Router angeschlossener Adapter ist die Wurzel), Geräte an den
    LAN-Buchsen und WLAN-Geräte an ihren Adapter hängen, Firmware je Adapter übernehmen."""
    from . import health
    pid = row["profile_id"]
    adapters = res.get("adapters", [])
    dev_of, new, links, own = {}, 0, 0, None
    for a in adapters:
        did = _find_device(c, pid, a["mac"], a["ip"])
        if not did:
            did = _new_device(c, pid, a["name"], "powerline", a["mac"], [a["ip"]] if a["ip"] else [], "devolo", a["product"], "devolo")
            new += 1
        _auto_set(c, did, manufacturer="devolo", model=a["product"])
        runner._set_online(c, did, 1, now(), "devolo")
        if a.get("firmware_info"):
            health.apply_firmware(c, pid, did, a["firmware_info"], "devolo")
        dev_of[a["mac"]] = did
        if a["mac"] == res.get("host_mac"):
            own = did
    root = next((a for a in adapters if a["router"]), None) or next((a for a in adapters if a["mac"] == res.get("host_mac")), None)
    by_mac = _device_by_mac(c, pid)
    for a in adapters:
        did = dev_of[a["mac"]]
        if root and a is not root and set_auto_uplink(c, pid, did, dev_of[root["mac"]], "powerline", source="devolo"):
            links += 1
        wlan = {x["mac"] for x in a.get("clients", [])}
        for x in a.get("clients", []):
            d = by_mac.get(x["mac"])
            if d and d["id"] not in dev_of.values() and set_auto_uplink(c, pid, d["id"], did, "wlan", source="devolo"):
                links += 1
        for mac in a.get("bridged", []):
            d = by_mac.get(mac)
            if not d or mac in wlan or d["id"] in dev_of.values():
                continue
            if a is root:  # an der Buchse des Wurzel-Adapters hängt der Router: der Adapter hängt am Router, nicht umgekehrt
                if d["type"] in ("router", "firewall", "modem", "switch") and set_auto_uplink(c, pid, did, d["id"], "lan", source="devolo"):
                    links += 1
            elif set_auto_uplink(c, pid, d["id"], did, "lan", source="devolo"):
                links += 1
    if own:
        c.execute("UPDATE integrations SET device_id=? WHERE id=? AND device_id IS NULL", (own, row["id"]))
    return dict(device_id=own, adapters=len(adapters), new=new, links=links,
                clients=sum(len(a.get("clients", [])) for a in adapters))


APPLY = {"fritzbox": apply_fritz, "snmp": apply_snmp, "asuswrt": apply_asus, "proxmox": apply_proxmox, "homeassistant": apply_ha,
         "omada": apply_controller, "unifi": apply_controller, "mikrotik": apply_mikrotik, "opnsense": apply_mikrotik, "docker": apply_docker,
         "shelly": apply_shelly, "dnsfilter": apply_dnsfilter, "devolo": apply_devolo}
