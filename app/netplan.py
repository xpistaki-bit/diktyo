"""Netzplan exportieren: SVG, PNG, draw.io und Poster-PDF (eine Seite A3–A0 oder auf A4 gekachelt).

Grundlage ist die Topologie wie in der Oberfläche – samt von Hand verschobener Knoten –, in der hellen Druckvariante
(export.topology_svg). Die draw.io-Datei enthält Geräte als Kästen an ihrer Position mit IP, MAC, Typ, Modell und
Standort als Eigenschaften (in draw.io: Rechtsklick → Daten bearbeiten), Verbindungen nach Art gestrichelt/gepunktet.
"""
import datetime
import io
from xml.sax.saxutils import escape, quoteattr

import cairosvg
from pypdf import PdfReader, PdfWriter

from . import catalog, export
from .pdf import FONT, esc

PAPER = {"a4": (297, 210), "a3": (420, 297), "a2": (594, 420), "a1": (841, 594), "a0": (1189, 841)}  # quer, mm
INK, MUTE, LINE, ACC = "#0A1A33", "#56708A", "#C9D6E3", "#0091A8"
T = {"title": ("Netzplan", "Network map"), "created": ("Stand {d}", "As of {d}"), "devices": ("{n} Geräte", "{n} devices"),
     "legend": ("Linien: durchgezogen LAN · gestrichelt WLAN · gepunktet Mesh · fein virtuell", "Lines: solid LAN · dashed Wi-Fi · dotted mesh · fine virtual"),
     "sheet": ("Blatt {r}/{c} · Zeile {y}, Spalte {x}", "Sheet {r}/{c} · row {y}, column {x}"), "glue": ("überlappend kleben", "overlap and glue"),
     "empty": ("Noch keine Geräte in der Topologie.", "No devices in the topology yet.")}


class NetplanError(Exception):
    pass


def _t(k, lang, **kw):
    s = T[k][1 if lang == "en" else 0]
    return s.format(**kw) if kw else s


def _when(lang):
    return datetime.datetime.now().strftime("%d.%m.%Y %H:%M" if lang != "en" else "%Y-%m-%d %H:%M")


def _drawing(c, pid, lang, expand):
    t = export.topology_layout(c, pid, expand)
    if not t["nodes"]:
        raise NetplanError(_t("empty", lang))
    inner, w, h = export.topology_svg(c, pid, lang, t=t)
    return inner, w, h, sum(1 for n in t["nodes"] if n["kind"] == "device")


# ------------------------------------------------------------ SVG / PNG
def svg(c, pid, lang="de", expand=False):
    """Eigenständiges SVG mit Kopfzeile (Profil, Stand) und Legende."""
    p = c.execute("SELECT name FROM profiles WHERE id=?", (pid,)).fetchone()
    inner, w, h, n = _drawing(c, pid, lang, expand)
    W, H = max(w, 640), h + 90
    head = (f'<text x="20" y="30" font-size="18" font-weight="bold" fill="{INK}">díktyo · {esc(p["name"])} · {_t("title", lang)}</text>'
            f'<text x="20" y="50" font-size="11" fill="{MUTE}">{esc(_t("created", lang, d=_when(lang)))} · {esc(_t("devices", lang, n=n))}</text>'
            f'<line x1="20" y1="60" x2="{W - 20}" y2="60" stroke="{LINE}"/>')
    foot = f'<text x="20" y="{H - 14}" font-size="10" fill="{MUTE}">{esc(_t("legend", lang))}</text>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT}">'
            f'<rect width="{W:.0f}" height="{H:.0f}" fill="#FFFFFF"/>{head}<g transform="translate(0 66)">{inner}</g>{foot}</svg>')


def png(c, pid, lang="de", expand=False, scale=2):
    return cairosvg.svg2png(bytestring=svg(c, pid, lang, expand).encode("utf-8"), scale=scale)


