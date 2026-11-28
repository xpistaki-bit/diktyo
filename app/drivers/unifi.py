"""Treiber Ubiquiti UniFi (UniFi-OS-Konsolen wie UDM/UCG/Cloud Key, selbst gehostete Network-Application), nur lesen.

Nutzt die offizielle lokale „Network Integration API“ mit API-Schlüssel (UniFi Network → Einstellungen →
Steuerung/Control Plane → Integrationen → API-Schlüssel erstellen). Liefert Gateways, Switches und Access Points mit
Uplink und Port-Status, die verbundenen Clients mit ihrem Access Point bzw. Switch sowie den WAN-Traffic des Gateways.

Pfad: UniFi-OS-Konsolen unter /proxy/network/integration, selbst gehostete Controller unter /integration – wird
automatisch erkannt. Nicht gegen echte Hardware getestet – aufgebaut nach der offiziellen OpenAPI-Beschreibung.
"""
import httpx

import time

from .controller import DriverError, counter_rates, mac, speed_text, vid_list, vlan_result

NAME = "Ubiquiti UniFi"
DEFAULT_INTERVAL = 60
FIELDS = [
    dict(key="host", label="Adresse", type="text", default="", required=True, placeholder="z. B. 192.168.1.1"),
    dict(key="port", label="Port", type="number", default=443),
    dict(key="password", label="API-Schlüssel", type="password", default="", secret=True),
    dict(key="site", label="Standort (Site)", type="text", default="", placeholder="leer = alle Sites"),
]
PREFIXES = ("/proxy/network/integration", "/integration")
GATEWAY = ("UDM", "UDR", "UCG", "UXG", "USG", "UX", "EFG", "UDW", "UCK-G2")  # Modellkürzel von Gateways/Konsolen
CONNECTOR = {"RJ45": "rj45", "SFP": "sfp", "SFPPLUS": "sfp+", "SFP28": "sfp28", "QSFP28": "sfp28"}


def _client(conf):
    return httpx.Client(base_url=f'https://{conf["host"]}:{int(conf.get("port") or 443)}', verify=False, timeout=15,
                        headers={"X-API-KEY": conf.get("password", ""), "Accept": "application/json"})


class _Api:
    def __init__(self, cl, state):
        self.cl, self.state = cl, state

    def get(self, path, **params):
        prefixes = [self.state["prefix"]] if self.state.get("prefix") else list(PREFIXES)
        last = None
        for p in prefixes:
            r = self.cl.get(f"{p}/v1{path}", params=params)
            if r.status_code in (401, 403):
                raise DriverError("API-Schlüssel abgelehnt (in UniFi Network unter Integrationen einen lokalen Schlüssel erstellen, nicht den Site-Manager-Schlüssel)")
            if r.status_code == 404 and len(prefixes) > 1:
                last = r
                continue
            if r.status_code >= 400:
                raise DriverError(f"Controller meldet HTTP {r.status_code}: {r.text[:120]}")
            try:
                j = r.json()
            except ValueError:
                raise DriverError("Unerwartete Antwort (ist das eine UniFi-Konsole mit Network 9.0 oder neuer?)")
            self.state["prefix"] = p
            return j
        raise DriverError(f"Integration API nicht gefunden (HTTP {last.status_code if last else '?'}) – UniFi Network 9.0 oder neuer nötig")

    def post(self, path, body):
        """Aktion an die Integration API (gleicher Pfad-Präfix wie beim Lesen)."""
        p = self.state.get("prefix") or PREFIXES[0]
        r = self.cl.post(f"{p}/v1{path}", json=body)
        if r.status_code in (401, 403):
            raise DriverError("API-Schlüssel hat keine Berechtigung für Aktionen (Schlüssel mit Schreibrecht nötig)")
        if r.status_code >= 400:
            raise DriverError(f"Controller meldet HTTP {r.status_code}: {r.text[:160]}")
        return r.json() if r.content else {}

    def pages(self, path):
        rows, off = [], 0
        while True:
            j = self.get(path, offset=off, limit=200)
            data = j.get("data") or []
            rows += data
            off += len(data)
            if not data or off >= int(j.get("totalCount") or 0) or off > 10000:
                return rows


