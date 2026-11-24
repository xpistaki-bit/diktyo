"""CSV- und PDF-Ausgabe eines Profils (DE/EN)."""
import csv
import datetime
import io

from . import catalog, inventory, ipam
from .pdf import Doc

SECTIONS = ("topology", "devices", "ipplan", "vlans", "ports", "cabling", "wlan", "notes")
MEDIUM = {"de": {"lan": "LAN", "wlan": "WLAN", "mesh": "Mesh-Backhaul", "virtual": "virtuell"},
          "en": {"lan": "LAN", "wlan": "Wi-Fi", "mesh": "Mesh backhaul", "virtual": "virtual"}}
KIND = {"de": {"static": "statisch", "dhcp": "DHCP", "reserved": "reserviert"}, "en": {"static": "static", "dhcp": "DHCP", "reserved": "reserved"}}
S = {
    "topology": ("Topologie", "Topology"), "loose": ("Ohne Verbindung", "Not connected"),
    "group_wlan": ("{n} WLAN-Geräte", "{n} Wi-Fi devices"), "group_virtual": ("{n} VMs / Container", "{n} VMs / containers"),
    "legend": ("Linien: durchgezogen LAN · gestrichelt WLAN · gepunktet Mesh-Backhaul · fein virtuell",
               "Lines: solid LAN · dashed Wi-Fi · dotted mesh backhaul · fine virtual"),
    "devices": ("Geräteliste", "Device list"), "ipplan": ("IP-Plan", "IP plan"), "vlans": ("VLANs", "VLANs"),
    "ports": ("Portbelegung", "Port assignment"), "wlan": ("WLAN-Übersicht", "Wi-Fi overview"), "notes": ("Notizen", "Notes"),
    "name": ("Name", "Name"), "type": ("Typ", "Type"), "model": ("Hersteller / Modell", "Manufacturer / model"), "ip": ("IP", "IP"),
    "mac": ("MAC", "MAC"), "location": ("Standort", "Location"), "uplink": ("Anschluss", "Connection"), "port": ("Port", "Port"),
    "peer": ("Verbunden mit", "Connected to"), "medium": ("Verbindung", "Link"), "kind": ("Art", "Kind"), "device": ("Gerät", "Device"),
    "hostname": ("Hostname", "Hostname"), "vid": ("VLAN-ID", "VLAN ID"), "subnets": ("Subnetze", "Subnets"),
    "description": ("Beschreibung", "Description"), "note": ("Notiz", "Note"), "gateway": ("Gateway", "Gateway"), "dns": ("DNS", "DNS"),
    "dhcp": ("DHCP-Bereich", "DHCP range"), "vlan": ("VLAN", "VLAN"), "usage": ("Belegt", "Used"), "free": ("Frei für statische Adressen", "Free for static addresses"),
    "speed": ("Geschwindigkeit", "Speed"), "clients": ("{n} Geräte", "{n} devices"), "none": ("Keine Einträge.", "No entries."),
    "created": ("Erstellt am {d}", "Created on {d}"), "page": ("Seite", "Page"), "title": ("Netzwerk-Dokumentation", "Network documentation"),
    "in_dhcp": (" (im DHCP-Bereich)", " (in DHCP range)"), "tags": ("Tags", "Tags"), "status": ("Status", "Status"),
    "free_more": ("… und {n} weitere Bereiche", "… and {n} more ranges"),
    "vlan_ports": ("VLANs je Port (produktiv)", "VLANs per port (productive)"), "vlan_changes": ("Geplante Umstellung", "Planned changes"),
    "untagged": ("Untagged", "Untagged"), "tagged": ("Tagged", "Tagged"), "now": ("Jetzt", "Now"), "planned": ("Geplant", "Planned"),
    "cabling": ("Verkabelung", "Cabling"), "switch_port": ("Switch · Port", "Switch · port"), "panel": ("Patchfeld · Port", "Patch panel · port"),
    "outlet": ("Dose", "Outlet"), "cable_a": ("Patchkabel", "Patch cable"), "cable_b": ("Verlegekabel", "Installed cable"),
    "cable_c": ("Anschlusskabel", "Device cable"), "panels": ("Patchfelder und Dosen", "Patch panels and outlets"),
    "ports_n": ("{n} Ports", "{n} ports"), "devices_n": ("{n} Geräte", "{n} devices"),
}


