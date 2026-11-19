"""Kleiner Seitensatz für A4-PDFs: Überschriften, Absätze und Tabellen mit Umbruch, als SVG gesetzt und mit CairoSVG gewandelt.

Einheiten sind Millimeter. Helle Druckvariante des HUD-Farbschemas.
"""
import io
import textwrap

import cairosvg
from pypdf import PdfReader, PdfWriter

W, H = 210, 297
M = 14  # Rand
TOP, BOTTOM = 26, H - 16
FONT = "DejaVu Sans, Arial, Helvetica, sans-serif"
MONO = "DejaVu Sans Mono, Menlo, Consolas, monospace"
INK, MUTE, LINE, ACC, NAVY, HEAD_BG, ZEBRA = "#0A1A33", "#56708A", "#C9D6E3", "#0091A8", "#0A1A33", "#E8F4F8", "#F6FAFC"
CHAR_W = {False: 0.6, True: 0.61}  # mittlere Zeichenbreite in Schriftgrößen-Einheiten (proportional / mono)


def esc(s):
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def wrap(text, width_mm, size, mono=False, max_lines=6):
    chars = max(4, int(width_mm / (size * CHAR_W[mono])))
    lines = []
    for para in str(text if text is not None else "").splitlines() or [""]:
        lines.extend(textwrap.wrap(para, chars, break_long_words=True, break_on_hyphens=False) or [""])
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(0, chars - 1)] + "…"
    return lines