def _type(d):
    model = str(d.get("model") or "").upper()
    feats = d.get("features") or {}
    if model.startswith(GATEWAY):
        return "router"
    if "switching" in feats:
        return "switch"
    if "accessPoint" in feats:
        return "ap"
    return "other"


def normalize(sites):
    """sites = [(site, devices(details), clients, stats{device_id})] -> (devices, clients, wan)"""
    devices, clients, wan = [], [], None
    for _site, devs, cls, stats in sites:
        site_id = (_site or {}).get("id", "")
        by_id = {d.get("id"): mac(d.get("macAddress")) for d in devs}
        for d in devs:
            ports = []
            for p in ((d.get("interfaces") or {}).get("ports") or []):
                if p.get("idx") is None:
                    continue
                ports.append(dict(port_no=int(p["idx"]), oper={"UP": "up", "DOWN": "down"}.get(p.get("state"), ""),
                                  speed=speed_text(p.get("speedMbps") or 0), max_speed=speed_text(p.get("maxSpeedMbps") or 0),
                                  kind=CONNECTOR.get(p.get("connector"), "rj45"), in_bps=None, out_bps=None, macs=[], lldp=[],
                                  poe=bool((p.get("poe") or {}).get("enabled")) if isinstance(p.get("poe"), dict) else None))
            typ = _type(d)
            dev = dict(mac=mac(d.get("macAddress")), ip=d.get("ipAddress") or "", name=d.get("name") or d.get("model") or "",
                       model=d.get("model") or "", type=typ, online=d.get("state") == "ONLINE",
                       uplink_mac=by_id.get((d.get("uplink") or {}).get("deviceId"), ""), uplink_port=None, clients=0,
                       firmware=d.get("firmwareVersion") or "", ports=ports, ref=dict(site=site_id, id=d.get("id", "")),
                       firmware_info=dict(installed=d.get("firmwareVersion") or "", latest="", update=bool(d.get("firmwareUpdatable"))))
            devices.append(dev)
            st = stats.get(d.get("id")) or {}
            up = st.get("uplink") or {}
            if typ == "router" and wan is None and (up.get("rxRateBps") is not None or dev["online"]):
                moving = (up.get("rxRateBps") or 0) + (up.get("txRateBps") or 0) > 0
                wan = dict(mac=dev["mac"], connected=True if dev["online"] and moving else None,  # Traffic fließt -> verbunden
                           rx_bps=up.get("rxRateBps"), tx_bps=up.get("txRateBps"),
                           uptime=st.get("uptimeSec"))
        for x in cls:
            typ = str(x.get("type") or "").upper()
            if typ not in ("WIRED", "WIRELESS"):
                continue  # VPN/Teleport haben keinen Platz im Heimnetz-Baum
            clients.append(dict(mac=mac(x.get("macAddress")), ip=x.get("ipAddress") or "", name=x.get("name") or "", online=True,
                                medium="wlan" if typ == "WIRELESS" else "lan", parent_mac=by_id.get(x.get("uplinkDeviceId"), ""),
                                port=None, band="", ssid="", vendor=""))
    for dev in devices:
        dev["clients"] = sum(1 for x in clients if x["parent_mac"] == dev["mac"])
    return devices, clients, wan


def _collect(conf, state, details=True):
    with _client(conf) as cl:
        api = _Api(cl, state)
        sites = api.pages("/sites")
        want = (conf.get("site") or "").strip().lower()
        if want:
            sites = [s for s in sites if want in (str(s.get("name", "")).lower(), str(s.get("internalReference", "")).lower())]
            if not sites:
                raise DriverError(f"Site „{conf['site']}“ nicht gefunden")
        out = []
        for s in sites:
            sid = s["id"]
            devs = api.pages(f"/sites/{sid}/devices")
            stats = {}
            if details:  # Uplink steht nur in den Details; WAN-Traffic in den Statistiken des Gateways
                full = []
                for d in devs:
                    try:
                        full.append({**d, **api.get(f"/sites/{sid}/devices/{d['id']}")})
                    except DriverError:
                        full.append(d)
                    if _type(d) == "router":
                        try:
                            stats[d["id"]] = api.get(f"/sites/{sid}/devices/{d['id']}/statistics/latest")
                        except DriverError:
                            pass
                devs = full
            out.append((s, devs, api.pages(f"/sites/{sid}/clients"), stats))
        if details and not state.get("no_sta"):
            state["sta"] = _sta(cl, state, [s.get("internalReference") or "default" for s in sites])
        if details and time.time() - (state.get("no_vlans") or 0) > 86400:
            state["vlans"] = _vlans(cl, state, [s.get("internalReference") or "default" for s in sites])
        if details and time.time() - (state.get("no_pfw") or 0) > 86400:
            state["pfw"] = _portforwards(cl, state, [s.get("internalReference") or "default" for s in sites])
        return out


