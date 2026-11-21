"""Gerätekatalog: Typen, Port-Gruppen, Startkatalog, CSV-Import und -Export."""
import csv
import io
import json
import pathlib

BASE = pathlib.Path(__file__).resolve().parent

# Gerätetypen (Schlüssel -> deutscher Name; englische Namen in TYPE_EN)
TYPES = {
    "router": "Router", "modem": "Modem", "firewall": "Firewall", "switch": "Switch", "ap": "Access Point",
    "mesh": "Mesh-Knoten", "repeater": "Repeater", "powerline": "Powerline", "server": "Server", "hypervisor": "Hypervisor",
    "vm": "VM", "container": "Container", "nas": "NAS", "computer": "Computer", "laptop": "Laptop", "phone": "Smartphone",
    "tablet": "Tablet", "tv": "TV / Medien", "speaker": "Smart Speaker", "camera": "Kamera", "iot": "IoT-Gerät",
    "printer": "Drucker", "console": "Spielkonsole", "ups": "USV", "printer3d": "3D-Drucker", "vacuum": "Saugroboter", "doorbell": "Türklingel", "hub": "Smart-Home-Hub (Zigbee, Matter, Thread)", "esp": "ESP-Gerät (ESPHome, Tasmota)", "plug": "Steckdose / Schalter", "light": "Licht / Lampe", "thermostat": "Thermostat / Heizung", "energy": "Energie (PV, Speicher, Zähler)", "wallbox": "Wallbox", "appliance": "Haushaltsgerät", "sensor": "Sensor", "voip": "Telefon / VoIP", "wearable": "Uhr / Wearable", "other": "Sonstiges",
}
TYPE_EN = {
    "router": "Router", "modem": "Modem", "firewall": "Firewall", "switch": "Switch", "ap": "Access point", "mesh": "Mesh node",
    "repeater": "Repeater", "powerline": "Powerline", "server": "Server", "hypervisor": "Hypervisor", "vm": "VM",
    "container": "Container", "nas": "NAS", "computer": "Computer", "laptop": "Laptop", "phone": "Smartphone", "tablet": "Tablet",
    "tv": "TV / media", "speaker": "Smart speaker", "camera": "Camera", "iot": "IoT device", "printer": "Printer",
    "console": "Game console", "ups": "UPS", "printer3d": "3D printer", "vacuum": "Robot vacuum", "doorbell": "Doorbell", "hub": "Smart home hub (Zigbee, Matter, Thread)", "esp": "ESP device (ESPHome, Tasmota)", "plug": "Plug / switch", "light": "Light / lamp", "thermostat": "Thermostat / heating", "energy": "Energy (PV, battery, meter)", "wallbox": "Wallbox", "appliance": "Household appliance", "sensor": "Sensor", "voip": "Phone / VoIP", "wearable": "Watch / wearable", "other": "Other",
}
PORT_KINDS = ("rj45", "sfp", "sfp+", "sfp28", "coax", "dsl", "fiber", "usb")
MEDIA = ("lan", "wlan", "mesh", "virtual")  # Verbindungsarten


def sorted_types(lang="de"):
    """Typen alphabetisch nach Anzeigename, „Sonstiges“ zuletzt."""
    names = TYPE_EN if lang == "en" else TYPES
    return sorted((k for k in TYPES if k != "other"), key=lambda k: names[k].lower()) + ["other"]


def type_name(t, lang="de"):
    return (TYPE_EN if lang == "en" else TYPES).get(t, t)


