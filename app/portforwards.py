"""Portfreigaben und UPnP: was aus dem Internet erreichbar ist.

Die Router-Treiber liefern res["forwards"] im gemeinsamen Format (drivers/controller.forward). Hier:
- track(): nach jeder Abfrage neue Freigaben erkennen (Ereignis „port_forward_new“, bis zum Quittieren als „neu“ markiert).
  Beim ersten Mal gilt alles Vorhandene als bekannt.
- state(): alle Freigaben des Profils mit Gerät hinter der Ziel-IP, Notiz und Kennzeichen „neu“.
Gespeichert in profiles.settings["portfw"] = {known: {key: ts}, new: {key: ts}, notes: {key: text}, base: [integration-id …]}.
"""
import json
import time

from .scan import runner

DRIVER_NAMES = {"fritzbox": "FRITZ!Box", "asuswrt": "ASUS", "openwrt": "OpenWrt", "mikrotik": "MikroTik", "opnsense": "OPNsense", "unifi": "UniFi"}


class PortError(Exception):
    pass


def key(iid, f):
    return f"{iid}:{f.get('kind') or ''}:{f['proto']}:{f['ext'] or '*'}>{f['ip']}:{f['port'] or '*'}"


def _load(c, pid):
    r = c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()
    s = json.loads(r["settings"] or "{}") if r else {}
    pf = s.get("portfw") or {}
    for k in ("known", "new", "notes"):
        pf.setdefault(k, {})
    pf.setdefault("base", [])
    return s, pf


def _save(c, pid, s, pf):
    s["portfw"] = pf
    c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(s, ensure_ascii=False), pid))


def target(f):
    return f"{f['ip']}:{f['port']}" if f.get("port") else f["ip"]


def track(c, row, res):
    """Nach einer Abfrage: neue Freigaben merken und melden. Zwischengespeicherte Listen zählen nicht."""
    fl = res.get("forwards")
    if fl is None or res.get("forwards_cached"):
        return 0
    pid, iid = row["profile_id"], row["id"]
    s, pf = _load(c, pid)
    now = int(time.time())
    cur = {key(iid, f): f for f in fl}
    prefix = f"{iid}:"
    gone = [k for k in pf["known"] if k.startswith(prefix) and k not in cur]
    for k in gone:
        pf["known"].pop(k, None)
        pf["new"].pop(k, None)
    fresh = [k for k in cur if k not in pf["known"]]
    first = iid not in pf["base"]
    for k in fresh:
        pf["known"][k] = now
        if not first:
            pf["new"][k] = now
            f = cur[k]
            runner.event(c, pid, "port_forward_new", row["device_id"], name=row["name"], proto=f["proto"], ext=f["ext"] or "*",
                         target=target(f), desc=f["desc"] or ("UPnP" if f["kind"] == "upnp" else ""))
    if first:
        pf["base"].append(iid)
    if fresh or gone or first:
        _save(c, pid, s, pf)
    return 0 if first else len(fresh)


def _devices_by_ip(c, pid):
    return {r["address"]: dict(id=r["device_id"], name=r["name"], type=r["type"]) for r in c.execute(
        "SELECT a.address, d.id AS device_id, d.name, d.type FROM ip_addresses a JOIN devices d ON d.id=a.device_id WHERE d.profile_id=?", (pid,))}


def state(c, pid, device_id=None):
    _, pf = _load(c, pid)
    by_ip = _devices_by_ip(c, pid)
    items, sources, problems = [], [], []
    for r in c.execute("SELECT id, name, driver, enabled, state FROM integrations WHERE profile_id=? ORDER BY id", (pid,)):
        res = (json.loads(r["state"] or "{}").get("result") or {})
        if "forwards" not in res:
            if res.get("forwards_error"):  # Quelle vorhanden, Liste aber nicht lesbar: Grund im Reiter zeigen
                problems.append(dict(id=r["id"], name=r["name"], driver=r["driver"], error=res["forwards_error"]))
            continue
        sources.append(dict(id=r["id"], name=r["name"], driver=r["driver"], kind=DRIVER_NAMES.get(r["driver"], r["driver"]),
                            count=len(res["forwards"] or []), enabled=bool(r["enabled"])))
        for f in res["forwards"] or []:
            k = key(r["id"], f)
            dev = by_ip.get(f["ip"])
            if device_id and (not dev or dev["id"] != device_id):
                continue
            items.append(dict(f, key=k, integration=r["id"], source=r["name"], driver=r["driver"], device=dev,
                              note=pf["notes"].get(k, ""), new=k in pf["new"], since=pf["known"].get(k)))
    items.sort(key=lambda x: (not x["new"], (x["device"] or {}).get("name", "~" + x["ip"]).lower(), x["proto"], x["ext"]))
    return dict(items=items, sources=sources, problems=problems, new=sum(1 for x in items if x["new"]),
                upnp=sum(1 for x in items if x["kind"] == "upnp"), total=len(items))


def ack(c, pid, keys=None):
    s, pf = _load(c, pid)
    for k in (list(pf["new"]) if keys is None else keys):
        pf["new"].pop(k, None)
    _save(c, pid, s, pf)


def set_note(c, pid, k, note):
    s, pf = _load(c, pid)
    if k not in pf["known"]:
        raise PortError("Diese Freigabe gibt es nicht (mehr)")
    note = str(note or "").strip()[:200]
    if note:
        pf["notes"][k] = note
    else:
        pf["notes"].pop(k, None)
    _save(c, pid, s, pf)


def forget_integration(c, pid, iid):
    """Integration gelöscht: ihre Einträge entfernen (Notizen bleiben nicht hängen)."""
    s, pf = _load(c, pid)
    prefix = f"{iid}:"
    for part in ("known", "new", "notes"):
        pf[part] = {k: v for k, v in pf[part].items() if not k.startswith(prefix)}
    pf["base"] = [x for x in pf["base"] if x != iid]
    _save(c, pid, s, pf)


def csv_text(st, lang="de"):
    import csv
    import io
    head = (["Neu", "Art", "Protokoll", "Port extern", "Ziel-IP", "Port intern", "Gerät", "Beschreibung", "Erlaubte Quelle", "Aktiv", "Quelle", "Notiz"]
            if lang != "en" else ["New", "Kind", "Protocol", "External port", "Target IP", "Internal port", "Device", "Description", "Allowed source", "Enabled", "Source", "Note"])
    kind = {"static": ("eingerichtet", "configured"), "upnp": ("UPnP", "UPnP"), "": ("–", "–")}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(head)
    for x in st["items"]:
        w.writerow(["x" if x["new"] else "", kind.get(x["kind"], kind[""])[lang == "en"], x["proto"], x["ext"] or "*", x["ip"], x["port"] or "*",
                    (x["device"] or {}).get("name", ""), x["desc"], x["remote"], "1" if x["enabled"] else "0", x["source"], x["note"]])
    return buf.getvalue()
