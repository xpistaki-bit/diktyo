"""devolo Powerline (Magic- und neuere dLAN-Adapter mit Geräte-API, wie sie die devolo Home Network App nutzt).

Ablauf (nur lesend):
1. mDNS-Anfrage direkt an den Adapter (Unicast an Port 5353): Dienste „_dvl-plcnetapi._tcp“ und „_dvl-deviceapi._tcp“ liefern
   Port, Pfad, API-Version, PLC-MAC, Seriennummer, Produkt und unterstützte Funktionen (TXT-Einträge).
2. GetNetworkOverview (plcnet-API) beim angegebenen Adapter: alle Adapter des Powerline-Netzes mit Name, Produkt, Firmware,
   IP-Adresse, „am Router angeschlossen“, Geräten an ihrer LAN-Buchse und den Datenraten zwischen je zwei Adaptern.
3. Je Adapter mit WLAN die verbundenen WLAN-Geräte (WifiConnectedStationsGet) und höchstens einmal am Tag die Firmware-Prüfung
   (UpdateFirmwareCheck).
Antworten sind Protobuf-Nachrichten; díktyo liest sie mit einem kleinen eigenen Decoder (keine zusätzliche Bibliothek).
Anmeldung per HTTP-Digest mit Benutzer „devolo“ und dem Gerätepasswort (leer, falls keins gesetzt); manche Firmware erwartet
statt des Passworts dessen SHA-256 – das wird automatisch versucht.
Ältere dLAN-Adapter ohne diese Geräte-API (nur über das alte dLAN Cockpit bedienbar) lassen sich nicht abfragen.
"""
import hashlib
import random
import socket
import struct
import time

import httpx

NAME = "devolo Powerline"
DEFAULT_INTERVAL = 300
FIELDS = [
    dict(key="host", label="Adresse eines devolo-Adapters", type="text", default="", placeholder="z. B. 192.168.178.40", required=True),
    dict(key="password", label="Gerätepasswort (leer lassen, wenn keins gesetzt ist)", type="password", default="", secret=True),
    dict(key="fw_check", label="Nach Firmware-Updates fragen", type="select", default="daily", options=[["daily", "einmal am Tag"], ["no", "nein"]]),
]
PLCNET, DEVICEAPI = "_dvl-plcnetapi._tcp.local", "_dvl-deviceapi._tcp.local"
USER = "devolo"
TECH = {3: "HomePlug AV (Thunderbolt)", 4: "HomePlug AV2 (Panther)", 7: "G.hn (Magic)"}
BAND = {1: "2,4 GHz", 2: "5 GHz"}
FW_EVERY = 86400


class DriverError(Exception):
    pass


# ------------------------------------------------------------ Protobuf (nur lesen)
def _varint(b, i):
    r = s = 0
    while True:
        if i >= len(b):
            raise ValueError("Protobuf: Nachricht abgeschnitten")
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        s += 7
        if not x & 0x80:
            return r, i


def pb(b):
    """Protobuf-Nachricht -> {Feldnummer: [Werte]} (Längenfelder als bytes, Varints als int, 64-Bit als bytes)."""
    out, i = {}, 0
    while i < len(b):
        key, i = _varint(b, i)
        n, w = key >> 3, key & 7
        if w == 0:
            v, i = _varint(b, i)
        elif w == 1:
            v, i = b[i:i + 8], i + 8
        elif w == 2:
            ln, i = _varint(b, i)
            v, i = b[i:i + ln], i + ln
        elif w == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"Protobuf: Feldtyp {w} nicht unterstützt")
        out.setdefault(n, []).append(v)
    return out


def _s(m, n):
    v = m.get(n)
    return v[0].decode("utf-8", "replace") if v and isinstance(v[0], (bytes, bytearray)) else ""


def _i(m, n, default=0):
    v = m.get(n)
    return v[0] if v and isinstance(v[0], int) else default


def _d(m, n):
    v = m.get(n)
    return round(struct.unpack("<d", v[0])[0], 1) if v and isinstance(v[0], (bytes, bytearray)) and len(v[0]) == 8 else None


def _mac(s):
    h = "".join(ch for ch in (s or "").upper() if ch in "0123456789ABCDEF")
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)) if len(h) == 12 else ""


