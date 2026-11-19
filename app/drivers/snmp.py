"""Treiber SNMP (v2c, nur lesen) für managed Switches, z. B. Zyxel XGS1935.

Liest System, Ports (Status, Tempo, Traffic aus 64-Bit-Zählern), gelernte MAC-Adressen je Port (Q-BRIDGE, sonst BRIDGE-MIB)
und LLDP-Nachbarn. Physische Ports sind die Ethernet-Schnittstellen in der Reihenfolge ihres ifIndex (Port 1, 2, …).
"""
import time

from . import snmplib

NAME = "Switch (SNMP)"
DEFAULT_INTERVAL = 60
V3 = dict(version="v3")
FIELDS = [
    dict(key="host", label="Adresse", type="text", default="", required=True),
    dict(key="port", label="Port", type="number", default=161),
    dict(key="version", label="SNMP-Version", type="select", default="v2c", options=[["v2c", "v2c (Community)"], ["v3", "v3 (Benutzer)"]]),
    dict(key="password", label="Community", type="password", default="public", secret=True, show=dict(version="v2c")),
    dict(key="username", label="Benutzer", type="text", default="", show=V3),
    dict(key="auth_proto", label="Authentifizierung", type="select", default="SHA", options=[["SHA", "SHA (SHA-1)"], ["SHA-256", "SHA-256"], ["MD5", "MD5"]], show=V3),
    dict(key="auth_pass", label="Auth-Passwort", type="password", default="", secret=True, show=V3),
    dict(key="priv_proto", label="Verschlüsselung (Privacy)", type="select", default="AES", options=[["AES", "AES-128"], ["none", "keine"]], show=V3),
    dict(key="priv_pass", label="Privacy-Passwort", type="password", default="", secret=True, show=V3),
]
SYS = {"descr": "1.3.6.1.2.1.1.1.0", "object_id": "1.3.6.1.2.1.1.2.0", "uptime": "1.3.6.1.2.1.1.3.0", "name": "1.3.6.1.2.1.1.5.0",
       "location": "1.3.6.1.2.1.1.6.0"}
IF_DESCR, IF_TYPE, IF_OPER = "1.3.6.1.2.1.2.2.1.2", "1.3.6.1.2.1.2.2.1.3", "1.3.6.1.2.1.2.2.1.8"
IF_NAME, IF_IN, IF_OUT, IF_SPEED, IF_ALIAS = ("1.3.6.1.2.1.31.1.1.1.1", "1.3.6.1.2.1.31.1.1.1.6", "1.3.6.1.2.1.31.1.1.1.10",
                                               "1.3.6.1.2.1.31.1.1.1.15", "1.3.6.1.2.1.31.1.1.1.18")
BASE_PORT_IF = "1.3.6.1.2.1.17.1.4.1.2"
QFDB_PORT, FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2", "1.3.6.1.2.1.17.4.3.1.2"
LLDP_NAME, LLDP_PORTID, LLDP_PORTDESC, LLDP_CHASSIS = ("1.0.8802.1.1.2.1.4.1.1.9", "1.0.8802.1.1.2.1.4.1.1.7",
                                                       "1.0.8802.1.1.2.1.4.1.1.8", "1.0.8802.1.1.2.1.4.1.1.5")
PHYS_TYPES = {6, 62, 69, 117}  # ethernetCsmacd, fastEther, fastEtherFX, gigabitEthernet


class DriverError(Exception):
    pass


def _client(conf):
    port = int(conf.get("port") or 161)
    if conf.get("version") == "v3":
        if not conf.get("username"):
            raise DriverError("Für SNMPv3 einen Benutzer angeben")
        try:
            return snmplib.ClientV3(conf["host"], conf["username"], conf.get("auth_proto") or "SHA", conf.get("auth_pass") or "",
                                    "" if conf.get("priv_proto") == "none" else conf.get("priv_proto") or "AES", conf.get("priv_pass") or "",
                                    port, timeout=2.5, retries=1)
        except snmplib.SNMPError as ex:
            raise DriverError(str(ex))
    return snmplib.Client(conf["host"], conf.get("password") or "public", port, timeout=2.0, retries=1)


def _idx(oid, base):
    return oid[len(base) + 1:]


def _col(c, base):
    return {_idx(o, base): v for o, v in c.walk(base).items()}


