"""Treiber MikroTik RouterOS 6 und 7 (hAP, hEX, RB2011, RB5009, CRS-Switches, cAP, Chateau …) über die RouterOS-API oder REST.

Liest: Modell und Version, Ports (Link, Tempo, Traffic, PoE), DHCP-Leases und ARP (Clients mit IP, MAC, Name), die
Bridge-Host-Tabelle (welches Gerät an welchem Port bzw. WLAN hängt), WLAN-Clients (Paket „wifi“, „wifiwave2“ oder
„wireless“) und Nachbarn per MNDP/LLDP/CDP; dazu WAN-Status und -Traffic (Interface-Liste „WAN“).
Schalten: Port aus/ein, PoE neu starten, WLAN aus/ein, Wake-on-LAN, Neustart.

Zugang (Standard): RouterOS-API, Dienst „api“ (Port 8728) bzw. „api-ssl“ (8729, mit TLS) – RouterOS 6 und 7, Benutzer
mit den Rechten read und api (für Aktionen zusätzlich write, reboot, test). Alternativ REST (RouterOS 7.1+, Dienst
www-ssl bzw. www ab 7.9, Recht rest-api). Menüpfade und Felder sind bei beiden gleich. Ein Konfigurations-Backup macht
díktyo bei MikroTik nicht – RouterOS hat dafür eigene Backups (auch in die MikroTik-Cloud).
"""
import re
import time

import httpx

from . import mikrotik_snmp, routeros_api
from .controller import DriverError, counter_rates, parse_rate, mac as norm_mac, vid_list, vlan_result

NAME = "MikroTik (RouterOS)"
DEFAULT_INTERVAL = 60
LOGIN = dict(access=["api", "api-ssl", "https", "http"])
FIELDS = [
    dict(key="host", label="Adresse", type="text", default="192.168.88.1", required=True),
    dict(key="access", label="Zugang", type="select", default="api", options=[
        ["api", "RouterOS-API (api, Port 8728)"], ["api-ssl", "RouterOS-API mit TLS (api-ssl, Port 8729)"],
        ["snmp", "SNMP (v2c oder v3, nur lesen)"],
        ["https", "REST über HTTPS (www-ssl, RouterOS 7)"], ["http", "REST über HTTP (www, RouterOS 7.9+)"]]),
    dict(key="port", label="Port (leer = Standard des Zugangs)", type="number", default=""),
    dict(key="username", label="Benutzer", type="text", default="diktyo", show=LOGIN),
    dict(key="password", label="Passwort", type="password", default="", secret=True, show=LOGIN),
    dict(key="snmp_version", label="SNMP-Version", type="select", default="v2c", options=[["v2c", "v2c (Community)"], ["v3", "v3 (Benutzer)"]],
         show=dict(access="snmp")),
    dict(key="community", label="Community", type="password", default="public", secret=True, show=dict(access="snmp", snmp_version="v2c")),
    dict(key="snmp_user", label="SNMP-Benutzer", type="text", default="", show=dict(access="snmp", snmp_version="v3")),
    dict(key="auth_proto", label="Authentifizierung", type="select", default="SHA", options=[["SHA", "SHA (SHA-1)"], ["SHA-256", "SHA-256"], ["MD5", "MD5"]],
         show=dict(access="snmp", snmp_version="v3")),
    dict(key="auth_pass", label="Auth-Passwort", type="password", default="", secret=True, show=dict(access="snmp", snmp_version="v3")),
    dict(key="priv_proto", label="Verschlüsselung (Privacy)", type="select", default="AES", options=[["AES", "AES-128"], ["none", "keine"]],
         show=dict(access="snmp", snmp_version="v3")),
    dict(key="priv_pass", label="Privacy-Passwort", type="password", default="", secret=True, show=dict(access="snmp", snmp_version="v3")),
]
CAN_BACKUP = False
DEFAULT_PORT = {"api": 8728, "api-ssl": 8729, "snmp": 161, "https": 443, "http": 80}
WIFI_MENUS = ("interface/wifi", "interface/wifiwave2", "interface/wireless")


