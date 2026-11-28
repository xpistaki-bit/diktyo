"""Treiber ASUS-Router mit AiMesh (ASUSWRT, z. B. ExpertWiFi EBM68, ZenWiFi, RT-AX…).

Nutzt die Schnittstelle der Weboberfläche (login.cgi, appGet.cgi) wie die ASUS-App. Liefert die Clients mit Name, IP, MAC,
Verbindung (LAN, WLAN 2,4/5/6 GHz) und dem Mesh-Knoten, an dem sie hängen, sowie die AiMesh-Knoten selbst.
Hinweis: ASUS-Router erlauben nur eine Admin-Sitzung; díktyo hält seine Sitzung offen, statt sich jedes Mal neu anzumelden.

Aktionen (applyapp.cgi wie die ASUS-App): klassische Gastnetze (wlX.Y_bss_enabled) ein/aus, Neustart. Bei Firmware mit
„Gastnetz Pro“ (SDN, z. B. ExpertWiFi) verwaltet der Router die Gastnetze anders – dort bietet díktyo das Schalten nicht an.
Konfigurations-Backup: Settings_<Modell>.CFG; die Datei wird zum Vergleichen entschlüsselt (HDR1 Klartext, HDR2 mit
Zufallswert verschleiert) und als sortierte Liste „schlüssel=wert“ gezeigt, Passwörter und Schlüssel maskiert.
"""
import base64
import hashlib
import json
import re

import httpx

NAME = "ASUS-Router (AiMesh)"
DEFAULT_INTERVAL = 300
FIELDS = [
    dict(key="host", label="Adresse", type="text", default="192.168.50.1", required=True),
    dict(key="port", label="Port", type="number", default=8443),
    dict(key="scheme", label="Protokoll", type="select", default="https", options=[["https", "HTTPS"], ["http", "HTTP"]]),
    dict(key="username", label="Benutzer", type="text", default="admin", required=True),
    dict(key="password", label="Passwort", type="password", default="", secret=True),
    dict(key="cfg_schedule", label="Konfiguration sichern", type="select", default="weekly", options=[
        ["weekly", "wöchentlich"], ["daily", "täglich"], ["no", "nein"]]),
]
CAN_BACKUP = True
UA = "asusrouter--DUTUtil-"
HOOK = ("get_clientlist();get_cfg_clientlist();nvram_get(productid);nvram_get(firmver);nvram_get(buildno);nvram_get(extendno);"
        "nvram_get(lan_ipaddr);nvram_get(label_mac);nvram_get(webs_state_flag);nvram_get(webs_state_info)")
GUEST_BAND = {0: "2,4 GHz", 1: "5 GHz", 2: "5 GHz-2 / 6 GHz", 3: "6 GHz"}
GUEST_HOOK = "".join(f";nvram_get(wl{u}.{i}_bss_enabled);nvram_get(wl{u}.{i}_ssid)" for u in range(4) for i in (1, 2, 3)) + ";nvram_get(sdn_rl)"
BANDS = {"0": ("lan", ""), "1": ("wlan", "2,4 GHz"), "2": ("wlan", "5 GHz"), "3": ("wlan", "5 GHz (2)"), "4": ("wlan", "6 GHz")}


class DriverError(Exception):
    pass


def _base(conf):
    port = int(conf.get("port") or (8443 if conf.get("scheme", "https") == "https" else 80))
    return f'{conf.get("scheme") or "https"}://{conf["host"]}:{port}'


def _login(cl, conf):
    auth = base64.b64encode(f'{conf.get("username") or "admin"}:{conf.get("password") or ""}'.encode()).decode()
    r = cl.post("/login.cgi", data={"login_authorization": auth}, headers={"Referer": f"{_base(conf)}/Main_Login.asp"})
    try:
        j = r.json()
    except ValueError:
        raise DriverError("Unerwartete Antwort beim Anmelden (ist das ein ASUS-Router?)")
    if j.get("asus_token"):
        return j["asus_token"]
    err = str(j.get("error_status", ""))
    raise DriverError({"3": "Anmeldung abgelehnt: Benutzer oder Passwort falsch", "7": "Anmeldung vorübergehend gesperrt (zu viele Versuche); bitte warten",
                       "10": "Router verlangt ein Captcha; einmal in der Weboberfläche anmelden"}.get(err, f"Anmeldung abgelehnt (Code {err or '?'})"))


def _client(conf):
    return httpx.Client(base_url=_base(conf), verify=False, timeout=12, headers={"User-Agent": UA}, follow_redirects=False)


