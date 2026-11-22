"""QR-Etiketten für Geräte: Aufkleber mit Link zum Gerät in díktyo, als PDF für Etikettenbögen oder Etikettendrucker.

Der QR-Code führt auf <Adresse der Weboberfläche>/#/p/<Profil>/geraete/<Gerät> und öffnet dort den Gerätedialog
(nach der Anmeldung, falls nötig). Neben dem Code stehen Name und wahlweise IP, MAC, Standort/Typ. Gesetzt wird als
SVG in Millimetern und mit CairoSVG gewandelt; der QR-Code wird lokal mit segno erzeugt.
"""
import io

import cairosvg
import segno
from pypdf import PdfReader, PdfWriter

from . import inventory
from .catalog import TYPE_EN, TYPES
from .pdf import FONT, MONO, esc, wrap

# Format -> Seite (B×H), Etikett (B×H), Spalten, Zeilen, Rand links/oben, Abstand Spalte/Zeile (alles mm)
FORMATS = {
    "a4-70x37": dict(name="A4 · 70 × 37 mm (24 je Bogen, z. B. Avery Zweckform 3474)", page=(210, 297), label=(70, 37), cols=3, rows=8,
                     left=0, top=0.5, gx=0, gy=0),
    "a4-99x38": dict(name="A4 · 99,1 × 38,1 mm (14 je Bogen, z. B. Avery L7163)", page=(210, 297), label=(99.1, 38.1), cols=2, rows=7,
                     left=4.65, top=15.15, gx=2.5, gy=0),
    "a4-48x25": dict(name="A4 · 48,5 × 25,4 mm (40 je Bogen, z. B. Avery Zweckform 3657)", page=(210, 297), label=(48.5, 25.4), cols=4, rows=10,
                     left=8, top=21.5, gx=0, gy=0),
    "roll-62x29": dict(name="Etikettendrucker · 62 × 29 mm (z. B. Brother DK-11209)", page=(62, 29), label=(62, 29), cols=1, rows=1,
                       left=0, top=0, gx=0, gy=0),
    "roll-54x25": dict(name="Etikettendrucker · 54 × 25 mm (z. B. Dymo 11352)", page=(54, 25), label=(54, 25), cols=1, rows=1,
                       left=0, top=0, gx=0, gy=0),
}
FORMAT_EN = {"a4-70x37": "A4 · 70 × 37 mm (24 per sheet, e.g. Avery 3474)", "a4-99x38": "A4 · 99.1 × 38.1 mm (14 per sheet, e.g. Avery L7163)",
             "a4-48x25": "A4 · 48.5 × 25.4 mm (40 per sheet, e.g. Avery 3657)", "roll-62x29": "Label printer · 62 × 29 mm (e.g. Brother DK-11209)",
             "roll-54x25": "Label printer · 54 × 25 mm (e.g. Dymo 11352)"}
FIELDS = ("ip", "mac", "loc")
MAX_LABELS = 500


class LabelError(Exception):
    pass


def formats(lang="de"):
    return [dict(key=k, name=FORMAT_EN[k] if lang == "en" else f["name"], sheet=f["cols"] * f["rows"]) for k, f in FORMATS.items()]


def device_url(base, pid, did):
    return f"{base.rstrip('/')}/#/p/{pid}/geraete/{did}"


def _qr(text, x, y, size):
    """QR-Code als SVG-Pfad (ein Rechteck je dunklem Modul, zu Zeilenläufen zusammengefasst)."""
    q = segno.make(text, error="m")
    mat = [list(r) for r in q.matrix]
    n = len(mat) + 2  # Ruhezone 1 Modul je Seite (der Etikettenrand kommt dazu)
    d = []
    for r, row in enumerate(mat):
        c = 0
        while c < len(row):
            if row[c]:
                s = c
                while c < len(row) and row[c]:
                    c += 1
                d.append(f"M{s + 1} {r + 1}h{c - s}v1h{s - c}z")
            else:
                c += 1
    return f'<svg x="{x:.2f}" y="{y:.2f}" width="{size:.2f}" height="{size:.2f}" viewBox="0 0 {n} {n}" shape-rendering="crispEdges"><path d="{"".join(d)}" fill="#000"/></svg>'