def access_of(conf):
    """Zugang aus der Einstellung; ältere Integrationen hatten nur „scheme“ (REST). Port 8728/8729 heißt immer API."""
    a = conf.get("access")
    if a in DEFAULT_PORT:
        return a
    port = str(conf.get("port") or "")
    if port == "161":
        return "snmp"
    if port == "8728":
        return "api"
    if port == "8729":
        return "api-ssl"
    if conf.get("scheme") in ("https", "http"):
        return conf["scheme"]
    return "api" if "access" in conf else "https"  # vor 0.33.1 angelegt: REST über HTTPS war der Standard


def _port(conf):
    try:
        return int(conf.get("port") or 0) or DEFAULT_PORT[access_of(conf)]
    except (TypeError, ValueError):
        return DEFAULT_PORT[access_of(conf)]


def _base(conf):
    scheme = access_of(conf)
    return f"{scheme}://{conf['host']}:{_port(conf)}/rest"


class _Conn:
    """Einheitlicher Zugang: RouterOS-API oder REST, jeweils mit request(method, path, optional, json)."""

    def __init__(self, conf, http=None, api=None):
        self.access = access_of(conf)
        user, pw = conf.get("username") or "admin", conf.get("password") or ""
        if http or api:  # für Tests: fertiger Client
            self.http, self.api = http, api
        elif self.access in ("api", "api-ssl"):
            try:
                self.api = routeros_api.Client(conf["host"], _port(conf), user, pw, use_ssl=self.access == "api-ssl")
            except routeros_api.APIError as ex:
                raise _api_error(ex, conf)
            self.http = None
        else:
            self.api = None
            self.http = httpx.Client(base_url=_base(conf), auth=(user, pw), verify=False, timeout=15, headers={"Content-Type": "application/json"})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        (self.api or self.http).close()


def _api_error(ex, conf=None):
    kind, _, msg = str(ex).partition(":")
    port = _port(conf) if conf else 8728
    if kind == "connect":
        return DriverError(f"MikroTik nicht erreichbar auf Port {port} ({msg}) – ist der Dienst api bzw. api-ssl unter IP → Services eingeschaltet "
                           "und für díktyo freigegeben (Available From)?")
    if kind == "tls":
        return DriverError("TLS-Verbindung fehlgeschlagen – für api-ssl braucht der MikroTik ein Zertifikat (IP → Services → api-ssl → Certificate) "
                           "oder „RouterOS-API“ ohne TLS wählen")
    if kind == "auth":
        return DriverError("Anmeldung abgelehnt (Benutzer/Passwort prüfen; die Benutzergruppe braucht die Rechte read und api)")
    if kind == "trap" and "permission" in msg:
        return DriverError("Keine Berechtigung – die Benutzergruppe braucht für diese Funktion zusätzliche Rechte (z. B. write, reboot, test)")
    if kind == "io":
        return DriverError(f"Verbindung zum MikroTik abgebrochen ({msg})")
    return DriverError(f"MikroTik meldet Fehler: {msg or ex}"[:200])


def _client(conf):
    return _Conn(conf)


def _req(cl, method, path, optional=False, **kw):
    if cl.api:
        try:
            return cl.api.request(method, path, json=kw.get("json"))
        except routeros_api.NoSuchCommand:
            if optional:
                return None
            raise DriverError(f"Diese RouterOS-Version kennt „{path}“ nicht")
        except routeros_api.APIError as ex:
            if optional and str(ex).startswith("trap:"):
                return None
            raise _api_error(ex)
    try:
        r = cl.http.request(method, "/" + path, **kw)
    except httpx.ConnectError as ex:
        if "WRONG_VERSION_NUMBER" in str(ex) or "wrong version number" in str(ex):
            raise DriverError("Am Port antwortet kein HTTPS-Dienst – für Port 8728 „RouterOS-API“ wählen, für den Dienst www „REST über HTTP“")
        raise DriverError(f"MikroTik nicht erreichbar ({ex}) – ist der Dienst www-ssl bzw. www unter IP → Services eingeschaltet?")
    except httpx.HTTPError as ex:
        raise DriverError(f"MikroTik nicht erreichbar: {ex}")
    if r.status_code == 401:
        raise DriverError("Anmeldung abgelehnt (Benutzer/Passwort prüfen; Gruppe braucht die Rechte read und rest-api)")
    if r.status_code == 403:
        raise DriverError("Keine Berechtigung – die Benutzergruppe braucht für diese Funktion zusätzliche Rechte (z. B. write, reboot, test)")
    if r.status_code in (400, 404) and optional:
        return None
    if r.status_code >= 400:
        try:
            j = r.json()
            msg = j.get("detail") or j.get("message") or r.text
        except ValueError:
            msg = r.text
        raise DriverError(f"MikroTik meldet Fehler {r.status_code}: {str(msg)[:160]}")
    if not r.content:
        return {}
    try:
        return r.json()
    except ValueError:
        raise DriverError("Unerwartete Antwort – ist das die REST-API von RouterOS 7? Sonst „RouterOS-API“ wählen")


