"""Treiber SNMP (v2c, nur lesen) für managed Switches, z. B. Zyxel XGS1935.

Liest System, Ports (Status, Tempo, Traffic aus 64-Bit-Zählern), gelernte MAC-Adressen je Port (Q-BRIDGE, sonst BRIDGE-MIB)
und LLDP-Nachbarn. Physische Ports sind die Ethernet-Schnittstellen in der Reihenfolge ihres ifIndex (Port 1, 2, …).
"""
import re
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
    dict(key="cfg_schedule", label="Konfiguration sichern", type="select", default="weekly", options=[
        ["weekly", "wöchentlich"], ["daily", "täglich"], ["no", "nein"]]),
    dict(key="ssh_auth", label="SSH-Anmeldung (für Konfigurations-Backup)", type="select", default="password", options=[
        ["password", "Benutzer und Passwort"], ["key_diktyo", "Schlüssel von díktyo"], ["key_own", "eigener privater Schlüssel"]]),
    dict(key="ssh_user", label="SSH-Benutzer", type="text", default="", placeholder="z. B. admin"),
    dict(key="ssh_pass", label="SSH-Passwort", type="password", default="", secret=True, show=dict(ssh_auth="password")),
    dict(key="ssh_pub", label="Öffentlicher Schlüssel von díktyo (auf das Gerät laden)", type="sshpub", default="", show=dict(ssh_auth="key_diktyo"), wide=True),
    dict(key="ssh_key", label="Privater Schlüssel (Inhalt der Datei, z. B. id_rsa)", type="textarea", default="", secret=True, show=dict(ssh_auth="key_own"), wide=True,
         placeholder="-----BEGIN OPENSSH PRIVATE KEY----- …"),
    dict(key="ssh_key_pass", label="Passphrase des Schlüssels (falls vergeben)", type="password", default="", secret=True, show=dict(ssh_auth="key_own")),
    dict(key="ssh_port", label="SSH-Port", type="number", default=22),
    dict(key="ssh_mode", label="Abruf", type="select", default="auto", options=[
        ["auto", "automatisch"], ["exec", "Einzelbefehl (ssh … \"Befehl\")"], ["shell", "interaktive Sitzung (mit Blättern bei -- More --)"]]),
    dict(key="ssh_command", label="Befehl für die Konfiguration", type="text", default="show running-config"),
]
CAN_BACKUP = True
SYS = {"descr": "1.3.6.1.2.1.1.1.0", "object_id": "1.3.6.1.2.1.1.2.0", "uptime": "1.3.6.1.2.1.1.3.0", "name": "1.3.6.1.2.1.1.5.0",
       "location": "1.3.6.1.2.1.1.6.0"}
IF_DESCR, IF_TYPE, IF_OPER = "1.3.6.1.2.1.2.2.1.2", "1.3.6.1.2.1.2.2.1.3", "1.3.6.1.2.1.2.2.1.8"
IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"                 # ifAdminStatus: 1 up, 2 down
POE_ADMIN = "1.3.6.1.2.1.105.1.1.1.3"            # POWER-ETHERNET-MIB pethPsePortAdminEnable.<gruppe>.<port>: 1 an, 2 aus
IF_NAME, IF_IN, IF_OUT, IF_SPEED, IF_ALIAS = ("1.3.6.1.2.1.31.1.1.1.1", "1.3.6.1.2.1.31.1.1.1.6", "1.3.6.1.2.1.31.1.1.1.10",
                                               "1.3.6.1.2.1.31.1.1.1.15", "1.3.6.1.2.1.31.1.1.1.18")
BASE_PORT_IF = "1.3.6.1.2.1.17.1.4.1.2"
QFDB_PORT, FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2", "1.3.6.1.2.1.17.4.3.1.2"
LLDP_NAME, LLDP_PORTID, LLDP_PORTDESC, LLDP_CHASSIS = ("1.0.8802.1.1.2.1.4.1.1.9", "1.0.8802.1.1.2.1.4.1.1.7",
                                                       "1.0.8802.1.1.2.1.4.1.1.8", "1.0.8802.1.1.2.1.4.1.1.5")
