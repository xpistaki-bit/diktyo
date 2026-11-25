"""Treiber OPNsense (Firewall/Router) über die offizielle REST-API (API-Schlüssel + Secret, Basic-Auth).

Liest: System (Name, Version, Firmware-Update), Schnittstellen (Status, Adressen, Traffic), ARP-Tabelle und DHCP-Leases
(Kea, Dnsmasq oder ISC), WAN-Status und -Traffic. Konfigurations-Backup über /api/core/backup/download/this (config.xml).
Schalten: Internetzugang je Gerät über einen Firewall-Alias (den der Nutzer in einer Block-Regel verwendet), Neustart.

Endpunkte nach der OPNsense-API-Dokumentation und den von der Home-Assistant-Integration genutzten Pfaden.
"""
import re
import time

import httpx

from .controller import DriverError, mac as norm_mac, vid_list, vlan_result

NAME = "OPNsense"
DEFAULT_INTERVAL = 60
FIELDS = [
    dict(key="host", label="Adresse", type="text", default="", required=True, placeholder="z. B. 192.168.1.1"),
    dict(key="port", label="Port", type="number", default=443),
    dict(key="username", label="API-Schlüssel (Key)", type="text", default="", required=True),
    dict(key="password", label="API-Secret", type="password", default="", secret=True),
    dict(key="block_alias", label="Alias für Internetsperre (optional)", type="text", default="", placeholder="z. B. diktyo_block"),
    dict(key="cfg_schedule", label="Konfiguration sichern", type="select", default="weekly", options=[
        ["weekly", "wöchentlich"], ["daily", "täglich"], ["no", "nein"]]),
]
CAN_BACKUP = True
LEASES = ("kea/leases4/search", "dnsmasq/leases/search", "dhcpv4/leases/search_lease")


def _client(conf):
    return httpx.Client(base_url=f'https://{conf["host"]}:{int(conf.get("port") or 443)}/api', auth=(conf.get("username") or "", conf.get("password") or ""),
                        verify=False, timeout=20)


def _req(cl, method, path, optional=False, **kw):
    try:
        r = cl.request(method, "/" + path, **kw)
    except httpx.HTTPError as ex:
        raise DriverError(f"OPNsense nicht erreichbar: {ex}")
    if r.status_code == 401:
        raise DriverError("API-Schlüssel oder Secret falsch (System → Zugang → Benutzer → API-Schlüssel)")
    if r.status_code == 403:
        if optional:
            return None
        raise DriverError(f"Keine Berechtigung für {path} – dem Benutzer die passenden Rechte geben (siehe Anleitung)")
    if r.status_code in (400, 404) and optional:
        return None
    if r.status_code >= 400:
        raise DriverError(f"OPNsense meldet Fehler {r.status_code} bei {path}")
    if "json" not in r.headers.get("content-type", "") and optional:
        return None
    try:
        return r.json()
    except ValueError:
        if optional:
            return None
        raise DriverError("Unerwartete Antwort – ist das die OPNsense-API?")


def _rows(j):
    if isinstance(j, dict):
        return j.get("rows") if isinstance(j.get("rows"), list) else []
    return j if isinstance(j, list) else []


def collect(conf, state):
    with _client(conf) as cl:
        out = dict(firmware=_req(cl, "GET", "core/firmware/status", optional=True) or {},
                   sysinfo=_req(cl, "GET", "diagnostics/system/system_information", optional=True) or {},
                   interfaces=_req(cl, "GET", "interfaces/overview/export", optional=True),
                   arp=_rows(_req(cl, "GET", "diagnostics/interface/search_arp?resolve=no", optional=True)),
                   vlans=_rows(_req(cl, "GET", "interfaces/vlan_settings/search_item", optional=True)),
                   leases=[])
        out["top"] = _req(cl, "GET", "diagnostics/traffic/top/" + ",".join(state.get("lan_ifs") or ["lan"]), optional=True) or {}
        if out["interfaces"] is None:  # Pflicht – sonst stimmt etwas mit Rechten oder Version nicht
            raise DriverError("Schnittstellen nicht lesbar (Recht „Status: Interfaces“ nötig, OPNsense 23.7 oder neuer)")
        for path in LEASES:
            rows = _rows(_req(cl, "GET", path, optional=True))
            if rows:
                out["leases"] = rows
                break
    return out


