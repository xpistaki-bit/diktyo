"""Anpassbare Übersicht: Reihenfolge, Breite und Sichtbarkeit der Felder sowie angeheftete Diagramme je Profil.

Gespeichert in profiles.settings["dashboard"] = {"items": [...]}; ein Eintrag ist entweder ein eingebautes Feld
({"id": "wan", "size": 5, "hidden": false}) oder ein angeheftetes Diagramm ({"id": "p_…", "size": 6, "pin": {...}}).
Eingebaute Felder, die in einer neueren Version dazukommen, landen hinter ihrem Vorgänger aus der Standard-Reihenfolge. Angeheftet werden können nur
Messreihen, die es im Profil gibt (WAN, Switch-Ports, ASUS-Schnittstellen, DNS-Filter, Antwortzeit und Leistung je Gerät).
"""
import json
import re
import secrets

# eingebaute Felder in der Standard-Reihenfolge mit Standardbreite (von 12 Spalten)
BUILTINS = [("wan", 5), ("speed", 4), ("issues", 3), ("watch", 4), ("ports", 4), ("live", 4), ("today", 4), ("rtt", 4), ("infra", 8),
            ("dns", 4), ("recent", 4)]
SIZES = (3, 4, 5, 6, 8, 12)
UNITS = ("bps", "ms", "W", "count", "pct", "dB")
STYLES = ("bars", "line")
MAX_PINS = 24
ASUS_IF = {"lan": "LAN", "bridge": "Bridge", "wl0": "WLAN 2,4 GHz", "wl1": "WLAN 5 GHz-1", "wl2": "WLAN 5 GHz-2", "wl3": "WLAN 6 GHz"}


class LayoutError(Exception):
    pass


def default_items():
    return [dict(id=k, size=s, hidden=False) for k, s in BUILTINS]


def _load(c, pid):
    p = c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()
    return json.loads(p["settings"] or "{}") if p else {}


def get(c, pid):
    """Gespeichertes Layout, ergänzt um neue eingebaute Felder; customized = vom Standard abweichend gespeichert."""
    saved = (_load(c, pid).get("dashboard") or {}).get("items")
    if not saved:
        return dict(items=default_items(), customized=False)
    have = {x["id"] for x in saved}
    known = dict(BUILTINS)
    items = [x for x in saved if x["id"] in known or x.get("pin")]
    for i, (k, s) in enumerate(BUILTINS):  # neue Felder hinter ihren Vorgänger in der Standard-Reihenfolge
        if k in have:
            continue
        prev = next((BUILTINS[j][0] for j in range(i - 1, -1, -1) if any(x["id"] == BUILTINS[j][0] for x in items)), None)
        at = next((n + 1 for n, x in enumerate(items) if x["id"] == prev), 0 if prev is None else len(items))
        items.insert(at, dict(id=k, size=s, hidden=False))
    return dict(items=items, customized=True)


def _series_keys(c, pid):
    return {r["key"] for r in c.execute("SELECT key FROM series WHERE profile_id=?", (pid,))}


def _clean_pin(p, keys_ok):
    if not isinstance(p, dict):
        raise LayoutError("Ungültiges Diagramm")
    keys = [str(k) for k in (p.get("keys") or [])][:4]
    if not keys or any(k not in keys_ok for k in keys):
        raise LayoutError("Messreihe gibt es in diesem Profil nicht (mehr)")
    names = [str(n)[:40] for n in (p.get("names") or [])][:len(keys)]
    names += [""] * (len(keys) - len(names))
    unit = p.get("unit") if p.get("unit") in UNITS else "bps"
    style = p.get("style") if p.get("style") in STYLES else "bars"
    return dict(title=str(p.get("title") or "").strip()[:80] or "Diagramm", keys=keys, names=names, unit=unit, style=style,
                mirror=bool(p.get("mirror")) and len(keys) == 2)


def save(c, pid, items):
    """Layout prüfen und speichern. items=None setzt auf den Standard zurück."""
    st = _load(c, pid)
    if items is None:
        st.pop("dashboard", None)
    else:
        if not isinstance(items, list):
            raise LayoutError("Ungültiges Layout")
        known, keys_ok, seen, out = dict(BUILTINS), _series_keys(c, pid), set(), []
        for x in items[:len(BUILTINS) + MAX_PINS + 4]:
            if not isinstance(x, dict) or not x.get("id") or x["id"] in seen:
                continue
            iid = str(x["id"])[:24]
            size = x.get("size") if x.get("size") in SIZES else None
            if iid in known:
                out.append(dict(id=iid, size=size or known[iid], hidden=bool(x.get("hidden"))))
            elif x.get("pin") and re.fullmatch(r"p_[0-9a-f]{6,16}", iid):
                out.append(dict(id=iid, size=size or 6, pin=_clean_pin(x["pin"], keys_ok)))
            else:
                continue
            seen.add(iid)
        if sum(1 for x in out if x.get("pin")) > MAX_PINS:
            raise LayoutError(f"Höchstens {MAX_PINS} angeheftete Diagramme")
        st["dashboard"] = dict(items=out)
    c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
    return get(c, pid)


