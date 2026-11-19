"""Ein Netzscan von Anfang bis Ende: Ziele bestimmen, erkennen, einsortieren."""
import asyncio
import concurrent.futures as cf
import ipaddress
import json
import pathlib
import time

from .. import inventory, ipam, security
from ..db import db, get_setting, now
from . import discover, ident, netinfo, oui

MODES = ("passive", "light", "full")
MAX_HOSTS = 4096
DEFAULTS = dict(mode="full", targets=[], exclude=[], schedule_hours=0, fingerbank=False)
HTTP_PORTS = (80, 443, 8080, 8443, 8006, 5000, 5001, 8123, 8000, 8081)


def settings(profile_row):
    s = json.loads(profile_row["settings"] or "{}").get("scan") or {}
    return {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}


def resolve_targets(c, pid, s, override=None):
    """Explizit gewählte Netze, sonst die IPv4-Subnetze aus dem IPAM, sonst die Netze der eigenen Schnittstellen."""
    t = override or s.get("targets") or []
    if not t:
        t = [r["cidr"] for r in c.execute("SELECT cidr FROM subnets WHERE profile_id=?", (pid,))
             if ipaddress.ip_network(r["cidr"]).version == 4 and ipaddress.ip_network(r["cidr"]).prefixlen >= 20]
    if not t:
        t = sorted({i["cidr"] for i in netinfo.interfaces()})
    return [str(ipaddress.ip_network(x, strict=False)) for x in t]


def ensure_subnets(c, pid, targets):
    """Erstinitialisierung: gescannte Netze, die es im IPAM noch nicht gibt, werden angelegt."""
    have = [ipaddress.ip_network(r["cidr"]) for r in c.execute("SELECT cidr FROM subnets WHERE profile_id=?", (pid,))]
    gw = netinfo.default_gateway()
    created = []
    for t in targets:
        net = ipaddress.ip_network(t)
        if any(net.version == h.version and net.subnet_of(h) for h in have):
            continue
        g = gw if gw and ipaddress.ip_address(gw) in net else ""
        c.execute("INSERT INTO subnets(profile_id, cidr, name, gateway) VALUES(?,?,?,?)", (pid, t, "Netzscan", g))
        created.append(t)
    return created


class Progress:
    def __init__(self, job_id):
        self.job_id, self.last = job_id, 0

    def __call__(self, pct, msg, force=False):
        if not force and time.time() - self.last < 0.7:
            return
        self.last = time.time()
        with db() as c:
            c.execute("UPDATE jobs SET progress=?, message=? WHERE id=?", (int(pct), msg, self.job_id))


def _own_hosts(targets):
    """Die eigene Adresse taucht nicht in der ARP-Tabelle auf; sie wird mit der MAC der Schnittstelle ergänzt."""
    out = {}
    for i in netinfo.interfaces():
        if any(ipaddress.ip_address(i["ip"]) in ipaddress.ip_network(t) for t in targets):
            try:
                mac = pathlib.Path(f"/sys/class/net/{i['ifname']}/address").read_text().strip().upper()
            except OSError:
                mac = ""
            out[i["ip"]] = mac
    return out


def _safe(fn, log, what):
    """Ein Baustein, der scheitert, darf nicht den ganzen Scan abbrechen."""
    try:
        return fn() or {}
    except Exception as ex:
        log(f"{what} fehlgeschlagen: {ex}")
        return {}