def parse_overview(b):
    """GetNetworkOverview -> dict(devices=[...], rates=[...])"""
    net = pb(pb(b).get(1, [b""])[0])
    devices = []
    for raw in net.get(1, []):
        m = pb(raw)
        devices.append(dict(product=_s(m, 1), product_id=_s(m, 2), firmware=_s(m, 3), firmware_full=_s(m, 4), name=_s(m, 5), network=_s(m, 6),
                            mac=_mac(_s(m, 7)), local=_i(m, 8) == 1, technology=TECH.get(_i(m, 9), ""),
                            bridged=[x for x in (_mac(v.decode("ascii", "replace")) for v in m.get(10, [])) if x],
                            ip=_s(m, 11), router=bool(_i(m, 12))))
    rates = []
    for raw in net.get(2, []):
        m = pb(raw)
        a, z = _mac(_s(m, 1)), _mac(_s(m, 2))
        if a and z:
            rates.append(dict(src=a, dst=z, tx=_d(m, 3), rx=_d(m, 4)))
    return dict(devices=devices, rates=rates)


def parse_stations(b):
    out = []
    for raw in pb(b).get(1, []):
        m = pb(raw)
        mac = _mac(_s(m, 1))
        if mac:
            out.append(dict(mac=mac, guest=_i(m, 2) == 2, band=BAND.get(_i(m, 3), ""), rx=_i(m, 4), tx=_i(m, 5)))
    return out


def parse_fw_check(b):
    m = pb(b)
    return dict(update=_i(m, 1, 1) == 0, latest=_s(m, 2))


# ------------------------------------------------------------ mDNS (Unicast-Anfrage an einen Adapter)
def _name(parts):
    return b"".join(bytes([len(p)]) + p.encode() for p in parts.split(".") if p) + b"\0"


def _read_name(data, i, depth=0):
    parts = []
    while depth < 12:
        n = data[i]
        if n & 0xC0 == 0xC0:
            return ".".join(parts + [_read_name(data, ((n & 0x3F) << 8) | data[i + 1], depth + 1)]), i + 2
        if n == 0:
            return ".".join(parts), i + 1
        parts.append(data[i + 1:i + 1 + n].decode("utf-8", "replace"))
        i += n + 1
    raise ValueError("DNS-Name zu tief verschachtelt")


def parse_mdns(data):
    """DNS-Antwort -> Liste (Name, Typ, rdata) mit PTR als Name, SRV als (Port, Ziel), TXT als dict, A als Adresse."""
    _, _, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    i = 12
    for _ in range(qd):
        _, i = _read_name(data, i)
        i += 4
    out = []
    for _ in range(an + ns + ar):
        name, i = _read_name(data, i)
        typ, _, _, ln = struct.unpack(">HHIH", data[i:i + 10])
        i += 10
        rd = data[i:i + ln]
        if typ == 12:
            out.append((name, "PTR", _read_name(data, i)[0]))
        elif typ == 33 and ln >= 7:
            out.append((name, "SRV", (struct.unpack(">H", rd[4:6])[0], _read_name(data, i + 6)[0])))
        elif typ == 16:
            txt, j = {}, 0
            while j < len(rd):
                n = rd[j]
                k, _, v = rd[j + 1:j + 1 + n].decode("utf-8", "replace").partition("=")
                if k:
                    txt[k] = v
                j += n + 1
            out.append((name, "TXT", txt))
        elif typ == 1 and ln == 4:
            out.append((name, "A", socket.inet_ntoa(rd)))
        i += ln
    return out


def _query(questions):
    tid = random.randint(0, 65535)
    q = struct.pack(">HHHHHH", tid, 0, len(questions), 0, 0, 0)
    for name, typ in questions:
        q += _name(name) + struct.pack(">HH", typ, 0x8001)  # Klasse IN mit QU-Bit: Antwort direkt an uns
    return q


def mdns(ip, timeout=2.0, port=5353):
    """-> {PLCNET|DEVICEAPI: dict(port, txt)} für die Dienste des Adapters unter ip."""
    want = (PLCNET, DEVICEAPI)
    recs, found = [], {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout / 2)
    try:
        for attempt in range(2):
            ptr = {n: v for n, t, v in recs if t == "PTR" and n in want}
            missing = [(inst, typ) for inst in ptr.values() for typ in (33, 16)
                       if not any(n == inst and t == ("SRV" if typ == 33 else "TXT") for n, t, _ in recs)]
            qs = [(w, 12) for w in want if w not in ptr] + missing
            if not qs:
                break
            try:
                s.sendto(_query(qs), (ip, port))
            except OSError as ex:
                raise DriverError(f"mDNS-Anfrage an {ip} nicht möglich: {ex}")
            end = time.time() + timeout / 2
            while time.time() < end:
                try:
                    data, addr = s.recvfrom(9000)
                except socket.timeout:
                    break
                if addr[0] != ip:
                    continue
                try:
                    recs += parse_mdns(data)
                except (ValueError, IndexError, struct.error):
                    continue
    finally:
        s.close()
    for w in want:
        inst = next((v for n, t, v in recs if t == "PTR" and n == w), None)
        srv = next((v for n, t, v in recs if t == "SRV" and n == inst), None)
        txt = next((v for n, t, v in recs if t == "TXT" and n == inst), {})
        if inst and srv:
            found[w] = dict(port=srv[0], txt=txt)
    return found