def _get(cl, path, optional=False):
    return _req(cl, "GET", path, optional=optional)


def _bool(v):
    return str(v).lower() in ("true", "yes", "1")


def _natural(name):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name)]


def _speed(rate):
    """„1Gbps“, „2.5Gbps“, „100Mbps“ -> Mbit/s"""
    m = re.match(r"([\d.]+)\s*([GM])", str(rate or ""))
    if not m:
        return 0
    return int(float(m.group(1)) * (1000 if m.group(2) == "G" else 1))


def _kind(name, typ):
    if name.startswith(("sfp28", "qsfp")):
        return "sfp28"
    if name.startswith("sfp-sfpplus") or name.startswith("sfpplus"):
        return "sfp+"
    if name.startswith("sfp"):
        return "sfp"
    return "rj45"


def collect(conf, state):
    """Rohdaten holen – über die RouterOS-API, REST oder (nur lesend) SNMP."""
    if access_of(conf) == "snmp":
        return mikrotik_snmp.collect(dict(conf, port=_port(conf)))
    with _client(conf) as cl:
        out = dict(resource=_get(cl, "system/resource"), identity=_get(cl, "system/identity"),
                   routerboard=_get(cl, "system/routerboard", optional=True) or {},
                   interfaces=_get(cl, "interface") or [], ethernet=_get(cl, "interface/ethernet", optional=True) or [],
                   poe=_get(cl, "interface/ethernet/poe", optional=True) or [],
                   addresses=_get(cl, "ip/address", optional=True) or [], leases=_get(cl, "ip/dhcp-server/lease", optional=True) or [],
                   arp=_get(cl, "ip/arp", optional=True) or [], hosts=_get(cl, "interface/bridge/host", optional=True) or [],
                   neighbors=_get(cl, "ip/neighbor", optional=True) or [],
                   wan_members=[m for m in (_get(cl, "interface/list/member", optional=True) or []) if m.get("list") == "WAN"],
                   kid=_get(cl, "ip/kid-control/device", optional=True) or [],
                   bridges=_get(cl, "interface/bridge", optional=True) or [], bridge_vlans=_get(cl, "interface/bridge/vlan", optional=True) or [],
                   bridge_ports=_get(cl, "interface/bridge/port", optional=True) or [], vlan_ifaces=_get(cl, "interface/vlan", optional=True) or [])
        out["wifi_menu"], out["wifi"], out["registrations"] = None, [], []
        for menu in WIFI_MENUS:
            ifs = _get(cl, menu, optional=True)
            if ifs is not None:
                out["wifi_menu"], out["wifi"] = menu, ifs
                out["registrations"] = _get(cl, f"{menu}/registration-table", optional=True) or []
                break
    return out


def _members(v):
    return [x.strip() for x in (v if isinstance(v, list) else str(v or "").split(",")) if x.strip()]


