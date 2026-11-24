"""MikroTik per SNMP (v2c oder v3, nur lesend) – liefert dieselben Rohdaten wie die RouterOS-API, damit
mikrotik.normalize() unverändert bleibt.

Quellen: IF-MIB (Schnittstellen, Tempo, Zähler, Alias), IP-MIB (eigene Adressen, ARP), BRIDGE-/Q-BRIDGE-MIB (welche
MAC an welchem Port), IP-FORWARD-MIB (Standardroute -> WAN), HOST-RESOURCES-MIB (CPU) und die MIKROTIK-MIB
(Enterprise 14988: Board, Version, Seriennummer, RouterBOOT, PoE, WLAN-Registrierungen, WLAN-SSIDs, Nachbarn).
Nicht per SNMP verfügbar: DHCP-Leases (Clients kommen dann aus ARP, Namen aus dem Netzscan) und Schaltaktionen.
"""
import re

from . import snmp, snmplib

IF_DESCR, IF_TYPE, IF_ADMIN, IF_OPER, IF_MAC = ("1.3.6.1.2.1.2.2.1.2", "1.3.6.1.2.1.2.2.1.3", "1.3.6.1.2.1.2.2.1.7", "1.3.6.1.2.1.2.2.1.8",
                                                 "1.3.6.1.2.1.2.2.1.6")
IF_NAME, IF_IN, IF_OUT, IF_SPEED, IF_ALIAS = snmp.IF_NAME, snmp.IF_IN, snmp.IF_OUT, snmp.IF_SPEED, snmp.IF_ALIAS
IP_ADDR = "1.3.6.1.2.1.4.20.1.1"
ARP_MAC, ARP_TYPE = "1.3.6.1.2.1.4.22.1.2", "1.3.6.1.2.1.4.22.1.4"
ROUTE_IF_OLD = "1.3.6.1.2.1.4.21.1.2.0.0.0.0"   # ipRouteIfIndex für 0.0.0.0
ROUTE_IF = "1.3.6.1.2.1.4.24.4.1.5"             # ipCidrRouteIfIndex (Index: Ziel.Maske.TOS.Nexthop)
CPU = "1.3.6.1.2.1.25.3.3.1.2"
MT = "1.3.6.1.4.1.14988.1.1"
MT_VERSION, MT_SERIAL, MT_FW, MT_FW_UP, MT_BOARD = f"{MT}.4.4.0", f"{MT}.7.3.0", f"{MT}.7.4.0", f"{MT}.7.7.0", f"{MT}.7.8.0"
MT_POE_NAME, MT_POE_STATUS = f"{MT}.15.1.1.2", f"{MT}.15.1.1.3"     # Index: ifIndex; Status 1 = aus
MT_RTAB_STRENGTH, MT_RTAB_TX, MT_RTAB_RX = f"{MT}.1.2.1.3", f"{MT}.1.2.1.4", f"{MT}.1.2.1.5"  # Index: MAC(6).ifIndex
MT_AP_SSID, MT_AP_BAND = f"{MT}.1.3.1.4", f"{MT}.1.3.1.8"            # Index: ifIndex
MT_NB_IP, MT_NB_MAC, MT_NB_PLATFORM, MT_NB_IDENTITY, MT_NB_IF = (f"{MT}.11.1.1.2", f"{MT}.11.1.1.3", f"{MT}.11.1.1.5", f"{MT}.11.1.1.6",
                                                                  f"{MT}.11.1.1.8")
PHYS = re.compile(r"^(ether|sfp|combo|qsfp|sfpplus|sfp28)", re.I)
WLAN = re.compile(r"^(wlan|wifi)", re.I)


