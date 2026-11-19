"""Treiber Proxmox VE (API-Token, nur lesen): Knoten, VMs und LXCs mit Status, MAC, Bridge, VLAN-Tag und IP-Adressen.

Einrichtung (einmal auf einem Knoten):
  pveum role add DiktyoRead -privs "VM.Audit,VM.GuestAgent.Audit,Sys.Audit,Datastore.Audit,SDN.Audit"
  pveum user add diktyo@pve && pveum acl modify / --users diktyo@pve --roles DiktyoRead
  pveum user token add diktyo@pve diktyo --privsep 1 && pveum acl modify / --tokens 'diktyo@pve!diktyo' --roles DiktyoRead
"""
import ipaddress
import re

import httpx

NAME = "Proxmox VE"
DEFAULT_INTERVAL = 300
FIELDS = [
    dict(key="host", label="Adresse", type="text", default="", required=True),
    dict(key="port", label="Port", type="number", default=8006),
    dict(key="username", label="Token-ID (z. B. diktyo@pve!diktyo)", type="text", default="diktyo@pve!diktyo", required=True),
    dict(key="password", label="Token-Secret", type="password", default="", secret=True),
    dict(key="verify", label="Zertifikat prüfen", type="select", default="no", options=[["no", "nein (selbstsigniert)"], ["yes", "ja"]]),
]
NET_RE = re.compile(r"^net\d+$")


class DriverError(Exception):
    pass


def _client(conf):
    tid, secret = conf.get("username") or "", conf.get("password") or ""
    if "!" not in tid or not secret:
        raise DriverError("Token-ID (benutzer@realm!name) und Token-Secret angeben")
    return httpx.Client(base_url=f'https://{conf["host"]}:{int(conf.get("port") or 8006)}/api2/json', timeout=12,
                        verify=conf.get("verify") == "yes", headers={"Authorization": f"PVEAPIToken={tid}={secret}"})


def _get(cl, path):
    try:
        r = cl.get(path)
    except httpx.HTTPError as ex:
        raise DriverError(f"Proxmox nicht erreichbar: {ex}")
    if r.status_code == 401:
        raise DriverError("Token abgelehnt (Token-ID oder Secret falsch)")
    if r.status_code == 403:
        raise PermissionError(path)
    r.raise_for_status()
    return r.json().get("data")