def vlans(raw, ports):
    """VLANs je Port: Bridge-VLAN-Tabelle (nur bei Bridges mit vlan-filtering), PVID der Bridge-Ports und
    VLAN-Schnittstellen direkt auf einem Port (Router-on-a-stick). -> Ergebnis wie beim SNMP-Switch oder None"""
    by_iface = {p["iface"]: p["port_no"] for p in ports}
    filtering = {b.get("name") for b in raw.get("bridges") or [] if _bool(b.get("vlan-filtering"))}
    names, members = {}, {}
    m = lambda iface: members.setdefault(by_iface[iface], dict(untagged=None, tagged=set()))  # noqa: E731
    for v in raw.get("vlan_ifaces") or []:
        vid = vid_list(v.get("vlan-id"))
        if not vid:
            continue
        names.setdefault(vid[0], v.get("name") or "")
        if v.get("interface") in by_iface and not _bool(v.get("disabled")):
            m(v["interface"])["tagged"].add(vid[0])
    for e in raw.get("bridge_vlans") or []:
        if e.get("bridge") not in filtering or _bool(e.get("disabled")):
            continue
        vids = vid_list(e.get("vlan-ids"))
        tagged = set(_members(e.get("tagged"))) | set(_members(e.get("current-tagged")))
        untagged = set(_members(e.get("untagged"))) | set(_members(e.get("current-untagged")))
        for iface in tagged & set(by_iface):
            m(iface)["tagged"].update(vids)
        for iface in untagged & set(by_iface):
            if vids:
                m(iface)["untagged"] = m(iface)["untagged"] or vids[0]
    for bp in raw.get("bridge_ports") or []:
        iface = bp.get("interface")
        if bp.get("bridge") in filtering and iface in by_iface and bp.get("frame-types") != "admit-only-vlan-tagged":
            pvid = vid_list(bp.get("pvid") or "1")
            if pvid and not m(iface)["untagged"]:
                m(iface)["untagged"] = pvid[0]
    return vlan_result(names, members)


