"""Treiber FRITZ!Box (TR-064, nur lesen).

Ohne Anmeldung: Hosts (MAC, IP, Name, LAN/WLAN, aktiv) und WAN-Übertragungsraten.
Mit einem FRITZ!Box-Benutzer zusätzlich: Mesh-Topologie (welches Gerät an welchem LAN-Port bzw. WLAN hängt), Geräteinfo, WLAN-Netze.
"""
import json

import httpx

NAME = "FRITZ!Box (TR-064)"
DEFAULT_INTERVAL = 60
FIELDS = [
    dict(key="host", label="Adresse", type="text", default="192.168.178.1", required=True),
    dict(key="username", label="Benutzer (optional)", type="text", default=""),
    dict(key="password", label="Passwort (optional)", type="password", default="", secret=True),
    dict(key="cfg_schedule", label="Konfiguration sichern", type="select", default="weekly", options=[
        ["weekly", "wöchentlich"], ["daily", "täglich"], ["no", "nein"]]),
    dict(key="export_pass", label="Passwort für die Konfigurationsdatei (sonst das Anmeldepasswort)", type="password", default="", secret=True),
]
CAN_BACKUP = True


class DriverError(Exception):
    pass


def _connect(conf):
    try:
        from fritzconnection import FritzConnection
    except ImportError:
        raise DriverError("fritzconnection ist nicht installiert")
    try:
        return FritzConnection(address=conf["host"], user=conf.get("username") or None, password=conf.get("password") or None,
                               timeout=8, use_cache=False)
    except Exception as ex:
        raise DriverError(f"FRITZ!Box nicht erreichbar: {ex}")


def _call(fc, svc, act, **kw):
    try:
        return fc.call_action(svc, act, **kw)
    except Exception as ex:
        if "401" in str(ex) or "Authorization" in type(ex).__name__:
            raise PermissionError(str(ex))
        raise


def _fetch(fc, url):
    """Eine von der FRITZ!Box gelieferte Datei (Hostliste, Mesh) mit den TR-064-Zugangsdaten laden."""
    auth = httpx.DigestAuth(fc.soaper.user, fc.soaper.password) if getattr(fc.soaper, "password", None) else None
    if url.startswith("/"):
        url = f"http://{fc.soaper.address.replace('http://', '').replace('https://', '')}:{fc.soaper.port}{url}"
    r = httpx.get(url, auth=auth, timeout=10, verify=False)
    r.raise_for_status()
    return r.text


def _hosts_basic(fc):
    n = int(_call(fc, "Hosts1", "GetHostNumberOfEntries")["NewHostNumberOfEntries"])
    out = []
    for i in range(min(n, 500)):
        try:
            h = _call(fc, "Hosts1", "GetGenericHostEntry", NewIndex=i)
        except PermissionError:
            raise
        except Exception:
            continue
        out.append(dict(ip=h.get("NewIPAddress") or "", mac=(h.get("NewMACAddress") or "").upper(), name=h.get("NewHostName") or "",
                        interface=h.get("NewInterfaceType") or "", active=str(h.get("NewActive")) in ("1", "True", "true"),
                        source=h.get("NewAddressSource") or ""))
    return out


def _mesh(fc):
    path = _call(fc, "Hosts1", "X_AVM-DE_GetMeshListPath")["NewX_AVM-DE_MeshListPath"]
    return parse_mesh(json.loads(_fetch(fc, path)))


def parse_mesh(data):
    """Mesh-Topologie -> {MAC eines Geräts: {"node": MAC der Gegenstelle, "iface": "LAN 3" / "WLAN 5 GHz", "medium", "rate"}}

    Die Gegenstelle ist die Seite einer Verbindung, die näher an der FRITZ!Box (Mesh-Master) liegt."""
    nodes = {n["uid"]: n for n in data.get("nodes", [])}
    if not nodes:
        return {}
    owner = {}
    for n in nodes.values():
        for i in n.get("node_interfaces", []):
            owner[i["uid"]] = (n["uid"], i)
    links, adj = [], {u: set() for u in nodes}
    for n in nodes.values():
        for i in n.get("node_interfaces", []):
            for lk in i.get("node_links", []):
                if lk.get("state") not in ("CONNECTED", None):
                    continue
                a, b = lk.get("node_interface_1_uid"), lk.get("node_interface_2_uid")
                if a in owner and b in owner and owner[a][0] != owner[b][0]:
                    links.append((a, b, lk))
                    adj[owner[a][0]].add(owner[b][0])
                    adj[owner[b][0]].add(owner[a][0])
    master = next((u for u, n in nodes.items() if n.get("mesh_role") == "master"), next(iter(nodes)))
    depth, queue = {master: 0}, [master]
    while queue:
        u = queue.pop(0)
        for v in adj[u]:
            if v not in depth:
                depth[v] = depth[u] + 1
                queue.append(v)
    out = {}
    for a, b, lk in links:
        (na, ia), (nb, ib) = owner[a], owner[b]
        if depth.get(na, 99) == depth.get(nb, 99):
            continue
        (pn, pi), cn = ((na, ia), nb) if depth.get(na, 99) < depth.get(nb, 99) else ((nb, ib), na)
        cmac = (nodes[cn].get("device_mac_address") or "").upper()
        if not cmac or cmac in out:
            continue
        name = pi.get("name") or ""
        if pi.get("type") == "LAN" or name.upper().startswith("LAN"):
            num = "".join(ch for ch in name.split(":")[-1] if ch.isdigit())
            label, medium = (f"LAN {num}" if num else "LAN"), "lan"
        else:
            up = name.upper()
            band = "5 GHz" if "5G" in up else "6 GHz" if "6G" in up else "2,4 GHz"
            label, medium = f"WLAN {band}", "wlan"
        out[cmac] = dict(node=(nodes[pn].get("device_mac_address") or "").upper(), node_name=nodes[pn].get("device_name", ""),
                         iface=label, medium=medium, rate=int(lk.get("cur_data_rate_rx") or 0) // 1000,
                         master=pn == master)
    return out