def tr(key, lang, **kw):
    s = S[key][1 if lang == "en" else 0]
    return s.format(**kw) if kw else s


def _uplink_text(d, lang):
    u = d.get("uplink")
    if not u:
        return ""
    port = f" · {tr('port', lang)} {u['port_name']}" if u.get("port_name") else ""
    return f"{u['device_name']}{port} ({MEDIUM[lang].get(u['medium'], u['medium'])})"


def _model_text(d):
    return " ".join(x for x in (d.get("manufacturer"), d.get("model")) if x)


def _ips(d):
    return ", ".join(x["address"] for x in d.get("ips", []))


# ------------------------------------------------------------ CSV
def devices_csv(c, pid, lang="de"):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([tr(k, lang) for k in ("name", "type", "model", "ip", "mac", "hostname", "location", "uplink", "tags", "note")])
    for d in inventory.list_devices(c, pid, "confirmed"):
        w.writerow([d["name"], catalog.type_name(d["type"], lang), _model_text(d), _ips(d), d["mac"], d["hostname"], d["location"],
                    _uplink_text(d, lang), ", ".join(d["tags"]), d["notes"]])
    return "﻿" + buf.getvalue()


def ips_csv(c, pid, lang="de"):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Subnetz" if lang == "de" else "Subnet", tr("ip", lang), tr("kind", lang), tr("device", lang), tr("mac", lang)])
    for s in ipam.list_subnets(c, pid):
        for a in ipam.subnet_detail(c, pid, s["id"])["addresses"]:
            w.writerow([s["cidr"], a["address"], KIND[lang].get(a["kind"], a["kind"]), a["device_name"], a["mac"]])
    return "﻿" + buf.getvalue()


# ------------------------------------------------------------ Topologie (helle Druckvariante)
PRINT_STYLE = {"lan": ("#0091A8", ""), "wlan": ("#13A88A", "7 6"), "mesh": ("#2D5BFF", "2 5"), "virtual": ("#7A8FA6", "1 4")}


def topology_layout(c, pid, expand=False):
    """Topologie wie in der Oberfläche (inkl. von Hand verschobener Knoten); expand: Gruppen (WLAN, VMs) aufgeklappt."""
    from . import topology
    t = topology.build(c, pid)
    if expand:
        groups = [n["id"][1:] for n in t["nodes"] if n["kind"] == "group"]
        if groups:
            t = topology.build(c, pid, expanded=groups)
    return t