# ------------------------------------------------------------ Poster-PDF
def _poster_body(c, pid, lang, expand, pw, ph):
    """-> SVG-Inhalt einer Posterseite (mm-Koordinaten) mit Zeichnung, Rahmen und Schriftfeld."""
    p = c.execute("SELECT name, description FROM profiles WHERE id=?", (pid,)).fetchone()
    inner, w, h, n = _drawing(c, pid, lang, expand)
    m = 10
    fw, fh = 120, 30  # Schriftfeld unten rechts
    aw, ah = pw - 2 * m, ph - 2 * m - fh - 4
    s = min(aw / w, ah / h)  # Zeichnung (px) -> mm
    ox, oy = m + (aw - w * s) / 2, m + (ah - h * s) / 2
    fx, fy = pw - m - fw, ph - m - fh
    rows = [(f'díktyo · {esc(p["name"])}', 6, "bold", INK), (_t("title", lang) + (f' · {esc(p["description"][:60])}' if p["description"] else ""), 3.6, "normal", INK),
            (esc(_t("created", lang, d=_when(lang))) + " · " + esc(_t("devices", lang, n=n)), 3, "normal", MUTE)]
    txt = "".join(f'<text x="{fx + 5}" y="{fy + 9 + i * 7.5}" font-size="{sz}" font-weight="{wt}" fill="{col}">{t}</text>' for i, (t, sz, wt, col) in enumerate(rows))
    legend = f'<text x="{m + 2}" y="{ph - m - 2}" font-size="3" fill="{MUTE}">{esc(_t("legend", lang))}</text>'
    return (f'<rect width="{pw}" height="{ph}" fill="#FFFFFF"/>'
            f'<rect x="{m / 2}" y="{m / 2}" width="{pw - m}" height="{ph - m}" fill="none" stroke="{LINE}" stroke-width="0.4"/>'
            f'<g transform="translate({ox:.2f} {oy:.2f}) scale({s:.5f})">{inner}</g>'
            f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" fill="#F6FAFC" stroke="{ACC}" stroke-width="0.5"/>'
            f'<rect x="{fx}" y="{fy}" width="2" height="{fh}" fill="{ACC}"/>{txt}{legend}')


def _orient(c, pid, expand, paper):
    pw, ph = PAPER[paper]
    t = export.topology_layout(c, pid, expand)
    if t["nodes"]:
        w = max(n["x"] for n in t["nodes"]) - min(n["x"] for n in t["nodes"])
        h = max(n["y"] for n in t["nodes"]) - min(n["y"] for n in t["nodes"])
        if h > w * 1.15:  # hohe Bäume: Hochformat
            pw, ph = ph, pw
    return pw, ph


def poster_pdf(c, pid, lang="de", expand=False, paper="a1", tiles=False):
    """Eine Seite im gewählten Format – oder (tiles) dieselbe Seite auf A4-Blätter verteilt, mit Überlappung und Marken."""
    if paper not in PAPER:
        raise NetplanError("Unbekanntes Papierformat")
    pw, ph = _orient(c, pid, expand, paper)
    body = _poster_body(c, pid, lang, expand, pw, ph)
    pages = []
    if not tiles or paper == "a4":
        pages.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{pw}mm" height="{ph}mm" viewBox="0 0 {pw} {ph}" font-family="{FONT}">{body}</svg>')
    else:
        tw, th = 210, 297  # A4 hoch, bedruckbare Fläche mit 8 mm Rand, 10 mm Überlappung
        mg, ov = 8, 10
        cw, ch = tw - 2 * mg, th - 2 * mg
        cols, rows = -(-(pw - ov) // (cw - ov)), -(-(ph - ov) // (ch - ov))
        cols, rows = int(max(1, cols)), int(max(1, rows))
        for r in range(rows):
            for col in range(cols):
                x0, y0 = col * (cw - ov), r * (ch - ov)
                marks = "".join(f'<path d="M{x},{y - 4} v8 M{x - 4},{y} h8" stroke="#9FB4C8" stroke-width="0.25"/>'
                                for x, y in ((mg, mg), (tw - mg, mg), (mg, th - mg), (tw - mg, th - mg)))
                label = _t("sheet", lang, r=r * cols + col + 1, c=rows * cols, y=r + 1, x=col + 1) + " · " + _t("glue", lang)
                pages.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{tw}mm" height="{th}mm" viewBox="0 0 {tw} {th}" font-family="{FONT}">'
                             f'<rect width="{tw}" height="{th}" fill="#FFFFFF"/>'
                             f'<svg x="{mg}" y="{mg}" width="{cw}" height="{ch}" viewBox="{x0} {y0} {cw} {ch}">{body}</svg>'
                             f'<rect x="{mg}" y="{mg}" width="{cw}" height="{ch}" fill="none" stroke="#C9D6E3" stroke-width="0.2" stroke-dasharray="1.5 1.5"/>'
                             f'{marks}<text x="{mg}" y="{th - 3}" font-size="2.6" fill="{MUTE}">{esc(label)}</text></svg>')
    w = PdfWriter()
    for page in pages:
        for pg in PdfReader(io.BytesIO(cairosvg.svg2pdf(bytestring=page.encode("utf-8")))).pages:
            w.add_page(pg)
    w.add_metadata({"/Title": "díktyo – " + _t("title", lang), "/Producer": "díktyo"})
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


# ------------------------------------------------------------ draw.io
DRAW_EDGE = {"lan": "strokeColor=#0091A8;", "wan": "strokeColor=#0091A8;strokeWidth=2;", "wlan": "strokeColor=#13A88A;dashed=1;dashPattern=8 6;",
             "mesh": "strokeColor=#2D5BFF;dashed=1;dashPattern=2 5;", "powerline": "strokeColor=#C77700;dashed=1;dashPattern=10 3 2 3;", "virtual": "strokeColor=#7A8FA6;dashed=1;dashPattern=1 4;"}