def _fetch(conf, state, hook=None):
    """appGet mit vorhandener Sitzung, bei Bedarf neu anmelden. -> (daten, token)"""
    with _client(conf) as cl:
        for attempt in (0, 1):
            token = state.get("token") if attempt == 0 else None
            if not token:
                token = _login(cl, conf)
            r = cl.get("/appGet.cgi", params={"hook": hook or HOOK}, cookies={"asus_token": token},
                       headers={"Referer": f"{_base(conf)}/index.asp"})
            txt = r.text.strip()
            if r.status_code == 200 and txt.startswith("{"):
                return parse_json(txt), token
            state.pop("token", None)
        raise DriverError("Router liefert keine Daten (Sitzung abgelaufen oder Firmware ohne appGet)")


def parse_json(txt):
    """appGet liefert nicht immer gültiges JSON (z. B. Kommas am Ende); vorsichtig bereinigen."""
    try:
        return json.loads(txt)
    except ValueError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", txt))


def backup(conf, state):
    """Einstellungsdatei des Routers (Administration → Wiederherstellen/Speichern → Einstellung speichern)."""
    data, token = _fetch(conf, state)
    product = re.sub(r"[^A-Za-z0-9_\-]", "", str(data.get("productid") or "router"))
    with _client(conf) as cl:
        r = cl.get(f"/Settings_{product}.CFG", cookies={"asus_token": token}, headers={"Referer": f"{_base(conf)}/Advanced_SettingBackup_Content.asp"})
    if r.status_code != 200 or len(r.content) < 100 or r.content[:15].lower().startswith((b"<html", b"<!doctype")):
        raise DriverError("Router hat keine Einstellungsdatei geliefert")
    state["token"] = token
    return f"Settings_{product}.CFG", r.content, False


# ------------------------------------------------------------ Einstellungsdatei (CFG) lesbar machen
CFG_MAGIC_NEW = (b"HDR2", b"N55U", b"AC55U")
SECRET = re.compile(r"(passw|psk|secret|token|_key\d*$|^key$|_pin$|wps_device_pin|_crt|cert|private|_hash$|_passphrase)", re.I)


