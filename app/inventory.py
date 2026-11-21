"""Geräte, Schnittstellen, Ports und Verbindungen eines Profils."""
import ipaddress
import json
import re

from fastapi import HTTPException

from . import catalog
from .db import now

MAC_HEX = re.compile(r"[^0-9a-fA-F]")
NUM = re.compile(r"(\d+)")


def natural(s):
    """Sortierschlüssel, bei dem „Gerät 2“ vor „Gerät 10“ kommt."""
    return [int(p) if p.isdigit() else p.lower() for p in NUM.split(str(s or ""))]


def norm_mac(s):
    s = str(s or "").strip()
    if not s:
        return ""
    h = MAC_HEX.sub("", s)
    if len(h) != 12:
        raise HTTPException(400, f"Ungültige MAC-Adresse: {s}")
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)).upper()


def norm_ip(s):
    try:
        return str(ipaddress.ip_address(str(s or "").strip()))
    except ValueError:
        raise HTTPException(400, f"Ungültige IP-Adresse: {s}")


def ip_key(a):
    try:
        ip = ipaddress.ip_address(a)
        return (ip.version, int(ip))
    except ValueError:
        return (9, 0)


# ------------------------------------------------------------ Standorte
def location_paths(c, pid):
    rows = {r["id"]: r for r in c.execute("SELECT * FROM locations WHERE profile_id=?", (pid,))}
    out = {}

    def path(i, seen=()):
        if i in out:
            return out[i]
        r = rows[i]
        p = r["parent_id"]
        out[i] = (path(p, seen + (i,)) + " › " if p in rows and p not in seen else "") + r["name"]
        return out[i]

    for i in rows:
        path(i)
    return out


def check_location(c, pid, lid):
    if lid in (None, "", 0):
        return None
    if not c.execute("SELECT 1 FROM locations WHERE id=? AND profile_id=?", (int(lid), pid)).fetchone():
        raise HTTPException(400, "Standort gehört nicht zu diesem Profil")
    return int(lid)


# ------------------------------------------------------------ Schnittstellen
def nic_of(c, did, create=True):
    r = c.execute("SELECT * FROM interfaces WHERE device_id=? AND role='nic' ORDER BY id LIMIT 1", (did,)).fetchone()
    if r or not create:
        return r
    cur = c.execute("INSERT INTO interfaces(device_id, role, name) VALUES(?, 'nic', 'LAN')", (did,))
    return c.execute("SELECT * FROM interfaces WHERE id=?", (cur.lastrowid,)).fetchone()


def sync_ports(c, did, groups):
    """Legt die Ports nach den Port-Gruppen an. Verbindungen an weiterhin vorhandenen Ports bleiben erhalten."""
    want = {p["port_no"]: p for p in catalog.expand_ports(groups)}
    have = {r["port_no"]: r for r in c.execute("SELECT * FROM interfaces WHERE device_id=? AND role='port'", (did,))}
    for no, p in want.items():
        if no in have:
            c.execute("UPDATE interfaces SET name=?, kind=?, speed=?, poe=? WHERE id=?", (p["name"], p["kind"], p["speed"], p["poe"], have[no]["id"]))
        else:
            c.execute("INSERT INTO interfaces(device_id, role, name, kind, port_no, speed, poe) VALUES(?, 'port', ?,?,?,?,?)",
                      (did, p["name"], p["kind"], no, p["speed"], p["poe"]))
    for no, r in have.items():
        if no not in want:
            c.execute("DELETE FROM interfaces WHERE id=?", (r["id"],))


def _device_of_if(c, iid):
    return c.execute("SELECT d.id, d.name, d.profile_id, i.role, i.name AS ifname FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE i.id=?",
                     (iid,)).fetchone()


def _uplink_parent(c, did):
    r = c.execute("""SELECT bi.device_id FROM links l JOIN interfaces ai ON ai.id=l.a_if JOIN interfaces bi ON bi.id=l.b_if
                     WHERE ai.device_id=? AND l.uplink=1 LIMIT 1""", (did,)).fetchone()
    return r["device_id"] if r else None