def run(job_id, log=print):
    with db() as c:
        job = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        p = c.execute("SELECT * FROM profiles WHERE id=?", (job["profile_id"],)).fetchone()
        params = json.loads(job["params"] or "{}")
        s = settings(p)
        mode = params.get("mode") if params.get("mode") in MODES else s["mode"]
        targets = resolve_targets(c, p["id"], s, params.get("targets"))
        created = ensure_subnets(c, p["id"], targets) if params.get("create_subnets", True) else []
        fb_key = ""
        if s.get("fingerbank") and get_setting(c, "fingerbank_key"):
            fb_key = security.decrypt(get_setting(c, "fingerbank_key"))
        rules, index = ident.load_rules(c), ident.catalog_index(c)
        subnet_rows = [dict(r) for r in c.execute("SELECT cidr, dns, gateway FROM subnets WHERE profile_id=?", (p["id"],))]
    prog = Progress(job_id)
    t0 = time.time()
    prog(2, "Herstellerliste prüfen", True)
    oui.ensure(log)

    exclude = s.get("exclude") or []
    ex_nets = [ipaddress.ip_network(x, strict=False) for x in exclude]
    in_targets = lambda ip: any(ipaddress.ip_address(ip) in ipaddress.ip_network(t) for t in targets)  # noqa: E731
    excluded = lambda ip: any(ipaddress.ip_address(ip) in e for e in ex_nets)  # noqa: E731
    probe = []
    for t in targets:
        probe += discover.hosts_of(t, exclude)
    probe = probe[:MAX_HOSTS]

    sweep = {}
    if mode != "passive":
        ports = discover.FULL_PORTS if mode == "full" else discover.LIGHT_PORTS
        prog(5, f"{len(probe)} Adressen prüfen", True)
        sweep = asyncio.run(discover.sweep(probe, ports, progress=lambda d, n: prog(5 + 45 * d / max(n, 1), f"Adressen prüfen: {d} von {n}")))
    arp = {ip: mac for ip, mac in discover.read_arp().items() if in_targets(ip)}
    own = _own_hosts(targets)
    alive = {ip for ip, r in sweep.items() if r["alive"]} | set(arp) | set(own)

    prog(52, "mDNS und UPnP abfragen", True)
    with cf.ThreadPoolExecutor(2) as ex:
        f_mdns, f_ssdp = ex.submit(discover.mdns, 4.0), ex.submit(discover.ssdp, 3.0)
        mdns = {ip: v for ip, v in _safe(f_mdns.result, log, "mDNS").items() if in_targets(ip)}
        ssdp = {ip: v for ip, v in _safe(f_ssdp.result, log, "UPnP").items() if in_targets(ip)}
    alive |= set(mdns) | set(ssdp)
    arp.update({ip: mac for ip, mac in discover.read_arp().items() if in_targets(ip)})
    active_ips = sorted((ip for ip in alive if not excluded(ip)), key=inventory.ip_key)

    prog(60, "Namen auflösen", True)
    rdns = _safe(lambda: discover.reverse_dns(sorted(alive)), log, "DNS")
    # Namen aus Netzen hinter einem Router: beim DNS des jeweiligen Subnetzes nachfragen (DNS-Angabe, sonst Gateway)
    servers = [(ipaddress.ip_network(r["cidr"]), (r["dns"].split(",")[0].strip() or r["gateway"])) for r in subnet_rows if (r["dns"] or r["gateway"])]
    for ip in sorted(alive - set(rdns) - set(own)):
        srv = next((sv for net, sv in servers if ipaddress.ip_address(ip) in net), None)
        if srv and srv != ip:
            name = discover.dns_ptr(ip, srv)
            if name:
                rdns[ip] = name
    http, nb, nm = {}, {}, {}
    if mode != "passive":
        prog(65, "Weboberflächen lesen", True)
        http = _safe(lambda: discover.http_probe([(ip, next(p for p in HTTP_PORTS if p in sweep[ip]["ports"]))
                                    for ip in active_ips if ip in sweep and any(p in sweep[ip]["ports"] for p in HTTP_PORTS)]), log, "HTTP")
    if mode == "full":
        prog(70, "NetBIOS-Namen abfragen", True)
        nb = _safe(lambda: discover.netbios(active_ips), log, "NetBIOS")
        if discover.nmap_available() and active_ips:
            prog(72, f"Dienste erkennen (nmap, {len(active_ips)} Geräte) – das kann einige Minuten dauern", True)
            nm = _safe(lambda: discover.nmap(active_ips, privileged=netinfo.has_raw()), log, "nmap")

    prog(90, "Geräte erkennen", True)
    hosts = []
    for ip in sorted(alive, key=inventory.ip_key):
        mac = arp.get(ip) or own.get(ip, "")
        h = dict(ip=ip, mac=mac, vendor=oui.vendor(mac) if mac else "", random=oui.is_random(mac) if mac else False,
                 hostname=rdns.get(ip, ""), netbios=nb.get(ip, ""), mdns=mdns.get(ip), ssdp=ssdp.get(ip), http=http.get(ip),
                 ports=sorted(set(sweep.get(ip, {}).get("ports", [])) | set(nm.get(ip, {}).get("ports", []))),
                 services=nm.get(ip, {}).get("services", {}), os=nm.get(ip, {}).get("os", ""), own=ip in own)
        h["ident"] = ident.identify(rules, index, h, fb_key)
        hosts.append(h)

    prog(96, "Ergebnisse speichern", True)
    with db() as c:
        stats = merge(c, p["id"], job_id, hosts, probed={ip for ip in probe} if mode != "passive" else set())
    stats.update(mode=mode, targets=targets, subnets_created=created, duration=round(time.time() - t0, 1), nmap=bool(nm),
                 os_detection=bool(nm) and netinfo.has_raw(), excluded=len(exclude))
    return stats


