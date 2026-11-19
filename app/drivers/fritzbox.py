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
    dict(key="totp_secret", label="Authenticator-Schlüssel (optional, für automatische Sicherungen)", type="password", default="",
         secret=True, placeholder="Base32-Schlüssel aus der FRITZ!Box"),
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
        out.append(dict(index=n, ssid=r.get("NewSSID", ""), channel=r.get("NewChannel"), enabled=str(r.get("NewEnable")) in ("1", "True"),
                        standard=r.get("NewStandard", "")))
    return out


# ------------------------------------------------------------ Zweiter Faktor (TR-064 X_AVM-DE_Auth)
class SecondFactorRequired(DriverError):
    """Die Aktion braucht eine Bestätigung an der FRITZ!Box (Taste oder Telefon-Code)."""


SF_ERRORS = {"866": None, "867": "Bestätigung an der FRITZ!Box gesperrt (zu viele Versuche) – bis zu 60 Minuten warten",
             "868": "Die FRITZ!Box wartet gerade auf eine andere Bestätigung – in zwei Minuten erneut versuchen"}
SF_STATES = {"disabled", "waitingforauth", "anotherauthprocess", "authenticated", "stopped", "blocked", "failure"}


def _soap(fc, svc, act, args=None, token=None):
    """TR-064-Aufruf mit optionalem Token des zweiten Faktors im SOAP-Header (fritzconnection kann keine eigenen Header)."""
    import re
    from xml.sax.saxutils import escape
    s = fc.services[svc]
    stype = s.serviceType
    body = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in (args or {}).items())
    head = (f'<s:Header><avm:token xmlns:avm="avm.de" s:mustUnderstand="1">{escape(token)}</avm:token></s:Header>' if token else "")
    env = (f'<?xml version="1.0" encoding="utf-8"?><s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" '
           f'xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">{head}<s:Body><u:{act} xmlns:u="{stype}">{body}</u:{act}></s:Body></s:Envelope>')
    auth = httpx.DigestAuth(fc.soaper.user, fc.soaper.password) if getattr(fc.soaper, "password", None) else None
    base = fc.soaper.address if fc.soaper.address.startswith("http") else f"http://{fc.soaper.address}"
    r = httpx.post(f"{base}:{fc.soaper.port}{s.controlURL}", content=env.encode(), auth=auth, timeout=10, verify=False,
                   headers={"Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f"{stype}#{act}"})
    if r.status_code == 401:
        raise PermissionError("401")
    code = re.search(r"<errorCode>(\d+)</errorCode>", r.text)
    if r.status_code >= 400 or code:
        c = code.group(1) if code else str(r.status_code)
        if c == "866":
            raise SecondFactorRequired("Die FRITZ!Box verlangt eine Bestätigung (zweiter Faktor)")
        if c in SF_ERRORS:
            raise DriverError(SF_ERRORS[c])
        if c in ("606", "401"):
            raise PermissionError(c)
        desc = re.search(r"<errorDescription>([^<]*)</errorDescription>", r.text)
        raise DriverError(f"FRITZ!Box meldet Fehler {c}{': ' + desc.group(1) if desc else ''}")
    return {m.group(1): m.group(2) for m in re.finditer(r"<(New[\w-]+)>([^<]*)</\1>", r.text)}


def second_factor_start(conf, state):
    """Bestätigung an der FRITZ!Box anfordern. -> dict(state, methods=[...], dtmf)"""
    fc = _connect(conf)
    r = _soap(fc, "X_AVM-DE_Auth1", "SetConfig", {"NewAction": "start"})
    state["sf_token"] = r.get("NewToken", "")
    methods = [m.strip() for m in (r.get("NewMethods") or "").split(",") if m.strip()]
    dtmf = next((m.split(";", 1)[1] for m in methods if m.startswith("dtmf;")), "")
    return dict(state=r.get("NewState", ""), button=any(m.startswith("button") for m in methods), dtmf=dtmf)


def second_factor_state(conf, state):
    if not state.get("sf_token"):
        return "stopped"
    st = _soap(_connect(conf), "X_AVM-DE_Auth1", "GetState", token=state["sf_token"]).get("NewState", "")
    return st if st in SF_STATES else "failure"


def second_factor_stop(conf, state):
    if state.get("sf_token"):
        try:
            _soap(_connect(conf), "X_AVM-DE_Auth1", "SetConfig", {"NewAction": "stop"}, token=state["sf_token"])
        except (DriverError, PermissionError, httpx.HTTPError):
            pass
    state.pop("sf_token", None)


# ------------------------------------------------------------ Weboberfläche (für den Code aus der Authenticator-App)
def _web_response(challenge, password):
    """Antwort auf die Anmelde-Challenge der Weboberfläche (PBKDF2 ab FRITZ!OS 7.24, sonst MD5)."""
    import hashlib
    if challenge.startswith("2$"):
        _, it1, salt1, it2, salt2 = challenge.split("$")
        h1 = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt1), int(it1))
        return f"{salt2}${hashlib.pbkdf2_hmac('sha256', h1, bytes.fromhex(salt2), int(it2)).hex()}"
    return f"{challenge}-{hashlib.md5(f'{challenge}-{password}'.encode('utf-16le')).hexdigest()}"