def _cut(text, width_mm, size):
    """Eine Zeile, zeichenweise gekürzt (DejaVu Sans: im Mittel gut 0,55 Schriftgrößen je Zeichen)."""
    n = max(4, int(width_mm / (size * 0.56)))
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _label(dev, url, w, h, fields, lang, outline):
    pad = max(1.6, min(2.6, h * 0.08))
    qs = min(h - 2 * pad, w * 0.46)
    tx = pad + qs + max(1.5, w * 0.03)
    tw = w - tx - pad
    big = min(h * 0.135, 4.2, tw / 8)
    small = big * 0.74
    out = [f'<rect width="{w}" height="{h}" fill="#fff"/>'] if not outline else \
        [f'<rect x="0.15" y="0.15" width="{w - 0.3:.2f}" height="{h - 0.3:.2f}" rx="1.5" fill="#fff" stroke="#B8C4D0" stroke-width="0.2" stroke-dasharray="1 0.8"/>']
    out.append(_qr(url, pad, (h - qs) / 2, qs))
    lines = []  # (Text, Größe, fett, mono, Farbe)
    for ln in wrap(dev["name"], tw, big * 1.02, max_lines=2):
        lines.append((ln, big, True, False, "#000"))
    ip = dev["ips"][0]["address"] if dev.get("ips") else ""
    if "ip" in fields and ip:
        lines.append((ip, small, False, True, "#000"))
    if "mac" in fields and dev.get("mac"):
        lines.append((dev["mac"], small * 0.92, False, True, "#333"))
    if "loc" in fields:
        typ = (TYPE_EN if lang == "en" else TYPES).get(dev["type"], "") if dev["type"] != "other" else ""
        extra = " · ".join(x for x in (dev.get("location") or "", typ) if x)
        if extra:
            lines.append((_cut(extra, tw, small * 0.92), small * 0.92, False, False, "#444"))
    lh = [s * 1.28 for _, s, *_ in lines]
    # so viele Zeilen wie passen (Name zuerst), senkrecht mittig
    while lines and sum(lh) > h - 2 * pad - small * 1.2 and len(lines) > 1:
        lines.pop(); lh.pop()
    foot = small * 0.8
    y = (h - sum(lh) - foot * 1.3) / 2
    for (txt, s, bold, mono, col), l in zip(lines, lh):
        y += l
        out.append(f'<text x="{tx:.2f}" y="{y - (l - s) / 2 - s * 0.1:.2f}" font-size="{s:.2f}" font-family="{MONO if mono else FONT}"'
                   f'{" font-weight=\"bold\"" if bold else ""} fill="{col}">{esc(txt)}</text>')
    out.append(f'<text x="{tx:.2f}" y="{y + foot * 1.3:.2f}" font-size="{foot:.2f}" font-family="{FONT}" fill="#0091A8" letter-spacing="0.15">díktyo</text>')
    return "".join(out)


def render(c, pid, ids, fmt="a4-70x37", fields=FIELDS, base="", skip=0, outline=False, lang="de"):
    """-> PDF-Bytes. ids in der gewünschten Reihenfolge; skip = schon benutzte Etiketten am Bogenanfang."""
    f = FORMATS.get(fmt)
    if not f:
        raise LabelError("Unbekanntes Etikettenformat")
    if not base.startswith(("http://", "https://")):
        raise LabelError("Adresse der Weboberfläche bitte mit http:// oder https:// angeben")
    by_id = {d["id"]: d for d in inventory.list_devices(c, pid)}
    devs = [by_id[i] for i in ids if i in by_id][:MAX_LABELS]
    if not devs:
        raise LabelError("Keine Geräte ausgewählt")
    per = f["cols"] * f["rows"]
    skip = max(0, min(int(skip or 0), per - 1)) if per > 1 else 0
    (pw, ph), (lw, lh) = f["page"], f["label"]
    slots = [None] * skip + devs
    pages = [slots[i:i + per] for i in range(0, len(slots), per)]
    w = PdfWriter()
    for page in pages:
        body = []
        for n, dev in enumerate(page):
            if dev is None:
                continue
            col, row = n % f["cols"], n // f["cols"]
            x, y = f["left"] + col * (lw + f["gx"]), f["top"] + row * (lh + f["gy"])
            body.append(f'<g transform="translate({x:.2f} {y:.2f})">{_label(dev, device_url(base, pid, dev["id"]), lw, lh, fields, lang, outline)}</g>')
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{pw}mm" height="{ph}mm" viewBox="0 0 {pw} {ph}">'
               f'<rect width="{pw}" height="{ph}" fill="#fff"/>{"".join(body)}</svg>')
        for p in PdfReader(io.BytesIO(cairosvg.svg2pdf(bytestring=svg.encode("utf-8")))).pages:
            w.add_page(p)
    w.add_metadata({"/Title": "díktyo – QR-Etiketten" if lang != "en" else "díktyo – QR labels", "/Producer": "díktyo"})
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()