def add_pin(c, pid, pin, size=6):
    """Diagramm hinten anheften (z. B. aus dem Gerätedialog oder einer Integrationskarte)."""
    cur = get(c, pid)["items"]
    if sum(1 for x in cur if x.get("pin")) >= MAX_PINS:
        raise LayoutError(f"Höchstens {MAX_PINS} angeheftete Diagramme")
    p = _clean_pin(pin, _series_keys(c, pid))
    if any(x.get("pin", {}).get("keys") == p["keys"] for x in cur):
        raise LayoutError("Dieses Diagramm ist schon angeheftet")
    cur.append(dict(id="p_" + secrets.token_hex(4), size=size if size in SIZES else 6, pin=p))
    return save(c, pid, cur)


EN = {"Schnittstellen": "Interfaces", "DNS-Filter": "DNS filter", "Antwortzeit je Gerät": "Response time per device",
      "Leistung je Gerät": "Power per device", "Antwortzeit": "Response time", "Leistung": "Power", "blockiert %": "blocked %",
      "Leitung (DSL/Kabel)": "Line (DSL/cable)", "neue Fehler": "new errors", "Leitung": "Line"}


def _tr(s, lang):
    if lang != "en":
        return s
    for de, en in EN.items():
        s = s.replace(de, en)
    return s


def candidates(c, pid, lang="de"):
    """Anheftbare Diagramme des Profils, gruppiert: [{group, title, keys, names, unit, style, mirror}]"""
    keys = _series_keys(c, pid)
    integ = {r["id"]: r for r in c.execute("SELECT id, name, driver, device_id FROM integrations WHERE profile_id=?", (pid,))}
    devs = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM devices WHERE profile_id=?", (pid,))}
    out = []
    from .dashboard import _port_peer

    def pair(base):
        return f"{base}:rx" in keys and f"{base}:tx" in keys

    for iid, r in sorted(integ.items()):
        dev = devs.get(r["device_id"]) or r["name"]
        if pair(f"i{iid}:wan"):
            out.append(dict(group="Internet (WAN)", title=f"WAN · {r['name']}", keys=[f"i{iid}:wan:rx", f"i{iid}:wan:tx"],
                            names=["Download", "Upload"], unit="bps", style="bars", mirror=True))
        ports = sorted({int(m.group(1)) for k in keys if (m := re.fullmatch(rf"i{iid}:port:(\d+):rx", k))})
        for n in ports:
            if not pair(f"i{iid}:port:{n}"):
                continue
            peers = _port_peer(c, r["device_id"], n)["peers"]
            who = ", ".join(x["name"] for x in peers[:2])
            out.append(dict(group=f"Ports · {dev}", title=f"{dev} · Port {n}" + (f" → {who}" if who else ""),
                            keys=[f"i{iid}:port:{n}:tx", f"i{iid}:port:{n}:rx"],
                            names=["zum Gerät", "vom Gerät"] if who else ["gesendet", "empfangen"], unit="bps", style="bars", mirror=True))
        for k, label in ASUS_IF.items():
            if pair(f"i{iid}:if:{k}"):
                out.append(dict(group=f"Schnittstellen · {r['name']}", title=f"{r['name']} · {label}",
                                keys=[f"i{iid}:if:{k}:rx", f"i{iid}:if:{k}:tx"], names=["empfangen", "gesendet"], unit="bps", style="bars", mirror=True))
        if f"i{iid}:dns:qpm" in keys:
            out.append(dict(group="DNS-Filter", title=f"DNS · {r['name']}", keys=[f"i{iid}:dns:qpm"] + ([f"i{iid}:dns:bpm"] if f"i{iid}:dns:bpm" in keys else []),
                            names=["Anfragen/min", "blockiert/min"], unit="count", style="bars", mirror=False))
        snr = [k for k in (f"i{iid}:line:snr_down", f"i{iid}:line:snr_up", f"i{iid}:line:snr_min") if k in keys]
        if snr:
            out.append(dict(group="Leitung (DSL/Kabel)", title=f"Leitung · {r['name']}", keys=snr,
                            names=["schwächster Kanal"] if snr[0].endswith("snr_min") else ["Störabstand ↓", "Störabstand ↑"][:len(snr)],
                            unit="dB", style="line", mirror=False))
        if f"i{iid}:line:err" in keys:
            out.append(dict(group="Leitung (DSL/Kabel)", title=f"Leitung · {r['name']} · neue Fehler", keys=[f"i{iid}:line:err"],
                            names=["Fehler"], unit="count", style="bars", mirror=False))
        if f"i{iid}:dns:blocked_pct" in keys:
            out.append(dict(group="DNS-Filter", title=f"DNS · {r['name']} · blockiert %", keys=[f"i{iid}:dns:blocked_pct"],
                            names=["blockiert"], unit="pct", style="line", mirror=False))
    for k in sorted(keys):
        m = re.fullmatch(r"d(\d+):(rtt|power)", k)
        if m and int(m.group(1)) in devs:
            name = devs[int(m.group(1))]
            if m.group(2) == "rtt":
                out.append(dict(group="Antwortzeit je Gerät", title=f"{name} · Antwortzeit", keys=[k], names=["Antwortzeit"], unit="ms", style="line", mirror=False))
            else:
                out.append(dict(group="Leistung je Gerät", title=f"{name} · Leistung", keys=[k], names=["Leistung"], unit="W", style="line", mirror=False))
    for x in out:
        x["group"], x["title"] = _tr(x["group"], lang), _tr(x["title"], lang)
    return out