PHYS_TYPES = {6, 62, 69, 117}  # ethernetCsmacd, fastEther, fastEtherFX, gigabitEthernet
# Logische Schnittstellen, die manche Switches trotzdem als Ethernet melden (Trunk/LAG, VLAN, CPU, Management …)
LOGICAL = re.compile(r"trunk|\blag|port-?channel|^po\d|^ae\d|vlan|cpu|mgmt|management|loopback|bond|^br\d|tunnel|stack|null|internal", re.I)


def physical_ports(types, names, descr, bridge_ifs=(), expected=None):
    """Die echten Frontports: (ifIndex-Liste, ausgelassen [(ifIndex, Name, Grund)]).
    1. Typ Ethernet; 2. Name nicht logisch; 3. als Bridge-Port bekannt (falls die Tabelle da ist);
    4. höchstens so viele wie das Katalogmodell Ports hat (erste nach ifIndex)."""
    skipped = []
    name = lambda k: snmplib.text(names.get(k)) or snmplib.text(descr.get(k))  # noqa: E731
    cand = []
    for k, t in sorted(types.items(), key=lambda x: int(x[0])):
        if t not in PHYS_TYPES:
            continue
        if LOGICAL.search(name(k) or ""):
            skipped.append((int(k), name(k), "logische Schnittstelle"))
            continue
        cand.append(int(k))
    bridge = set(bridge_ifs or ())
    if bridge:
        inb = [i for i in cand if i in bridge]
        if len(inb) >= len(cand) / 2:  # nur anwenden, wenn die Tabelle plausibel ist
            skipped += [(i, name(str(i)), "kein Bridge-Port") for i in cand if i not in bridge]
            cand = inb
    if expected and len(cand) > expected:
        skipped += [(i, name(str(i)), f"mehr als die {expected} Ports des Katalogmodells") for i in cand[expected:]]
        cand = cand[:expected]
    return cand, skipped


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


def backup(conf, state):
    """Laufende Konfiguration per SSH lesen (z. B. Zyxel, Cisco-artige CLI). Host-Schlüssel wird beim ersten Mal gemerkt."""
    from .. import sshcfg
    auth = conf.get("ssh_auth") or "password"
    if not conf.get("ssh_user"):
        raise DriverError("Für das Konfigurations-Backup den SSH-Benutzer des Switches angeben")
    if auth == "password" and not conf.get("ssh_pass"):
        raise DriverError("Für das Konfigurations-Backup SSH-Benutzer und -Passwort des Switches angeben – oder unter „SSH-Anmeldung“ einen Schlüssel wählen")
    try:
        pkey = None
        if auth == "key_diktyo":
            from ..db import db
            with db() as c:
                pkey, _ = sshcfg.own_key(c)
        elif auth == "key_own":
            pkey = sshcfg.load_key(conf.get("ssh_key"), conf.get("ssh_key_pass"))
        text, fp = sshcfg.run(conf["host"], int(conf.get("ssh_port") or 22), conf["ssh_user"], conf.get("ssh_pass") if pkey is None else None,
                              conf.get("ssh_command") or "show running-config", known=state.get("ssh_hostkey"), pkey=pkey,
                              mode=conf.get("ssh_mode") or "auto")
    except sshcfg.SSHError as ex:
        raise DriverError(str(ex))
    state["ssh_hostkey"] = fp
    return "running-config.txt", text.encode("utf-8"), True