def _portforwards(cl, state, refs):
    """Portfreigaben aus der klassischen Network-API (rest/portforward); antwortet sie nicht: am nächsten Tag wieder."""
    from .controller import forward
    out = []
    for ref in refs:
        rows = _classic(cl, state, f"/api/s/{ref}/rest/portforward")
        if rows is None:
            state["no_pfw"] = time.time()
            return None
        for r in rows:
            out.append(forward("static", r.get("proto"), r.get("dst_port"), r.get("fwd"), r.get("fwd_port"), r.get("name"),
                               r.get("enabled", True) is not False, r.get("src") or ""))
    return out


def _classic(cl, state, path):
    base = "/proxy/network" if state.get("prefix", PREFIXES[0]) == PREFIXES[0] else ""
    try:
        r = cl.get(f"{base}{path}")
        return r.json().get("data") if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError, AttributeError):
        return None


def _vlans(cl, state, refs):
    """VLANs je Switch-Port aus der klassischen Network-API (Netze, Port-Profile, Port-Überschreibungen). Die Integration
    API kennt keine Port-VLANs. Antwortet die Konsole darauf nicht, wird es erst am nächsten Tag wieder versucht. -> {Switch-MAC: Ergebnis}"""
    out = {}
    for ref in refs:
        nets, profiles, devs = (_classic(cl, state, f"/api/s/{ref}/{p}") for p in ("rest/networkconf", "rest/portconf", "stat/device"))
        if nets is None or devs is None:
            state["no_vlans"] = time.time()  # erst am nächsten Tag wieder versuchen
            return {}
        out.update(port_vlans(nets, profiles or [], devs))
    return out


def port_vlans(nets, profiles, devs):
    """Netze (networkconf), Port-Profile (portconf) und Geräte (stat/device mit port_table/port_overrides) -> {MAC: Ergebnis}"""
    vid_of, names = {}, {}
    for n in nets:
        if n.get("purpose") not in ("corporate", "vlan-only", "guest") or not n.get("_id"):
            continue
        if n.get("vlan_enabled") or n.get("purpose") == "vlan-only":
            vid = vid_list(n.get("vlan"))[:1]
        else:  # ohne VLAN-ID nur das Standardnetz (untagged, VLAN 1)
            vid = [1] if n.get("attr_no_delete") or n.get("attr_hidden_id") == "LAN" else []
        if vid:
            vid_of[n["_id"]] = vid[0]
            names.setdefault(vid[0], n.get("name") or "")
    if not vid_of:
        return {}
    default = next((i for i, v in vid_of.items() if v == 1), None)
    prof = {p.get("_id"): p for p in profiles}

    def apply(cfg, st):
        if cfg.get("native_networkconf_id") is not None:
            st["native"] = cfg.get("native_networkconf_id") or None
        mgmt, fwd = cfg.get("tagged_vlan_mgmt"), cfg.get("forward")
        if mgmt == "block_all" or fwd in ("native", "disabled"):
            st["tagged"] = set()
        elif mgmt == "auto" or fwd == "all":
            st["tagged"] = set(vid_of)
        elif mgmt == "custom" or fwd == "customize":
            if cfg.get("tagged_networkconf_ids") is not None:
                st["tagged"] = set(cfg.get("tagged_networkconf_ids") or [])
            else:
                st["tagged"] = set(vid_of) - set(cfg.get("excluded_networkconf_ids") or [])
        if fwd == "disabled":
            st["native"] = None

    out = {}
    for d in devs:
        if d.get("type") not in ("usw", "udm") or not d.get("mac"):
            continue
        ov = {o.get("port_idx"): o for o in d.get("port_overrides") or []}
        members = {}
        for p in d.get("port_table") or []:
            idx = p.get("port_idx")
            if not isinstance(idx, int):
                continue
            st = dict(native=default, tagged=set(vid_of))  # ohne Einstellung: Standardnetz untagged, alle anderen tagged
            o = ov.get(idx) or {}
            pc = prof.get(o.get("portconf_id") or p.get("portconf_id"))
            if pc:
                apply(pc, st)
            apply(o, st)
            u = vid_of.get(st["native"])
            members[idx] = dict(untagged=u, tagged={vid_of[i] for i in st["tagged"] if i in vid_of} - {u})
        vl = vlan_result(names, members)
        if vl:
            out[mac(d["mac"])] = vl
    return out


