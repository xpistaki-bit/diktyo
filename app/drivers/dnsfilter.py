"""Treiber Pi-hole / AdGuard Home: Hostnamen der Geräte, Anfragen und Blockierte je Gerät, Gesamtstatistik, Werbeblocker
pausieren.

Pi-hole v6: REST unter /api. Anmeldung POST /api/auth mit dem (App-)Passwort -> Sitzung (sid); die Sitzung wird im Zustand
gemerkt und wiederverwendet, weil Pi-hole die Zahl gleichzeitiger Sitzungen begrenzt. Pi-hole v5 (alte api.php mit Token)
liefert nur Zusammenfassung und Top-Clients.
AdGuard Home: /control/* mit Basic-Auth. Blockierte je Client stammen aus den letzten Einträgen des Abfrage-Protokolls
(AdGuard führt dazu keine Statistik).

Gespeichert werden nur Zahlen je Gerät und die meistblockierten Domains insgesamt – keine besuchten Domains einzelner Geräte.
"""
import time

import httpx

from .controller import DriverError, mac as norm_mac

NAME = "Pi-hole / AdGuard Home"
DEFAULT_INTERVAL = 300
FIELDS = [
    dict(key="kind", label="Art", type="select", default="pihole", options=[["pihole", "Pi-hole"], ["adguard", "AdGuard Home"]]),
    dict(key="host", label="Adresse", type="text", default="", required=True, placeholder="z. B. 192.168.1.53"),
    dict(key="port", label="Port", type="number", default=80),
    dict(key="scheme", label="Protokoll", type="select", default="http", options=[["http", "HTTP"], ["https", "HTTPS"]]),
    dict(key="username", label="Benutzer (nur AdGuard Home)", type="text", default="", show=dict(kind="adguard")),
    dict(key="password", label="Passwort (Pi-hole: App-Passwort bzw. Web-Passwort)", type="password", default="", secret=True),
]
TOP = 50
QUERYLOG = 1000


def _client(conf):
    return httpx.Client(base_url=f'{conf.get("scheme") or "http"}://{conf["host"]}:{int(conf.get("port") or 80)}', verify=False, timeout=10,
                        auth=httpx.BasicAuth(conf.get("username") or "", conf.get("password") or "") if conf.get("kind") == "adguard" else None)