def _web_login(cl, conf):
    import re
    r = cl.get("/login_sid.lua", params={"version": "2"})
    ch = re.search(r"<Challenge>([^<]+)</Challenge>", r.text)
    if not ch:
        raise DriverError("Weboberfläche der FRITZ!Box nicht erreichbar")
    block = re.search(r"<BlockTime>(\d+)</BlockTime>", r.text)
    if block and int(block.group(1)) > 0:
        raise DriverError(f"Anmeldung an der FRITZ!Box für {block.group(1)} s gesperrt – kurz warten")
    r = cl.post("/login_sid.lua", params={"version": "2"},
                data={"username": conf.get("username") or "", "response": _web_response(ch.group(1), conf.get("password") or "")})
    sid = re.search(r"<SID>([0-9a-f]{16})</SID>", r.text)
    if not sid or set(sid.group(1)) == {"0"}:
        raise DriverError("Anmeldung an der Weboberfläche der FRITZ!Box abgelehnt (Benutzer/Passwort prüfen)")
    return sid.group(1)


def _web_client(conf):
    return httpx.Client(base_url=f"http://{conf['host']}", timeout=20, verify=False, follow_redirects=True)


def backup_web_totp(conf, code):
    """Export über die Weboberfläche: anmelden, Bestätigung mit dem Code der Authenticator-App, dann wie
    „System → Sicherung“ exportieren. TR-064 kennt diesen Weg nicht (nur Taste/Telefon)."""
    import time as _t
    with _web_client(conf) as cl:
        sid = _web_login(cl, conf)
        try:
            cl.post("/twofactor.lua", data={"xhr": "1", "sid": sid, "tfa_start": "", "no_sidrenew": ""})
            _t.sleep(0.5)
            r = cl.post("/twofactor.lua", data={"xhr": "1", "sid": sid, "tfa_googleauth": code, "no_sidrenew": ""})
            if r.status_code >= 400:
                raise DriverError("FRITZ!Box hat den Code nicht angenommen")
            _t.sleep(0.5)
            r = cl.post("/cgi-bin/firmwarecfg", files={"sid": (None, sid), "ImportExportPassword": (None, conf.get("export_pass") or conf["password"]),
                                                       "ConfigExport": (None, "")})
            if not r.content.startswith(b"****"):
                raise DriverError("Export abgelehnt – Code falsch oder abgelaufen? Neuen Code aus der App nehmen.")
            return r.content
        finally:
            try:
                cl.post("/login_sid.lua", params={"version": "2"}, data={"logout": "1", "sid": sid})
            except httpx.HTTPError:
                pass


