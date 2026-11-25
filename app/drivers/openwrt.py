"""Treiber OpenWrt über ubus (JSON-RPC von uhttpd/rpcd, wie LuCI).

Anmeldung: `session login` mit einem rpcd-Benutzer (root oder eigener Benutzer mit ACL, siehe Anleitung). Gelesen werden
System/Board (Modell, OpenWrt-Version), Ports (network.device status: Link, Tempo, Traffic), WAN (network.interface dump),
Clients (DHCP-Leases und Host-Hinweise von luci-rpc, WLAN-Geräte aus iwinfo assoclist), WLANs (network.wireless status)
und VLANs (bridge-vlan-Abschnitte der UCI-Netzwerkkonfiguration, DSA). Schalten: WLAN ein/aus (UCI + network reload),
Neustart. Konfigurations-Backup über /cgi-bin/cgi-backup (wie „Sicherung herunterladen“ in LuCI).
Welcher LAN-Port zu welchem Gerät führt, verrät OpenWrt per ubus nicht – das klären Switch (SNMP) oder Nachbarn.
"""
import gzip
import io
import re
import tarfile
import time

import httpx

from .controller import DriverError, mac as norm_mac, vid_list, vlan_result

NAME = "OpenWrt"
DEFAULT_INTERVAL = 60
FIELDS = [
    dict(key="host", label="Adresse", type="text", default="", required=True, placeholder="z. B. 192.168.1.1"),
    dict(key="scheme", label="Verbindung", type="select", default="auto", options=[
        ["auto", "automatisch (HTTPS, sonst HTTP)"], ["https", "HTTPS"], ["http", "HTTP"]]),
    dict(key="port", label="Port (leer = 443 bzw. 80)", type="number", default=""),
    dict(key="username", label="Benutzer", type="text", default="root"),
    dict(key="password", label="Passwort", type="password", default="", secret=True),
    dict(key="cfg_schedule", label="Konfiguration sichern", type="select", default="weekly", options=[
        ["weekly", "wöchentlich"], ["daily", "täglich"], ["no", "nein"]]),
]
CAN_BACKUP = True
NO_SESSION = "00000000000000000000000000000000"
PHYS = re.compile(r"^(lan|wan|port|sw|ge|eth)\d*$")
BAND = {"2g": "2,4 GHz", "5g": "5 GHz", "6g": "6 GHz", "60g": "60 GHz"}
UBUS_ERR = {1: "ungültiger Befehl", 2: "ungültiges Argument", 3: "Methode nicht gefunden", 4: "nicht gefunden", 5: "keine Daten",
            6: "keine Berechtigung", 7: "Zeitüberschreitung", 8: "nicht unterstützt", 9: "unbekannter Fehler", 10: "Verbindung fehlgeschlagen"}


class UbusError(DriverError):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


def _bases(conf, state):
    if state.get("base"):
        return [state["base"]]
    host, port, scheme = conf["host"].strip().rstrip("/"), conf.get("port"), conf.get("scheme") or "auto"
    host = re.sub(r"^https?://", "", host)
    schemes = ["https", "http"] if scheme == "auto" else [scheme]
    return [f"{s}://{host}{':' + str(int(port)) if port else ''}" for s in schemes]