def test(conf):
    try:
        r = _client(conf).get(SYS["descr"], SYS["name"])
    except snmplib.SNMPError as ex:
        raise DriverError(str(ex))
    return dict(name=snmplib.text(r.get(SYS["name"])), descr=snmplib.text(r.get(SYS["descr"]))[:120])


def poll(conf, state):
    c = _client(conf)
    try:
        sysv = c.get(*SYS.values())
    except snmplib.SNMPError as ex:
        raise DriverError(str(ex))
    info = {k: (snmplib.text(sysv.get(o)) if k != "uptime" else int(sysv.get(o) or 0) // 100) for k, o in SYS.items()}
    types, oper = _col(c, IF_TYPE), _col(c, IF_OPER)
    names, descr = _col(c, IF_NAME), _col(c, IF_DESCR)
    speed, alias = _col(c, IF_SPEED), _col(c, IF_ALIAS)
    hc_in, hc_out = _col(c, IF_IN), _col(c, IF_OUT)
    phys = sorted((int(i) for i, t in types.items() if t in PHYS_TYPES), key=int)
    now = time.time()
    prev = state.get("counters", {})
    counters, metrics, ports = {}, {}, []
    for no, ifi in enumerate(phys, start=1):
        k = str(ifi)
        cin, cout = hc_in.get(k), hc_out.get(k)
        in_bps = out_bps = None
        if cin is not None and k in prev and now > prev[k][2]:
            dt = now - prev[k][2]
            if cin >= prev[k][0] and cout >= prev[k][1]:  # Zählerüberlauf oder Neustart: Wert auslassen
                in_bps, out_bps = round((cin - prev[k][0]) * 8 / dt), round((cout - prev[k][1]) * 8 / dt)
                metrics[f"port:{no}:rx"], metrics[f"port:{no}:tx"] = in_bps, out_bps
        if cin is not None:
            counters[k] = (cin, cout, now)
        ports.append(dict(port_no=no, ifindex=ifi, name=snmplib.text(names.get(k)) or snmplib.text(descr.get(k)), alias=snmplib.text(alias.get(k)),
                          oper="up" if oper.get(k) == 1 else "down", speed=int(speed.get(k) or 0), in_bps=in_bps, out_bps=out_bps, macs=[], lldp=None))
    by_if = {p["ifindex"]: p for p in ports}
    # Bridge-Port -> ifIndex
    bp = {int(k): int(v) for k, v in _col(c, BASE_PORT_IF).items() if isinstance(v, int)}
    to_if = lambda b: bp.get(b, b)  # noqa: E731  ohne Tabelle sind Bridge-Port und ifIndex meist gleich
    fdb = _col(c, QFDB_PORT)
    entries = []
    if fdb:
        for idx, port in fdb.items():
            parts = idx.split(".")
            if len(parts) >= 7 and port:
                entries.append((":".join(f"{int(x):02X}" for x in parts[-6:]), int(port), int(parts[0])))
    else:
        for idx, port in _col(c, FDB_PORT).items():
            parts = idx.split(".")
            if len(parts) == 6 and port:
                entries.append((":".join(f"{int(x):02X}" for x in parts), int(port), None))
    for mac, b, vlan in entries:
        p = by_if.get(to_if(b))
        if p and mac not in p["macs"]:
            p["macs"].append(mac)
    # LLDP: Index = timeMark.localPort.remIndex
    lname, lpid, lpdesc, lch = _col(c, LLDP_NAME), _col(c, LLDP_PORTID), _col(c, LLDP_PORTDESC), _col(c, LLDP_CHASSIS)
    for idx, v in lname.items():
        parts = idx.split(".")
        if len(parts) < 3:
            continue
        lp = int(parts[1])
        p = by_if.get(to_if(lp)) or next((x for x in ports if x["port_no"] == lp), None)
        if p:
            ch = lch.get(idx)
            p["lldp"] = dict(name=snmplib.text(v), port=snmplib.text(lpdesc.get(idx)) or snmplib.text(lpid.get(idx)),
                             chassis=snmplib.mac(ch) if isinstance(ch, bytes) and len(ch) == 6 else snmplib.text(ch))
    res = dict(info=info, ports=ports, fdb_size=len(entries))
    return res, metrics, dict(counters=counters)
