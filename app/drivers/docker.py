"""Treiber Docker (Engine-API) – Container als virtuelle Geräte am Docker-Host.

Empfohlen über einen Socket-Proxy (z. B. tecnativa/docker-socket-proxy), der nur die nötigen Bereiche freigibt:
lesen CONTAINERS, INFO, VERSION, NETWORKS; für Aktionen zusätzlich POST, ALLOW_START, ALLOW_STOP, ALLOW_RESTARTS.
Den Docker-Socket selbst nie ungeschützt ins Netz geben.

Liest: Docker-Version und Host, Container mit Name, Image, Zustand, Netzwerken (IP, MAC) und veröffentlichten Ports.
Schalten: Container starten, stoppen, neu starten. díktyo selbst und der Socket-Proxy werden nicht gestoppt.
"""
import socket

import httpx

from .controller import DriverError, mac as norm_mac

NAME = "Docker"
DEFAULT_INTERVAL = 60
FIELDS = [
    dict(key="host", label="Adresse des Docker-Hosts bzw. Socket-Proxys", type="text", default="", required=True, placeholder="z. B. 192.168.50.20"),
    dict(key="port", label="Port", type="number", default=2375),
    dict(key="scheme", label="Protokoll", type="select", default="http", options=[["http", "HTTP (Socket-Proxy im eigenen Netz)"], ["https", "HTTPS"]]),
    dict(key="only_lan", label="Container anlegen", type="select", default="all", options=[
        ["all", "alle Container"], ["lan", "nur Container mit eigener IP im Heimnetz (macvlan/ipvlan/host)"]]),
]
PROTECT = ("docker-socket-proxy", "socket-proxy", "diktyo")


def _client(conf):
    scheme = conf.get("scheme") or "http"
    return httpx.Client(base_url=f'{scheme}://{conf["host"]}:{int(conf.get("port") or 2375)}', verify=False, timeout=15)


def _get(cl, path, optional=False):
    try:
        r = cl.get(path)
    except httpx.HTTPError as ex:
        raise DriverError(f"Docker-API nicht erreichbar ({ex}) – Socket-Proxy gestartet und Port freigegeben?")
    if r.status_code == 403:
        if optional:
            return None
        raise DriverError(f"Socket-Proxy verweigert {path} – dort den Bereich freigeben (z. B. CONTAINERS=1)")
    if r.status_code >= 400:
        if optional:
            return None
        raise DriverError(f"Docker meldet Fehler {r.status_code} bei {path}")
    try:
        return r.json()
    except ValueError:
        raise DriverError("Unerwartete Antwort – ist das die Docker-Engine-API?")


def _lan_ip(ip):
    import ipaddress
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    # Standard-Bridge-Netze von Docker (172.16/12) gelten als intern
    return a.version == 4 and a.is_private and a not in ipaddress.ip_network("172.16.0.0/12")


def collect(conf):
    with _client(conf) as cl:
        return dict(version=_get(cl, "/version"), info=_get(cl, "/info", optional=True) or {},
                    containers=_get(cl, "/containers/json?all=1") or [])


def normalize(raw, conf):
    v, info = raw["version"] or {}, raw["info"] or {}
    host = dict(name=info.get("Name") or "", version=v.get("Version") or "", os=info.get("OperatingSystem") or v.get("Os") or "",
                cpus=info.get("NCPU"), memory=info.get("MemTotal"), running=info.get("ContainersRunning"), total=info.get("Containers"))
    out = []
    for ct in raw["containers"]:
        name = ((ct.get("Names") or ["/?"])[0]).lstrip("/")
        nets = (ct.get("NetworkSettings") or {}).get("Networks") or {}
        ips, mac = [], ""
        for nname, n in nets.items():
            if n.get("IPAddress"):
                ips.append(n["IPAddress"])
            mac = mac or norm_mac(n.get("MacAddress"))
        mode = ((ct.get("HostConfig") or {}).get("NetworkMode")) or ""
        lan = any(_lan_ip(ip) for ip in ips)
        if mode == "host" and conf.get("host"):
            ips, lan = [conf["host"]], True
        if conf.get("only_lan") == "lan" and not lan:
            continue
        ports = sorted({f'{p.get("PublicPort")}→{p.get("PrivatePort")}/{p.get("Type", "tcp")}' for p in ct.get("Ports") or [] if p.get("PublicPort")})
        out.append(dict(id=ct.get("Id", "")[:64], name=name, image=ct.get("Image", ""), state=ct.get("State", ""), status=ct.get("Status", ""),
                        running=ct.get("State") == "running", ips=[ip for ip in ips if _lan_ip(ip) or mode == "host"], all_ips=ips, mac=mac if lan else "",
                        network=mode, ports=ports, compose=(ct.get("Labels") or {}).get("com.docker.compose.project", "")))
    return host, out


def test(conf):
    raw = collect(conf)
    host, cts = normalize(raw, conf)
    return dict(version=host["version"], os=host["os"], containers=len(cts), running=sum(1 for c in cts if c["running"]))


def poll(conf, state):
    raw = collect(conf)
    host, cts = normalize(raw, conf)
    return dict(info=host, containers=cts), {}, state


def protected(c):
    """Container, die díktyo nicht stoppt: díktyo selbst (Hostname = Container-ID) und der Socket-Proxy."""
    me = socket.gethostname()
    if c["id"].startswith(me) and len(me) >= 12:
        return "díktyo läuft in diesem Container."
    if any(p in (c["image"] or "").lower() or p in c["name"].lower() for p in PROTECT):
        return "Über diesen Container erreicht díktyo Docker (bzw. es ist díktyo selbst)."
    return ""


def action(conf, state, kind, params):
    """kind: container (id, op=start|stop|restart)"""
    op = params.get("op")
    if kind != "container" or op not in ("start", "stop", "restart"):
        raise DriverError("Unbekannte Aktion")
    with _client(conf) as cl:
        try:
            r = cl.post(f'/containers/{params["id"]}/{op}', params={"t": 20} if op != "start" else None, timeout=60)
        except httpx.HTTPError as ex:
            raise DriverError(f"Docker-API nicht erreichbar: {ex}")
    if r.status_code == 403:
        raise DriverError("Socket-Proxy erlaubt das nicht – dort POST=1 sowie ALLOW_START/ALLOW_STOP/ALLOW_RESTARTS=1 setzen")
    if r.status_code == 304:
        return f"Container „{params.get('name', '')}“ war schon {'gestartet' if op == 'start' else 'gestoppt'}"
    if r.status_code >= 400:
        raise DriverError(f"Docker meldet Fehler {r.status_code}: {r.text[:160]}")
    return f"Container „{params.get('name', '')}“ {'gestartet' if op == 'start' else 'gestoppt' if op == 'stop' else 'neu gestartet'}"