def snmp_conf(conf):
    """Felder der MikroTik-Integration -> Zugangsdaten für den SNMP-Client."""
    return dict(host=conf["host"], port=conf.get("port") or 161, version=conf.get("snmp_version") or "v2c",
                password=conf.get("community") or "public", username=conf.get("snmp_user") or "",
                auth_proto=conf.get("auth_proto") or "SHA", auth_pass=conf.get("auth_pass") or "",
                priv_proto=conf.get("priv_proto") or "AES", priv_pass=conf.get("priv_pass") or "")


def _col(c, oid):
    try:
        return snmp._col(c, oid)
    except snmplib.SNMPError:
        return {}


def _txt(v):
    return snmplib.text(v) if v is not None else ""


def _mac(v):
    return snmplib.mac(v) if isinstance(v, (bytes, bytearray)) and len(v) == 6 else ""


def _uptime(ticks):
    s = int(ticks or 0) // 100
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return (f"{d}d" if d else "") + f"{h}h{m}m{s}s"


def collect(conf):
    """Rohdaten wie mikrotik.collect() (RouterOS-API) – nur aus SNMP."""
    from .controller import DriverError
    c = snmp._client(snmp_conf(conf))
    try:
        sysv = c.get(*snmp.SYS.values())
    except snmplib.SNMPError as ex:
        raise DriverError(str(ex))
    sysd = {k: sysv.get(o) for k, o in snmp.SYS.items()}
    names, descr, types = _col(c, IF_NAME), _col(c, IF_DESCR), _col(c, IF_TYPE)
    admin, oper, macs = _col(c, IF_ADMIN), _col(c, IF_OPER), _col(c, IF_MAC)
    hc_in, hc_out, speed, alias = _col(c, IF_IN), _col(c, IF_OUT), _col(c, IF_SPEED), _col(c, IF_ALIAS)
    ifname = {k: _txt(names.get(k)) or _txt(descr.get(k)) for k in types}

    def kind(k):
        n, t = ifname[k], types.get(k)
        if PHYS.match(n) and t == 6:
            return "ether"
        if WLAN.match(n) or t == 71:
            return "wlan"
        return "bridge" if t == 209 or n.startswith("bridge") else "other"

    interfaces = [{".id": k, "name": ifname[k], "type": kind(k), "mac-address": _mac(macs.get(k)), "running": "true" if oper.get(k) == 1 else "false",
                   "disabled": "true" if admin.get(k) == 2 else "false", "rx-byte": str(hc_in.get(k) or 0), "tx-byte": str(hc_out.get(k) or 0),
                   "comment": _txt(alias.get(k))} for k in sorted(types, key=lambda x: int(x))]
    ethernet = [{"name": ifname[k], "speed": f"{int(speed.get(k) or 0)}Mbps"} for k in types if kind(k) == "ether" and speed.get(k)]
    poe_status = _col(c, MT_POE_STATUS)
    poe = [{"name": _txt(n) or ifname.get(k, ""), "poe-out": "off" if poe_status.get(k) == 1 else "auto-on"} for k, n in _col(c, MT_POE_NAME).items()]
    addresses = [{"address": k + "/32"} for k in _col(c, IP_ADDR)]  # Index ist die Adresse selbst
    # ARP: Index ifIndex.a.b.c.d
    atype = _col(c, ARP_TYPE)
    arp = []
    for k, v in _col(c, ARP_MAC).items():
        parts = k.split(".")
        if len(parts) == 5 and _mac(v) and atype.get(k) != 2:
            arp.append({"address": ".".join(parts[1:]), "mac-address": _mac(v), "interface": ifname.get(parts[0], ""), "complete": "true"})
    # Bridge: MAC -> Port (Q-BRIDGE, sonst BRIDGE-MIB); Bridge-Port -> ifIndex
    bp = {k: str(v) for k, v in _col(c, snmp.BASE_PORT_IF).items() if isinstance(v, int)}
    hosts = []
    fdb = _col(c, snmp.QFDB_PORT)
    for idx, port in (fdb or _col(c, snmp.FDB_PORT)).items():
        parts = idx.split(".")
        if len(parts) >= 6 and port:
            mac = ":".join(f"{int(x):02X}" for x in parts[-6:])
            hosts.append({"mac-address": mac, "on-interface": ifname.get(bp.get(str(port), str(port)), ""), "local": "false"})
    # WLAN: SSID/Band je Schnittstelle, Registrierungen (Index MAC.ifIndex)
    ssid, band = _col(c, MT_AP_SSID), _col(c, MT_AP_BAND)
    wifi = [{".id": None, "name": ifname[k], "ssid": _txt(ssid.get(k)), "band": _txt(band.get(k)), "disabled": "true" if admin.get(k) == 2 else "false",
             "running": "true" if oper.get(k) == 1 else "false"} for k in types if kind(k) == "wlan"]
    strength, txb, rxb = _col(c, MT_RTAB_STRENGTH), _col(c, MT_RTAB_TX), _col(c, MT_RTAB_RX)
    registrations = []
    for idx, s in strength.items():
        parts = idx.split(".")
        if len(parts) == 7:
            registrations.append({"mac-address": ":".join(f"{int(x):02X}" for x in parts[:6]), "interface": ifname.get(parts[6], ""), "signal": str(s),
                                  **({"bytes": f"{txb[idx]},{rxb[idx]}"} if idx in txb and idx in rxb else {})})
    # Nachbarn (MNDP/LLDP/CDP)
    nb_if, nb_ip, nb_mac, nb_id, nb_pf = (_col(c, o) for o in (MT_NB_IF, MT_NB_IP, MT_NB_MAC, MT_NB_IDENTITY, MT_NB_PLATFORM))
    neighbors = [{"interface": ifname.get(str(nb_if.get(k)), ""), "address": _ip_val(nb_ip.get(k)), "mac-address": _mac(nb_mac.get(k)),
                  "identity": _txt(nb_id.get(k)), "platform": _txt(nb_pf.get(k))} for k in nb_if]
    # WAN: Schnittstelle der Standardroute
    wan_if = None
    try:
        wan_if = c.get(ROUTE_IF_OLD).get(ROUTE_IF_OLD)
    except snmplib.SNMPError:
        pass
    if not isinstance(wan_if, int):
        wan_if = next((v for k, v in _col(c, ROUTE_IF).items() if k.startswith("0.0.0.0.0.0.0.0.") and isinstance(v, int)), None)
    wan_members = [{"list": "WAN", "interface": ifname[str(wan_if)]}] if wan_if and str(wan_if) in ifname else []
    try:
        mt = c.get(MT_VERSION, MT_SERIAL, MT_FW, MT_FW_UP, MT_BOARD)
    except snmplib.SNMPError:
        mt = {}
    descr_s = _txt(sysd.get("descr"))
    board = _txt(mt.get(MT_BOARD)) or (descr_s.split(" ", 1)[1] if descr_s.startswith("RouterOS ") else descr_s)
    loads = [v for v in _col(c, CPU).values() if isinstance(v, int)]
    return dict(resource={"board-name": board, "version": _txt(mt.get(MT_VERSION)), "uptime": _uptime(sysd.get("uptime")),
                          "cpu-load": str(round(sum(loads) / len(loads))) if loads else None},
                identity={"name": _txt(sysd.get("name"))},
                routerboard={"model": board, "serial-number": _txt(mt.get(MT_SERIAL)), "current-firmware": _txt(mt.get(MT_FW)),
                             "upgrade-firmware": _txt(mt.get(MT_FW_UP))},
                interfaces=interfaces, ethernet=ethernet, poe=poe, addresses=addresses, leases=[], arp=arp, hosts=hosts, neighbors=neighbors,
                wan_members=wan_members, kid=[], wifi_menu=None, wifi=wifi, registrations=registrations)


def _ip_val(v):
    if isinstance(v, (bytes, bytearray)) and len(v) == 4:
        return ".".join(str(b) for b in v)
    return _txt(v)
