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
HOOK = "get_clientlist();get_cfg_clientlist();nvram_get(productid);nvram_get(firmver);nvram_get(buildno);nvram_get(lan_ipaddr);nvram_get(label_mac)"
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


def _fetch(conf, state):
    """appGet mit vorhandener Sitzung, bei Bedarf neu anmelden. -> (daten, token)"""
    with _client(conf) as cl:
        for attempt in (0, 1):
            token = state.get("token") if attempt == 0 else None
            if not token:
                token = _login(cl, conf)
            r = cl.get("/appGet.cgi", params={"hook": HOOK}, cookies={"asus_token": token},
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


def poll(conf, state):
    data, token = _fetch(conf, state)
    info, nodes, clients = normalize(data)
    res = dict(info=info, nodes=nodes, clients=clients, keys=sorted(data.keys())[:30])
    return res, {}, dict(state, token=token)