# ------------------------------------------------------------ Einsortieren
def event(c, pid, kind, did=None, **data):
    """Ereignis für Benachrichtigungen (wird z. B. per MQTT an Home Assistant gemeldet)."""
    c.execute("INSERT INTO events(profile_id, ts, kind, device_id, data) VALUES(?,?,?,?,?)",
              (pid, now(), kind, did, json.dumps(data, ensure_ascii=False)))


def _set_online(c, did, online, ts, source="scan"):
    r = c.execute("SELECT online, status, profile_id, name FROM devices WHERE id=?", (did,)).fetchone()
    if r is None:
        return
    if r["online"] != online:
        c.execute("INSERT INTO status_events(device_id, ts, online, source) VALUES(?,?,?,?)", (did, ts, online, source))
        # Meldung nur bei echten Wechseln bestätigter Geräte (nicht beim ersten Sehen)
        if r["status"] == "confirmed" and r["online"] is not None:
            event(c, r["profile_id"], "device_online" if online else "device_offline", did, name=r["name"], source=source)
    if online:
        c.execute("UPDATE devices SET online=1, last_seen=? WHERE id=?", (ts, did))
    else:
        c.execute("UPDATE devices SET online=0 WHERE id=?", (did,))


def _ip_kind(c, pid, ip):
    """DHCP, wenn die Adresse im DHCP-Bereich eines Subnetzes liegt, sonst statisch."""
    a = int(ipaddress.ip_address(ip))
    for s in c.execute("SELECT dhcp_start, dhcp_end FROM subnets WHERE profile_id=? AND dhcp_start<>''", (pid,)):
        if int(ipaddress.ip_address(s["dhcp_start"])) <= a <= int(ipaddress.ip_address(s["dhcp_end"])):
            return "dhcp"
    return "static"


def _seen_summary(h):
    m, s, w = h.get("mdns") or {}, h.get("ssdp") or {}, h.get("http") or {}
    return {k: v for k, v in dict(
        vendor=h.get("vendor"), hostname=h.get("hostname"), netbios=h.get("netbios"), mdns_names=m.get("names"), mdns_services=m.get("services"),
        mdns_txt=m.get("txt"), ssdp_model=" ".join(x for x in (s.get("manufacturer"), s.get("modelName"), s.get("modelNumber")) if x),
        ssdp_name=s.get("friendlyName"), http_title=w.get("title"), http_server=w.get("server"), ports=h.get("ports"),
        services=h.get("services"), os=h.get("os"), random=h.get("random")).items() if v}


