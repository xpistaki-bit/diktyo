"""Treiber TP-Link Omada (Software-Controller, OC200/OC300, Omada-Gateway mit Controller), nur lesen.

Nutzt die offizielle Open API des Controllers (Einstellungen → Plattform-Integration → Open API → App im
„Client“-Modus). Anmeldung per Client-ID/-Secret (OAuth2 client_credentials); der Zugriffstoken wird gemerkt und
bei Ablauf erneuert. Liefert Gateways, Switches und Access Points mit Uplink (Gerät und Port) sowie die Clients mit
dem Access Point bzw. Switch-Port, an dem sie hängen.

Nicht gegen echte Hardware getestet – aufgebaut nach der Open-API-Dokumentation und bestehenden Integrationen.
"""
import time

import httpx

from .controller import DriverError, counter_rates, mac

NAME = "TP-Link Omada"
DEFAULT_INTERVAL = 60
FIELDS = [
    dict(key="host", label="Adresse", type="text", default="", required=True, placeholder="z. B. 192.168.0.10"),
    dict(key="port", label="Port", type="number", default=8043),
    dict(key="omada_id", label="Omada-ID", type="text", default="", required=True, placeholder="aus Einstellungen → Plattform-Integration → Open API"),
    dict(key="username", label="Client-ID", type="text", default="", required=True),
    dict(key="password", label="Client-Secret", type="password", default="", secret=True),
    dict(key="site", label="Standort (Site)", type="text", default="", placeholder="leer = alle Sites"),
]
RADIO = {0: "2,4 GHz", 1: "5 GHz", 2: "5 GHz (2)", 3: "6 GHz"}
TYPES = {"gateway": "router", "switch": "switch", "ap": "ap"}
AUTH_ERRORS = {-44106, -44111, -44112, -44113, -44116}  # Token ungültig/abgelaufen


def _base(conf):
    return f'https://{conf["host"]}:{int(conf.get("port") or 8043)}'


def _client(conf):
    return httpx.Client(base_url=_base(conf), verify=False, timeout=15)


def _token(cl, conf):
    r = cl.post("/openapi/authorize/token", params={"grant_type": "client_credentials"},
                json={"omadacId": conf.get("omada_id", ""), "client_id": conf.get("username", ""), "client_secret": conf.get("password", "")})
    try:
        j = r.json()
    except ValueError:
        raise DriverError(f"Unerwartete Antwort des Controllers (HTTP {r.status_code}) – ist das ein Omada-Controller mit Open API?")
    if j.get("errorCode") != 0:
        raise DriverError(f"Anmeldung abgelehnt: {j.get('msg') or j.get('errorCode')} (Client-ID, Client-Secret und Omada-ID prüfen)")
    t = j["result"]
    return t["accessToken"], time.time() + int(t.get("expiresIn") or 7200) - 120


class _Api:
    def __init__(self, cl, conf, state):
        self.cl, self.conf, self.state = cl, conf, state

    def _auth(self, force=False):
        if force or not self.state.get("token") or self.state.get("token_exp", 0) < time.time():
            self.state["token"], self.state["token_exp"] = _token(self.cl, self.conf)
        return {"Authorization": f'AccessToken={self.state["token"]}'}

    def get(self, path, **params):
        for attempt in (0, 1):
            r = self.cl.get(f'/openapi/v1/{self.conf.get("omada_id", "")}{path}', params=params, headers=self._auth(force=attempt == 1))
            try:
                j = r.json()
            except ValueError:
                raise DriverError(f"Unerwartete Antwort des Controllers (HTTP {r.status_code})")
            code = j.get("errorCode")
            if code == 0:
                return j.get("result")
            if (code in AUTH_ERRORS or r.status_code == 401) and attempt == 0:
                continue
            raise DriverError(f"Controller meldet Fehler {code}: {j.get('msg', '')}".strip())

    def pages(self, path, size=200):
        rows, page = [], 1
        while True:
            res = self.get(path, page=page, pageSize=size) or {}
            data = res.get("data") or []
            rows += data
            if len(rows) >= int(res.get("totalRows") or 0) or len(data) < size or page > 50:
                return rows
            page += 1


def _sites(api, conf):
    sites = api.pages("/sites")
    want = (conf.get("site") or "").strip().lower()
    if want:
        sites = [s for s in sites if str(s.get("name", "")).lower() == want]
        if not sites:
            raise DriverError(f"Site „{conf['site']}“ nicht gefunden")
    return sites


def _online(d):
    if d.get("statusCategory") is not None:
        return d["statusCategory"] == 1
    return bool(d.get("status"))


def normalize(sites):
    """sites = [(site, devices, clients)] -> (devices, clients) einheitlich"""
    devices, clients = [], []
    for _site, devs, cls in sites:
        for d in devs:
            port = d.get("uplinkDevicePort")
            devices.append(dict(mac=mac(d.get("mac")), ip=d.get("ip") or "", name=d.get("name") or d.get("model") or "", model=d.get("model") or "",
                                type=TYPES.get(str(d.get("type", "")).lower(), "other"), online=_online(d),
                                uplink_mac=mac(d.get("uplinkDeviceMac")), uplink_port=int(port) if str(port or "").isdigit() else None,
                                clients=int(d.get("clientNum") or 0), firmware=d.get("firmwareVersion") or "", ports=[],
                                firmware_info=dict(installed=d.get("firmwareVersion") or "", latest="",
                                                   update=bool(d.get("needUpgrade")) if "needUpgrade" in d else None)))
        for x in cls:
            wl = bool(x.get("wireless"))
            parent = mac(x.get("apMac")) if wl else mac(x.get("switchMac") or x.get("gatewayMac"))
            port = x.get("port")
            clients.append(dict(mac=mac(x.get("mac")), ip=x.get("ip") or "", name=x.get("name") or x.get("hostName") or "",
                                online=x.get("active", True) is not False, medium="wlan" if wl else "lan", parent_mac=parent,
                                port=int(port) if not wl and str(port or "").isdigit() else None,
                                band=RADIO.get(x.get("radioId"), "") if wl else "", ssid=x.get("ssid") or "", vendor=x.get("vendor") or "",
                                _down=x.get("trafficDown"), _up=x.get("trafficUp")))
    return devices, clients


def _collect(conf, state):
    with _client(conf) as cl:
        api = _Api(cl, conf, state)
        out = []
        for s in _sites(api, conf):
            sid = s.get("siteId") or s.get("id")
            out.append((s, api.pages(f"/sites/{sid}/devices"), api.pages(f"/sites/{sid}/clients")))
        return out


def test(conf):
    sites = _collect(conf, {})
    devices, clients = normalize(sites)
    return dict(sites=", ".join(s.get("name", "") for s, _, _ in sites), devices=len(devices), clients=len(clients))


def poll(conf, state):
    state = dict(state)
    sites = _collect(conf, state)
    devices, clients = normalize(sites)
    state["client_counters"] = counter_rates(clients, state.get("client_counters") or {}, time.time())
    info = dict(controller="Omada", sites=[s.get("name", "") for s, _, _ in sites])
    return dict(info=info, devices=devices, clients=clients), {}, state