def parse_net(value):
    """'virtio=BC:24:11:..,bridge=vmbr0,tag=10' (VM) bzw. 'name=eth0,bridge=vmbr0,hwaddr=..,ip=192.168.50.16/24' (LXC)."""
    out = {}
    for part in str(value).split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    mac = out.get("hwaddr") or next((v for k, v in out.items() if re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", v)), "")
    ip = out.get("ip", "")
    return dict(mac=mac.upper(), bridge=out.get("bridge", ""), tag=out.get("tag", ""), name=out.get("name", ""),
                ip=ip.split("/")[0] if ip and ip not in ("dhcp", "manual") and "/" in ip else "", ip_mode=ip)


def _usable(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.version == 4 and not (a.is_loopback or a.is_link_local)
    except ValueError:
        return False


def action(conf, state, kind, params):
    """kind: vm (node, kind=qemu|lxc, vmid, op=start|shutdown|reboot) -> Meldung. Braucht VM.PowerMgmt."""
    op = params.get("op")
    if kind != "vm" or op not in ("start", "shutdown", "reboot") or params.get("kind") not in ("qemu", "lxc"):
        raise DriverError("Unbekannte Aktion")
    with _client(conf) as cl:
        try:
            r = cl.post(f'/nodes/{params["node"]}/{params["kind"]}/{int(params["vmid"])}/status/{op}')
        except httpx.HTTPError as ex:
            raise DriverError(f"Proxmox nicht erreichbar: {ex}")
    if r.status_code in (401, 403):
        raise DriverError("Token darf VMs nicht schalten. Auf dem Proxmox-Knoten: pveum role add DiktyoPower -privs VM.PowerMgmt && "
                          "pveum acl modify / --tokens 'diktyo@pve!diktyo' --roles DiktyoPower")
    if r.status_code >= 400:
        raise DriverError(f"Proxmox meldet Fehler {r.status_code}: {r.text[:160]}")
    return {"start": "wird gestartet", "shutdown": "wird heruntergefahren", "reboot": "wird neu gestartet"}[op]


def test(conf):
    with _client(conf) as cl:
        v = _get(cl, "/version")
        res = _get(cl, "/cluster/resources?type=vm") or []
    return dict(version=v.get("version", ""), guests=len([g for g in res if not g.get("template")]))


def poll(conf, state):
    warn = ""
    with _client(conf) as cl:
        version = (_get(cl, "/version") or {}).get("version", "")
        try:
            status = _get(cl, "/cluster/status") or []
        except PermissionError:
            status = []
        nodes = [dict(name=n["name"], ip=n.get("ip", ""), online=bool(n.get("online", 1))) for n in status if n.get("type") == "node"]
        if not nodes:
            nodes = [dict(name=n["node"], ip="", online=n.get("status") == "online") for n in _get(cl, "/nodes") or []]
        guests = []
        for g in _get(cl, "/cluster/resources?type=vm") or []:
            if g.get("template"):
                continue
            kind = g.get("type")  # qemu | lxc
            path = f'/nodes/{g["node"]}/{kind}/{g["vmid"]}'
            try:
                cfg = _get(cl, f"{path}/config") or {}
            except PermissionError:
                cfg = {}
                warn = "Keine Berechtigung für die VM-Konfiguration (Rolle mit VM.Audit nötig)"
            nets = [parse_net(v) for k, v in sorted(cfg.items()) if NET_RE.match(k)]
            ips = [n["ip"] for n in nets if n["ip"]]
            if g.get("status") == "running":
                try:
                    if kind == "qemu" and str(cfg.get("agent", "0")).split(",")[0] in ("1", "enabled=1"):
                        for i in (_get(cl, f"{path}/agent/network-get-interfaces") or {}).get("result", []):
                            ips += [a["ip-address"] for a in i.get("ip-addresses", []) if _usable(a.get("ip-address", ""))]
                    elif kind == "lxc":
                        for i in _get(cl, f"{path}/interfaces") or []:
                            if i.get("inet"):
                                ips.append(i["inet"].split("/")[0])
                except (PermissionError, httpx.HTTPError, DriverError):
                    pass  # Gast-Agent nicht aktiv oder keine Berechtigung (VM.GuestAgent.Audit)
            guests.append(dict(vmid=g["vmid"], name=g.get("name") or f'{kind}-{g["vmid"]}', node=g["node"], kind=kind,
                               running=g.get("status") == "running", nets=nets, ips=[ip for ip in dict.fromkeys(ips) if _usable(ip)],
                               _down=g.get("netin"), _up=g.get("netout")))
    import time as _tm
    from .controller import counter_rates
    state = dict(state, guest_counters=counter_rates(guests, state.get("guest_counters") or {}, _tm.time(), key="vmid"))
    res = dict(info=dict(version=version, nodes=len(nodes)), nodes=nodes, guests=guests)
    # Paket-Updates je Knoten (höchstens alle 6 Stunden; braucht Sys.Audit bzw. Sys.Modify – ohne Recht einfach weglassen)
    import time as _t
    if _t.time() - state.get("apt_checked", 0) >= 6 * 3600:
        fw = []
        with _client(conf) as cl:
            for n in nodes:
                try:
                    pk = _get(cl, f"/nodes/{n['name']}/apt/update") or []
                except (PermissionError, DriverError, httpx.HTTPError):
                    continue
                pve = next((p for p in pk if p.get("Package") == "pve-manager"), None)
                fw.append(dict(node=n["name"], installed=version, latest=(pve or {}).get("Version", "") or (f"{len(pk)} Paket-Updates" if pk else ""),
                               update=bool(pk), info=""))
        state = dict(state, apt_checked=_t.time(), apt=fw)
    res["nodes_fw"] = state.get("apt") or []
    if warn:
        res["warning"] = warn
    return res, {}, state
