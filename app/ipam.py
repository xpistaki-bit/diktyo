"""IPAM: Subnetze, Belegung, freie Bereiche und Konflikte."""
import ipaddress

from fastapi import HTTPException

FREE_LIST_MAX_PREFIX = 16  # freie Bereiche nur für IPv4-Netze ab /16 berechnen


def _ip(s, field):
    s = str(s or "").strip()
    if not s:
        return None
    try:
        return ipaddress.ip_address(s)
    except ValueError:
        raise HTTPException(400, f"Ungültige IP-Adresse: {s}")


def clean_subnet(c, pid, body):
    try:
        net = ipaddress.ip_network(str(body.get("cidr") or "").strip(), strict=False)
    except ValueError:
        raise HTTPException(400, "Ungültiges Netz, Beispiel: 192.168.178.0/24")
    gw = _ip(body.get("gateway"), "gateway")
    if gw and gw not in net:
        raise HTTPException(400, "Das Gateway liegt nicht im Netz")
    ds, de = _ip(body.get("dhcp_start"), "dhcp_start"), _ip(body.get("dhcp_end"), "dhcp_end")
    if bool(ds) != bool(de):
        raise HTTPException(400, "Für den DHCP-Bereich Anfang und Ende angeben")
    if ds and (ds not in net or de not in net or int(ds) > int(de)):
        raise HTTPException(400, "Der DHCP-Bereich muss im Netz liegen und mit der kleineren Adresse beginnen")
    vlan_id = body.get("vlan_id") or None
    if vlan_id and not c.execute("SELECT 1 FROM vlans WHERE id=? AND profile_id=?", (int(vlan_id), pid)).fetchone():
        raise HTTPException(400, "VLAN gehört nicht zu diesem Profil")
    dns = []
    for part in str(body.get("dns") or "").replace(";", ",").split(","):
        if part.strip():
            dns.append(str(_ip(part, "dns")))
    return dict(cidr=str(net), name=str(body.get("name") or "").strip()[:120], gateway=str(gw) if gw else "", dns=", ".join(dns),
                dhcp_start=str(ds) if ds else "", dhcp_end=str(de) if de else "", vlan_id=int(vlan_id) if vlan_id else None,
                description=str(body.get("description") or "").strip()[:2000])


def clean_vlan(body):
    try:
        vid = int(body.get("vid"))
    except (TypeError, ValueError):
        vid = 0
    if not 1 <= vid <= 4094:
        raise HTTPException(400, "Die VLAN-ID muss zwischen 1 und 4094 liegen")
    return dict(vid=vid, name=str(body.get("name") or "").strip()[:80], description=str(body.get("description") or "").strip()[:2000])


def usable(net):
    if net.version == 4 and net.prefixlen <= 30:
        return net.num_addresses - 2
    return net.num_addresses


def host_range(net):
    if net.version == 4 and net.prefixlen <= 30:
        return int(net.network_address) + 1, int(net.broadcast_address) - 1
    return int(net.network_address), int(net.broadcast_address)


def _addrs(c, pid):
    out = []
    for r in c.execute("""SELECT a.*, d.name AS device_name, d.type AS device_type, i.mac
                          FROM ip_addresses a LEFT JOIN devices d ON d.id=a.device_id LEFT JOIN interfaces i ON i.id=a.interface_id
                          WHERE a.profile_id=?""", (pid,)):
        try:
            ip = ipaddress.ip_address(r["address"])
        except ValueError:
            continue
        out.append((ip, r))
    return out


def subnet_of(nets, ip):
    """Spezifischstes Subnetz, das die Adresse enthält."""
    best = None
    for sid, net in nets:
        if ip.version == net.version and ip in net and (best is None or net.prefixlen > best[1].prefixlen):
            best = (sid, net)
    return best[0] if best else None


def _subnets(c, pid):
    rows = c.execute("SELECT s.*, v.vid, v.name AS vlan_name FROM subnets s LEFT JOIN vlans v ON v.id=s.vlan_id WHERE s.profile_id=?", (pid,)).fetchall()
    return rows, [(r["id"], ipaddress.ip_network(r["cidr"])) for r in rows]


def list_subnets(c, pid):
    rows, nets = _subnets(c, pid)
    count = {}
    for ip, _ in _addrs(c, pid):
        sid = subnet_of(nets, ip)
        if sid:
            count.setdefault(sid, set()).add(ip)
    out = []
    for r in rows:
        net = ipaddress.ip_network(r["cidr"])
        dhcp = int(ipaddress.ip_address(r["dhcp_end"])) - int(ipaddress.ip_address(r["dhcp_start"])) + 1 if r["dhcp_start"] else 0
        out.append(dict(id=r["id"], cidr=r["cidr"], name=r["name"], gateway=r["gateway"], dns=r["dns"], dhcp_start=r["dhcp_start"],
                        dhcp_end=r["dhcp_end"], vlan_id=r["vlan_id"], vid=r["vid"], vlan_name=r["vlan_name"] or "", description=r["description"],
                        size=usable(net), used=len(count.get(r["id"], ())), dhcp_size=dhcp))
    return sorted(out, key=lambda s: (ipaddress.ip_network(s["cidr"]).version, ipaddress.ip_network(s["cidr"])))