# ------------------------------------------------------------ Port-Gruppen
# Ein Gerät hat Port-Gruppen, z. B. [{"count": 24, "kind": "rj45", "speed": "1G"}, {"count": 4, "kind": "sfp+", "speed": "10G"}].
# Daraus entstehen fortlaufend nummerierte Ports. Textform (CSV): "24:rj45:1G, 4:sfp+:10G, 1:rj45:2.5G:WAN:poe".
def clean_groups(groups):
    out = []
    for g in groups or []:
        try:
            n = int(g.get("count") or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            continue
        kind = str(g.get("kind") or "rj45").lower()
        out.append(dict(count=min(n, 128), kind=kind if kind in PORT_KINDS else "rj45", speed=str(g.get("speed") or "").strip()[:12],
                        label=str(g.get("label") or "").strip()[:20], poe=bool(g.get("poe"))))
    return out[:16]


def parse_ports(text):
    groups = []
    for part in str(text or "").replace(";", ",").split(","):
        f = [x.strip() for x in part.split(":")]
        if not f or not f[0]:
            continue
        groups.append(dict(count=f[0], kind=f[1] if len(f) > 1 else "rj45", speed=f[2] if len(f) > 2 else "",
                           label=f[3] if len(f) > 3 else "", poe=len(f) > 4 and f[4].lower() in ("poe", "1", "ja", "yes", "true")))
    return clean_groups(groups)


def format_ports(groups):
    out = []
    for g in clean_groups(groups):
        f = [str(g["count"]), g["kind"], g["speed"], g["label"], "poe" if g["poe"] else ""]
        while f and not f[-1]:
            f.pop()
        out.append(":".join(f))
    return ", ".join(out)


def expand_ports(groups):
    """-> Liste der Ports mit port_no, name, kind, speed, poe."""
    ports, no = [], 0
    for g in clean_groups(groups):
        for i in range(g["count"]):
            no += 1
            if g["label"]:
                name = g["label"] if g["count"] == 1 else f'{g["label"]} {i + 1}'
            else:
                name = str(no)
            ports.append(dict(port_no=no, name=name, kind=g["kind"], speed=g["speed"], poe=1 if g["poe"] else 0))
    return ports


def port_summary(groups):
    return " + ".join(f'{g["count"]}× {g["label"] + " " if g["label"] else ""}{g["kind"].upper()}{" " + g["speed"] if g["speed"] else ""}{" PoE" if g["poe"] else ""}'
                      for g in clean_groups(groups))


# ------------------------------------------------------------ Datenbank
def row(r):
    d = json.loads(r["data"] or "{}")
    return dict(id=r["id"], type=r["type"], manufacturer=r["manufacturer"], model=r["model"], custom=bool(r["custom"]), **d,
                ports_text=format_ports(d.get("ports")), port_summary=port_summary(d.get("ports")))


def clean_data(body):
    d = dict(
        ports=clean_groups(body.get("ports")) if isinstance(body.get("ports"), list) else parse_ports(body.get("ports_text") or body.get("ports")),
        wifi=str(body.get("wifi") or "").strip()[:80],
        managed=bool(body.get("managed")),
        driver=str(body.get("driver") or "").strip()[:40],
        note=str(body.get("note") or "").strip()[:500],
        verified=bool(body.get("verified")),
    )
    if isinstance(body.get("match"), dict):
        d["match"] = body["match"]
    if body.get("source"):
        d["source"] = str(body["source"])[:120]
    return d


def merge_seed(c):
    """Startkatalog einspielen: fehlende Einträge anlegen, neue Felder nachtragen, eigene Änderungen nie überschreiben."""
    have = {(r["manufacturer"], r["model"]): r for r in c.execute("SELECT * FROM device_models")}
    for e in json.loads((BASE / "catalog_seed.json").read_text(encoding="utf-8")):
        old = have.get((e["manufacturer"], e["model"]))
        if old is None:
            c.execute("INSERT INTO device_models(type, manufacturer, model, data, custom) VALUES(?,?,?,?,0)",
                      (e["type"], e["manufacturer"], e["model"], json.dumps(e["data"], ensure_ascii=False)))
        elif not old["custom"]:
            data = json.loads(old["data"] or "{}")
            add = {k: v for k, v in e["data"].items() if k not in data}
            if add:
                data.update(add)
                c.execute("UPDATE device_models SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), old["id"]))


# ------------------------------------------------------------ CSV
CSV_COLS = ["type", "manufacturer", "model", "ports", "wifi", "managed", "driver", "verified", "note"]
ALIASES = {"typ": "type", "art": "type", "hersteller": "manufacturer", "modell": "model", "ports": "ports", "anschlüsse": "ports",
           "wlan": "wifi", "verwaltet": "managed", "managed": "managed", "treiber": "driver", "geprüft": "verified", "geprueft": "verified",
           "hinweis": "note", "notiz": "note"}
TYPE_ALIASES = {v.lower(): k for k, v in TYPES.items()} | {v.lower(): k for k, v in TYPE_EN.items()} | {"accesspoint": "ap", "access-point": "ap"}
TRUE = ("1", "ja", "yes", "true", "x", "wahr")


def parse_csv(raw):
    """-> (einträge, fehlerliste). Trennzeichen ; oder , wird erkannt."""
    text = raw.decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text.strip() else ""
    delim = ";" if first.count(";") >= first.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if not rows:
        return [], ["Datei ist leer"]
    head = [ALIASES.get(h.strip().lower(), h.strip().lower()) for h in rows[0]]
    if "manufacturer" not in head or "model" not in head:
        return [], ["Spalten 'manufacturer' und 'model' (Hersteller, Modell) sind erforderlich"]
    out, errs = [], []
    for n, r in enumerate(rows[1:], start=2):
        d = {h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(head) if h in CSV_COLS}
        if not d.get("manufacturer") or not d.get("model"):
            errs.append(f"Zeile {n}: Hersteller oder Modell fehlt")
            continue
        t = d.get("type", "").lower()
        t = t if t in TYPES else TYPE_ALIASES.get(t, "other")
        data = clean_data(dict(ports_text=d.get("ports", ""), wifi=d.get("wifi"), managed=d.get("managed", "").lower() in TRUE,
                               driver=d.get("driver"), verified=d.get("verified", "").lower() in TRUE, note=d.get("note"), source="CSV"))
        out.append(dict(type=t, manufacturer=d["manufacturer"][:80], model=d["model"][:120], data=data))
    return out, errs


def export_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(CSV_COLS)
    for r in rows:
        d = json.loads(r["data"] or "{}")
        w.writerow([r["type"], r["manufacturer"], r["model"], format_ports(d.get("ports")), d.get("wifi", ""),
                    "1" if d.get("managed") else "", d.get("driver", ""), "1" if d.get("verified") else "", d.get("note", "")])
    return "﻿" + buf.getvalue()