class Doc:
    def __init__(self, title, subtitle, footer, page_word="Seite"):
        self.title, self.subtitle, self.footer, self.page_word = title, subtitle, footer, page_word
        self.pages = []
        self._new()

    def _new(self):
        self.pages.append([])
        self.y = TOP

    def _put(self, s):
        self.pages[-1].append(s)

    def _need(self, h):
        if self.y + h > BOTTOM:
            self._new()
            return True
        return False

    def gap(self, h=3):
        self.y += h

    def heading(self, text, size=5.2):
        self._need(size + 14)  # Überschrift nie allein am Seitenende
        if self.y > TOP + 1:
            self.y += 3 if size > 4.5 else 1.5
        self._put(f'<rect x="{M}" y="{self.y - size * 0.85:.2f}" width="1.4" height="{size * 1.05:.2f}" fill="{ACC}"/>')
        self._put(f'<text x="{M + 3.5}" y="{self.y:.2f}" font-size="{size}" font-weight="bold" fill="{NAVY}">{esc(text)}</text>')
        self.y += 4.5

    def para(self, text, size=3.2, color=MUTE):
        for ln in wrap(text, W - 2 * M, size, max_lines=40):
            self._need(size * 1.5)
            self._put(f'<text x="{M}" y="{self.y + size:.2f}" font-size="{size}" fill="{color}">{esc(ln)}</text>')
            self.y += size * 1.45
        self.y += 1.5

    def kv(self, pairs, size=3.1):
        """Schlüssel-Wert-Zeile, z. B. Gateway, DHCP, VLAN."""
        txt = "   ·   ".join(f"{k}: {v}" for k, v in pairs if v not in (None, ""))
        if txt:
            self.para(txt, size, INK)

    def table(self, cols, rows, size=2.9):
        """cols: [(Titel, Anteil, mono)], rows: Listen von Zellen."""
        total = sum(c[1] for c in cols)
        widths = [(W - 2 * M) * c[1] / total for c in cols]
        pad, lh = 1.4, size * 1.32

        hs = size * 0.88
        heads = [wrap(str(t).upper(), w - 2 * pad, hs / 0.56 * 0.7, max_lines=2) for (t, _, _), w in zip(cols, widths)]

        def header():
            hh = max(len(x) for x in heads) * hs * 1.25 + 2 * pad
            self._put(f'<rect x="{M}" y="{self.y:.2f}" width="{W - 2 * M}" height="{hh:.2f}" fill="{HEAD_BG}"/>')
            x = M
            for lines, w in zip(heads, widths):
                for k, ln in enumerate(lines):
                    self._put(f'<text x="{x + pad:.2f}" y="{self.y + pad + hs * 0.9 + k * hs * 1.25:.2f}" font-size="{hs:.2f}" font-weight="bold" '
                              f'fill="{MUTE}" letter-spacing="0.12">{esc(ln)}</text>')
                x += w
            self.y += hh

        self._need(size * 6)
        header()
        for n, row in enumerate(rows):
            cells = [wrap(v, w - 2 * pad, size, cols[i][2]) for i, (v, w) in enumerate(zip(row, widths))]
            h = max(len(c) for c in cells) * lh + 2 * pad - (lh - size)
            if self._need(h):
                header()
            if n % 2:
                self._put(f'<rect x="{M}" y="{self.y:.2f}" width="{W - 2 * M}" height="{h:.2f}" fill="{ZEBRA}"/>')
            x = M
            for i, (lines, w) in enumerate(zip(cells, widths)):
                fam = f' font-family="{MONO}"' if cols[i][2] else ""
                for k, ln in enumerate(lines):
                    self._put(f'<text x="{x + pad:.2f}" y="{self.y + pad + size * 0.85 + k * lh:.2f}" font-size="{size}"{fam} fill="{INK}">{esc(ln)}</text>')
                x += w
            self.y += h
            self._put(f'<line x1="{M}" y1="{self.y:.2f}" x2="{W - M}" y2="{self.y:.2f}" stroke="{LINE}" stroke-width="0.2"/>')
        if not rows:
            self.para("–", size)
        self.y += 3

    def figure(self, inner, w, h, max_scale=0.32):
        """Eine Zeichnung (SVG-Inhalt in eigenen Einheiten) auf Seitenbreite skaliert einsetzen, bei Bedarf über mehrere Seiten."""
        scale = min((W - 2 * M) / w, max_scale)
        drawn_h = h * scale
        top = 0.0
        while top < drawn_h - 0.01:
            avail = BOTTOM - self.y
            if avail < 30:
                self._new()
                avail = BOTTOM - self.y
            part = min(avail, drawn_h - top)
            self._put(f'<svg x="{M}" y="{self.y:.2f}" width="{w * scale:.2f}" height="{part:.2f}" viewBox="0 {top / scale:.2f} {w:.2f} {part / scale:.2f}">{inner}</svg>')
            self.y += part
            top += part
            if top < drawn_h - 0.01:
                self._new()
        self.y += 4

    def _svg(self, body, n, total):
        head = (f'<rect x="0" y="0" width="{W}" height="17" fill="{NAVY}"/>'
                f'<rect x="0" y="17" width="{W}" height="0.8" fill="{ACC}"/>'
                f'<text x="{M}" y="8.6" font-size="5" font-weight="bold" fill="#FFFFFF" letter-spacing="0.6">díktyo</text>'
                f'<text x="{M + 24}" y="8.6" font-size="4.2" fill="#BFEFFF">{esc(self.title)}</text>'
                f'<text x="{M}" y="13.4" font-size="2.9" fill="#8FB3CC">{esc(self.subtitle)}</text>')
        foot = (f'<line x1="{M}" y1="{H - 10}" x2="{W - M}" y2="{H - 10}" stroke="{LINE}" stroke-width="0.25"/>'
                f'<text x="{M}" y="{H - 6}" font-size="2.6" fill="{MUTE}">{esc(self.footer)}</text>'
                f'<text x="{W - M}" y="{H - 6}" font-size="2.6" fill="{MUTE}" text-anchor="end">{esc(self.page_word)} {n} / {total}</text>')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}" font-family="{FONT}">'
                f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>{head}{"".join(body)}{foot}</svg>')

    def render(self):
        pages = [p for p in self.pages if p] or [[]]
        w = PdfWriter()
        for i, body in enumerate(pages, start=1):
            pdf = cairosvg.svg2pdf(bytestring=self._svg(body, i, len(pages)).encode("utf-8"))
            for p in PdfReader(io.BytesIO(pdf)).pages:
                w.add_page(p)
        w.add_metadata({"/Title": f"díktyo – {self.title}", "/Producer": "díktyo"})
        out = io.BytesIO()
        w.write(out)
        return out.getvalue()