def normalize(raw, state, now=None):
    """-> (res, metrics, counters) im gemeinsamen Format (info, ports, clients, wifi, wan)."""
    now = now or time.time()
    res_ = raw["resource"] or {}
    info = dict(name=(raw["identity"] or {}).get("name", ""), model=res_.get("board-name") or (raw["routerboard"] or {}).get("model", ""),
                version=res_.get("version", ""), uptime=res_.get("uptime", ""), cpu=res_.get("cpu-load"),
                serial=(raw["routerboard"] or {}).get("serial-number", ""))
    eth = {e.get("name"): e for e in raw["ethernet"]}
    poe = {p.get("name"): p for p in raw["poe"]}
    prev = state.get("counters", {})
    counters, metrics, ports = {}, {}, []
    phys = sorted((i for i in raw["interfaces"] if i.get("type") == "ether"), key=lambda i: _natural(i.get("name", "")))
    own_macs = {norm_mac(i.get("mac-address")) for i in raw["interfaces"] if i.get("mac-address")}
    for no, i in enumerate(phys, start=1):
        name = i.get("name", "")
        rx, tx = int(i.get("rx-byte") or 0), int(i.get("tx-byte") or 0)
        in_bps = out_bps = None
        if name in prev and now > prev[name][2] and rx >= prev[name][0] and tx >= prev[name][1]:
            dt = now - prev[name][2]
            in_bps, out_bps = round((rx - prev[name][0]) * 8 / dt), round((tx - prev[name][1]) * 8 / dt)
            metrics[f"port:{no}:rx"], metrics[f"port:{no}:tx"] = in_bps, out_bps
        counters[name] = (rx, tx, now)
        e = eth.get(name, {})
        p = poe.get(name)
        ports.append(dict(port_no=no, iface=name, id=i.get(".id"), name=name, alias=i.get("comment", ""), kind=_kind(name, i.get("type")),
                          oper="up" if _bool(i.get("running")) else "down", admin="down" if _bool(i.get("disabled")) else "up",
                          speed=_speed(e.get("speed") or e.get("rate")), poe=None if not p else p.get("poe-out") != "off",
                          in_bps=in_bps, out_bps=out_bps, macs=[], lldp=None, mac=norm_mac(i.get("mac-address"))))
    by_iface = {p["iface"]: p for p in ports}
    # WLAN-Schnittstellen
    wifi = []
    for w in raw["wifi"]:
        ssid = w.get("configuration.ssid") or w.get("ssid") or ""
        band = w.get("configuration.band") or w.get("band") or w.get("channel.band") or ""
        wifi.append(dict(iface=w.get("name", ""), id=w.get(".id"), ssid=ssid, band="5 GHz" if "5ghz" in band else "2,4 GHz" if "2ghz" in band else "6 GHz" if "6ghz" in band else "",
                         enabled=not _bool(w.get("disabled")), running=_bool(w.get("running")), master=w.get("master-interface", "")))
    wifi_if = {w["iface"]: w for w in wifi}
    # Wer hängt wo: Bridge-Hosts (Port bzw. WLAN), WLAN-Registrierungen
    where = {}
    for h in raw["hosts"]:
        m = norm_mac(h.get("mac-address"))
        if not m or _bool(h.get("local")) or m in own_macs:
            continue
        iface = h.get("on-interface") or h.get("interface") or ""
        where[m] = iface
        if iface in by_iface:
            by_iface[iface]["macs"].append(m)
    signal, wbytes = {}, {}
    for r in raw["registrations"]:
        m = norm_mac(r.get("mac-address"))
        if m:
            where[m] = r.get("interface", where.get(m, ""))
            signal[m] = r.get("signal") or r.get("signal-strength") or ""
            b = str(r.get("bytes") or "").split(",")
            if len(b) == 2 and all(v.strip().isdigit() for v in b):
                wbytes[m] = (int(b[0]), int(b[1]))  # gesendet an den Client, empfangen vom Client
    kid = {}
    for k in raw.get("kid") or []:
        m = norm_mac(k.get("mac-address"))
        down, up = parse_rate(k.get("rate-down")), parse_rate(k.get("rate-up"))
        if m and down is not None and up is not None:
            kid[m] = (down, up)
    # Nachbarn (MNDP/LLDP/CDP) an Ports
    for n in raw["neighbors"]:
        iface = (n.get("interface") or "").split(",")[0]
        if iface in by_iface:
            by_iface[iface]["lldp"] = dict(name=n.get("identity") or n.get("system-description", "")[:40], port=n.get("interface-name", ""),
                                           mac=norm_mac(n.get("mac-address")), ip=n.get("address", ""), platform=n.get("platform", ""))
    # Clients aus DHCP und ARP
    clients = {}
    for l in raw["leases"]:
        m = norm_mac(l.get("active-mac-address") or l.get("mac-address"))
        ip = l.get("active-address") or l.get("address") or ""
        if not m or not ip:
            continue
        clients[m] = dict(mac=m, ip=ip, name=l.get("comment") or l.get("host-name") or "", online=l.get("status") == "bound", static=not _bool(l.get("dynamic")))
    for a in raw["arp"]:
        m = norm_mac(a.get("mac-address"))
        if m and a.get("address") and m not in clients and m not in own_macs and _bool(a.get("complete", "true")):
            clients[m] = dict(mac=m, ip=a["address"], name="", online=True, static=False)
    out_clients = []
    for m, cl in clients.items():
        iface = where.get(m, "")
        if iface in wifi_if or iface.startswith(("wifi", "wlan")):
            medium, port, band = "wlan", None, (wifi_if.get(iface) or {}).get("band", "")
        elif iface in by_iface:
            medium, port, band = "lan", by_iface[iface]["port_no"], ""
        else:
            medium, port, band = "lan", None, ""
        e = dict(cl, medium=medium, port=port, band=band, iface=iface, signal=signal.get(m, ""))
        if m in kid:
            e["down_bps"], e["up_bps"] = kid[m]
        elif m in wbytes:
            e["_down"], e["_up"] = wbytes[m]
        out_clients.append(e)
    counters["clients"] = counter_rates(out_clients, prev.get("clients") or {}, now)
    # WAN: Interface-Liste „WAN“ (Standardkonfiguration), sonst ether1
    wan_ifaces = [m.get("interface") for m in raw["wan_members"]] or (["ether1"] if "ether1" in by_iface else [])
    wan = None
    for name in wan_ifaces:
        i = next((x for x in raw["interfaces"] if x.get("name") == name), None)
        if not i:
            continue
        rx, tx = int(i.get("rx-byte") or 0), int(i.get("tx-byte") or 0)
        key = f"wan:{name}"
        rate = None
        if key in prev and now > prev[key][2] and rx >= prev[key][0] and tx >= prev[key][1]:
            dt = now - prev[key][2]
            rate = (round((rx - prev[key][0]) * 8 / dt), round((tx - prev[key][1]) * 8 / dt))
        counters[key] = (rx, tx, now)
        wan = dict(iface=name, mac=norm_mac(i.get("mac-address")), connected=True if _bool(i.get("running")) else False,
                   rx_bps=rate[0] if rate else None, tx_bps=rate[1] if rate else None)
        if rate:
            metrics["wan:rx"], metrics["wan:tx"] = rate
        break
    addrs = [a.get("address", "").split("/")[0] for a in raw["addresses"] if a.get("address")]
    info["addresses"] = addrs
    res = dict(info=info, ports=ports, wifi=wifi, clients=out_clients, wan=wan, wifi_menu=raw.get("wifi_menu"),
               fdb_size=sum(len(p["macs"]) for p in ports))
    vl = vlans(raw, ports)
    if vl:
        res["vlans"] = vl
    return res, metrics, counters