def _val(d, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return ""


def normalize(raw, state, now=None):
    now = now or time.time()
    fw_raw = raw["firmware"] or {}
    prod = fw_raw.get("product") or {}
    si = raw["sysinfo"] or {}
    info = dict(name=si.get("name") or "", model="OPNsense", vendor="Deciso", version=prod.get("product_version") or "",
                uptime=si.get("uptime") or "")
    ifs = raw["interfaces"]
    ifs = list(ifs.values()) if isinstance(ifs, dict) else (ifs or [])
    prev = state.get("counters", {})
    counters, metrics, ports, wan = {}, {}, [], None
    addresses = []
    for n, i in enumerate([x for x in ifs if isinstance(x, dict) and x.get("identifier")], start=1):
        st = i.get("statistics") or {}
        rx = int(_val(st, "bytes received", "bytes_received", "inbytes") or 0)
        tx = int(_val(st, "bytes transmitted", "bytes_transmitted", "outbytes") or 0)
        key = i["identifier"]
        rate = None
        if key in prev and now > prev[key][2] and rx >= prev[key][0] and tx >= prev[key][1]:
            dt = now - prev[key][2]
            rate = (round((rx - prev[key][0]) * 8 / dt), round((tx - prev[key][1]) * 8 / dt))
            metrics[f"port:{n}:rx"], metrics[f"port:{n}:tx"] = rate
        counters[key] = (rx, tx, now)
        status = str(i.get("status") or "").lower()
        up = status in ("up", "associated")
        addr = str(i.get("addr4") or "")
        if addr:
            addresses.append(addr)
        ports.append(dict(port_no=n, iface=key, id=key, name=f'{i.get("description") or key.upper()} ({i.get("device") or ""})'.replace(" ()", ""),
                          alias=key, kind="rj45", oper="up" if up else "down", admin="down" if i.get("enabled") is False else "up", speed=0, poe=None,
                          in_bps=rate[0] if rate else None, out_bps=rate[1] if rate else None, macs=[], lldp=None, mac=norm_mac(i.get("macaddr")),
                          addr4=addr, device=str(i.get("device") or "")))
        if key == "wan":
            wan = dict(iface=key, mac=norm_mac(i.get("macaddr")), connected=up, rx_bps=rate[0] if rate else None, tx_bps=rate[1] if rate else None)
            if rate:
                metrics["wan:rx"], metrics["wan:tx"] = rate
    # Clients: Leases + ARP
    clients = {}
    for l in raw["leases"]:
        m = norm_mac(_val(l, "hwaddr", "mac", "hw_address"))
        ip = _val(l, "address", "ip_address", "ip")
        if not m or not ip:
            continue
        name = str(_val(l, "hostname", "client_hostname")).strip(".")
        clients[m] = dict(mac=m, ip=ip, name="" if name in ("*", "?") else name, online=True, iface=_val(l, "if_name", "if", "interface"))
    own = {p["mac"] for p in ports}
    for a in raw["arp"]:
        m = norm_mac(_val(a, "mac", "mac-address"))
        ip = _val(a, "ip", "ip-address")
        if not m or not ip or m in own or str(_val(a, "permanent")).lower() == "true":
            continue
        name = str(_val(a, "hostname")).strip().strip("?").strip()
        c = clients.setdefault(m, dict(mac=m, ip=ip, name=name, online=True, iface=_val(a, "intf", "interface")))
        c["online"] = True
        if name and not c["name"]:
            c["name"] = name
    out_clients = [dict(c, medium="lan", port=None, band="", signal="") for c in clients.values()]
    by_ip = {c["ip"]: c for c in out_clients}
    for _if, v in (raw.get("top") or {}).items():
        for t in (v.get("records") if isinstance(v, dict) else None) or []:
            c = by_ip.get(t.get("address"))
            if c and t.get("rate_bits_in") is not None:
                # aus Sicht der Firewall-Schnittstelle: „in“ kommt vom Host (Upload), „out“ geht zum Host (Download)
                c["down_bps"], c["up_bps"] = int(t.get("rate_bits_out") or 0), int(t.get("rate_bits_in") or 0)
    firmware = dict(installed=prod.get("product_version") or "", latest=(prod.get("product_latest") or "").replace("_", "."),
                    update=fw_raw.get("status") == "update" if fw_raw.get("status") in ("update", "none") else None,
                    info=f'https://github.com/opnsense/changelog' if fw_raw.get("status") == "update" else "")
    info["addresses"] = addresses
    res = dict(info=info, ports=ports, wifi=[], clients=out_clients, wan=wan, firmware=firmware, fdb_size=None)
    vl = vlans(raw.get("vlans") or [], ports)
    if vl:
        res["vlans"] = vl
    return res, metrics, counters


def vlans(rows, ports):
    """VLAN-Schnittstellen (Interfaces → Devices → VLAN): auf der Eltern-Schnittstelle tagged, die zugewiesene
    VLAN-Schnittstelle selbst gehört untagged zu ihrem VLAN. -> Ergebnis wie beim SNMP-Switch oder None"""
    by_dev = {p["device"]: p for p in ports if p.get("device")}
    names, members = {}, {}
    for r in rows:
        vid = vid_list(r.get("tag"))
        if not vid:
            continue
        vid = vid[0]
        dev = str(r.get("vlanif") or "")
        own = by_dev.get(dev)
        names.setdefault(vid, str(r.get("descr") or "") or (own["name"].split(" (")[0] if own else ""))
        parent = by_dev.get(str(r.get("if") or ""))
        if parent:
            members.setdefault(parent["port_no"], dict(untagged=None, tagged=set()))["tagged"].add(vid)
        if own:
            members.setdefault(own["port_no"], dict(untagged=None, tagged=set()))["untagged"] = vid
    return vlan_result(names, members)


def test(conf):
    raw = collect(conf, {})
    res, _, _ = normalize(raw, {})
    i = res["info"]
    return dict(name=i["name"], model="OPNsense", version=i["version"], ports=len(res["ports"]), clients=len(res["clients"]), wifi=0)


def poll(conf, state):
    raw = collect(conf, state)
    res, metrics, counters = normalize(raw, state)
    return res, metrics, dict(state, counters=counters)


def backup(conf, state):
    """config.xml über die API (OPNsense 23.1+)."""
    with _client(conf) as cl:
        try:
            r = cl.get("/core/backup/download/this")
        except httpx.HTTPError as ex:
            raise DriverError(f"OPNsense nicht erreichbar: {ex}")
    if r.status_code in (401, 403):
        raise DriverError("Keine Berechtigung für das Konfigurations-Backup (Recht „Diagnostics: Configuration History“ bzw. „Backup & Restore“)")
    if r.status_code >= 400 or b"<opnsense" not in r.content[:2000]:
        raise DriverError(f"OPNsense hat keine Konfiguration geliefert (HTTP {r.status_code})")
    text = re.sub(rb"<revision>.*?</revision>", b"<revision>(entfernt)</revision>", r.content, flags=re.S)  # wechselt bei jedem Speichern
    return "config-opnsense.xml", text, True


def action(conf, state, kind, params):
    """kind: internet (ip, block) über den Alias | reboot"""
    with _client(conf) as cl:
        if kind == "internet":
            alias = (conf.get("block_alias") or "").strip()
            if not alias:
                raise DriverError("Für die Internetsperre in der Integration einen Firewall-Alias eintragen (siehe Anleitung)")
            j = _req(cl, "POST", f"firewall/alias_util/{'add' if params['block'] else 'delete'}/{alias}", json={"address": params["ip"]})
            if isinstance(j, dict) and str(j.get("status", "done")).lower() not in ("done", "ok"):
                raise DriverError(f"OPNsense: Alias „{alias}“ nicht geändert ({j.get('status')}) – gibt es den Alias vom Typ „Host(s)“?")
            return f"Internet für {params['ip']} {'gesperrt' if params['block'] else 'freigegeben'} (Alias {alias})"
        if kind == "reboot":
            try:
                _req(cl, "POST", "core/system/reboot", json={})
            except DriverError as ex:
                if "nicht erreichbar" not in str(ex):
                    raise
            return "OPNsense startet neu (dauert einige Minuten)"
    raise DriverError(f"Unbekannte Aktion {kind}")
