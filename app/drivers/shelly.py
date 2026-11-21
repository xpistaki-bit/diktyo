"""Treiber Shelly / Tasmota direkt (ohne Cloud): Leistung, Energie, Ausgänge schalten, Firmware.

Eine Integration für viele Geräte. „Adressen“: einzelne IPs, durch Komma getrennt, und/oder „auto“ – dann übergibt díktyo
die Adressen aller Geräte, die es als Shelly/Tasmota erkannt hat, und die von ESP-Modulen (Espressif), die oft Tasmota tragen
(conf["targets"], siehe integrations.smart_targets). Was nicht antwortet, wird für einige Stunden übersprungen.

Unterstützt:
  Shelly Gen1 (HTTP):        /shelly, /status, /relay/<n>?turn=on|off, /ota?update=1 – Basic-Auth
  Shelly Gen2/3/4 (RPC):     /shelly, /rpc Shelly.GetStatus, Switch.Set, Shelly.Update – Digest-Auth (Benutzer admin)
  Tasmota:                   /cm?cmnd=Status 0, Power<n> On|Off, Upgrade 1 – user/password als Parameter
"""
import concurrent.futures as cf
import time

import httpx

from .controller import DriverError, mac as norm_mac

NAME = "Shelly / Tasmota"
DEFAULT_INTERVAL = 60
FIELDS = [
    dict(key="host", label="Adressen", type="text", default="auto", required=True,
         placeholder="auto oder 192.168.1.40, 192.168.1.41 (auto = alle erkannten Shelly/Tasmota)"),
    dict(key="username", label="Benutzer (falls Anmeldung eingeschaltet)", type="text", default="", placeholder="Shelly Gen2+: admin"),
    dict(key="password", label="Passwort (falls Anmeldung eingeschaltet)", type="password", default="", secret=True),
]
TIMEOUT = 4
SKIP_S = 6 * 3600  # Adressen ohne Antwort so lange überspringen (bei „auto“)


def _auth(conf, digest=False):
    if not conf.get("password"):
        return None
    user = conf.get("username") or "admin"
    return httpx.DigestAuth(user, conf["password"]) if digest else httpx.BasicAuth(user, conf["password"])