def merge(c, pid, job_id, hosts, probed=(), source="scan", record=True):
    ts = now()
    by_mac = {r["mac"]: r["device_id"] for r in c.execute(
        "SELECT i.mac, i.device_id FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND i.mac<>''", (pid,))}
    by_ip = {}
    for r in c.execute("SELECT address, device_id FROM ip_addresses WHERE profile_id=? AND device_id IS NOT NULL", (pid,)):
        by_ip.setdefault(r["address"], r["device_id"])
    stats = dict(hosts=len(hosts), new=0, known=0, offline=0, ignored=0)
    seen = set()
    for h in hosts:
        did = by_mac.get(h["mac"]) if h["mac"] else None
        if did is None and h["ip"] in by_ip:
            cand = by_ip[h["ip"]]
            nic = inventory.nic_of(c, cand, create=False)
            if not h["mac"] or not nic or not nic["mac"]:
                did = cand
        idt = h["ident"]
        if did:
            d = c.execute("SELECT * FROM devices WHERE id=?", (did,)).fetchone()
            data = json.loads(d["data"] or "{}")
            data["ident"], data["seen"] = idt, _seen_summary(h)
            sets = dict(data=json.dumps(data, ensure_ascii=False))
            if not d["hostname"] and ident.good_host(h["hostname"]):
                sets["hostname"] = ident.good_host(h["hostname"])
            if d["status"] == "discovered":  # Vorschläge im Posteingang dürfen sich verbessern
                sets.update(type=idt["type"], manufacturer=idt["manufacturer"], model=idt["model"], model_id=idt["model_id"])
            c.execute(f"UPDATE devices SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), did))
            nic = inventory.nic_of(c, did)
            if h["mac"] and not nic["mac"] and h["mac"] not in by_mac:
                c.execute("UPDATE interfaces SET mac=? WHERE id=?", (h["mac"], nic["id"]))
                by_mac[h["mac"]] = did
            ips = c.execute("SELECT * FROM ip_addresses WHERE device_id=?", (did,)).fetchall()
            if not ips:
                c.execute("INSERT INTO ip_addresses(profile_id, device_id, interface_id, address, kind, source) VALUES(?,?,?,?,?,?)",
                          (pid, did, nic["id"], h["ip"], _ip_kind(c, pid, h["ip"]), source))
            elif h["ip"] not in {r["address"] for r in ips}:
                auto = [r for r in ips if r["kind"] == "dhcp" or r["source"] != "manual"]
                if len(auto) == 1:  # neue Adresse übernehmen; manuelle statische Angaben bleiben unangetastet
                    c.execute("UPDATE ip_addresses SET address=?, kind=? WHERE id=?", (h["ip"], _ip_kind(c, pid, h["ip"]), auto[0]["id"]))
            stats["ignored" if d["status"] == "ignored" else "known"] += 1
        else:
            m = c.execute("SELECT data FROM device_models WHERE id=?", (idt["model_id"],)).fetchone() if idt["model_id"] else None
            body = dict(name=ident.suggest_name(h, idt), type=idt["type"], model_id=idt["model_id"], manufacturer=idt["manufacturer"],
                        model=idt["model"], hostname=ident.good_host(h["hostname"]), mac=h["mac"], status="discovered",
                        ips=[dict(address=h["ip"], kind=_ip_kind(c, pid, h["ip"]), source=source)],
                        ports=json.loads(m["data"]).get("ports", []) if m else [])
            did = inventory.save_device(c, pid, body)
            d = c.execute("SELECT data FROM devices WHERE id=?", (did,)).fetchone()
            data = json.loads(d["data"] or "{}")
            data["ident"], data["seen"] = idt, _seen_summary(h)
            c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), did))
            if h["mac"]:
                by_mac[h["mac"]] = did
            by_ip.setdefault(h["ip"], did)
            stats["new"] += 1
            event(c, pid, "new_device", did, name=body["name"], ip=h["ip"], mac=h["mac"], label=idt.get("label", ""), source=source)
        seen.add(did)
        if record:
            c.execute("INSERT INTO observations(profile_id, job_id, device_id, ip, mac, data, seen) VALUES(?,?,?,?,?,?,?)",
                      (pid, job_id, did, h["ip"], h["mac"], discover.dumps({k: v for k, v in h.items() if k != "ident"}), ts))
        _set_online(c, did, 1, ts, source)
    # Geräte mit einer geprüften Adresse, die nicht geantwortet haben, gelten als offline
    if probed:
        for r in c.execute("SELECT DISTINCT a.device_id, a.address FROM ip_addresses a JOIN devices d ON d.id=a.device_id WHERE a.profile_id=?", (pid,)).fetchall():
            if r["device_id"] not in seen and r["address"] in probed:
                before = c.execute("SELECT online FROM devices WHERE id=?", (r["device_id"],)).fetchone()["online"]
                _set_online(c, r["device_id"], 0, ts, source)
                if before != 0:
                    stats["offline"] += 1
                seen.add(r["device_id"])
    ipam.reclassify(c, pid)
    c.execute("""DELETE FROM observations WHERE profile_id=? AND job_id NOT IN
                 (SELECT id FROM jobs WHERE profile_id=? AND kind='scan' ORDER BY id DESC LIMIT 20)""", (pid, pid))
    return stats