def test(conf):
    raw = collect(conf, {})
    res, _, _ = normalize(raw, {})
    i = res["info"]
    return dict(name=i["name"], model=i["model"], version=i["version"], ports=len(res["ports"]), clients=len(res["clients"]),
                wifi=len(res["wifi"]))


def firmware(conf, state, rb=None):
    """RouterOS-Update prüfen (höchstens alle 12 Stunden – der MikroTik fragt dabei bei MikroTik an) und RouterBOOT."""
    now_ = time.time()
    fw = state.get("fw") or {}
    if now_ - state.get("fw_checked", 0) >= 12 * 3600:
        with _client(conf) as cl:
            try:
                _req(cl, "POST", "system/package/update/check-for-updates", json={}, optional=True)
            except DriverError:
                pass
            u = _get(cl, "system/package/update", optional=True) or {}
        inst, latest = u.get("installed-version", ""), u.get("latest-version", "")
        fw = dict(installed=inst, latest=latest, update=bool(latest and inst and latest != inst),
                  info="https://mikrotik.com/download/changelogs" if latest else "")
        state["fw_checked"], state["fw"] = now_, fw
    if rb and rb.get("current-firmware") and rb.get("upgrade-firmware") and rb["current-firmware"] != rb["upgrade-firmware"]:
        fw = dict(fw, update=True, latest=(fw.get("latest") or "") + f" (RouterBOOT {rb['upgrade-firmware']})")
    return fw


def poll(conf, state):
    raw = collect(conf, state)
    res, metrics, counters = normalize(raw, state)
    state = dict(state, counters=counters)
    if access_of(conf) == "snmp":  # SNMP: installierte Version, RouterBOOT-Upgrade aus der MIKROTIK-MIB (keine Online-Prüfung)
        rb = raw.get("routerboard") or {}
        upd = bool(rb.get("current-firmware") and rb.get("upgrade-firmware") and rb["current-firmware"] != rb["upgrade-firmware"])
        res["firmware"] = dict(installed=res["info"]["version"], latest=f"RouterBOOT {rb['upgrade-firmware']}" if upd else "", update=upd, info="")
        res["access"] = "snmp"
        return res, metrics, state
    try:
        res["firmware"] = firmware(conf, state, raw.get("routerboard"))
    except DriverError:
        pass
    return res, metrics, state


def action(conf, state, kind, params):
    """kind: port (iface, id, up) | poe_cycle (iface) | wlan (iface, id, menu, on) | wol (mac, iface) | reboot"""
    if access_of(conf) == "snmp":
        raise DriverError("Mit SNMP kann díktyo bei MikroTik nur lesen – für Aktionen den Zugang „RouterOS-API“ wählen")
    with _client(conf) as cl:
        if kind == "port":
            _req(cl, "PATCH", f"interface/{params['id']}", json={"disabled": "false" if params["up"] else "true"})
            return f"Port {params['iface']} {'eingeschaltet' if params['up'] else 'abgeschaltet'}"
        if kind == "poe_cycle":
            _req(cl, "POST", "interface/ethernet/poe/power-cycle", json={"numbers": params["iface"], "duration": "5s"})
            return f"PoE an {params['iface']} für 5 Sekunden unterbrochen"
        if kind == "wlan":
            _req(cl, "PATCH", f"{params['menu']}/{params['id']}", json={"disabled": "false" if params["on"] else "true"})
            return f"WLAN „{params.get('ssid') or params['iface']}“ {'eingeschaltet' if params['on'] else 'ausgeschaltet'}"
        if kind == "wol":
            _req(cl, "POST", "tool/wol", json={"mac": params["mac"], **({"interface": params["iface"]} if params.get("iface") else {})})
            return f"Weckruf an {params['mac']} gesendet"
        if kind == "reboot":
            try:
                _req(cl, "POST", "system/reboot", json={})
            except DriverError as ex:
                if "nicht erreichbar" not in str(ex) and "abgebrochen" not in str(ex):  # die Verbindung bricht beim Neustart oft ab
                    raise
            return "MikroTik startet neu (dauert etwa eine Minute)"
    raise DriverError(f"Unbekannte Aktion {kind}")
