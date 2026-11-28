"""Treiber FRITZ!Box (TR-064, nur lesen).

Ohne Anmeldung: Hosts (MAC, IP, Name, LAN/WLAN, aktiv) und WAN-Übertragungsraten.
Mit einem FRITZ!Box-Benutzer zusätzlich: Mesh-Topologie (welches Gerät an welchem LAN-Port bzw. WLAN hängt), Geräteinfo, WLAN-Netze.
Leitungswerte: DSL über TR-064 (Sync, Störabstand, Dämpfung, Fehler), Kabel (DOCSIS-Kanäle mit Pegel, MSE/MER, Fehler) über die
Weboberfläche, nur alle 15 Minuten.
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
    dict(key="line", label="Leitungswerte bei Kabel (Anmeldung an der Weboberfläche alle 15 Minuten)", type="select", default="yes",
         options=[["yes", "ja"], ["no", "nein"]]),
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
        # HTTP 401 = Anmeldung abgelehnt; UPnP-Fehler 401 („Invalid Action“, FritzActionError) heißt nur: Aktion fehlt
        if "Authorization" in type(ex).__name__ or ("401" in str(ex) and type(ex).__name__ not in ("FritzActionError", "FritzServiceError")
                                                     and "errorCode" not in str(ex)):
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


# ------------------------------------------------------------ Leitungswerte (DSL über TR-064, Kabel/DOCSIS über die Weboberfläche)
LINE_WEB_S = 900  # DOCSIS-Werte nur alle 15 Minuten: jede Abfrage ist eine Anmeldung (steht in der Ereignisliste der FRITZ!Box)
LINE_BLOCK_S = 3600  # nach abgelehnter Anmeldung so lange nicht erneut versuchen (die FRITZ!Box sperrt sonst immer länger)
# Richtwerte (übliche Empfehlungen der Netzbetreiber; keine harten Grenzen)
DSL_SNR_WARN, DSL_SNR_BAD = 6.0, 3.0  # Störabstandsmarge in dB
DS_PWR = (-8.0, 15.0)  # Kabel Downstream-Pegel in dBmV
US_PWR = (35.0, 51.0)  # Kabel Upstream-Pegel in dBmV
SNR_MIN = {"1024QAM": 37.0, "256QAM": 32.0, "64QAM": 26.0}  # DOCSIS 3.0: MSE (als positiver Wert) je Modulation
MER_MIN_31 = 35.0  # DOCSIS 3.1: MER
ERR_DELTA_WARN = 50  # neue nicht korrigierbare Fehler (Kabel) bzw. CRC-Fehler (DSL) zwischen zwei Messungen

HINTS = {  # Code -> (deutsch, englisch)
    "snr_low": ("Störabstand niedrig: {v} dB (Richtwert ab {lim} dB)", "Low noise margin: {v} dB (guide value from {lim} dB)"),
    "snr_bad": ("Störabstand sehr niedrig: {v} dB – Abbrüche wahrscheinlich", "Noise margin very low: {v} dB – dropouts likely"),
    "crc": ("{n} neue CRC-Fehler seit der letzten Messung", "{n} new CRC errors since the last measurement"),
    "retrain": ("Leitung hat neu synchronisiert ({n}×)", "Line resynchronised ({n}×)"),
    "ds_pwr": ("Downstream-Pegel außerhalb des üblichen Bereichs: {v} dBmV (Kanal {ch}, Richtwert {lo} bis {hi})",
               "Downstream power outside the usual range: {v} dBmV (channel {ch}, guide value {lo} to {hi})"),
    "us_pwr": ("Upstream-Pegel außerhalb des üblichen Bereichs: {v} dBmV (Kanal {ch}, Richtwert {lo} bis {hi})",
               "Upstream power outside the usual range: {v} dBmV (channel {ch}, guide value {lo} to {hi})"),
    "mse": ("Signalqualität schwach: {v} dB auf Kanal {ch} ({mod}, Richtwert ab {lim} dB)",
            "Weak signal quality: {v} dB on channel {ch} ({mod}, guide value from {lim} dB)"),
    "uncorr": ("{n} neue nicht korrigierbare Fehler seit der letzten Messung", "{n} new uncorrectable errors since the last measurement"),
}


def _hint(code, level="warn", **kw):
    import re
    de, en = HINTS[code]
    kw_de = {k: v.replace(".", ",") if isinstance(v, str) and re.fullmatch(r"-?\d+\.\d+", v) else v for k, v in kw.items()}
    return dict(code=code, level=level, de=de.format(**kw_de), en=en.format(**kw))


def _num(v):
    """Zahl aus den Feldern der FRITZ!Box („-36.6“, „3,9“, „42 dB“, 0) – sonst None."""
    import re
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


def _fmt(v):
    return f"{v:.1f}".rstrip("0").rstrip(".") if v is not None else "?"


def access_type(fc):
    try:
        return str(_call(fc, "WANCommonIFC1", "GetCommonLinkProperties").get("NewWANAccessType") or "")
    except Exception:
        return ""


def dsl_values(fc):
    """DSL-Leitung über TR-064 (WANDSLInterfaceConfig). None, wenn die Box keine DSL-Schnittstelle hat."""
    try:
        r = _call(fc, "WANDSLInterfaceConfig1", "GetInfo")
    except Exception:
        return None
    tenth = lambda k: (_num(r.get(k)) / 10) if _num(r.get(k)) is not None else None  # noqa: E731  AVM liefert 1/10 dB
    kbit = lambda k: int(_num(r.get(k)) * 1000) if _num(r.get(k)) is not None else None  # noqa: E731
    out = dict(kind="dsl", status=str(r.get("NewStatus") or ""), rate_down=kbit("NewDownstreamCurrRate"), rate_up=kbit("NewUpstreamCurrRate"),
               max_down=kbit("NewDownstreamMaxRate"), max_up=kbit("NewUpstreamMaxRate"),
               snr_down=tenth("NewDownstreamNoiseMargin"), snr_up=tenth("NewUpstreamNoiseMargin"),
               att_down=tenth("NewDownstreamAttenuation"), att_up=tenth("NewUpstreamAttenuation"),
               power_down=tenth("NewDownstreamPower"), power_up=tenth("NewUpstreamPower"))
    try:
        s = _call(fc, "WANDSLInterfaceConfig1", "GetStatisticsTotal")
        for k, f in (("crc", "NewCRCErrors"), ("fec", "NewFECErrors"), ("hec", "NewHECErrors"), ("es", "NewErroredSecs"),
                     ("ses", "NewSeverelyErroredSecs"), ("retrain", "NewLinkRetrain")):
            if _num(s.get(f)) is not None:
                out[k] = int(_num(s[f]))
    except Exception:
        pass
    return out


def parse_docinfo(data):
    """Antwort von data.lua?page=docInfo (FRITZ!Box Cable) -> Kanallisten und Zusammenfassung."""
    d = (data or {}).get("data") or data or {}

    def chans(side):
        out = []
        for ver, rows in ((d.get(side) or {}).items() if isinstance(d.get(side), dict) else []):
            for x in rows or []:
                if not isinstance(x, dict):
                    continue
                mod = str(x.get("type") or x.get("modulation") or "")
                ch = dict(docsis="3.1" if "31" in ver else "3.0", id=x.get("channelID", x.get("channel")), freq=_num(x.get("frequency")),
                          power=_num(x.get("powerLevel")), mod=mod)
                if side == "channelDs":
                    mse, mer = _num(x.get("mse")), _num(x.get("mer"))
                    ch.update(snr=abs(mse) if mse is not None else mer, corr=int(_num(x.get("corrErrors")) or 0),
                              uncorr=int(_num(x.get("nonCorrErrors")) or 0), latency=_num(x.get("latency")))
                else:
                    ch["multiplex"] = str(x.get("multiplex") or "")
                out.append(ch)
        return sorted(out, key=lambda c: (c["docsis"], _num(c["freq"]) or 0))
    ds, us = chans("channelDs"), chans("channelUs")
    if not ds and not us:
        return None
    pw = lambda xs: [c["power"] for c in xs if c["power"] is not None]  # noqa: E731
    snrs = [c["snr"] for c in ds if c.get("snr") is not None]
    return dict(kind="cable", ds=ds, us=us, ds_30=sum(c["docsis"] == "3.0" for c in ds), ds_31=sum(c["docsis"] == "3.1" for c in ds),
                us_30=sum(c["docsis"] == "3.0" for c in us), us_31=sum(c["docsis"] == "3.1" for c in us),
                ds_pwr_min=min(pw(ds), default=None), ds_pwr_max=max(pw(ds), default=None),
                us_pwr_min=min(pw(us), default=None), us_pwr_max=max(pw(us), default=None),
                snr_min=min(snrs, default=None), corr=sum(c["corr"] for c in ds), uncorr=sum(c["uncorr"] for c in ds))


def docsis_values(conf):
    """DOCSIS-Kanäle über die Weboberfläche (TR-064 kennt sie nicht): anmelden, docInfo lesen, abmelden."""
    with _web_client(conf) as cl:
        sid = _web_login(cl, conf)
        try:
            r = cl.post("/data.lua", data={"xhr": "1", "sid": sid, "lang": "de", "page": "docInfo", "xhrId": "all", "no_sidrenew": ""})
            r.raise_for_status()
            try:
                return parse_docinfo(r.json())
            except ValueError:
                return None
        finally:
            try:
                cl.post("/login_sid.lua", params={"version": "2"}, data={"logout": "1", "sid": sid})
            except httpx.HTTPError:
                pass


def line_hints(line, prev=None):
    """Hinweise zur Leitung nach Richtwerten; prev = vorherige Messung (für neue Fehler)."""
    out = []
    if not line:
        return out
    prev = prev if prev and prev.get("kind") == line.get("kind") else {}
    if line["kind"] == "dsl":
        snr = line.get("snr_down")
        if snr is not None and line.get("status", "Up") in ("Up", ""):
            if snr < DSL_SNR_BAD:
                out.append(_hint("snr_bad", "bad", v=_fmt(snr)))
            elif snr < DSL_SNR_WARN:
                out.append(_hint("snr_low", v=_fmt(snr), lim=_fmt(DSL_SNR_WARN)))
        for k, code in (("crc", "crc"), ("retrain", "retrain")):
            if line.get(k) is not None and prev.get(k) is not None and line[k] >= prev[k]:
                n = line[k] - prev[k]
                if (code == "crc" and n >= ERR_DELTA_WARN) or (code == "retrain" and n > 0):
                    out.append(_hint(code, n=n))
        return out
    for c in line.get("ds") or []:
        if c["power"] is not None and not DS_PWR[0] <= c["power"] <= DS_PWR[1]:
            out.append(_hint("ds_pwr", v=_fmt(c["power"]), ch=c["id"], lo=_fmt(DS_PWR[0]), hi=_fmt(DS_PWR[1])))
            break
    for c in line.get("us") or []:
        if c["power"] is not None and not US_PWR[0] <= c["power"] <= US_PWR[1]:
            out.append(_hint("us_pwr", v=_fmt(c["power"]), ch=c["id"], lo=_fmt(US_PWR[0]), hi=_fmt(US_PWR[1])))
            break
    weak = []
    for c in line.get("ds") or []:
        if c.get("snr") is None:
            continue
        lim = MER_MIN_31 if c["docsis"] == "3.1" else next((v for k, v in SNR_MIN.items() if k in c["mod"].upper().replace("-", "")), None)
        if lim and c["snr"] < lim:
            weak.append((c["snr"] - lim, c, lim))
    if weak:
        _, c, lim = min(weak, key=lambda x: x[0])
        out.append(_hint("mse", v=_fmt(c["snr"]), ch=c["id"], mod=c["mod"] or c["docsis"], lim=_fmt(lim)))
    if prev.get("uncorr") is not None and line.get("uncorr") is not None and line["uncorr"] >= prev["uncorr"]:
        n = line["uncorr"] - prev["uncorr"]
        if n >= ERR_DELTA_WARN:
            out.append(_hint("uncorr", n=n))
    return out


def line_metrics(line, prev=None):
    """Messwerte für den Verlauf: Störabstand (dB), Sync-Rate (bit/s), neue Fehler seit der letzten Messung."""
    if not line:
        return {}
    prev = prev if prev and prev.get("kind") == line.get("kind") else {}
    m = {}
    if line["kind"] == "dsl":
        for k in ("snr_down", "snr_up", "rate_down", "rate_up"):
            if line.get(k) is not None:
                m[f"line:{k}"] = line[k]
        err = "crc"
    else:
        if line.get("snr_min") is not None:
            m["line:snr_min"] = line["snr_min"]
        if line.get("us_pwr_max") is not None:
            m["line:us_pwr_max"] = line["us_pwr_max"]
        err = "uncorr"
    if line.get(err) is not None and prev.get(err) is not None:
        m["line:err"] = max(0, line[err] - prev[err])  # Zähler beginnt nach einem Neustart bei 0
    return m


def poll_line(fc, conf, state, now=None):
    """Leitungswerte je nach Anschluss; Kabel nur alle LINE_WEB_S Sekunden (sonst die letzte Messung). -> (line, metrics)"""
    import time
    now = now or time.time()
    prev = state.get("line_last")
    kind = state.get("line_kind") or ""
    if kind != "cable":
        line = dsl_values(fc)
        if line:
            state["line_kind"] = "dsl"
            line["ts"] = int(now)
            line["hints"] = line_hints(line, prev)
            state["line_last"] = {k: v for k, v in line.items() if k != "hints"}
            return line, line_metrics(line, prev)
        if "cable" not in access_type(fc).lower():
            state["line_kind"] = "none"
            return None, {}
        state["line_kind"] = kind = "cable"
    if conf.get("line") == "no":
        return None, {}
    if not conf.get("password"):
        return dict(kind="cable", error="Für die Kabelwerte Benutzer und Passwort angeben"), {}
    if prev and now - (prev.get("ts") or 0) < LINE_WEB_S:
        return dict(prev, hints=state.get("line_hints") or [], cached=True), {}
    if now < (state.get("line_block_until") or 0):
        return (dict(prev, hints=state.get("line_hints") or [], cached=True) if prev else
                dict(kind="cable", error="Anmeldung an der Weboberfläche abgelehnt – nächster Versuch in einer Stunde")), {}
    try:
        line = docsis_values(conf)
    except DriverError as ex:
        if "abgelehnt" in str(ex):
            state["line_block_until"] = now + LINE_BLOCK_S
        return dict(kind="cable", error=str(ex)), {}
    except httpx.HTTPError:
        return dict(kind="cable", error="Kabelwerte nicht lesbar (Weboberfläche)"), {}
    if not line:
        return dict(kind="cable", error="Kabelwerte nicht lesbar (Weboberfläche)"), {}
    line["ts"] = int(now)
    hints = line_hints(line, prev)
    state["line_last"], state["line_hints"] = line, hints
    return dict(line, hints=hints), line_metrics(line, prev)


# ------------------------------------------------------------ Portfreigaben (TR-064, nur mit Benutzer)
FORWARDS_S = 300  # je Eintrag eine eigene Abfrage – deshalb nur alle 5 Minuten


def _pf_services(fc):
    """Dienste mit Portfreigaben: die Standardverbindung zuerst (Layer3Forwarding), dann alle WANIP-/WANPPP-Dienste der Box."""
    names = list(getattr(fc, "services", None) or [])
    cand = [n for n in names if n.startswith(("WANIPConn", "WANPPPConn"))] or ["WANIPConn1", "WANPPPConnection1"]
    try:
        d = str(_call(fc, "Layer3Forwarding1", "GetDefaultConnectionService").get("NewDefaultConnectionService") or "")
        pref = "WANPPPConnection" if "WANPPP" in d else "WANIPConn" if "WANIP" in d else ""
        if pref:
            cand.sort(key=lambda n: not n.startswith(pref))
    except Exception:
        pass
    return cand


def _pf_err(ex):
    """Fehler einer TR-064-Abfrage als Kurzbeschreibung."""
    txt = str(ex)
    if isinstance(ex, PermissionError) or type(ex).__name__ == "FritzSecurityError" or "606" in txt:
        return "perm"
    if type(ex).__name__ in ("FritzActionError", "FritzServiceError") or "401" in txt or "Invalid Action" in txt:
        return "missing"
    return " ".join(txt.split())[:160] or type(ex).__name__


def forwards(fc, errors=None):
    """IPv4-Portfreigaben über TR-064 (WANIPConnection bzw. WANPPPConnection). TR-064 unterscheidet nicht, ob eine Freigabe
    in der Oberfläche eingerichtet oder von einem Gerät (UPnP/PCP) angelegt wurde – mit Laufzeit gilt sie als automatisch.
    Kennt die Box GetPortMappingNumberOfEntries nicht, wird bis zum ersten ungültigen Index gelesen.
    None, wenn die Box die Liste nicht liefert; die Gründe landen dann in errors."""
    from .controller import forward
    errors = [] if errors is None else errors
    best = None
    for svc in _pf_services(fc):
        n = None
        try:
            n = int(_call(fc, svc, "GetPortMappingNumberOfEntries").get("NewPortMappingNumberOfEntries") or 0)
        except Exception as ex:
            errors.append(_pf_err(ex))
        out, ok = [], n is not None
        for i in range(min(n, 200) if n is not None else 200):
            try:
                r = _call(fc, svc, "GetGenericPortMappingEntry", NewPortMappingIndex=i)
            except Exception as ex:
                e = _pf_err(ex)
                if n is None and i == 0 and type(ex).__name__ != "FritzArrayIndexError" and "713" not in str(ex):
                    errors.append(e)  # Eintrag 0 nicht lesbar und keine Anzahl: dieser Dienst liefert nichts
                else:
                    ok = True  # Liste zu Ende (713 = ungültiger Index)
                break
            ok = True
            lease = r.get("NewLeaseDuration")
            out.append(forward("upnp" if str(lease or "0") not in ("0", "") else "", r.get("NewProtocol"), r.get("NewExternalPort"),
                               r.get("NewInternalClient"), r.get("NewInternalPort"), r.get("NewPortMappingDescription"),
                               str(r.get("NewEnabled")) in ("1", "True", "true"), r.get("NewRemoteHost") or "", lease))
        if ok and (best is None or len(out) > len(best)):
            best = out
    return best


PF_ERR = {
    "perm": "Keine Berechtigung für die Portfreigaben – der FRITZ!Box-Benutzer braucht das Recht „FRITZ!Box Einstellungen“",
    "missing": "Diese FRITZ!Box liefert die Portfreigaben nicht über TR-064",
    "nopw": "Für die Portfreigaben Benutzer und Passwort angeben",
}


def poll_forwards(fc, conf, state, now=None):
    """-> (liste oder None, aus dem Zwischenspeicher?, fehlertext oder "")"""
    import time
    now = now or time.time()
    if not conf.get("password"):
        return None, False, PF_ERR["nopw"]
    if "pf_list" in state and now - (state.get("pf_ts") or 0) < FORWARDS_S:
        return state["pf_list"], True, state.get("pf_err") or ""
    errors = []
    try:
        lst = forwards(fc, errors)
    except Exception as ex:
        lst, errors = None, [_pf_err(ex)]
    err = ""
    if lst is None:
        code = "perm" if "perm" in errors else next((e for e in errors if e not in ("perm", "missing")), "missing")
        err = PF_ERR.get(code) or f"Portfreigaben nicht lesbar: {code}"
    state["pf_ts"], state["pf_list"], state["pf_err"] = now, lst, err
    return lst, False, err


def fw_version(s):
    """FRITZ!OS lesbar: „161.08.25“ -> „8.25“, „161.07.57-114812“ -> „7.57-114812“; sonst unverändert."""
    import re
    s = str(s or "").strip()
    m = re.fullmatch(r"\d+\.(\d{2})\.(\d{2})(.*)", s)
    return f"{int(m.group(1))}.{m.group(2)}{m.group(3)}" if m else s


def poll(conf, state):
    fc = _connect(conf)
    res = dict(info=_info(fc), wan=_wan(fc), auth=False, mesh={}, wlan=[])
    try:  # Firmware: prüft die FRITZ!Box selbst; hier nur deren Ergebnis lesen
        u = _call(fc, "UserInterface1", "X_AVM-DE_GetInfo")
        res["firmware"] = dict(installed=fw_version(res["info"].get("firmware", "")), latest=fw_version(u.get("NewX_AVM-DE_Version") or ""),
                               update=str(u.get("NewUpgradeAvailable")) in ("1", "True", "true"), info=u.get("NewX_AVM-DE_InfoURL") or "")
    except Exception:
        res["firmware"] = dict(installed=fw_version(res["info"].get("firmware", "")), latest="", update=None)
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
    state = dict(state)
    fw_list, cached, fw_err = poll_forwards(fc, conf, state)
    if fw_list is not None:
        res["forwards"], res["forwards_cached"] = fw_list, cached
    elif fw_err:
        res["forwards_error"] = fw_err
    line, lm = poll_line(fc, conf, state)
    if line:
        res["line"] = line
        metrics.update(lm)
    return res, metrics, state
