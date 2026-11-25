"""Kabel-Etiketten: Kabelnummern aus der Verkabelung als Aufkleber (A4-Bögen, Etikettendrucker, Schriftband).

Jede eingetragene Kabelnummer eines Kabelwegs (Patchkabel, Verlegekabel, Anschlusskabel) ergibt ein Etikett: die
Nummer groß, darunter die beiden Enden des Kabels (z. B. „Switch · Port 3“ und „PP1 · 5“). Die Enden ergeben sich
wie in der Tabelle der Kabelwege: Ein Kabel reicht von der Station davor bis zur nächsten eingetragenen Station.
Wahlweise zwei Etiketten je Kabel – eins für jedes Ende. Gesetzt wird mit labels.sheets (SVG → PDF).
"""
import re

from . import cabling, labels
from .labels import FORMATS, _cut
from .pdf import FONT, MONO, esc

KEYS = ("a", "b", "c")  # Spalte cable_a/b/c: Kabel zwischen Station i und der nächsten
KIND = {"a": ("Patchkabel", "Patch cable"), "b": ("Verlegekabel", "Installation cable"), "c": ("Anschlusskabel", "Device cable")}
FORMATS_CABLE = {
    "a4-38x21": dict(name="A4 · 38 × 21,2 mm (65 je Bogen, z. B. Avery Zweckform 3666, L7651)", page=(210, 297), label=(38.1, 21.2), cols=5, rows=13,
                     left=4.75, top=10.7, gx=2.5, gy=0),
    "a4-48x25": FORMATS["a4-48x25"],
    "a4-70x37": FORMATS["a4-70x37"],
    "roll-62x29": FORMATS["roll-62x29"],
    "roll-54x25": FORMATS["roll-54x25"],
    "tape-12": dict(name="Schriftband · 12 mm, 60 mm lang (z. B. Brother P-touch TZe)", page=(60, 12), label=(60, 12), cols=1, rows=1,
                    left=0, top=0, gx=0, gy=0),
}
FORMAT_EN = {**labels.FORMAT_EN, "a4-38x21": "A4 · 38 × 21.2 mm (65 per sheet, e.g. Avery 3666, L7651)",
             "tape-12": "Label tape · 12 mm, 60 mm long (e.g. Brother P-touch TZe)"}
MAX_LABELS = 1000


def formats(lang="de"):
    return [dict(key=k, name=FORMAT_EN[k] if lang == "en" else f["name"], sheet=f["cols"] * f["rows"]) for k, f in FORMATS_CABLE.items()]


def _nat(s):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", s)]


def cables(c, pid, lang="de"):
    """Alle Kabel mit Nummer: key („<Kabelweg><a|b|c>“), Nummer, Art, Enden – nach Nummer sortiert."""
    out = []
    for r in cabling.overview(c, pid)["runs"]:
        port = f"{'Port ' if lang != 'en' else 'port '}{r['port_name']}" if str(r["port_name"]).isdigit() else r["port_name"]
        st = [f"{r['switch']} · {port}" if r["switch"] else "", f"{r['panel']} · {r['panel_port']}" if r["panel"] else "",
              f"{r['outlet']} · {r['outlet_port']}" if r["outlet"] else "", r["device"] or ""]
        for i, k in enumerate(KEYS):
            no = (r[f"cable_{k}"] or "").strip()
            if not no:
                continue
            left = next((st[j] for j in range(i, -1, -1) if st[j]), "")
            right = next((st[j] for j in range(i + 1, 4) if st[j]), "")
            out.append(dict(key=f"{r['id']}{k}", run=r["id"], number=no, kind=KIND[k][lang == "en"], a=left, b=right))
    return sorted(out, key=lambda x: (_nat(x["number"]), x["key"]))