def topology_svg(c, pid, lang="de", expand=False, t=None):
    """-> (SVG-Inhalt, Breite, Höhe) des Gesamtbaums; WLAN-Gruppen bleiben zusammengefasst, außer expand."""
    from .pdf import esc
    t = t or topology_layout(c, pid, expand)
    if not t["nodes"]:
        return "", 0, 0
    NW, NH, PAD = t["node_w"], t["node_h"], 20
    # nach oben/links verschobene Knoten: alles so verschieben, dass die Zeichnung bei 0 beginnt
    dx, dy = -min(0, t["bbox"][0]), -min(0, t["bbox"][1])
    if dx or dy:
        for n in t["nodes"]:
            n["x"] += dx
            n["y"] += dy
        t["width"] += dx
        t["height"] += dy
        if t.get("loose_from") is not None:
            t["loose_from"] += dy
    by = {n["id"]: n for n in t["nodes"]}
    out = []
    for e in t["edges"]:
        a, b = by[e["source"]], by[e["target"]]
        x1, y1, x2, y2 = a["x"] + NW + PAD, a["y"] + PAD, b["x"] + PAD, b["y"] + PAD
        mx = (x1 + x2) / 2
        col, dash = PRINT_STYLE.get(e["medium"], ("#0091A8", "") if e["medium"] == "wan" else PRINT_STYLE["lan"])
        out.append(f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" fill="none" stroke="{col}" stroke-width="1.6" stroke-dasharray="{dash}"/>')
        if e["label"]:
            out.append(f'<text x="{x1 + 6}" y="{y1 - 4}" font-size="10" fill="#56708A">{esc(e["label"])}</text>')
    if t["loose_from"]:
        out.append(f'<text x="{PAD}" y="{t["loose_from"] + PAD - NH / 2 - 8}" font-size="11" font-weight="bold" fill="#56708A">{esc(tr("loose", lang).upper())}</text>')
    for n in t["nodes"]:
        x, y = n["x"] + PAD, n["y"] + PAD - NH / 2
        if n["kind"] == "internet":
            st = {1: ("verbunden", "connected"), 0: ("getrennt", "disconnected")}.get(n["online"], ("Status unbekannt", "status unknown"))[1 if lang == "en" else 0]
            out.append(f'<rect x="{x}" y="{y}" width="{NW}" height="{NH}" rx="24" fill="#EAF7FB" stroke="#0091A8"/>'
                       f'<text x="{x + 14}" y="{y + 21}" font-size="13" font-weight="bold" fill="#0A1A33">Internet</text>'
                       f'<text x="{x + 14}" y="{y + 37}" font-size="10" fill="#56708A">{esc(st)}</text>')
            continue
        if n["kind"] == "group":
            col = PRINT_STYLE.get(n["medium"], PRINT_STYLE["lan"])[0]
            label = tr("group_wlan" if n["medium"] != "virtual" else "group_virtual", lang, n=n["count"])
            out.append(f'<rect x="{x}" y="{y}" width="{NW}" height="{NH}" rx="8" fill="#F6FAFC" stroke="{col}" stroke-dasharray="5 4"/>'
                       f'<text x="{x + 12}" y="{y + 21}" font-size="13" font-weight="bold" fill="#0A1A33">{esc(label)}</text>'
                       f'<text x="{x + 12}" y="{y + 37}" font-size="10" fill="#56708A">{esc(", ".join(n["names"][:4])[:44])}</text>')
            continue
        dot = {1: "#1E9E5A", 0: "#D23A55"}.get(n["online"], "#A9B8C6")
        typ = catalog.type_name(n["type"], lang)
        sub = f"{n['ip']} · {typ}" if n["ip"] else typ
        out.append(f'<rect x="{x}" y="{y}" width="{NW}" height="{NH}" rx="8" fill="#FFFFFF" stroke="#9FB4C8"/>'
                   f'<circle cx="{x + NW - 12}" cy="{y + 12}" r="4" fill="{dot}"/>'
                   f'<text x="{x + 12}" y="{y + 20}" font-size="13" font-weight="bold" fill="#0A1A33">{esc(n["name"][:26])}</text>'
                   f'<text x="{x + 12}" y="{y + 36}" font-size="10" fill="#56708A" font-family="DejaVu Sans Mono, monospace">'
                   f'{esc(sub)}</text>')
    right = max(n["x"] for n in t["nodes"]) + NW
    bottom = max(n["y"] for n in t["nodes"]) + NH / 2
    return "".join(out), right + PAD * 2, bottom + PAD * 2


# ------------------------------------------------------------ PDF
def profile_pdf(c, pid, sections=SECTIONS, lang="de"):
    p = c.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
    devs = inventory.list_devices(c, pid, "confirmed")
    d = datetime.datetime.now().strftime("%d.%m.%Y %H:%M" if lang == "de" else "%Y-%m-%d %H:%M")
    doc = Doc(p["name"], tr("title", lang) + (" · " + p["description"] if p["description"] else ""), tr("created", lang, d=d), tr("page", lang))
    secs = [s for s in SECTIONS if s in sections]

    for s in secs:
        if s == "topology":
            doc.heading(tr("topology", lang))
            inner, w, h = topology_svg(c, pid, lang)
            if inner:
                doc.para(tr("legend", lang), 2.8)
                doc.figure(inner, w, h)
            else:
                doc.para(tr("none", lang))
        elif s == "devices":
            doc.heading(f'{tr("devices", lang)} ({tr("devices_n", lang, n=len(devs))})')
            doc.table([(tr("name", lang), 27, False), (tr("type", lang), 21, False), (tr("model", lang), 24, False), (tr("ip", lang), 27, True),
                       (tr("mac", lang), 30, True), (tr("location", lang), 19, False), (tr("uplink", lang), 34, False)],
                      [[x["name"], catalog.type_name(x["type"], lang), _model_text(x), "\n".join(i["address"] for i in x["ips"]), x["mac"], x["location"],
                        _uplink_text(x, lang)] for x in devs], size=2.7)
        elif s == "ipplan":
            doc.heading(tr("ipplan", lang))
            subnets = ipam.list_subnets(c, pid)
            if not subnets:
                doc.para(tr("none", lang))
            for sn in subnets:
                det = ipam.subnet_detail(c, pid, sn["id"])
                doc.heading(f'{sn["cidr"]}{"  " + sn["name"] if sn["name"] else ""}', size=4)
                doc.kv([(tr("vlan", lang), f'{sn["vid"]} {sn["vlan_name"]}'.strip() if sn["vid"] else ""), (tr("gateway", lang), sn["gateway"]),
                        (tr("dns", lang), sn["dns"]), (tr("dhcp", lang), f'{sn["dhcp_start"]} – {sn["dhcp_end"]}' if sn["dhcp_start"] else ""),
                        (tr("usage", lang), f'{sn["used"]} / {sn["size"]}')])
                doc.table([(tr("ip", lang), 16, True), (tr("device", lang), 30, False), (tr("mac", lang), 19, True), (tr("kind", lang), 15, False)],
                          [[a["address"], a["device_name"], a["mac"], KIND[lang].get(a["kind"], a["kind"]) + (tr("in_dhcp", lang) if a["in_dhcp"] and a["kind"] == "static" else "")]
                           for a in det["addresses"]])
                if det["free"]:
                    static_free = [f for f in det["free"] if not f["dhcp"]]
                    shown = ", ".join(f'{f["start"]}' + (f' – {f["end"]}' if f["count"] > 1 else "") for f in static_free[:12])
                    more = f' {tr("free_more", lang, n=len(static_free) - 12)}' if len(static_free) > 12 else ""
                    doc.kv([(tr("free", lang), (shown + more) or "–")])
        elif s == "vlans":
            doc.heading(tr("vlans", lang))
            subs = {}
            for sn in ipam.list_subnets(c, pid):
                if sn["vlan_id"]:
                    subs.setdefault(sn["vlan_id"], []).append(sn["cidr"])
            doc.table([(tr("vid", lang), 10, True), (tr("name", lang), 20, False), (tr("subnets", lang), 25, True), (tr("description", lang), 45, False)],
                      [[str(v["vid"]), v["name"], ", ".join(subs.get(v["id"], [])), v["description"]]
                       for v in c.execute("SELECT * FROM vlans WHERE profile_id=? ORDER BY vid", (pid,))])
            from . import vlanplan
            per, chg = vlanplan.pdf_tables(c, pid, lang)
            for name, rows in per:
                doc.heading(f'{tr("vlan_ports", lang)} · {name}', size=4)
                doc.table([(tr("port", lang), 22, False), (tr("peer", lang), 70, False), (tr("untagged", lang), 30, True), (tr("tagged", lang), 60, True)], rows, size=2.7)
            if chg:
                doc.heading(tr("vlan_changes", lang), size=4)
                doc.table([(tr("device", lang), 50, False), (tr("port", lang), 22, False), (tr("now", lang), 55, True), (tr("planned", lang), 55, True)], chg, size=2.7)
        elif s == "ports":
            doc.heading(tr("ports", lang))
            any_ports = False
            for x in devs:
                if not x["ports_total"]:
                    continue
                any_ports = True
                det = inventory.device_detail(c, pid, x["id"])
                doc.heading(f'{x["name"]}  ({_model_text(x)})' if _model_text(x) else x["name"], size=4)
                doc.table([(tr("port", lang), 14, False), (tr("speed", lang), 27, False), (tr("peer", lang), 35, False), (tr("ip", lang), 28, True),
                           (tr("mac", lang), 30, True), (tr("medium", lang), 22, False)],
                          [[pt["name"], f'{pt["kind"].upper()} {pt["speed"]}{" PoE" if pt["poe"] else ""}'.strip(),
                            (pt["peer"] or {}).get("device_name", ""), (pt["peer"] or {}).get("ip", ""), (pt["peer"] or {}).get("mac", ""),
                            MEDIUM[lang].get((pt["peer"] or {}).get("medium", ""), "") if pt["peer"] else ""] for pt in det["ports"]], size=2.7)
            if not any_ports:
                doc.para(tr("none", lang))
        elif s == "cabling":
            from . import cabling
            doc.heading(tr("cabling", lang))
            rows = cabling.pdf_rows(c, pid, lang)
            if not rows:
                doc.para(tr("none", lang))
            else:
                doc.table([(tr("switch_port", lang), 34, False), (tr("cable_a", lang), 18, True), (tr("panel", lang), 30, False),
                           (tr("cable_b", lang), 18, True), (tr("outlet", lang), 28, False), (tr("cable_c", lang), 18, True), (tr("device", lang), 36, False)],
                          rows, size=2.7)
                pans = cabling.overview(c, pid)["panels"]
                if pans:
                    doc.heading(tr("panels", lang), size=4)
                    doc.table([(tr("name", lang), 50, False), (tr("kind", lang), 30, False), (tr("location", lang), 50, False), (tr("port", lang), 52, False)],
                              [[x["name"], tr("panel" if x["kind"] == "panel" else "outlet", lang).split(" ·")[0],
                                x["location"], f'{len(x["used"])} / {tr("ports_n", lang, n=x["ports"])}'] for x in pans], size=2.7)
        elif s == "wlan":
            doc.heading(tr("wlan", lang))
            by_ap = {}
            for x in devs:
                u = x.get("uplink")
                if u and u["medium"] in ("wlan", "mesh"):
                    by_ap.setdefault((u["device_name"], u["device_id"]), []).append(x)
            if not by_ap:
                doc.para(tr("none", lang))
            for (ap, _), clients in sorted(by_ap.items(), key=lambda kv: kv[0][0].lower()):
                doc.heading(f'{ap}  ({tr("clients", lang, n=len(clients))})', size=4)
                doc.table([(tr("name", lang), 38, False), (tr("type", lang), 24, False), (tr("ip", lang), 28, True), (tr("mac", lang), 31, True),
                           (tr("medium", lang), 25, False), (tr("location", lang), 30, False)],
                          [[x["name"], catalog.type_name(x["type"], lang), _ips(x), x["mac"], MEDIUM[lang][x["uplink"]["medium"]], x["location"]] for x in clients])
        elif s == "notes":
            doc.heading(tr("notes", lang))
            rows = [[x["name"], x["notes"]] for x in devs if x["notes"].strip()]
            doc.table([(tr("device", lang), 25, False), (tr("note", lang), 75, False)], rows)
    return doc.render()