def set_uplink(c, pid, did, up):
    """up = {device_id, port_id (Port der Gegenstelle), local_port_id (eigener Port), medium} oder leer."""
    c.execute("DELETE FROM links WHERE uplink=1 AND a_if IN (SELECT id FROM interfaces WHERE device_id=?)", (did,))
    if not up or not up.get("device_id"):
        return
    medium = up.get("medium") if up.get("medium") in catalog.MEDIA else "lan"
    target = c.execute("SELECT * FROM devices WHERE id=? AND profile_id=?", (int(up["device_id"]), pid)).fetchone()
    if not target:
        raise HTTPException(400, "Gegenstelle gehört nicht zu diesem Profil")
    if target["id"] == did:
        raise HTTPException(400, "Ein Gerät kann nicht mit sich selbst verbunden werden")
    # keine Ringe im Baum: die Gegenstelle darf nicht (indirekt) an diesem Gerät hängen
    seen, cur = set(), target["id"]
    while cur and cur not in seen:
        if cur == did:
            raise HTTPException(400, "Diese Verbindung würde einen Ring ergeben")
        seen.add(cur)
        cur = _uplink_parent(c, cur)

    def port(iid, owner):
        r = c.execute("SELECT * FROM interfaces WHERE id=? AND device_id=? AND role='port'", (int(iid), owner)).fetchone()
        if not r:
            raise HTTPException(400, "Port nicht gefunden")
        used = c.execute("""SELECT l.id, ad.name AS a_name, bd.name AS b_name, l.a_if, l.b_if FROM links l
                            JOIN interfaces ai ON ai.id=l.a_if JOIN devices ad ON ad.id=ai.device_id
                            JOIN interfaces bi ON bi.id=l.b_if JOIN devices bd ON bd.id=bi.device_id
                            WHERE l.a_if=? OR l.b_if=?""", (r["id"], r["id"])).fetchone()
        if used:
            other = used["a_name"] if used["b_if"] == r["id"] else used["b_name"]
            raise HTTPException(400, f"Port {r['name']} ist schon mit {other} belegt")
        return r["id"]

    b_if = port(up["port_id"], target["id"]) if up.get("port_id") else nic_of(c, target["id"])["id"]
    a_if = port(up["local_port_id"], did) if up.get("local_port_id") else nic_of(c, did)["id"]
    c.execute("INSERT INTO links(profile_id, a_if, b_if, medium, uplink, source) VALUES(?,?,?,?,1,'manual')", (pid, a_if, b_if, medium))


# ------------------------------------------------------------ Speichern
def lock_name(c, did):
    r = c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()
    data = json.loads(r["data"] or "{}")
    if not data.get("name_manual"):
        data["name_manual"] = True
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), did))


def name_locked(c, did, data=None):
    """Hat jemand den Namen von Hand vergeben? (Merker, sonst ein früherer Eintrag „Name geändert“ von einem Benutzer im Verlauf)"""
    if data is None:
        r = c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()
        data = json.loads(r["data"] or "{}") if r else {}
    if data.get("name_manual"):
        return True
    return bool(c.execute("SELECT 1 FROM changes WHERE device_id=? AND field='name' AND user_id IS NOT NULL LIMIT 1", (did,)).fetchone())