class _Ubus:
    def __init__(self, conf, state):
        self.conf, self.state, self.cl, self.base = conf, state, None, None

    def __enter__(self):
        last = None
        for base in _bases(self.conf, self.state):
            cl = httpx.Client(base_url=base, verify=False, timeout=15)
            try:
                self.cl, self.base = cl, base
                self._login()
                self.state["base"] = base
                return self
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as ex:
                last = ex
                cl.close()
        raise DriverError(f"OpenWrt unter {self.conf['host']} nicht erreichbar ({type(last).__name__ if last else 'keine Adresse'})")

    def __exit__(self, *a):
        if self.cl:
            self.cl.close()

    def _rpc(self, sid, obj, method, args):
        r = self.cl.post("/ubus", json={"jsonrpc": "2.0", "id": 1, "method": "call", "params": [sid, obj, method, args or {}]})
        if r.status_code == 404:
            raise DriverError("Keine ubus-Schnittstelle unter /ubus – auf dem Router das Paket uhttpd-mod-ubus installieren (bei LuCI vorhanden)")
        try:
            j = r.json()
        except ValueError:
            raise DriverError(f"Unerwartete Antwort (HTTP {r.status_code}) – ist das ein OpenWrt-Router mit LuCI?")
        if j.get("error"):
            code = j["error"].get("code")
            raise UbusError(code, "Zugriff verweigert – Sitzung abgelaufen oder fehlende Rechte" if code == -32002 else f"ubus-Fehler {code}")
        res = j.get("result") or [9]
        if res[0] != 0:
            raise UbusError(res[0], f"{obj} {method}: {UBUS_ERR.get(res[0], 'Fehler ' + str(res[0]))}")
        return res[1] if len(res) > 1 else {}

    def _login(self):
        try:
            r = self._rpc(NO_SESSION, "session", "login", {"username": self.conf.get("username") or "root", "password": self.conf.get("password") or ""})
        except UbusError as ex:
            if ex.code in (6, -32002):
                raise DriverError("Anmeldung abgelehnt – Benutzer und Passwort prüfen (rpcd-Benutzer, z. B. root)")
            raise
        self.sid = r.get("ubus_rpc_session") or ""
        if not self.sid:
            raise DriverError("Anmeldung ohne Sitzung – rpcd antwortet unerwartet")

    def call(self, obj, method, args=None, optional=False):
        for attempt in (0, 1):
            try:
                return self._rpc(self.sid, obj, method, args)
            except UbusError as ex:
                if ex.code == -32002 and attempt == 0:
                    self._login()
                    continue
                if optional and ex.code in (2, 3, 4, 5, 6, 8, -32002):
                    return None
                raise


def collect(conf, state):
    with _Ubus(conf, state) as u:
        out = dict(board=u.call("system", "board") or {}, sysinfo=u.call("system", "info", optional=True) or {},
                   devices=u.call("network.device", "status", optional=True) or {},
                   ifaces=(u.call("network.interface", "dump", optional=True) or {}).get("interface") or [],
                   leases=(u.call("luci-rpc", "getDHCPLeases", optional=True) or {}).get("dhcp_leases") or [],
                   hints=u.call("luci-rpc", "getHostHints", optional=True) or {},
                   wireless=u.call("network.wireless", "status", optional=True) or {},
                   network_uci=(u.call("uci", "get", {"config": "network"}, optional=True) or {}).get("values") or {},
                   assoc={})
        for radio in out["wireless"].values():
            for w in (radio or {}).get("interfaces") or []:
                ifn = w.get("ifname")
                if ifn:
                    out["assoc"][ifn] = (u.call("iwinfo", "assoclist", {"device": ifn}, optional=True) or {}).get("results") or []
    return out


def _speed(v):
    m = re.match(r"(\d+)", str(v or ""))
    return int(m.group(1)) if m else 0


def _natural(name):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name)]


def physical(devices):
    """Frontports: lanN/wanN/portN; nur wenn es keine gibt, die ethN (ohne DSA sind das die Ports, mit DSA der CPU-Anschluss)."""
    names = [n for n, d in devices.items() if PHYS.match(n) and isinstance(d, dict) and d.get("present", True) is not False]
    named = [n for n in names if not n.startswith("eth")]
    return sorted(named or names, key=lambda n: (n.startswith("wan"), _natural(n)))


def vlans(network_uci, ports):
    """bridge-vlan-Abschnitte (DSA): ports = ["lan1:u*", "lan2:t", "lan3"] – ohne Zusatz untagged, * = PVID."""
    by_iface = {p["iface"]: p["port_no"] for p in ports}
    names, members = {}, {}
    # Name: die Schnittstelle (z. B. „iot“), deren Gerät „<bridge>.<vid>“ ist
    for sec, s in network_uci.items():
        if isinstance(s, dict) and s.get(".type") == "interface":
            m = re.fullmatch(r"[\w-]+\.(\d+)", str(s.get("device") or ""))
            if m:
                names.setdefault(int(m.group(1)), s.get(".name") or sec)
    for s in network_uci.values():
        if not isinstance(s, dict) or s.get(".type") != "bridge-vlan":
            continue
        vid = vid_list(s.get("vlan"))
        if not vid:
            continue
        vid = vid[0]
        if s.get("description"):
            names[vid] = s["description"]
        plist = s.get("ports") or []
        for entry in plist if isinstance(plist, list) else str(plist).split():
            iface, _, flags = str(entry).partition(":")
            if iface not in by_iface:
                continue
            m = members.setdefault(by_iface[iface], dict(untagged=None, tagged=set()))
            if "t" in flags:
                m["tagged"].add(vid)
            elif "*" in flags or not m["untagged"]:
                m["untagged"] = vid
    return vlan_result(names, members)


