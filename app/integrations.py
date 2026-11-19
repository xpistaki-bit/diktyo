"""Integrationen abfragen und die Ergebnisse auf den Bestand übertragen (FRITZ!Box, SNMP-Switch)."""
import json
import time

from . import catalog, inventory, metrics, security
from .db import db, now
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
    try:
        res, values, new_state = drv.poll(conf_of(row), state)
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
        if summary.get("device_id"):
            runner._set_online(c, summary["device_id"], 1, now(), row["driver"])
        metrics.put(c, row["profile_id"], {f"i{iid}:{k}": v for k, v in values.items()})
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()  # apply_ha schreibt eigenen Zustand
        new_state = {**json.loads(row["state"] or "{}"), **new_state}
        new_state.update(summary=summary, result=_slim(row["driver"], res), ts=time.time())
        c.execute("UPDATE integrations SET state=?, last_ok=?, last_error=? WHERE id=?",
                  (json.dumps(new_state, ensure_ascii=False), now(), res.get("warning", ""), iid))
    return summary


def _fail(iid, msg):
    with db() as c:
        c.execute("UPDATE integrations SET last_error=? WHERE id=?", (msg[:500], iid))
    return None


def _slim(driver, res):
    """Was die Oberfläche anzeigen soll (ohne die vollständige Hostliste)."""
    if driver == "asuswrt":
        return dict(info=res.get("info"), nodes=[{k: n[k] for k in ("name", "model", "ip", "online", "wired_backhaul")} for n in res.get("nodes", [])],
                    clients=len(res.get("clients", [])), online=sum(1 for x in res.get("clients", []) if x["online"]),
                    wlan=sum(1 for x in res.get("clients", []) if x["online"] and x["medium"] == "wlan"))
    if driver == "proxmox":
        return dict(info=res.get("info"), nodes=res.get("nodes"), guests=len(res.get("guests", [])),
                    running=sum(1 for g in res.get("guests", []) if g["running"]))
    if driver == "homeassistant":
        return dict(info=res.get("info"))
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


def set_auto_uplink(c, pid, did, target, medium="lan", port_name=None, port_id=None, local_port_id=None, source="auto"):
    """Verbindung aus einer Integration setzen. Von Hand gesetzte Verbindungen haben immer Vorrang."""
    cur = c.execute("""SELECT l.*, bi.device_id AS target FROM links l JOIN interfaces ai ON ai.id=l.a_if JOIN interfaces bi ON bi.id=l.b_if
                       WHERE ai.device_id=? AND l.uplink=1""", (did,)).fetchone()
    if cur and cur["source"] == "manual":
        return False
    if port_name and not port_id:
        r = c.execute("SELECT id FROM interfaces WHERE device_id=? AND role='port' AND lower(name)=lower(?)", (target, port_name)).fetchone()
        port_id = r["id"] if r else None
    b_if = port_id or inventory.nic_of(c, target)["id"]
    a_if = local_port_id or inventory.nic_of(c, did)["id"]
    if cur and cur["b_if"] == b_if and cur["a_if"] == a_if and cur["medium"] == medium:
        return False
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
    c.execute("INSERT INTO links(profile_id, a_if, b_if, medium, uplink, source) VALUES(?,?,?,?,1,?)", (pid, a_if, b_if, medium, source))
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
    sw = _own_device(c, row, info.get("name") or f"Switch {row['host']}", info.get("descr", "")[:80], "", "switch", ENTERPRISE.get(ent, ""))
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
    return dict(device_id=sw, ports=len(res.get("ports", [])), up=up, links=links, macs=res.get("fdb_size", 0))


def live_ports(c, did):
    """Port-Status aus der letzten SNMP-Abfrage eines Geräts -> {port_no: {...}}"""
    r = c.execute("SELECT state FROM integrations WHERE device_id=? AND driver='snmp' ORDER BY id LIMIT 1", (did,)).fetchone()
    if not r:
        return {}
    st = json.loads(r["state"] or "{}")
    return {p["port_no"]: p for p in (st.get("result") or {}).get("ports") or []}


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
            if hd.get("name") and hd["name"] != d["name"] and (mode == "all" or (mode == "new" and _auto_name(d))):
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
        event_types=["device_offline", "device_online", "new_device"]), True))
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


APPLY = {"fritzbox": apply_fritz, "snmp": apply_snmp, "asuswrt": apply_asus, "proxmox": apply_proxmox, "homeassistant": apply_ha}