# ------------------------------------------------------------ HTTP
def _url(ip, svc, sub):
    txt = svc["txt"]
    path = txt.get("Path") or txt.get("path") or ""
    return f"http://{ip}:{svc['port']}/{path}/{txt.get('Version') or 'v0'}/{sub}"


def _get(ip, svc, sub, password, timeout=10.0):
    url = _url(ip, svc, sub)
    try:
        r = httpx.get(url, auth=httpx.DigestAuth(USER, password or ""), timeout=timeout)
        if r.status_code == 401:
            r = httpx.get(url, auth=httpx.DigestAuth(USER, hashlib.sha256((password or "").encode()).hexdigest()), timeout=timeout)
    except httpx.HTTPError as ex:
        raise DriverError(f"Adapter {ip} nicht erreichbar: {type(ex).__name__}")
    if r.status_code == 401:
        raise DriverError(f"Adapter {ip} lehnt die Anmeldung ab – Gerätepasswort prüfen (in der devolo Home Network App gesetzt)")
    if r.status_code >= 400:
        raise DriverError(f"Adapter {ip} meldet HTTP {r.status_code} für {sub}")
    return r.content


def _no_api(host):
    return DriverError(f"Unter {host} antwortet kein devolo-Adapter mit Geräte-API (mDNS-Dienst _dvl-plcnetapi). Ältere dLAN-Adapter, "
                       "die nur das dLAN Cockpit kennen, lassen sich nicht abfragen.")


def test(conf):
    host = conf["host"]
    svc = mdns(host)
    if PLCNET not in svc:
        raise _no_api(host)
    ov = parse_overview(_get(host, svc[PLCNET], "GetNetworkOverview", conf.get("password")))
    me = next((d for d in ov["devices"] if d["ip"] == host or d["local"]), {})
    return dict(name=me.get("name") or me.get("product") or host, product=me.get("product", ""), adapters=len(ov["devices"]))


def poll(conf, state):
    host, pw = conf["host"], conf.get("password") or ""
    svc = mdns(host)
    if PLCNET not in svc:
        raise _no_api(host)
    ov = parse_overview(_get(host, svc[PLCNET], "GetNetworkOverview", pw))
    if not ov["devices"]:
        raise DriverError(f"Adapter {host} meldet kein Powerline-Netz")
    checked = dict(state.get("fw_checked") or {})
    fw_known = dict(state.get("fw") or {})
    adapters, warnings = [], []
    for d in ov["devices"]:
        a = dict(d, name=d["name"] or d["product"] or d["mac"], clients=[], serial="", features=[])
        dsvc = svc if d["ip"] == host or (d["local"] and not d["ip"]) else (mdns(d["ip"], timeout=1.5) if d["ip"] else {})
        api = dsvc.get(DEVICEAPI)
        ip = d["ip"] or host
        if api:
            a["serial"] = api["txt"].get("SN", "")
            a["features"] = [f for f in (api["txt"].get("Features") or "").split(",") if f]
            try:
                if "wifi1" in a["features"]:
                    a["clients"] = parse_stations(_get(ip, api, "WifiConnectedStationsGet", pw))
                if conf.get("fw_check", "daily") != "no" and "update" in (a["features"] or ["update"]) \
                        and time.time() - checked.get(d["mac"], 0) > FW_EVERY:
                    fw_known[d["mac"]] = parse_fw_check(_get(ip, api, "UpdateFirmwareCheck", pw, timeout=30.0))
                    checked[d["mac"]] = time.time()
            except DriverError as ex:
                warnings.append(str(ex))
        fw = fw_known.get(d["mac"]) or {}
        a["firmware_info"] = dict(installed=d["firmware"], latest=fw.get("latest", ""), update=fw.get("update")) if d["firmware"] else None
        adapters.append(a)
    metrics = {}
    for r in ov["rates"]:
        key = f"plc:{r['src'].replace(':', '')}:{r['dst'].replace(':', '')}"
        if r["tx"] is not None:
            metrics[f"{key}:tx"] = r["tx"]
        if r["rx"] is not None:
            metrics[f"{key}:rx"] = r["rx"]
    me = next((a for a in adapters if a["ip"] == host), None) or next((a for a in adapters if a["local"]), adapters[0])
    res = dict(info=dict(name=me["name"], model=me["product"], firmware=me["firmware"], technology=me["technology"], network=me["network"],
                         adapters=len(adapters)),
               adapters=adapters, rates=ov["rates"], host_mac=me["mac"])
    if warnings:
        res["warning"] = warnings[0][:300]
    return res, metrics, dict(fw_checked=checked, fw=fw_known)
