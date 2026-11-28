"""Gemeinsame Hilfen für Controller-Treiber (Omada, UniFi).

Einheitliches Ergebnis von poll():
  info    = dict(controller, version, sites=[...])
  devices = [dict(mac, ip, name, model, type ("router"|"switch"|"ap"), online, uplink_mac, uplink_port, clients, ports=[...])]
            ports = [dict(port_no, oper ("up"|"down"|""), speed, kind, in_bps, out_bps, macs, lldp)]
  clients = [dict(mac, ip, name, online, medium ("lan"|"wlan"), parent_mac, port, band, ssid, vendor)]
  wan     = dict(mac, connected, rx_bps, tx_bps) oder fehlt
"""
import re


class DriverError(Exception):
    pass


def mac(v):
    """'aa-bb-cc-dd-ee-ff' / 'aabb.ccdd.eeff' -> 'AA:BB:CC:DD:EE:FF'"""
    h = re.sub(r"[^0-9A-Fa-f]", "", str(v or ""))
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)).upper() if len(h) == 12 else ""


def vid_list(v):
    """VLAN-IDs aus "10", "10,20", "10-12", [10, "20"] -> sortierte Liste gültiger IDs (1–4094)."""
    out = set()
    for part in (v if isinstance(v, (list, tuple, set)) else str(v or "").replace(";", ",").split(",")):
        s = str(part).strip()
        if "-" in s:
            a, _, b = s.partition("-")
            if a.strip().isdigit() and b.strip().isdigit() and int(b) - int(a) <= 4094:
                out.update(range(int(a), int(b) + 1))
        elif s.isdigit():
            out.add(int(s))
    return sorted(x for x in out if 1 <= x <= 4094)


def vlan_result(names, members):
    """Einheitliches VLAN-Ergebnis wie beim SNMP-Switch.
    names = {vid: name}, members = {port_no: dict(untagged=vid|None, tagged=set)} -> dict(vlans, ports) oder None"""
    ports = {}
    for no, m in members.items():
        u = m.get("untagged")
        t = sorted(set(m.get("tagged") or ()) - {u})
        if u or t:
            ports[int(no)] = dict(untagged=u, tagged=t)
    if not ports:
        return None
    used = {v for p in ports.values() for v in ([p["untagged"]] if p["untagged"] else []) + p["tagged"]}
    return dict(vlans=[dict(vid=v, name=(names.get(v) or "")[:80]) for v in sorted(used | set(names))], ports=ports)


def port_groups(ports):
    """Ports eines Geräts (port_no, kind, speed) -> Port-Gruppen wie im Katalog."""
    groups = []
    for p in sorted(ports, key=lambda x: x["port_no"]):
        key = (p.get("kind") or "rj45", p.get("max_speed") or "")
        if groups and (groups[-1]["kind"], groups[-1]["speed"]) == key:
            groups[-1]["count"] += 1
        else:
            groups.append(dict(count=1, kind=key[0], speed=key[1]))
    return groups


def speed_text(mbps):
    if not mbps:
        return ""
    return f"{mbps // 1000}G" if mbps >= 1000 and mbps % 1000 == 0 else (f"{mbps / 1000:g}G" if mbps >= 1000 else f"{mbps}M")


def counter_rates(items, prev, now, key="mac"):
    """Live-Raten je Client aus kumulativen Byte-Zählern.

    items: Einträge mit _down/_up (Bytes aus Sicht des Clients, steigen bis zum Neustart). Setzt down_bps/up_bps, sobald ein
    vorheriger Wert da ist, und entfernt die Zähler aus dem Ergebnis. Gibt die neuen Zähler {key: [down, up, ts]} zurück."""
    out = {}
    for x in items:
        d, u = x.pop("_down", None), x.pop("_up", None)
        k = x.get(key)
        if d is None or u is None or not k:
            continue
        try:
            d, u = int(d), int(u)
        except (TypeError, ValueError):
            continue
        p = prev.get(str(k))
        if p and now > p[2] and d >= p[0] and u >= p[1] and now - p[2] < 3600:
            dt = now - p[2]
            x["down_bps"], x["up_bps"] = round((d - p[0]) * 8 / dt), round((u - p[1]) * 8 / dt)
        out[str(k)] = [d, u, now]
    return out


def parse_rate(v):
    """'1.5Mbps' / '800kbps' / '1200' -> bit/s (int) oder None."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([kMG]?)(?:bps|bit/s)?\s*", str(v or ""))
    if not m:
        return None
    return round(float(m.group(1)) * {"": 1, "k": 1e3, "M": 1e6, "G": 1e9}[m.group(2)])


# ------------------------------------------------------------ Portfreigaben (alle Router-Treiber)
def proto_name(v):
    """„tcp“, „tcp udp“, „tcp_udp“, „BOTH“, „6“ … -> „TCP“, „UDP“, „TCP/UDP“ oder der Wert in Großbuchstaben."""
    s = str(v or "").lower()
    if isinstance(v, (list, tuple)):
        s = " ".join(str(x).lower() for x in v)
    if s in ("both", "tcpudp", "tcp_udp", "tcp/udp", "tcp+udp") or ("tcp" in s and "udp" in s):
        return "TCP/UDP"
    if s in ("6", "tcp"):
        return "TCP"
    if s in ("17", "udp"):
        return "UDP"
    return s.upper() if s else "TCP/UDP"


def _ports(v):
    s = str(v if v is not None else "").strip().replace(":", "-").replace(" ", "")
    return s if s and s.lower() not in ("any", "all", "0") else ""


def forward(kind, proto, ext, ip, port="", desc="", enabled=True, remote="", lease=None):
    """Eine Portfreigabe im gemeinsamen Format: kind „static“ (eingerichtet), „upnp“ (vom Gerät selbst angelegt) oder „“
    (unbekannt); ext/port als Text (auch Bereich „8000-8010“ oder Liste); ext „“ = alle Ports."""
    try:
        lease = int(lease) if lease not in (None, "") and int(lease) > 0 else None
    except (TypeError, ValueError):
        lease = None
    ext = _ports(ext)
    return dict(kind=kind, proto=proto_name(proto), ext=ext, ip=str(ip or "").strip(), port=_ports(port) or ext,
                desc=str(desc or "").strip()[:120], enabled=bool(enabled), remote="" if str(remote or "").lower() in ("any", "0.0.0.0/0") else str(remote or "").strip(),
                lease=lease)