def _source_ip(host, port=161):
    """Absenderadresse, die díktyo für den Weg zum Gerät benutzt (ohne etwas zu senden)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, port))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def _tcp_open(host, port, timeout=1.0):
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ping(host):
    import subprocess
    try:
        return subprocess.run(["ping", "-c", "1", "-W", "1", host], capture_output=True, timeout=4).returncode == 0
    except Exception:
        return None


def diagnose(conf, nat_hint=None):
    """Schritt für Schritt prüfen, woran der SNMP-Zugriff scheitert. -> dict(steps=[...], summary)
    nat_hint = (ip, name) eines Routers zwischen díktyo und Gerät (aus dem Bestand ermittelt), falls bekannt."""
    import ipaddress
    from ..scan import netinfo
    host, port = conf["host"], int(conf.get("port") or 161)
    steps = []

    def step(ok, title, detail=""):
        steps.append(dict(ok=ok, title=title, detail=detail))

    # 1. Netzweg
    src = _source_ip(host, port)
    local = netinfo.interfaces()
    try:
        tgt = ipaddress.ip_address(host)
        direct = next((i for i in local if tgt in ipaddress.ip_network(i["cidr"])), None)
    except ValueError:
        tgt, direct = None, None
    if direct:
        step(True, "Netzweg: direkt im selben Netz", f"díktyo erreicht {host} über {direct['ifname']} ({direct['ip']}). Der Switch sieht als Absender {direct['ip']}.")
        sender = direct["ip"]
    else:
        gw = netinfo.default_gateway()
        nat = f"{nat_hint[0]} ({nat_hint[1]})" if nat_hint else "die WAN-Adresse des Routers dazwischen"
        step(None, "Netzweg: über einen Router", f"{host} liegt nicht in einem Netz von díktyo (eigene Adresse {src or '?'}), der Weg führt über {gw or 'das Gateway'}. "
             f"Macht der Router NAT, sieht der Switch als Absender nicht {src or 'díktyo'}, sondern {nat}. Genau diese Adresse muss am Switch erlaubt sein.")
        sender = nat_hint[0] if nat_hint else ""
    # 2. Erreichbarkeit
    ping = _ping(host)
    mgmt = [p for p in (443, 80, 22, 23) if _tcp_open(host, p)]
    if ping or mgmt:
        step(True, "Gerät erreichbar", ("antwortet auf Ping" if ping else "kein Ping") + (f", offene Verwaltungs-Ports: {', '.join(map(str, mgmt))}" if mgmt else ""))
    else:
        step(False, "Gerät nicht erreichbar", "Weder Ping noch Weboberfläche/SSH antworten – Adresse und Netzweg prüfen.")
    # 3. Antwortet der SNMP-Dienst überhaupt? (v3-Discovery braucht keine Zugangsdaten)
    agent = None
    try:
        probe = snmplib.ClientV3(host, "diktyo-probe", None, "", None, "", port=port, timeout=2.0, retries=1)
        probe._discover()
        agent = True
        step(True, "SNMP-Dienst antwortet", f"Engine-ID {probe.engine_id.hex()} – Filter (Service Access / Trusted Hosts) lassen díktyo durch.")
    except snmplib.SNMPError:
        agent = False if conf.get("version") == "v3" else None
        if conf.get("version") == "v3":
            step(False, "SNMP-Dienst antwortet nicht",
                 "Keine Antwort auf die SNMPv3-Anfrage. Der Switch verwirft die Pakete: SNMP unter Service Access nicht erlaubt, "
                 f"oder Trusted Hosts/Secured Client enthält {sender or 'die Absenderadresse'} nicht. Danach am Switch mit Save speichern.")
        else:
            step(None, "SNMPv3-Probe ohne Antwort", "Bei v2c normal, wenn v3 am Switch aus ist – weiter mit der eigentlichen Abfrage.")
    except Exception as ex:  # unerwartete Antwort
        step(None, "SNMP-Probe uneindeutig", str(ex)[:120])
    # 4. Eigentliche Abfrage mit den Zugangsdaten
    try:
        r = _client(conf).get(SYS["descr"], SYS["name"])
        step(True, "Abfrage mit Zugangsdaten erfolgreich", f"{snmplib.text(r.get(SYS['name']))} · {snmplib.text(r.get(SYS['descr']))[:80]}")
        summary = "SNMP funktioniert."
        try:
            cl = _client(conf)
            types, names, descr = _col(cl, IF_TYPE), _col(cl, IF_NAME), _col(cl, IF_DESCR)
            bridge = {int(v) for v in _col(cl, BASE_PORT_IF).values() if isinstance(v, int)}
            phys, skipped = physical_ports(types, names, descr, bridge, conf.get("expected_ports"))
            other = sum(1 for t in types.values() if t not in PHYS_TYPES)
            step(True, "Schnittstellen", f"{len(phys)} Ports übernommen (ifIndex {phys[0] if phys else '–'}–{phys[-1] if phys else '–'}), "
                 f"{other} andere Schnittstellen" + ("; ausgelassen: " + "; ".join(f"ifIndex {i} „{n}“ ({g})" for i, n, g in skipped[:12]) if skipped else ""))
        except Exception as ex:  # nur Zusatzinfo
            step(None, "Schnittstellen", f"nicht lesbar: {ex}"[:160])
    except (snmplib.SNMPError, DriverError) as ex:
        msg = str(ex)
        if conf.get("version") != "v3" and "Keine Antwort" in msg:
            step(False, "Keine Antwort auf SNMPv2c",
                 "Ein Switch antwortet bei v2c auf eine falsche Community gar nicht – Community prüfen. Sonst wie bei v3: SNMP unter Service Access erlauben und "
                 f"{sender or 'die Absenderadresse'} als Trusted Host eintragen.")
        else:
            step(False, "Abfrage mit Zugangsdaten fehlgeschlagen", msg + (" – der Dienst antwortet, also liegt es an Benutzer, Passwörtern oder Verfahren (SHA/AES)." if agent else ""))
        if agent:
            summary = "Der Switch antwortet, aber die Anmeldung passt nicht: Benutzer, Auth-/Privacy-Passwort und Verfahren vergleichen."
        elif not direct:
            summary = (f"Der Switch lässt díktyo nicht durch. Am Switch die Adresse {sender} erlauben (Trusted Host) – oder díktyo eine Netzwerkkarte im Netz des Switches geben."
                       if sender else "Der Switch lässt díktyo nicht durch. Am Switch die WAN-Adresse des Routers zwischen díktyo und Switch erlauben – oder díktyo eine Netzwerkkarte im Netz des Switches geben.")
        else:
            summary = "Der Switch lässt díktyo nicht durch: SNMP unter Service Access erlauben und díktyos Adresse als Trusted Host eintragen."
    return dict(steps=steps, summary=summary, source=src, sender=sender)


def action(conf, state, kind, params):
    """Schaltaktion am Switch. kind: port (ifindex, up) | poe_cycle (port_no). -> Meldung"""
    import time as _t
    c = _client(conf)
    try:
        if kind == "port":
            c.set_int(f"{IF_ADMIN}.{int(params['ifindex'])}", 1 if params["up"] else 2)
            return f"Port {params['port_no']} {'eingeschaltet' if params['up'] else 'abgeschaltet'}"
        if kind == "poe_cycle":
            oid = f"{POE_ADMIN}.1.{int(params['port_no'])}"
            c.set_int(oid, 2)
            _t.sleep(5)
            c.set_int(oid, 1)
            return f"PoE an Port {params['port_no']} aus- und wieder eingeschaltet"
    except snmplib.SNMPError as ex:
        msg = str(ex)
        if "Schreib" in msg or "Keine Antwort" in msg:
            msg += (" – Zyxel: unter Management → Access Control → SNMP den Benutzer einer Gruppe mit Schreibrechten (z. B. „admin“) "
                    "zuordnen bzw. eine Community mit read-write anlegen, dann Save.")
        raise DriverError(msg)
    raise DriverError(f"Unbekannte Aktion {kind}")


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
    admin = _col(c, IF_ADMIN)
    try:
        poe = {k: v for k, v in _col(c, POE_ADMIN).items() if k.startswith("1.")}  # Gruppe 1 = Ports des Switches
    except Exception:
        poe = {}
    names, descr = _col(c, IF_NAME), _col(c, IF_DESCR)
    speed, alias = _col(c, IF_SPEED), _col(c, IF_ALIAS)
    hc_in, hc_out = _col(c, IF_IN), _col(c, IF_OUT)
    try:
        bridge_ifs = {int(v) for v in _col(c, BASE_PORT_IF).values() if isinstance(v, int)}
    except Exception:
        bridge_ifs = set()
    phys, skipped = physical_ports(types, names, descr, bridge_ifs, conf.get("expected_ports"))
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
                          oper="up" if oper.get(k) == 1 else "down", admin="down" if admin.get(k) == 2 else "up",
                          poe=None if f"1.{no}" not in poe else poe[f"1.{no}"] == 1,
                          speed=int(speed.get(k) or 0), in_bps=in_bps, out_bps=out_bps, macs=[], lldp=None))
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
