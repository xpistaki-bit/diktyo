"""Treiber ASUS-Router mit AiMesh (ASUSWRT, z. B. ExpertWiFi EBM68, ZenWiFi, RT-AX…), nur lesen.

Nutzt die Schnittstelle der Weboberfläche (login.cgi, appGet.cgi) wie die ASUS-App. Liefert die Clients mit Name, IP, MAC,
Verbindung (LAN, WLAN 2,4/5/6 GHz) und dem Mesh-Knoten, an dem sie hängen, sowie die AiMesh-Knoten selbst.
Hinweis: ASUS-Router erlauben nur eine Admin-Sitzung; díktyo hält seine Sitzung offen, statt sich jedes Mal neu anzumelden.
"""
import base64
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


def poll(conf, state):
    import time as _t
    data, token = _fetch(conf, state, HOOK + ";netdev(appobj)")
    info, nodes, clients = normalize(data)
    res = dict(info=info, nodes=nodes, clients=clients, keys=sorted(data.keys())[:30])
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
