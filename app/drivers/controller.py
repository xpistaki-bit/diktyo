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