def decode_cfg(data):
    """Settings_*.CFG -> {nvram-Schlüssel: Wert} oder None, wenn das Format unbekannt ist.
    HDR1: 4 Byte Kennung, 4 Byte Länge, dann Klartext „k=v\0k=v\0…“. HDR2 (und N55U/AC55U): 4 Byte Kennung, 3 Byte Länge,
    1 Byte Zufallswert r; jedes Byte b steht für (0xFF + r − b) & 0xFF, Bytes über 0xFC sind Trennzeichen (ehemals 0)."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 8:
        return None
    if data[:4] == b"HDR1":
        n = int.from_bytes(data[4:8], "little")
        body = bytes(data[8:8 + n])
    elif data[:4] in CFG_MAGIC_NEW or data[:5] in CFG_MAGIC_NEW:
        off = 5 if data[:5] == b"AC55U" else 4
        n = int.from_bytes(data[off:off + 3], "little")
        rnd = data[off + 3]
        raw = data[off + 4:off + 4 + n]
        out = bytearray(len(raw))
        for i, b in enumerate(raw):
            if b > 0xFC:
                out[i] = 0  # Trenner (mehrere hintereinander sind Füllung)
            else:
                out[i] = (0xFF + rnd - b) & 0xFF
        body = bytes(out)
    else:
        return None
    entries = [x for x in body.split(b"\0") if x]
    if not entries:
        return None
    pairs = {}
    good = 0
    for e in entries:
        k, sep, v = e.decode("utf-8", "replace").partition("=")
        if sep and k and re.fullmatch(r"[\w.:\-]{1,80}", k):
            pairs[k] = v
            good += 1
    return pairs if good >= max(1, int(len(entries) * 0.8)) else None


def _mask(k, v):
    if not v or not SECRET.search(k):
        return v
    return f"•••••• (#{hashlib.sha256(v.encode()).hexdigest()[:4]})"


def config_text(data):
    """Lesbare, sortierte Fassung der Einstellungsdatei (Geheimnisse maskiert) oder None."""
    d = decode_cfg(data)
    if d is None:
        return None
    return "\n".join(f"{k}={_mask(k, v)}" for k, v in sorted(d.items())) + "\n"


def canonical(data):
    """Für „unverändert?“: entschlüsselter Inhalt (die Datei selbst enthält jedes Mal andere Zufallsbytes)."""
    d = decode_cfg(data)
    return data if d is None else json.dumps(d, sort_keys=True, ensure_ascii=False).encode()


# ------------------------------------------------------------ Gastnetze und Aktionen
def guests(data):
    """Klassische Gastnetze aus appGet -> [dict(unit, idx, band, ssid, enabled)] und ob „Gastnetz Pro“ (SDN) aktiv ist."""
    out = []
    for u in range(4):
        for i in (1, 2, 3):
            ssid = str(data.get(f"wl{u}.{i}_ssid") or "")
            en = str(data.get(f"wl{u}.{i}_bss_enabled") or "")
            if ssid and en in ("0", "1"):
                out.append(dict(unit=u, idx=i, band=GUEST_BAND[u], ssid=ssid, enabled=en == "1"))
    sdn = str(data.get("sdn_rl") or "").strip()
    # sdn_rl gibt es bei Firmware mit SDN; mehr als der Standardeintrag (Hauptnetz) heißt: Gastnetze laufen über SDN
    return out, sdn.count("<") > 1


def _apply(conf, state, values):
    """Einstellung setzen bzw. Dienst auslösen über applyapp.cgi (mit der gemerkten Sitzung, bei Bedarf neu anmelden)."""
    with _client(conf) as cl:
        for attempt in (0, 1):
            token = state.get("token") if attempt == 0 else None
            if not token:
                token = _login(cl, conf)
                state["token"] = token
            try:
                r = cl.post("/applyapp.cgi", data=values, cookies={"asus_token": token}, headers={"Referer": f"{_base(conf)}/index.asp"})
            except (httpx.ReadTimeout, httpx.RemoteProtocolError):
                return {}  # z. B. Neustart: der Router antwortet nicht mehr
            if r.status_code in (301, 302) or "Main_Login" in r.text[:2000]:
                state.pop("token", None)
                continue
            if r.status_code >= 400:
                raise DriverError(f"Router meldet HTTP {r.status_code}")
            try:
                return parse_json(r.text) if r.text.strip().startswith("{") else {}
            except ValueError:
                return {}
        raise DriverError("Router nimmt die Einstellung nicht an (Sitzung abgelaufen)")


def action(conf, state, kind, params):
    """kind: guest (unit, idx, on) | reboot"""
    if kind == "guest":
        u, i = int(params["unit"]), int(params["idx"])
        if not (0 <= u <= 3 and 1 <= i <= 3):
            raise DriverError("Gastnetz nicht gefunden – Integration einmal abfragen")
        _apply(conf, state, {f"wl{u}.{i}_bss_enabled": "1" if params["on"] else "0", "action_mode": "apply", "rc_service": "restart_wireless"})
        return f"Gastnetz „{params.get('ssid') or f'wl{u}.{i}'}“ {'eingeschaltet' if params['on'] else 'ausgeschaltet'}"
    if kind == "reboot":
        _apply(conf, state, {"action_mode": "apply", "rc_service": "reboot"})
        return "ASUS-Router startet neu (dauert etwa zwei Minuten)"
    raise DriverError(f"Unbekannte Aktion {kind}")


def test(conf):
    data, _ = _fetch(conf, {})
    clients = (data.get("get_clientlist") or {}).get("maclist") or []
    nodes = data.get("get_cfg_clientlist") or []
    return dict(model=data.get("productid", ""), firmware=f'{data.get("firmver", "")}.{data.get("buildno", "")}'.strip("."),
                clients=len(clients), nodes=len(nodes))


def _mac(v):
    return str(v or "").strip().upper()


def normalize(data):
    """-> (info, nodes, clients) in einheitlicher Form."""
    info = dict(model=data.get("productid", ""), firmware=f'{data.get("firmver", "")}.{data.get("buildno", "")}'.strip("."),
                ip=data.get("lan_ipaddr", ""), mac=_mac(data.get("label_mac")))
    nodes = []
    for n in data.get("get_cfg_clientlist") or []:
        if not isinstance(n, dict):
            continue
        aps = {_mac(n.get(k)) for k in ("ap2g", "ap5g", "ap5g1", "ap6g", "ap2g_fh", "ap5g_fh", "mac") if n.get(k)}
        parent = _mac(n.get("pap5g") or n.get("pap2g") or n.get("pap6g"))
        nodes.append(dict(mac=_mac(n.get("mac")), ip=n.get("ip", ""), name=n.get("alias") or n.get("ui_model_name") or n.get("model_name") or "",
                          model=n.get("ui_model_name") or n.get("model_name") or "", firmware=n.get("fwver", ""), online=str(n.get("online", "1")) == "1",
                          level=int(n.get("level") or 0), parent_ap=parent, aps=sorted(aps - {""}),
                          wired_backhaul=not parent and int(n.get("level") or 0) > 0))
    cl = data.get("get_clientlist") or {}
    clients = []
    for mac in cl.get("maclist") or []:
        e = cl.get(mac) or {}
        if not isinstance(e, dict) or str(e.get("amesh_isRe", "0")) == "1":
            continue  # Mesh-Knoten erscheinen auch als Client
        medium, band = BANDS.get(str(e.get("isWL", "0")), ("wlan", ""))
        clients.append(dict(mac=_mac(e.get("mac") or mac), ip=e.get("ip", ""), name=e.get("nickName") or e.get("name") or "",
                            online=str(e.get("isOnline", "1")) == "1", medium=medium, band=band, parent_ap=_mac(e.get("amesh_papMac")),
                            vendor=e.get("vendor", ""), guest=str(e.get("isGN", "0")) not in ("0", ""), rssi=e.get("rssi", "")))
    return info, nodes, clients


# ------------------------------------------------------------ Traffic (Traffic Monitor, Traffic Analyzer)
NETDEV = {"INTERNET": ("wan", "WAN"), "WIRED": ("lan", "LAN"), "BRIDGE": ("bridge", "Bridge"), "WIRELESS0": ("wl0", "2,4 GHz"),
          "WIRELESS1": ("wl1", "5 GHz-1"), "WIRELESS2": ("wl2", "5 GHz-2"), "WIRELESS3": ("wl3", "6 GHz")}
ANALYZER_EVERY = 900   # Traffic Analyzer höchstens alle 15 Minuten abfragen


def fw_version(s):
    """ASUS-Firmware lesbar: „3006_102_46475-ga27e679_498-g0e4e1_sec“, „3.0.0.6_102_46475“ oder „3.0.0.6.102_46475“
    -> „3.0.0.6.102_46475“. Unbekanntes Format bleibt (gekürzt) stehen."""
    import re
    s = str(s or "").strip()
    m = re.match(r"(\d)\.?(\d)\.?(\d)\.?(\d)[._](\d+)(?:[._](\d+))?", s)
    if not m:
        return s[:40]
    base = ".".join(m.group(i) for i in range(1, 5)) + "." + m.group(5)
    return f"{base}_{m.group(6)}" if m.group(6) else base


def _num(v):
    """Zähler aus netdev: meist hexadezimal („0x1a2b“), manchmal dezimal."""
    s = str(v or "").strip()
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(float(s))
    except ValueError:
        return None


def parse_netdev(nd, prev, now):
    """-> (traffic{key: dict(name, rx_bps, tx_bps, rx_total, tx_total)}, zähler)"""
    out, counters = {}, {}
    for k, (key, name) in NETDEV.items():
        rx, tx = _num(nd.get(f"{k}_rx")), _num(nd.get(f"{k}_tx"))
        if rx is None or tx is None:
            continue
        rate = (None, None)
        p = prev.get(key)
        if p and now > p[2] and rx >= p[0] and tx >= p[1]:  # Zählerüberlauf/Neustart: auslassen
            dt = now - p[2]
            rate = (round((rx - p[0]) * 8 / dt), round((tx - p[1]) * 8 / dt))
        counters[key] = (rx, tx, now)
        out[key] = dict(name=name, rx_bps=rate[0], tx_bps=rate[1], rx_total=rx, tx_total=tx)
    return out, counters


def parse_statistics(text):
    """Antwort von getAppTraffic/getWanTraffic: „array_statistics = [[…], …];“ -> Liste"""
    m = re.search(r"array_statistics\s*=\s*(\[.*?\])\s*;", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("'", '"'))
    except ValueError:
        return None


def traffic_analyzer(conf, token, now=None):
    """Traffic pro Client der letzten 24 Stunden und WAN-Stundenwerte aus dem Traffic Analyzer (falls eingeschaltet).
    -> dict(clients=[dict(mac, tx, rx)], wan_hours=[[tx, rx], …], source) oder None"""
    import time as _t
    now = int(now or _t.time())
    with _client(conf) as cl:
        for suffix in ("", "_Dns"):
            try:
                r = cl.get(f"/getAppTraffic{suffix}.asp", params={"client": "all", "mode": "detail", "dura": 24, "date": now},
                           cookies={"asus_token": token}, headers={"Referer": f"{_base(conf)}/TrafficAnalyzer_Statistic.asp"})
            except httpx.HTTPError:
                return None
            rows = parse_statistics(r.text) if r.status_code == 200 else None
            if rows is None:
                continue
            clients = []
            for x in rows:
                if isinstance(x, list) and len(x) >= 3:
                    try:
                        clients.append(dict(mac=_mac(x[0]), tx=int(float(x[1])), rx=int(float(x[2]))))
                    except (TypeError, ValueError):
                        continue
            hours = None
            try:
                w = cl.get(f"/getWanTraffic{suffix}.asp", params={"client": "all", "mode": "hour", "dura": 24, "date": now},
                           cookies={"asus_token": token}, headers={"Referer": f"{_base(conf)}/TrafficAnalyzer_Statistic.asp"})
                hours = parse_statistics(w.text) if w.status_code == 200 else None
            except httpx.HTTPError:
                pass
            clients.sort(key=lambda c: -(c["tx"] + c["rx"]))
            return dict(clients=clients[:100], wan_hours=hours if isinstance(hours, list) else None, source=f"getAppTraffic{suffix}", ts=now)
    return None


# ------------------------------------------------------------ Portfreigaben
FW_HOOK = ";nvram_get(vts_enable_x);nvram_get(vts_rulelist);nvram_get(upnp_enable)"
UPNP_S = 300


def parse_vts(v, enabled=True):
    """vts_rulelist: „<Name>Port extern>IP>Port intern>Protokoll[>Quell-IP]“ je Eintrag."""
    from .controller import forward
    out = []
    for ent in str(v or "").split("<"):
        f = ent.split(">")
        if len(f) < 3 or not (f[1] or f[2]):
            continue
        out.append(forward("static", f[4] if len(f) > 4 and f[4] else "TCP", f[1], f[2], f[3] if len(f) > 3 else "", f[0], enabled,
                           f[5] if len(f) > 5 else ""))
    return out


def parse_upnp(text):
    """Ausgabe von get_upnp_array() (Liste von Zeilen wie [\"TCP\", \"51413\", \"192.168.50.20\", \"51413\", \"Beschreibung\"]).
    Die Reihenfolge der Felder unterscheidet sich je Firmware – deshalb nach Art des Werts zuordnen."""
    from .controller import forward
    out = []
    for grp in re.findall(r"\[([^\[\]]*)\]", text or ""):
        f = re.findall(r'"([^"]*)"', grp)
        if not f or f[0].upper() not in ("TCP", "UDP"):
            continue
        nums = [x for x in f[1:] if re.fullmatch(r"\d+", x)]
        ip = next((x for x in f[1:] if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", x)), "")
        desc = next((x for x in f[1:] if x and x not in nums and x != ip), "")
        if nums and ip:
            out.append(forward("upnp", f[0], nums[0], ip, nums[1] if len(nums) > 1 else nums[0], desc))
    return out


def upnp_list(conf, token):
    with _client(conf) as cl:
        r = cl.get("/appGet.cgi", params={"hook": "get_upnp_array()"}, cookies={"asus_token": token},
                   headers={"Referer": f"{_base(conf)}/index.asp"})
        return parse_upnp(r.text) if r.status_code == 200 else None


def poll(conf, state):
    import time as _t
    data, token = _fetch(conf, state, HOOK + ";netdev(appobj)" + GUEST_HOOK + FW_HOOK)
    info, nodes, clients = normalize(data)
    res = dict(info=info, nodes=nodes, clients=clients, keys=sorted(data.keys())[:30])
    res["guest"], res["sdn"] = guests(data)
    now = _t.time()
    traffic, counters = parse_netdev(data.get("netdev") or {}, state.get("counters", {}), now)
    metrics = {}
    if traffic:
        res["traffic"] = traffic
        for key, t in traffic.items():
            if t["rx_bps"] is not None:
                metrics[f"{'wan' if key == 'wan' else 'if:' + key}:rx"], metrics[f"{'wan' if key == 'wan' else 'if:' + key}:tx"] = t["rx_bps"], t["tx_bps"]
        w = traffic.get("wan")
        if w:
            res["wan"] = dict(rx_bps=w["rx_bps"], tx_bps=w["tx_bps"], connected=None, mac=info.get("mac", ""))
    state = dict(state, counters=counters)
    if now - state.get("ta_checked", 0) >= ANALYZER_EVERY:
        ta = traffic_analyzer(conf, token)
        state.update(ta_checked=now, ta=ta)
    if state.get("ta"):
        res["analyzer"] = state["ta"]
    if "vts_rulelist" in data:  # Portfreigaben; UPnP-Liste nur alle 5 Minuten
        res["forwards"] = parse_vts(data.get("vts_rulelist"), str(data.get("vts_enable_x", "1")) == "1")
        res["forwards_cached"] = False
        if str(data.get("upnp_enable", "0")) == "1":
            if now - state.get("upnp_ts", 0) >= UPNP_S:
                try:
                    state.update(upnp_ts=now, upnp=upnp_list(conf, token))
                except httpx.HTTPError:
                    state.update(upnp_ts=now, upnp=None)
            else:
                res["forwards_cached"] = True
            res["forwards"] += state.get("upnp") or []
    flag = str(data.get("webs_state_flag", ""))
    installed = fw_version(f'{data.get("firmver", "")}_{data.get("buildno", "")}_{data.get("extendno", "")}') or info["firmware"]
    latest = fw_version(data.get("webs_state_info")) if flag in ("1", "2") else ""
    res["firmware"] = dict(installed=installed, latest=latest, update=flag in ("1", "2") if flag else None)
    return res, metrics, dict(state, token=token)


def diagnose(conf, nat_hint=None):
    """Was liefert dieser Router? Prüft Anmeldung, Client-Liste, Traffic Monitor, Traffic Analyzer und Firmware-Felder."""
    import time as _t
    steps = []

    def step(ok, title, detail=""):
        steps.append(dict(ok=ok, title=title, detail=detail))
    st = {}
    try:
        data, token = _fetch(conf, st, HOOK + ";netdev(appobj);nvram_get(bwdpi_db_enable);nvram_get(dns_dpi_trf_analysis)")
    except DriverError as ex:
        step(False, "Anmeldung", str(ex))
        return dict(steps=steps, summary="Anmeldung fehlgeschlagen – Adresse, Port und Admin-Zugang prüfen.")
    step(True, "Anmeldung", f"{data.get('productid', '')} · Firmware {data.get('firmver', '')}.{data.get('buildno', '')}")
    cl = (data.get("get_clientlist") or {})
    macs = cl.get("maclist") or []
    first = next((cl[m] for m in macs if isinstance(cl.get(m), dict)), {})
    step(bool(macs), "Client-Liste", f"{len(macs)} Clients; Felder: {', '.join(sorted(first.keys())[:40]) or '–'}")
    nd = data.get("netdev") or {}
    tr, _ = parse_netdev(nd, {}, _t.time())
    if tr:
        step(True, "Traffic Monitor (netdev)", "Zähler für: " + ", ".join(f"{t['name']} (↓{t['rx_total']:,} ↑{t['tx_total']:,} Byte)" for t in tr.values()))
    else:
        step(False, "Traffic Monitor (netdev)", f"keine Zähler – Felder: {', '.join(sorted(nd.keys())[:20]) or 'keine Antwort'}")
    enabled = str(data.get("bwdpi_db_enable", "")) == "1" or str(data.get("dns_dpi_trf_analysis", "")) == "1"
    ta = traffic_analyzer(conf, token)
    if ta and ta["clients"]:
        step(True, "Traffic Analyzer (pro Client)", f"{len(ta['clients'])} Clients über {ta['source']}; WAN-Stundenwerte: {'ja' if ta['wan_hours'] else 'nein'}")
    elif ta is not None:
        step(None, "Traffic Analyzer (pro Client)", "Schnittstelle antwortet, aber ohne Daten" + ("" if enabled else " – Traffic Analyzer → Statistik am Router einschalten"))
    else:
        step(False if enabled else None, "Traffic Analyzer (pro Client)", "keine Antwort" + ("" if enabled else " – ist der Traffic Analyzer am Router eingeschaltet?"))
    flag = data.get("webs_state_flag")
    step(None if flag in (None, "") else True, "Firmware-Status", f"webs_state_flag={flag!r}, webs_state_info={data.get('webs_state_info')!r}")
    ok = bool(tr) and bool(ta and ta["clients"])
    return dict(steps=steps, summary="Alle Daten verfügbar." if ok else "Nicht alle Daten verfügbar – Details oben. Diese Ausgabe hilft bei der Anpassung an deine Firmware.")