def save_device(c, pid, body, did=None):
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(400, "Name fehlt")
    typ = body.get("type") if body.get("type") in catalog.TYPES else "other"
    model_id = body.get("model_id") or None
    if model_id and not c.execute("SELECT 1 FROM device_models WHERE id=?", (int(model_id),)).fetchone():
        raise HTTPException(400, "Katalogeintrag nicht gefunden")
    tags = body.get("tags") or []
    if isinstance(tags, str):
        tags = [x.strip() for x in tags.split(",")]
    tags = [str(x).strip()[:40] for x in tags if str(x).strip()][:20]
    data = {}
    if did:
        old = c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()
        data = json.loads(old["data"] or "{}")
    data["ports"] = catalog.clean_groups(body.get("ports")) if "ports" in body else data.get("ports", [])
    vals = (name, typ, int(model_id) if model_id else None, str(body.get("manufacturer") or "").strip()[:80],
            str(body.get("model") or "").strip()[:120], check_location(c, pid, body.get("location_id")),
            str(body.get("hostname") or "").strip()[:120], str(body.get("notes") or "").strip()[:5000],
            json.dumps(tags, ensure_ascii=False), json.dumps(data, ensure_ascii=False), now())
    if did:
        c.execute("""UPDATE devices SET name=?, type=?, model_id=?, manufacturer=?, model=?, location_id=?, hostname=?, notes=?,
                     tags=?, data=?, updated=? WHERE id=?""", vals + (did,))
        if body.get("status") in ("confirmed", "discovered", "ignored"):
            c.execute("UPDATE devices SET status=? WHERE id=?", (body["status"], did))
    else:
        cur = c.execute("""INSERT INTO devices(name, type, model_id, manufacturer, model, location_id, hostname, notes, tags, data, updated,
                           profile_id, status, created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        vals + (pid, body.get("status") if body.get("status") in ("confirmed", "discovered") else "confirmed", now()))
        did = cur.lastrowid

    nic = nic_of(c, did)
    medium = (body.get("uplink") or {}).get("medium") or ""
    c.execute("UPDATE interfaces SET mac=?, name=?, kind=? WHERE id=?",
              (norm_mac(body.get("mac")), "WLAN" if medium in ("wlan", "mesh") else "LAN", "wlan" if medium in ("wlan", "mesh") else "rj45", nic["id"]))
    sync_ports(c, did, data["ports"])

    if "ips" in body:
        # Herkunft erhalten, wenn Adresse und Art gleich bleiben; sonst gilt die Angabe als manuell
        old_src = {(r["address"], r["kind"]): r["source"] for r in c.execute("SELECT address, kind, source FROM ip_addresses WHERE device_id=?", (did,))}
        c.execute("DELETE FROM ip_addresses WHERE device_id=?", (did,))
        seen = set()
        for ip in body.get("ips") or []:
            if not str(ip.get("address") or "").strip():
                continue
            a = norm_ip(ip["address"])
            if a in seen:
                continue
            seen.add(a)
            kind = ip.get("kind") if ip.get("kind") in ("static", "dhcp", "reserved") else "static"
            src = ip.get("source") if ip.get("source") in ("scan", "fritzbox", "snmp") else old_src.get((a, kind), "manual")
            c.execute("INSERT INTO ip_addresses(profile_id, device_id, interface_id, address, kind, note, source) VALUES(?,?,?,?,?,?,?)",
                      (pid, did, nic["id"], a, kind, str(ip.get("note") or "").strip()[:200], src))
    if "uplink" in body:
        set_uplink(c, pid, did, body.get("uplink"))
    return did


# ------------------------------------------------------------ Lesen
def _links_by_device(c, pid):
    """-> (uplinks: device_id -> dict, children: device_id -> [device_id], port_peer: interface_id -> dict)"""
    rows = c.execute("""SELECT l.*, ai.device_id AS a_dev, ai.role AS a_role, ai.name AS a_name, bi.device_id AS b_dev, bi.role AS b_role,
                               bi.name AS b_name, ad.name AS a_devname, bd.name AS b_devname
                        FROM links l JOIN interfaces ai ON ai.id=l.a_if JOIN interfaces bi ON bi.id=l.b_if
                        JOIN devices ad ON ad.id=ai.device_id JOIN devices bd ON bd.id=bi.device_id
                        WHERE l.profile_id=?""", (pid,)).fetchall()
    uplinks, children, port_peer = {}, {}, {}
    for r in rows:
        if r["uplink"]:
            uplinks[r["a_dev"]] = dict(device_id=r["b_dev"], device_name=r["b_devname"], medium=r["medium"],
                                       port_id=r["b_if"] if r["b_role"] == "port" else None, port_name=r["b_name"] if r["b_role"] == "port" else "",
                                       local_port_id=r["a_if"] if r["a_role"] == "port" else None,
                                       local_port_name=r["a_name"] if r["a_role"] == "port" else "")
            children.setdefault(r["b_dev"], []).append(r["a_dev"])
        if r["b_role"] == "port":
            port_peer[r["b_if"]] = dict(device_id=r["a_dev"], device_name=r["a_devname"], medium=r["medium"], direction="down")
        if r["a_role"] == "port":
            port_peer[r["a_if"]] = dict(device_id=r["b_dev"], device_name=r["b_devname"], medium=r["medium"], direction="up")
    return uplinks, children, port_peer


def _ident_short(data):
    i = json.loads(data or "{}").get("ident")
    if not i:
        return None
    return {k: i.get(k) for k in ("label", "label_en", "type", "confidence", "reasons", "vendor", "random", "model", "manufacturer", "also")}


def list_devices(c, pid, status=None):
    locs = location_paths(c, pid)
    nics = {r["device_id"]: r for r in c.execute(
        "SELECT i.* FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND i.role='nic' ORDER BY i.id DESC", (pid,))}
    ports = {}
    for r in c.execute("SELECT i.device_id, i.id FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND i.role='port'", (pid,)):
        ports.setdefault(r["device_id"], []).append(r["id"])
    ips = {}
    for r in c.execute("SELECT device_id, address, kind FROM ip_addresses WHERE profile_id=?", (pid,)):
        ips.setdefault(r["device_id"], []).append(dict(address=r["address"], kind=r["kind"]))
    uplinks, children, port_peer = _links_by_device(c, pid)
    out = []
    for d in c.execute("SELECT * FROM devices WHERE profile_id=? ORDER BY name COLLATE NOCASE", (pid,)):
        if status and d["status"] != status:
            continue
        nic = nics.get(d["id"])
        pl = ports.get(d["id"], [])
        out.append(dict(
            id=d["id"], name=d["name"], type=d["type"], model_id=d["model_id"], manufacturer=d["manufacturer"], model=d["model"],
            location_id=d["location_id"], location=locs.get(d["location_id"], ""), status=d["status"], hostname=d["hostname"],
            notes=d["notes"], tags=json.loads(d["tags"] or "[]"), mac=nic["mac"] if nic else "",
            ips=sorted(ips.get(d["id"], []), key=lambda x: ip_key(x["address"])), uplink=uplinks.get(d["id"]),
            ports_total=len(pl), ports_used=sum(1 for i in pl if i in port_peer), children=len(children.get(d["id"], [])),
            updated=d["updated"], online=d["online"], last_seen=d["last_seen"], ident=_ident_short(d["data"]),
            fw_update=bool((json.loads(d["data"] or "{}").get("firmware") or {}).get("update"))))
    return sorted(out, key=lambda x: natural(x["name"]))


def _services_job(c, pid, did):
    for j in c.execute("SELECT id, params FROM jobs WHERE profile_id=? AND kind='services' AND status IN ('queued','running')", (pid,)):
        if json.loads(j["params"] or "{}").get("device_id") == did:
            return j["id"]
    return None


def device_detail(c, pid, did):
    d = c.execute("SELECT * FROM devices WHERE id=? AND profile_id=?", (did, pid)).fetchone()
    if not d:
        raise HTTPException(404, "Gerät nicht gefunden")
    by_id = {x["id"]: x for x in list_devices(c, pid)}
    base = by_id[did]
    uplinks, children, port_peer = _links_by_device(c, pid)
    from .integrations import live_ports
    live = live_ports(c, did)
    ports = []
    for r in c.execute("SELECT * FROM interfaces WHERE device_id=? AND role='port' ORDER BY port_no", (did,)):
        peer = port_peer.get(r["id"])
        if peer:
            o = by_id.get(peer["device_id"], {})
            peer = dict(peer, ip=(o.get("ips") or [{}])[0].get("address", ""), mac=o.get("mac", ""), type=o.get("type", ""))
        lp = live.get(r["port_no"])
        ports.append(dict(id=r["id"], port_no=r["port_no"], name=r["name"], kind=r["kind"], speed=r["speed"], poe=bool(r["poe"]), peer=peer,
                          live=dict(oper=lp["oper"], speed=lp["speed"], in_bps=lp["in_bps"], out_bps=lp["out_bps"], macs=len(lp["macs"]),
                                    lldp=lp["lldp"], admin=lp.get("admin", "up"), poe=lp.get("poe")) if lp else None))
    kids = [dict(id=k, name=by_id[k]["name"], type=by_id[k]["type"], medium=uplinks[k]["medium"], port_name=uplinks[k]["port_name"],
                 ip=(by_id[k]["ips"] or [{}])[0].get("address", ""), mac=by_id[k]["mac"]) for k in children.get(did, []) if k in by_id]
    data = json.loads(d["data"] or "{}")
    events = [dict(ts=r["ts"], online=bool(r["online"])) for r in c.execute(
        "SELECT ts, online FROM status_events WHERE device_id=? ORDER BY id DESC LIMIT 10", (did,))]
    integ = [dict(id=r["id"], driver=r["driver"], name=r["name"]) for r in c.execute("SELECT id, driver, name FROM integrations WHERE device_id=?", (did,))]
    from .configbackup import listing
    configs = listing(c, pid, did)
    return dict(base, ports=ports, port_groups=data.get("ports", []), connected=sorted(kids, key=lambda x: x["name"].lower()),
                seen=data.get("seen"), ident_full=data.get("ident"), events=events, integrations=integ, configs=configs,
                services_scan=data.get("services_scan"), smart=data.get("smart"), dns=data.get("dns"),
                services_job=_services_job(c, pid, did))


def ports_of(c, pid, did):
    """Ports eines Geräts mit Belegung – für die Auswahl „Verbunden mit … Port“."""
    if not c.execute("SELECT 1 FROM devices WHERE id=? AND profile_id=?", (did, pid)).fetchone():
        raise HTTPException(404, "Gerät nicht gefunden")
    _, _, port_peer = _links_by_device(c, pid)
    return [dict(id=r["id"], name=r["name"], kind=r["kind"], speed=r["speed"], peer=port_peer.get(r["id"]))
            for r in c.execute("SELECT * FROM interfaces WHERE device_id=? AND role='port' ORDER BY port_no", (did,))]