def _sta(cl, state, refs):
    """Byte-Zähler je Client aus der klassischen Network-API (stat/sta). Die Integration API kennt keine Raten je Client.
    Antwortet die Konsole darauf nicht (z. B. API-Schlüssel dort nicht zugelassen), wird es nicht wieder versucht."""
    base = "/proxy/network" if state.get("prefix", PREFIXES[0]) == PREFIXES[0] else ""
    out = {}
    for ref in refs:
        try:
            r = cl.get(f"{base}/api/s/{ref}/stat/sta")
            rows = r.json().get("data") if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            rows = None
        if rows is None:
            state["no_sta"] = True
            return {}
        for x in rows:
            m = mac(x.get("mac"))
            if m and x.get("tx_bytes") is not None:
                # Sicht des Access Points: tx = zum Client (Download des Clients)
                out[m] = (x.get("tx_bytes"), x.get("rx_bytes"))
    return out


def test(conf):
    st = {}
    with _client(conf) as cl:
        info = _Api(cl, st).get("/info")
    sites = _collect(conf, st, details=False)
    devices, clients, _ = normalize(sites)
    return dict(version=info.get("applicationVersion", ""), sites=", ".join(s.get("name", "") for s, *_ in sites),
                devices=len(devices), clients=len(clients))


def poll(conf, state):
    state = dict(state)
    sites = _collect(conf, state)
    devices, clients, wan = normalize(sites)
    sta = state.pop("sta", None) or {}
    pfw = state.pop("pfw", None)
    for dev, vl in (state.pop("vlans", None) or {}).items():
        for d in devices:
            if d["mac"] == dev:
                d["vlans"] = vl
    for x in clients:
        if x["mac"] in sta:
            x["_down"], x["_up"] = sta[x["mac"]]
    state["client_counters"] = counter_rates(clients, state.get("client_counters") or {}, time.time())
    res = dict(info=dict(controller="UniFi", sites=[s.get("name", "") for s, *_ in sites]), devices=devices, clients=clients)
    if pfw is not None:
        res["forwards"] = pfw
    values = {}
    if wan:
        res["wan"] = wan
        if wan.get("rx_bps") is not None:
            values = {"wan:rx": wan["rx_bps"], "wan:tx": wan["tx_bps"] or 0}
    return res, values, state


def action(conf, state, kind, params):
    """Neustart eines Geräts bzw. PoE-Neustart eines Switch-Ports über die Integration API. -> Meldung"""
    site, dev = params.get("site"), params.get("id")
    if not site or not dev:
        raise DriverError("Gerät beim Controller nicht gefunden – Integration einmal abfragen")
    with _client(conf) as cl:
        api = _Api(cl, dict(state))
        if kind == "reboot":
            api.post(f"/sites/{site}/devices/{dev}/actions", {"action": "RESTART"})
            return f"{params.get('name') or 'Gerät'} startet neu"
        if kind == "poe_cycle":
            api.post(f"/sites/{site}/devices/{dev}/interfaces/ports/{int(params['port_no'])}/actions", {"action": "POWER_CYCLE"})
            return f"PoE an Port {params['port_no']} aus- und wieder eingeschaltet"
    raise DriverError(f"Unbekannte Aktion {kind}")