def _get(ip, path, conf, digest=False, params=None):
    try:
        r = httpx.get(f"http://{ip}{path}", params=params, auth=_auth(conf, digest), timeout=TIMEOUT)
    except httpx.HTTPError as ex:
        raise DriverError(f"{ip} nicht erreichbar ({type(ex).__name__})")
    if r.status_code == 401:
        raise DriverError(f"{ip}: Anmeldung verlangt – Benutzer/Passwort in der Integration eintragen")
    if r.status_code >= 400:
        raise DriverError(f"{ip}: HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise DriverError(f"{ip}: keine JSON-Antwort")


def _rpc(ip, method, conf, params=None):
    try:
        r = httpx.post(f"http://{ip}/rpc", json=dict(id=1, method=method, params=params or {}), auth=_auth(conf, True), timeout=TIMEOUT)
    except httpx.HTTPError as ex:
        raise DriverError(f"{ip} nicht erreichbar ({type(ex).__name__})")
    if r.status_code == 401:
        raise DriverError(f"{ip}: Anmeldung verlangt – Passwort (Benutzer admin) in der Integration eintragen")
    j = r.json() if r.content else {}
    if "error" in j:
        raise DriverError(f"{ip}: {j['error'].get('message', j['error'])}")
    return j.get("result", j)


def _tasmota(ip, cmnd, conf):
    params = {"cmnd": cmnd}
    if conf.get("password"):
        params.update(user=conf.get("username") or "admin", password=conf["password"])
    return _get(ip, "/cm", conf, params=params)


# ------------------------------------------------------------ Lesen
def _w(v):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def newer(latest, installed):
    """Ist latest wirklich neuer als installed? („1.14.0“ gegen „1.14.1“ -> nein)"""
    import re
    num = lambda s: tuple(int(x) for x in re.findall(r"\d+", str(s or ""))[:4])  # noqa: E731
    return bool(latest) and num(latest) > num(installed)


def read_shelly1(ip, info, st, settings=None):
    relays = st.get("relays") or []
    meters = st.get("meters") or []
    emeters = st.get("emeters") or []
    ch = []
    for i, r in enumerate(relays):
        m = meters[i] if i < len(meters) else {}
        ch.append(dict(id=i, name=r.get("name") or (f"Ausgang {i + 1}" if len(relays) > 1 else "Ausgang"), on=bool(r.get("ison")),
                       power_w=_w(m.get("power"))))
    power = sum(x for x in [_w(m.get("power")) for m in meters] + [_w(e.get("power")) for e in emeters] if x is not None) if (meters or emeters) else None
    energy = sum((m.get("total") or 0) / 60000 for m in meters) + sum((e.get("total") or 0) / 1000 for e in emeters) if (meters or emeters) else None
    up = st.get("update") or {}
    inst, new = _fw1(info.get("fw") or up.get("old_version")), _fw1(up.get("new_version")) if up.get("has_update") else ""
    upd = newer(new, inst) if up else None
    return dict(kind="shelly", gen=1, model=info.get("type", ""), mac=norm_mac(info.get("mac") or st.get("mac")),
                name=((settings or {}).get("name") or st.get("name") or ""),
                channels=ch, power_w=power, energy_kwh=round(energy, 3) if energy is not None else None,
                rssi=(st.get("wifi_sta") or {}).get("rssi"), voltage=_w((emeters[0] if emeters else {}).get("voltage")),
                firmware=dict(installed=inst, latest=new if upd else "", update=upd))


def _fw1(s):
    """„20230913-114008/v1.14.0-gcb84623“ -> „1.14.0“"""
    s = str(s or "")
    return s.split("/v")[-1].split("-")[0] if "/v" in s else s


def read_shelly2(ip, info, st):
    ch, power, energy = [], [], []
    for key, v in sorted(st.items()):
        if not isinstance(v, dict):
            continue
        typ = key.split(":")[0]
        if typ in ("switch", "light"):
            ch.append(dict(id=v.get("id", int(key.split(":")[1]) if ":" in key else 0), name="", on=bool(v.get("output")), power_w=_w(v.get("apower")),
                           comp=typ))
            if v.get("apower") is not None:
                power.append(_w(v["apower"]))
            if (v.get("aenergy") or {}).get("total") is not None:
                energy.append(v["aenergy"]["total"] / 1000)
        elif typ == "pm1" and v.get("apower") is not None:
            power.append(_w(v["apower"]))
            if (v.get("aenergy") or {}).get("total") is not None:
                energy.append(v["aenergy"]["total"] / 1000)
        elif typ == "em" and v.get("total_act_power") is not None:      # Pro 3EM: Summe der drei Phasen
            power.append(_w(v["total_act_power"]))
        elif typ == "em1" and v.get("act_power") is not None:
            power.append(_w(v["act_power"]))
        elif typ == "emdata" and v.get("total_act") is not None:
            energy.append(v["total_act"] / 1000)
    if len(ch) == 1:
        ch[0]["name"] = "Ausgang"
    for c in ch:
        c["name"] = c["name"] or f"Ausgang {c['id'] + 1}"
    upd = ((st.get("sys") or {}).get("available_updates") or {}).get("stable") or {}
    voltage = next((_w(v.get("voltage")) for k, v in st.items() if isinstance(v, dict) and k.startswith(("switch:", "pm1:")) and v.get("voltage") is not None), None)
    return dict(kind="shelly", gen=int(info.get("gen") or 2), model=info.get("model") or info.get("app") or "", mac=norm_mac(info.get("mac")),
                name=info.get("name") or "", channels=ch, power_w=round(sum(p for p in power if p is not None), 1) if power else None,
                energy_kwh=round(sum(energy), 3) if energy else None, rssi=(st.get("wifi") or {}).get("rssi"), voltage=voltage,
                firmware=dict(installed=str(info.get("ver") or ""), latest=str(upd.get("version") or "") if newer(upd.get("version"), info.get("ver")) else "",
                              update=newer(upd.get("version"), info.get("ver"))))


def read_tasmota(ip, s):
    fw = (s.get("StatusFWR") or {}).get("Version", "")
    net = s.get("StatusNET") or {}
    sts = s.get("StatusSTS") or {}
    en = ((s.get("StatusSNS") or {}).get("ENERGY")) or {}
    keys = sorted(k for k in sts if k.startswith("POWER"))
    ch = [dict(id=int(k[5:] or 1), name=f"Ausgang {k[5:]}" if len(keys) > 1 else "Ausgang", on=str(sts[k]).upper() == "ON", power_w=None) for k in keys]
    if len(ch) == 1 and en.get("Power") is not None:
        ch[0]["power_w"] = _w(en["Power"] if not isinstance(en["Power"], list) else sum(en["Power"]))
    p = en.get("Power")
    return dict(kind="tasmota", gen=None, model=(s.get("Status") or {}).get("DeviceName") or (s.get("StatusFWR") or {}).get("Hardware", ""),
                mac=norm_mac(net.get("Mac")), name=((s.get("Status") or {}).get("FriendlyName") or [""])[0], channels=ch,
                power_w=_w(sum(p) if isinstance(p, list) else p), energy_kwh=_w(en.get("Total")), rssi=(sts.get("Wifi") or {}).get("RSSI"),
                voltage=_w(en.get("Voltage") if not isinstance(en.get("Voltage"), list) else en["Voltage"][0]),
                firmware=dict(installed=fw.split("(")[0].strip(), latest="", update=None))


def read(ip, conf):
    """Ein Gerät lesen (Art wird erkannt). -> dict oder DriverError"""
    try:
        info = _get(ip, "/shelly", conf)
    except DriverError as ex:
        if "Anmeldung" in str(ex):
            raise
        info = None
    if info and (info.get("gen") or 0) >= 2:
        return dict(read_shelly2(ip, info, _rpc(ip, "Shelly.GetStatus", conf)), ip=ip)
    if info and info.get("type"):
        try:
            settings = _get(ip, "/settings", conf)  # Gerätename steht bei Gen1 nur hier
        except DriverError:
            settings = {}
        return dict(read_shelly1(ip, info, _get(ip, "/status", conf), settings), ip=ip)
    s = _tasmota(ip, "Status 0", conf)
    if "StatusFWR" not in s and "Status" not in s:
        raise DriverError(f"{ip}: weder Shelly noch Tasmota")
    return dict(read_tasmota(ip, s), ip=ip)


def _targets(conf, state=None):
    ips = [x.strip() for x in str(conf.get("host") or "").replace(";", ",").split(",") if x.strip() and x.strip().lower() != "auto"]
    for ip in conf.get("targets") or []:
        if ip not in ips:
            ips.append(ip)
    return ips


def _read_all(conf, state):
    now = time.time()
    skip = dict((state or {}).get("skip") or {})
    manual = set(_targets(dict(conf, targets=[])))
    todo = [ip for ip in _targets(conf) if ip in manual or skip.get(ip, 0) < now]
    out, errors = [], {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(read, ip, conf): ip for ip in todo}
        for f in cf.as_completed(futs):
            ip = futs[f]
            try:
                out.append(f.result())
                skip.pop(ip, None)
            except DriverError as e:
                errors[ip] = str(e)
                if ip not in manual and "Anmeldung" not in str(e):
                    skip[ip] = now + SKIP_S
            except Exception as e:  # unerwartete Antwort eines Geräts darf die anderen nicht stören
                errors[ip] = f"{ip}: {type(e).__name__}"
    return sorted(out, key=lambda d: d["ip"]), errors, skip


def test(conf):
    ips = _targets(conf)
    if not ips:
        raise DriverError("Keine Adressen – IPs eintragen oder „auto“ (dann zuerst einen Netzscan, damit díktyo Shelly/Tasmota kennt)")
    devs, errors, _ = _read_all(conf, {})
    if not devs:
        raise DriverError("Kein Gerät hat geantwortet: " + "; ".join(list(errors.values())[:3]))
    return dict(devices=len(devs), shelly=sum(1 for d in devs if d["kind"] == "shelly"), tasmota=sum(1 for d in devs if d["kind"] == "tasmota"),
                power_w=round(sum(d["power_w"] or 0 for d in devs), 1))


def poll(conf, state):
    devs, errors, skip = _read_all(conf, state)
    if not devs and errors and all(ip in set(_targets(dict(conf, targets=[]))) for ip in errors):
        raise DriverError("; ".join(list(errors.values())[:3]))
    manual_err = {ip: e for ip, e in errors.items() if ip in set(_targets(dict(conf, targets=[])))}
    res = dict(info=dict(devices=len(devs)), devices=devs)
    if manual_err:
        res["warning"] = "; ".join(list(manual_err.values())[:3])
    return res, {}, dict(state, skip=skip)


# ------------------------------------------------------------ Schalten
def action(conf, state, kind, params):
    ip, fam = params["ip"], params.get("kind")
    if kind == "relay":
        ch, on = int(params["channel"]), bool(params["on"])
        if fam == "tasmota":
            _tasmota(ip, f"Power{ch} {'On' if on else 'Off'}", conf)
        elif params.get("gen", 1) >= 2:
            _rpc(ip, "Light.Set" if params.get("comp") == "light" else "Switch.Set", conf, {"id": ch, "on": on})
        else:
            _get(ip, f"/relay/{ch}", conf, params={"turn": "on" if on else "off"})
        return f"{params.get('name') or ip}: {'eingeschaltet' if on else 'ausgeschaltet'}"
    if kind == "fw_update":
        if fam == "tasmota":
            _tasmota(ip, "Upgrade 1", conf)
        elif params.get("gen", 1) >= 2:
            _rpc(ip, "Shelly.Update", conf, {"stage": "stable"})
        else:
            _get(ip, "/ota", conf, params={"update": "1"})
        return f"{params.get('name') or ip}: Firmware-Update gestartet (Gerät startet danach neu)"
    raise DriverError(f"Unbekannte Aktion {kind}")
