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


def conf_of(row):
    return dict(host=row["host"], port=row["port"], username=row["username"],
                password=security.decrypt(row["secret"]) if row["secret"] else "", options=json.loads(row["options"] or "{}"))


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
        summary = (apply_fritz if row["driver"] == "fritzbox" else apply_snmp)(c, row, res)
        runner._set_online(c, summary["device_id"], 1, now(), row["driver"])
        metrics.put(c, row["profile_id"], {f"i{iid}:{k}": v for k, v in values.items()})
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