def subnet_detail(c, pid, sid):
    r = c.execute("SELECT * FROM subnets WHERE id=? AND profile_id=?", (sid, pid)).fetchone()
    if not r:
        raise HTTPException(404, "Subnetz nicht gefunden")
    _, nets = _subnets(c, pid)
    net = ipaddress.ip_network(r["cidr"])
    ds = int(ipaddress.ip_address(r["dhcp_start"])) if r["dhcp_start"] else None
    de = int(ipaddress.ip_address(r["dhcp_end"])) if r["dhcp_end"] else None
    addrs = []
    for ip, a in _addrs(c, pid):
        if subnet_of(nets, ip) == sid:
            addrs.append(dict(address=str(ip), kind=a["kind"], device_id=a["device_id"], device_name=a["device_name"] or "",
                              device_type=a["device_type"] or "", mac=a["mac"] or "", in_dhcp=bool(ds is not None and ds <= int(ip) <= de),
                              gateway=str(ip) == r["gateway"]))
    addrs.sort(key=lambda x: int(ipaddress.ip_address(x["address"])))
    free = None
    if net.version == 4 and net.prefixlen >= FREE_LIST_MAX_PREFIX:
        lo, hi = host_range(net)
        taken = sorted({int(ipaddress.ip_address(a["address"])) for a in addrs} | ({int(ipaddress.ip_address(r["gateway"]))} if r["gateway"] else set()))
        free, cur = [], lo
        for t in taken + [hi + 1]:
            if t < lo:
                continue
            if t > cur:
                a, b = cur, min(t - 1, hi)
                if a <= b:
                    free.append(dict(start=str(ipaddress.ip_address(a)), end=str(ipaddress.ip_address(b)), count=b - a + 1,
                                     dhcp=bool(ds is not None and ds <= a and b <= de)))
            cur = max(cur, t + 1)
        # Bereiche an den Grenzen des DHCP-Pools teilen, damit „frei für statische Adressen“ sichtbar wird
        if ds is not None:
            split = []
            for f in free:
                a, b = int(ipaddress.ip_address(f["start"])), int(ipaddress.ip_address(f["end"]))
                for lo2, hi2, inside in ((a, min(b, ds - 1), False), (max(a, ds), min(b, de), True), (max(a, de + 1), b, False)):
                    if lo2 <= hi2:
                        split.append(dict(start=str(ipaddress.ip_address(lo2)), end=str(ipaddress.ip_address(hi2)), count=hi2 - lo2 + 1, dhcp=inside))
            free = split
    return dict(subnet=next(s for s in list_subnets(c, pid) if s["id"] == sid), addresses=addrs, free=free)


def conflicts(c, pid):
    """Strukturierte Hinweise; die Oberfläche formuliert sie (DE/EN)."""
    out = []
    rows, nets = _subnets(c, pid)
    by_sid = {r["id"]: r for r in rows}
    seen = {}
    for ip, a in _addrs(c, pid):
        seen.setdefault(str(ip), []).append(a)
        sid = subnet_of(nets, ip)
        if nets and sid is None:
            out.append(dict(level="warn", code="outside", ip=str(ip), device_id=a["device_id"], device=a["device_name"] or ""))
        elif sid and a["kind"] == "static":
            s = by_sid[sid]
            if s["dhcp_start"] and int(ipaddress.ip_address(s["dhcp_start"])) <= int(ip) <= int(ipaddress.ip_address(s["dhcp_end"])):
                out.append(dict(level="warn", code="in_dhcp", ip=str(ip), device_id=a["device_id"], device=a["device_name"] or "", subnet=s["cidr"]))
    for addr, lst in seen.items():
        devs = {x["device_id"] for x in lst}
        if len(devs) > 1:
            out.append(dict(level="err", code="dup_ip", ip=addr, devices=sorted({x["device_name"] or "" for x in lst})))
    macs = {}
    for r in c.execute("""SELECT i.mac, d.id, d.name FROM interfaces i JOIN devices d ON d.id=i.device_id
                          WHERE d.profile_id=? AND i.mac<>''""", (pid,)):
        macs.setdefault(r["mac"], {})[r["id"]] = r["name"]
    for mac, devs in macs.items():
        if len(devs) > 1:
            out.append(dict(level="err", code="dup_mac", mac=mac, devices=sorted(devs.values())))
    for i, (sa, na) in enumerate(nets):
        for sb, nb in nets[i + 1:]:
            if na.version == nb.version and na.overlaps(nb):
                out.append(dict(level="warn", code="overlap", a=str(na), b=str(nb)))
    order = {"err": 0, "warn": 1}
    return sorted(out, key=lambda x: (order[x["level"]], x["code"], x.get("ip", ""), x.get("mac", "")))