def _wan(fc):
    out = {}
    try:
        r = _call(fc, "WANCommonIFC1", "GetAddonInfos")
        out["rx_bps"] = int(r.get("NewByteReceiveRate") or 0) * 8
        out["tx_bps"] = int(r.get("NewByteSendRate") or 0) * 8
    except Exception:
        pass
    try:
        r = _call(fc, "WANCommonIFC1", "GetCommonLinkProperties")
        out["max_down"] = int(r.get("NewLayer1DownstreamMaxBitRate") or 0)
        out["max_up"] = int(r.get("NewLayer1UpstreamMaxBitRate") or 0)
        out["link"] = r.get("NewPhysicalLinkStatus", "")
    except Exception:
        pass
    for svc in ("WANIPConn1", "WANPPPConnection1"):
        try:
            r = _call(fc, svc, "GetStatusInfo")
            out["connected"] = r.get("NewConnectionStatus") == "Connected"
            out["uptime"] = int(r.get("NewUptime") or 0)
            break
        except Exception:
            continue
    return out


def _info(fc):
    info = dict(model=getattr(fc, "modelname", "") or "", firmware=getattr(fc, "system_version", "") or "")
    try:
        r = _call(fc, "DeviceInfo1", "GetInfo")
        info.update(serial=r.get("NewSerialNumber", ""), firmware=r.get("NewSoftwareVersion", info["firmware"]), uptime=int(r.get("NewUpTime") or 0))
    except Exception:
        pass
    return info


def _wlan(fc):
    out = []
    for n in range(1, 5):
        try:
            r = _call(fc, f"WLANConfiguration{n}", "GetInfo")
        except Exception:
            break
        out.append(dict(ssid=r.get("NewSSID", ""), channel=r.get("NewChannel"), enabled=str(r.get("NewEnable")) in ("1", "True"),
                        standard=r.get("NewStandard", "")))
    return out


def backup(conf, state):
    """Konfigurationsexport der FRITZ!Box (wie System → Sicherung). -> (Dateiname, Inhalt, Text?)"""
    if not conf.get("password"):
        raise DriverError("Für das Konfigurations-Backup Benutzer und Passwort der FRITZ!Box angeben")
    fc = _connect(conf)
    try:
        r = _call(fc, "DeviceConfig1", "X_AVM-DE_GetConfigFile", **{"NewX_AVM-DE_Password": conf.get("export_pass") or conf["password"]})
    except PermissionError:
        raise DriverError("Benutzer hat nicht das Recht „FRITZ!Box Einstellungen“")
    url = r.get("NewX_AVM-DE_ConfigFileUrl")
    if not url:
        raise DriverError("FRITZ!Box hat keine Konfigurationsdatei geliefert")
    data = _fetch(fc, url).encode("utf-8")
    model = (getattr(fc, "modelname", "") or "FRITZ.Box").replace(" ", "_").replace("!", "")
    return f"{model}.export", data, True


def test(conf):
    fc = _connect(conf)
    res = dict(model=getattr(fc, "modelname", ""), firmware=getattr(fc, "system_version", ""))
    try:
        res["hosts"] = int(_call(fc, "Hosts1", "GetHostNumberOfEntries")["NewHostNumberOfEntries"])
    except PermissionError:
        raise DriverError("Die FRITZ!Box verlangt eine Anmeldung. Benutzer und Passwort angeben.")
    try:
        _call(fc, "Hosts1", "X_AVM-DE_GetMeshListPath")
        res["auth"] = True
    except Exception:
        res["auth"] = False
    return res


def poll(conf, state):
    fc = _connect(conf)
    res = dict(info=_info(fc), wan=_wan(fc), auth=False, mesh={}, wlan=[])
    try:
        res["hosts"] = _hosts_basic(fc)
    except PermissionError:
        raise DriverError("Die FRITZ!Box verlangt eine Anmeldung. Benutzer und Passwort angeben.")
    if conf.get("password"):
        try:
            res["mesh"] = _mesh(fc)
            res["auth"] = True
        except PermissionError:
            res["warning"] = "Anmeldung abgelehnt: Mesh-Topologie und WLAN-Daten fehlen. Benutzerrechte prüfen (FRITZ!Box-Einstellungen)."
        except Exception as ex:
            res["warning"] = f"Mesh-Topologie nicht lesbar: {ex}"
        res["wlan"] = _wlan(fc)
    metrics = {}
    if "rx_bps" in res["wan"]:
        metrics = {"wan:rx": res["wan"]["rx_bps"], "wan:tx": res["wan"]["tx_bps"]}
    return res, metrics, state