def normalize(raw, state, now=None):
    now = now or time.time()
    b = raw["board"] or {}
    rel = b.get("release") or {}
    model = b.get("model") or ""
    info = dict(name=b.get("hostname") or "", model=model, vendor=model.split()[0] if model else "OpenWrt",
                version=" ".join(x for x in (rel.get("version"), rel.get("revision")) if x), target=rel.get("target") or "",
                uptime=(raw["sysinfo"] or {}).get("uptime"))
    devs = raw["devices"] or {}
    prev = state.get("counters", {})
    counters, metrics, ports = {}, {}, []
    for no, name in enumerate(physical(devs), start=1):
        d = devs[name]
        st = d.get("statistics") or {}
        rx, tx = int(st.get("rx_bytes") or 0), int(st.get("tx_bytes") or 0)
        rate = None
        if name in prev and now > prev[name][2] and rx >= prev[name][0] and tx >= prev[name][1]:
            dt = now - prev[name][2]
            rate = (round((rx - prev[name][0]) * 8 / dt), round((tx - prev[name][1]) * 8 / dt))
            metrics[f"port:{no}:rx"], metrics[f"port:{no}:tx"] = rate
        counters[name] = (rx, tx, now)
        ports.append(dict(port_no=no, iface=name, id=name, name=name, alias="", kind="rj45", oper="up" if d.get("carrier") else "down",
                          admin="up" if d.get("up", True) else "down", speed=_speed(d.get("speed")), poe=None,
                          in_bps=rate[0] if rate else None, out_bps=rate[1] if rate else None, macs=[], lldp=None, mac=norm_mac(d.get("macaddr"))))
    # WAN und eigene Adressen
    wan, addrs = None, []
    for i in raw["ifaces"]:
        for a in i.get("ipv4-address") or []:
            if a.get("address"):
                addrs.append(a["address"])
        if i.get("interface") == "wan" and wan is None:
            dev = i.get("l3_device") or i.get("device") or ""
            st = (devs.get(dev) or {}).get("statistics") or {}
            rx, tx = int(st.get("rx_bytes") or 0), int(st.get("tx_bytes") or 0)
            key, rate = f"wan:{dev}", None
            if key in prev and now > prev[key][2] and rx >= prev[key][0] and tx >= prev[key][1]:
                dt = now - prev[key][2]
                rate = (round((rx - prev[key][0]) * 8 / dt), round((tx - prev[key][1]) * 8 / dt))
                metrics["wan:rx"], metrics["wan:tx"] = rate
            counters[key] = (rx, tx, now)
            wan = dict(iface=dev, mac=norm_mac((devs.get(dev) or {}).get("macaddr")), connected=bool(i.get("up")),
                       rx_bps=rate[0] if rate else None, tx_bps=rate[1] if rate else None)
    info["addresses"] = addrs
    # WLANs
    wifi, band_of = [], {}
    for rname, radio in (raw["wireless"] or {}).items():
        rc = (radio or {}).get("config") or {}
        band = BAND.get(rc.get("band"), "") or ("5 GHz" if "a" in str(rc.get("hwmode") or "") else "2,4 GHz" if rc.get("hwmode") else "")
        for w in (radio or {}).get("interfaces") or []:
            cfg = w.get("config") or {}
            if cfg.get("mode") not in (None, "ap"):
                continue
            ifn = w.get("ifname") or ""
            band_of[ifn] = band
            wifi.append(dict(iface=ifn, id=w.get("section") or "", ssid=cfg.get("ssid") or "", band=band, radio=rname,
                             enabled=not (str(cfg.get("disabled")) in ("1", "true") or str(rc.get("disabled")) in ("1", "true")),
                             running=bool(radio.get("up")) and bool(ifn)))
    # Clients: aktive DHCP-Leases und WLAN-Geräte; Namen aus den Host-Hinweisen
    hints = {norm_mac(k): v for k, v in (raw["hints"] or {}).items() if norm_mac(k)}
    own = {p["mac"] for p in ports} | {norm_mac(d.get("macaddr")) for d in devs.values() if isinstance(d, dict)}
    clients = {}
    for l in raw["leases"]:
        m = norm_mac(l.get("macaddr"))
        if m and l.get("ipaddr") and m not in own:
            clients[m] = dict(mac=m, ip=l["ipaddr"], name=l.get("hostname") or (hints.get(m) or {}).get("name") or "", online=True,
                              medium="lan", port=None, band="", signal="", iface="")
    for ifn, rows in (raw["assoc"] or {}).items():
        for a in rows:
            m = norm_mac(a.get("mac"))
            if not m:
                continue
            h = hints.get(m) or {}
            ips = h.get("ipaddrs") if isinstance(h.get("ipaddrs"), list) else []
            c = clients.setdefault(m, dict(mac=m, ip=ips[0] if ips else "", name=h.get("name") or "", online=True,
                                           medium="lan", port=None, band="", signal="", iface=""))
            c.update(medium="wlan", iface=ifn, band=band_of.get(ifn, ""), signal=str(a.get("signal") or ""))
    out_clients = [x for x in clients.values() if x["ip"]]
    firmware = dict(installed=rel.get("version") or "", latest="", update=None, info="")
    res = dict(info=info, ports=ports, wifi=wifi, clients=out_clients, wan=wan, firmware=firmware, fdb_size=None,
               role="router" if wan else "ap" if wifi else "switch")
    vl = vlans(raw["network_uci"] or {}, ports)
    if vl:
        res["vlans"] = vl
    return res, metrics, counters