DRAW_FILL = {"router": "#E6F4F8", "firewall": "#FCE9EC", "modem": "#E6F4F8", "switch": "#EAF1FF", "ap": "#E9F8F1", "mesh": "#E9F8F1",
             "hypervisor": "#F2EEFF", "server": "#F2EEFF", "nas": "#F2EEFF"}


def drawio(c, pid, lang="de", expand=False):
    """draw.io-Datei (unkomprimiertes mxGraph-XML)."""
    from . import inventory
    p = c.execute("SELECT name FROM profiles WHERE id=?", (pid,)).fetchone()
    t = export.topology_layout(c, pid, expand)
    if not t["nodes"]:
        raise NetplanError(_t("empty", lang))
    devs = {d["id"]: d for d in inventory.list_devices(c, pid, "confirmed")}
    NW, NH = t["node_w"], t["node_h"]
    x0, y0 = min(n["x"] for n in t["nodes"]), min(n["y"] for n in t["nodes"]) - NH / 2
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    ids = {}
    for i, n in enumerate(t["nodes"]):
        cid = f"n{i}"
        ids[n["id"]] = cid
        x, y = n["x"] - x0 + 40, n["y"] - NH / 2 - y0 + 40
        geo = f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{NW}" height="{NH}" as="geometry"/>'
        if n["kind"] == "internet":
            cells.append(f'<mxCell id="{cid}" value="Internet" style="ellipse;whiteSpace=wrap;html=1;fillColor=#EAF7FB;strokeColor=#0091A8;fontStyle=1;" '
                         f'vertex="1" parent="1">{geo}</mxCell>')
            continue
        if n["kind"] == "group":
            label = export.group_label(n, lang)
            value = f"<b>{escape(label)}</b><br><font color='#56708A' style='font-size:10px'>{escape(', '.join(n['names'][:6]))}</font>"
            cells.append(f'<mxCell id="{cid}" value={quoteattr(value)} style="rounded=1;whiteSpace=wrap;html=1;dashed=1;fillColor=#F6FAFC;strokeColor={n.get("color") or "#9FB4C8"};'
                         f'align=left;spacingLeft=8;" vertex="1" parent="1">{geo}</mxCell>')
            continue
        d = devs.get(n.get("device_id"), {})
        typ = catalog.type_name(n["type"], lang)
        value = f"<b>{escape(n['name'])}</b><br><font color='#56708A' style='font-size:10px'>{escape(n['ip'] or '')}{' · ' if n['ip'] else ''}{escape(typ)}</font>"
        attrs = dict(label=value, type=typ, ip=", ".join(x["address"] for x in d.get("ips") or []), mac=d.get("mac") or "",
                     model=" ".join(x for x in (d.get("manufacturer"), d.get("model")) if x), location=d.get("location") or "", diktyo_id=str(n.get("device_id") or ""))
        attr = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items() if v)
        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={DRAW_FILL.get(n['type'], '#FFFFFF')};strokeColor=#9FB4C8;fontColor=#0A1A33;"
                 f"align=left;spacingLeft=8;arcSize=12;")
        cells.append(f'<UserObject id="{cid}" {attr}><mxCell style="{style}" vertex="1" parent="1">{geo}</mxCell></UserObject>')
    for i, e in enumerate(t["edges"]):
        if e["source"] not in ids or e["target"] not in ids:
            continue
        style = "edgeStyle=entityRelationEdgeStyle;curved=1;html=1;endArrow=none;startArrow=none;exitX=1;exitY=0.5;entryX=0;entryY=0.5;fontSize=9;fontColor=#56708A;"
        style += DRAW_EDGE.get(e["medium"], DRAW_EDGE["lan"])
        label = " → ".join(x for x in (e.get("label") or "", e.get("child_label") or "") if x)
        cells.append(f'<mxCell id="e{i}" value={quoteattr(label)} style="{style}" edge="1" parent="1" source="{ids[e["source"]]}" target="{ids[e["target"]]}">'
                     f'<mxGeometry relative="1" as="geometry"/></mxCell>')
    name = escape(f"{p['name']} · {_t('title', lang)}")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<mxfile host="diktyo" agent="díktyo" modified="{datetime.datetime.now().astimezone().isoformat(timespec="seconds")}" type="device">'
            f'<diagram id="diktyo-{pid}" name={quoteattr(name)}><mxGraphModel grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
            f'fold="1" page="0" pageScale="1" math="0" shadow="0"><root>{"".join(cells)}</root></mxGraphModel></diagram></mxfile>')


def filename(profile_name, ext):
    import re
    return (re.sub(r"[^A-Za-z0-9._-]+", "_", profile_name).strip("_") or "profil") + "-netzplan." + ext