def totp_now(secret, t=None, digits=6, step=30):
    """Aktueller Code einer Authenticator-App (RFC 6238, SHA-1) aus dem Base32-Schlüssel bzw. einer otpauth://-Adresse."""
    import base64
    import hashlib
    import hmac
    import struct
    import time as _t
    import urllib.parse
    s = str(secret or "").strip()
    if s.lower().startswith("otpauth://"):
        s = urllib.parse.parse_qs(urllib.parse.urlparse(s).query).get("secret", [""])[0]
    s = s.replace(" ", "").replace("-", "").upper()
    try:
        key = base64.b32decode(s + "=" * (-len(s) % 8))
    except ValueError:
        raise DriverError("Authenticator-Schlüssel ungültig (Base32 aus der FRITZ!Box, z. B. „WI5M JOGQ …“)")
    counter = int((t if t is not None else _t.time()) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def backup(conf, state):
    """Konfigurationsexport der FRITZ!Box (wie System → Sicherung). -> (Dateiname, Inhalt, Text?)
    Verlangt die FRITZ!Box einen zweiten Faktor, wird SecondFactorRequired geworfen; nach der Bestätigung liegt der
    Token in state["sf_token"] und wird im SOAP-Header mitgeschickt."""
    if not conf.get("password"):
        raise DriverError("Für das Konfigurations-Backup Benutzer und Passwort der FRITZ!Box angeben")
    if state.get("totp"):
        code = state.pop("totp")
        try:
            model = (_connect(conf).modelname or "FRITZ.Box")
        except DriverError:
            model = "FRITZ.Box"
        return f"{model.replace(' ', '_').replace('!', '')}.export", backup_web_totp(conf, code), True
    fc = _connect(conf)
    try:
        r = _soap(fc, "DeviceConfig1", "X_AVM-DE_GetConfigFile", {"NewX_AVM-DE_Password": conf.get("export_pass") or conf["password"]},
                  token=state.get("sf_token"))
    except PermissionError:
        raise DriverError("Benutzer hat nicht das Recht „FRITZ!Box Einstellungen“")
    except SecondFactorRequired:
        if not conf.get("totp_secret") or state.get("sf_token"):
            raise
        # Schlüssel der Authenticator-App hinterlegt: Code selbst erzeugen (auch für den Zeitplan)
        model = (getattr(fc, "modelname", "") or "FRITZ.Box").replace(" ", "_").replace("!", "")
        return f"{model}.export", backup_web_totp(conf, totp_now(conf["totp_secret"])), True
    finally:
        state.pop("sf_token", None)  # ein Token gilt nur für einen Vorgang
    url = r.get("NewX_AVM-DE_ConfigFileUrl")
    if not url:
        raise DriverError("FRITZ!Box hat keine Konfigurationsdatei geliefert")
    data = _fetch(fc, url).encode("utf-8")
    model = (getattr(fc, "modelname", "") or "FRITZ.Box").replace(" ", "_").replace("!", "")
    return f"{model}.export", data, True


def action(conf, state, kind, params):
    """Schaltaktion an der FRITZ!Box. kind: wlan (index, on) | internet (ip, block) | wol (mac) | reboot.
    Verlangt die Box einen zweiten Faktor, wird SecondFactorRequired geworfen; danach mit state["sf_token"] erneut."""
    if not conf.get("password"):
        raise DriverError("Für Schaltaktionen Benutzer und Passwort der FRITZ!Box angeben (Recht „FRITZ!Box Einstellungen“)")
    fc = _connect(conf)
    token = state.pop("sf_token", None)
    try:
        if kind == "wlan":
            _soap(fc, f"WLANConfiguration{int(params['index'])}", "SetEnable", {"NewEnable": 1 if params["on"] else 0}, token=token)
            return f"WLAN „{params.get('ssid', '')}“ {'eingeschaltet' if params['on'] else 'ausgeschaltet'}"
        if kind == "internet":
            _soap(fc, "X_AVM-DE_HostFilter1", "DisallowWANAccessByIP", {"NewIPv4Address": params["ip"], "NewDisallow": 1 if params["block"] else 0}, token=token)
            return f"Internet für {params['ip']} {'gesperrt' if params['block'] else 'freigegeben'}"
        if kind == "wol":
            _soap(fc, "Hosts1", "X_AVM-DE_WakeOnLANByMACAddress", {"NewMACAddress": params["mac"]}, token=token)
            return f"Weckruf an {params['mac']} gesendet"
        if kind == "reboot":
            _soap(fc, "DeviceConfig1", "Reboot", token=token)
            return "FRITZ!Box startet neu (dauert etwa 2–3 Minuten)"
    except PermissionError:
        raise DriverError("Benutzer hat nicht das Recht „FRITZ!Box Einstellungen“ bzw. „Zugang aus dem Internet“")
    except KeyError as ex:
        raise DriverError(f"Diese FRITZ!Box kennt die Funktion nicht ({ex})")
    raise DriverError(f"Unbekannte Aktion {kind}")


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