def _label(cab, w, h, outline, end=None):
    """Ein Etikett. end: None = beide Enden, 0/1 = Etikett für dieses Ende (das andere wird als Gegenstelle genannt)."""
    out = [f'<rect width="{w}" height="{h}" fill="#fff"/>'] if not outline else \
        [f'<rect x="0.15" y="0.15" width="{w - 0.3:.2f}" height="{h - 0.3:.2f}" rx="1.2" fill="#fff" stroke="#B8C4D0" stroke-width="0.2" stroke-dasharray="1 0.8"/>']
    a, b = cab["a"] or "–", cab["b"] or "–"
    if end == 1:
        a, b = b, a
    pad = max(1.2, min(2.4, h * 0.08))
    bar = max(1.2, w * 0.03)  # Farbstreifen links: Art des Kabels
    col = {"a": "#0091A8", "b": "#E08A00", "c": "#5B6B7F"}[cab["key"][-1]]
    out.append(f'<rect x="{0.3 if outline else 0}" y="{0.3 if outline else 0}" width="{bar:.2f}" height="{h - (0.6 if outline else 0):.2f}" fill="{col}"/>')
    x0 = bar + pad
    tw = w - x0 - pad
    both_ends = end is None

    def text(x, y, s, size, bold=False, mono=False, fill="#000", anchor="start"):
        out.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size:.2f}" font-family="{MONO if mono else FONT}"{" font-weight=\"bold\"" if bold else ""}'
                   f' fill="{fill}" text-anchor="{anchor}">{esc(s)}</text>')

    def arrow(x, y, size):
        """Pfeil vor der zweiten Zeile als Linie (Pfeilzeichen fehlen in manchen Druckschriften) -> Breite."""
        L, m, k = size * 0.95, y - size * 0.34, size * 0.26
        d = f"M{x:.2f} {m:.2f}h{L:.2f}M{x + L - k:.2f} {m - k:.2f}l{k:.2f} {k:.2f}l{-k:.2f} {k:.2f}"
        if both_ends:
            d += f"M{x + k:.2f} {m - k:.2f}l{-k:.2f} {k:.2f}l{k:.2f} {k:.2f}"
        out.append(f'<path d="{d}" stroke="#111" stroke-width="{size * 0.1:.2f}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
        return L + size * 0.4

    def fit(num, width, cap):
        """Schriftgröße, bei der die Nummer (fett, Festbreite) ganz in die Breite passt – sie wird nie gekürzt."""
        return min(cap, width / (max(1, len(num)) * 0.62))
    num = cab["number"]
    if h < 16:  # Schriftband: Nummer links, Enden rechts in zwei Zeilen
        big = fit(num, tw * 0.5, h * 0.62)
        nw = len(num) * big * 0.62
        text(x0, h / 2 + big * 0.36, num, big, bold=True, mono=True)
        sm = min(h * 0.24, 2.7)
        rx, rw = x0 + nw + 1.5, tw - nw - 1.5
        text(rx, h / 2 - sm * 0.3, _cut(a, rw, sm), sm, fill="#222")
        aw = arrow(rx, h / 2 + sm * 1.0, sm)
        text(rx + aw, h / 2 + sm * 1.0, _cut(b, rw - aw, sm), sm, fill="#222")
        return "".join(out)
    big = fit(num, tw, min(h * 0.34, 11))
    sm = min(h * 0.12, 3.4, tw / 14)
    foot = sm * 0.78
    y = pad + max(big, sm * 2) * 0.86
    text(x0, y, num, big, bold=True, mono=True)
    y += sm * 1.55
    text(x0, y, _cut(a, tw, sm), sm, fill="#111")
    y += sm * 1.3
    aw = arrow(x0, y, sm)
    text(x0 + aw, y, _cut(b, tw - aw, sm), sm, fill="#111")
    if y + foot * 1.6 <= h - pad * 0.6:
        text(x0, h - pad, _cut(cab["kind"], tw * 0.7, foot), foot, fill="#555")
        text(w - pad, h - pad, "díktyo", foot, fill="#0091A8", anchor="end")
    return "".join(out)


def render(c, pid, keys, fmt="a4-48x25", both=False, skip=0, outline=False, lang="de"):
    """-> PDF-Bytes. keys in gewünschter Reihenfolge (leer = alle); both = je Kabelende ein Etikett."""
    f = FORMATS_CABLE.get(fmt)
    if not f:
        raise labels.LabelError("Unbekanntes Etikettenformat")
    allc = cables(c, pid, lang)
    if keys:
        by = {x["key"]: x for x in allc}
        sel = [by[k] for k in keys if k in by]
    else:
        sel = allc
    if not sel:
        raise labels.LabelError("Keine Kabel ausgewählt")
    items = []
    for cab in sel:
        ends = (0, 1) if both else (None,)
        items += [(lambda w, h, cab=cab, e=e: _label(cab, w, h, outline, e)) for e in ends]
    return labels.sheets(f, items[:MAX_LABELS], skip, "díktyo – Kabel-Etiketten" if lang != "en" else "díktyo – cable labels")