def test(conf):
    raw = collect(conf, {})
    res, _, _ = normalize(raw, {})
    i = res["info"]
    return dict(name=i["name"], model=i["model"], version=i["version"], ports=len(res["ports"]), clients=len(res["clients"]), wifi=len(res["wifi"]))


def poll(conf, state):
    state = dict(state)
    raw = collect(conf, state)
    res, metrics, counters = normalize(raw, state)
    state["counters"] = counters
    return res, metrics, state


def action(conf, state, kind, params):
    """kind: wlan (id = UCI-Abschnitt, on) | reboot"""
    with _Ubus(conf, dict(state)) as u:
        if kind == "wlan":
            sec = str(params.get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_]+", sec):
                raise DriverError("WLAN beim Router nicht gefunden – Integration einmal abfragen")
            u.call("uci", "set", {"config": "wireless", "section": sec, "values": {"disabled": "0" if params["on"] else "1"}})
            u.call("uci", "commit", {"config": "wireless"})
            u.call("network", "reload", {}, optional=True)
            return f"WLAN „{params.get('ssid') or sec}“ {'eingeschaltet' if params['on'] else 'ausgeschaltet'}"
        if kind == "reboot":
            try:
                u.call("system", "reboot", {})
            except httpx.HTTPError:
                pass  # Router startet schon neu
            return "OpenWrt startet neu (dauert etwa eine Minute)"
    raise DriverError(f"Unbekannte Aktion {kind}")


MAX_BACKUP = 20 * 1024 * 1024


def normalize_archive(data):
    """Sicherungsarchiv von OpenWrt deterministisch neu packen (sortiert, ohne Zeitstempel im gzip-Kopf), damit eine
    unveränderte Konfiguration als „unverändert“ erkannt wird. Bleibt in LuCI einspielbar (tar.gz)."""
    src = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as dst:
        for m in sorted(src.getmembers(), key=lambda x: x.name):
            if not (m.isfile() or m.isdir() or m.issym()):
                continue
            fobj = src.extractfile(m) if m.isfile() else None
            m.mtime, m.uname, m.gname = 0, "", ""
            dst.addfile(m, fobj)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def backup(conf, state):
    with _Ubus(conf, dict(state)) as u:
        try:
            r = u.cl.post("/cgi-bin/cgi-backup", data={"sessionid": u.sid}, timeout=60)
        except httpx.HTTPError as ex:
            raise DriverError(f"OpenWrt nicht erreichbar: {type(ex).__name__}")
    if r.status_code in (401, 403):
        raise DriverError("Keine Berechtigung für die Sicherung (ACL „cgi-io: backup“ bzw. Benutzer root nötig)")
    if r.status_code == 404:
        raise DriverError("Sicherung nicht verfügbar – auf dem Router fehlt cgi-io (Teil von LuCI)")
    if r.status_code >= 400 or r.content[:2] != b"\x1f\x8b" or len(r.content) > MAX_BACKUP:
        raise DriverError(f"OpenWrt hat keine Sicherung geliefert (HTTP {r.status_code})")
    try:
        data = normalize_archive(r.content)
    except (tarfile.TarError, OSError, EOFError):
        data = r.content
    return f"backup-{re.sub(r'[^A-Za-z0-9_.-]', '_', conf['host'])}.tar.gz", data, False