def _json(r, what):
    if r.status_code in (401, 403):
        raise DriverError(f"{what}: Anmeldung abgelehnt – Passwort prüfen")
    if r.status_code >= 400:
        raise DriverError(f"{what}: HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise DriverError(f"{what}: keine JSON-Antwort (Adresse/Port richtig?)")


# ------------------------------------------------------------ Pi-hole v6
class _Pihole:
    def __init__(self, cl, conf, state):
        self.cl, self.conf, self.state = cl, conf, state

    def _login(self):
        r = self.cl.post("/api/auth", json={"password": self.conf.get("password") or ""})
        if r.status_code == 404:
            raise LookupError("v5")
        j = _json(r, "Pi-hole")
        s = j.get("session") or {}
        if not s.get("valid"):
            raise DriverError("Pi-hole: Anmeldung abgelehnt – App-Passwort (Einstellungen → Web-Oberfläche/API) prüfen")
        self.state["sid"] = s.get("sid") or ""
        self.state["sid_exp"] = time.time() + int(s.get("validity") or 300) - 30

    def get(self, path, **params):
        for attempt in (0, 1):
            if attempt or not self.state.get("sid_exp") or self.state["sid_exp"] < time.time():
                self._login()
            h = {"X-FTL-SID": self.state["sid"]} if self.state.get("sid") else {}
            r = self.cl.get(path, params=params, headers=h)
            if r.status_code == 401 and attempt == 0:
                continue
            j = _json(r, "Pi-hole")
            self.state["sid_exp"] = time.time() + 1500  # jede Anfrage verlängert die Sitzung
            return j

    def post(self, path, body):
        if not self.state.get("sid_exp") or self.state["sid_exp"] < time.time():
            self._login()
        h = {"X-FTL-SID": self.state["sid"]} if self.state.get("sid") else {}
        return _json(self.cl.post(path, json=body, headers=h), "Pi-hole")


def _pihole(conf, state):
    with _client(conf) as cl:
        api = _Pihole(cl, conf, state)
        try:
            ver = api.get("/api/info/version").get("version") or {}
        except LookupError:  # keine /api: Pi-hole v5
            return _pihole_v5(cl, conf)
        summ = api.get("/api/stats/summary")
        allq = api.get("/api/stats/top_clients", blocked="false", count=TOP).get("clients") or []
        blk = api.get("/api/stats/top_clients", blocked="true", count=TOP).get("clients") or []
        doms = api.get("/api/stats/top_domains", blocked="true", count=10).get("domains") or []
        blocking = api.get("/api/dns/blocking")
        try:
            devs = api.get("/api/network/devices", max_devices=500, max_addresses=5).get("devices") or []
        except DriverError:
            devs = []
        try:
            leases = api.get("/api/dhcp/leases").get("leases") or []
        except DriverError:
            leases = []
    names = {}
    for d in devs:
        for a in d.get("ips") or []:
            if a.get("ip"):
                names[a["ip"]] = dict(mac=norm_mac(d.get("hwaddr")), name=a.get("name") or "")
    for l in leases:
        if l.get("ip"):
            names.setdefault(l["ip"], dict(mac=norm_mac(l.get("hwaddr")), name=""))
            if l.get("name") and l["name"] != "*":
                names[l["ip"]]["name"] = names[l["ip"]]["name"] or l["name"]
    clients = {}
    for c in allq:
        clients[c["ip"]] = dict(ip=c["ip"], name=c.get("name") or "", queries=int(c.get("count") or 0), blocked=0)
    for c in blk:
        clients.setdefault(c["ip"], dict(ip=c["ip"], name=c.get("name") or "", queries=0, blocked=0))["blocked"] = int(c.get("count") or 0)
    q = summ.get("queries") or {}
    core = ((ver.get("core") or {}).get("local") or {}).get("version") or ((ver.get("ftl") or {}).get("local") or {}).get("version") or ""
    return _result("pihole", core, blocking.get("blocking") == "enabled", int(q.get("total") or 0), int(q.get("blocked") or 0),
                   int((summ.get("gravity") or {}).get("domains_being_blocked") or 0), clients, names,
                   [dict(domain=d.get("domain", ""), count=int(d.get("count") or 0)) for d in doms], window="24 h")


def _pihole_v5(cl, conf):
    tok = conf.get("password") or ""
    summ = _json(cl.get("/admin/api.php", params={"summaryRaw": "", "auth": tok}), "Pi-hole v5")
    src = _json(cl.get("/admin/api.php", params={"getQuerySources": TOP, "auth": tok}), "Pi-hole v5").get("top_sources") or {}
    blk = _json(cl.get("/admin/api.php", params={"topClientsBlocked": TOP, "auth": tok}), "Pi-hole v5").get("top_sources_blocked") or {}
    clients, names = {}, {}
    for key, n in src.items():
        name, _, ip = key.partition("|")
        ip = ip or name
        clients[ip] = dict(ip=ip, name=name if ip != name else "", queries=int(n), blocked=0)
        if ip != name:
            names[ip] = dict(mac="", name=name)
    for key, n in blk.items():
        name, _, ip = key.partition("|")
        clients.setdefault(ip or name, dict(ip=ip or name, name="", queries=0, blocked=0))["blocked"] = int(n)
    return _result("pihole", "v5", summ.get("status") == "enabled", int(summ.get("dns_queries_today") or 0), int(summ.get("ads_blocked_today") or 0),
                   int(summ.get("domains_being_blocked") or 0), clients, names, [], window="heute")


# ------------------------------------------------------------ AdGuard Home
def _adguard(conf, state):
    with _client(conf) as cl:
        st = _json(cl.get("/control/status"), "AdGuard Home")
        stats = _json(cl.get("/control/stats"), "AdGuard Home")
        try:
            cls = _json(cl.get("/control/clients"), "AdGuard Home")
        except DriverError:
            cls = {}
        try:
            dhcp = _json(cl.get("/control/dhcp/status"), "AdGuard Home")
        except DriverError:
            dhcp = {}
        try:
            log = _json(cl.get("/control/querylog", params={"limit": QUERYLOG, "response_status": "blocked"}), "AdGuard Home").get("data") or []
        except DriverError:
            log = []
    names = {}
    for a in cls.get("auto_clients") or []:
        if a.get("ip") and a.get("name"):
            names[a["ip"]] = dict(mac="", name=a["name"])
    for c in cls.get("clients") or []:
        for i in c.get("ids") or []:
            if i.count(".") == 3 and "/" not in i:
                names[i] = dict(mac=names.get(i, {}).get("mac", ""), name=c.get("name") or "")
    for l in (dhcp.get("leases") or []) + (dhcp.get("static_leases") or []):
        if l.get("ip"):
            n = names.setdefault(l["ip"], dict(mac="", name=""))
            n["mac"] = norm_mac(l.get("mac")) or n["mac"]
            n["name"] = n["name"] or l.get("hostname") or ""
    clients = {}
    for item in stats.get("top_clients") or []:
        for ip, n in item.items():
            clients[ip] = dict(ip=ip, name="", queries=int(n), blocked=0)
    for e in log:
        ip = e.get("client")
        if ip:
            clients.setdefault(ip, dict(ip=ip, name=(e.get("client_info") or {}).get("name") or "", queries=0, blocked=0))["blocked"] += 1
    doms = [dict(domain=d, count=int(n)) for item in (stats.get("top_blocked_domains") or [])[:10] for d, n in item.items()]
    window = f"letzte {len(log)} blockierte Anfragen" if len(log) >= QUERYLOG else "Abfrage-Protokoll"
    return _result("adguard", st.get("version", ""), bool(st.get("protection_enabled")), int(stats.get("num_dns_queries") or 0),
                   int(stats.get("num_blocked_filtering") or 0), None, clients, names, doms, window=window)


# ------------------------------------------------------------ gemeinsam
def _result(kind, version, blocking, total, blocked, listed, clients, names, top_domains, window):
    out = []
    for ip, c in clients.items():
        n = names.get(ip) or {}
        name = n.get("name") or c.get("name") or ""
        out.append(dict(ip=ip, mac=n.get("mac", ""), name="" if name == ip else name, queries=c["queries"], blocked=c["blocked"],
                        pct=round(100 * c["blocked"] / c["queries"], 1) if c["queries"] else None))
    for ip, n in names.items():  # Geräte ohne Anfragen im Zeitraum, aber mit Namen (für die Hostnamen)
        if ip not in clients and n.get("name"):
            out.append(dict(ip=ip, mac=n.get("mac", ""), name=n["name"], queries=0, blocked=0, pct=None))
    out.sort(key=lambda x: -x["queries"])
    return dict(info=dict(kind=kind, version=version, blocking=blocking, window=window),
                summary=dict(queries=total, blocked=blocked, pct=round(100 * blocked / total, 1) if total else 0, listed=listed),
                clients=out, top_domains=top_domains)


def test(conf):
    res = (_adguard if conf.get("kind") == "adguard" else _pihole)(conf, {})
    return dict(kind=res["info"]["kind"], version=res["info"]["version"], queries=res["summary"]["queries"], blocked=res["summary"]["blocked"],
                clients=len(res["clients"]), names=sum(1 for c in res["clients"] if c["name"]))


def poll(conf, state):
    state = dict(state)
    res = (_adguard if conf.get("kind") == "adguard" else _pihole)(conf, state)
    s = res["summary"]
    metrics = {"dns:blocked_pct": s["pct"]}
    prev = state.get("dns_prev")
    now = time.time()
    if prev and s["queries"] >= prev[0] and now > prev[2]:  # Anfragen je Minute aus dem Tageszähler
        dt = (now - prev[2]) / 60
        metrics["dns:qpm"] = round((s["queries"] - prev[0]) / dt, 1)
        metrics["dns:bpm"] = round(max(0, s["blocked"] - prev[1]) / dt, 1)
    state["dns_prev"] = [s["queries"], s["blocked"], now]
    return res, metrics, state


def action(conf, state, kind, params):
    if kind != "dns_blocking":
        raise DriverError(f"Unbekannte Aktion {kind}")
    on = bool(params["on"])
    if conf.get("kind") == "adguard":
        with _client(conf) as cl:
            r = cl.post("/control/protection", json={"enabled": on})
            if r.status_code == 404:  # ältere Versionen
                r = cl.post("/control/dns_config", json={"protection_enabled": on})
            if r.status_code >= 400:
                raise DriverError(f"AdGuard Home: HTTP {r.status_code}")
        return f"AdGuard-Schutz {'eingeschaltet' if on else 'ausgeschaltet'}"
    with _client(conf) as cl:
        _Pihole(cl, conf, state).post("/api/dns/blocking", {"blocking": on, "timer": None})
    return f"Pi-hole-Werbeblocker {'eingeschaltet' if on else 'ausgeschaltet'}"
