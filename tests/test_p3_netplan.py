"""Netzplan-Export: SVG, PNG, draw.io, Poster-PDF (eine Seite A1, gekachelt auf A4), Gruppen aufklappen, Fehlerfälle."""
import io
import xml.dom.minidom

from pypdf import PdfReader

from app import actions
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


def _mm(pt):
    return round(float(pt) / 72 * 25.4)


def test_netplan_exports(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Netzplan")
    r = cl.get(f"{P}/export/netplan.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml") and "attachment" in r.headers["content-disposition"]
    assert "<svg" in r.text and "Netzplan" in r.text and "FRITZ!Box" in r.text and "Fernseher" in r.text
    assert "192.168.178.50 · TV" in r.text  # IP und Typ, Typ nicht doppelt
    r = cl.get(f"{P}/export/netplan.png")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    # draw.io: gültiges XML, Geräte mit Eigenschaften, Verbindungen
    r = cl.get(f"{P}/export/netplan.drawio")
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('.drawio"')
    doc = xml.dom.minidom.parseString(r.content)
    objs = {o.getAttribute("diktyo_id"): o for o in doc.getElementsByTagName("UserObject")}
    tv = objs[str(d["tv"])]
    assert tv.getAttribute("ip") == "192.168.178.50" and tv.getAttribute("mac") == "BB:BB:BB:BB:BB:50" and "Fernseher" in tv.getAttribute("label")
    edges = [e for e in doc.getElementsByTagName("mxCell") if e.getAttribute("edge") == "1"]
    assert len(edges) >= 2 and all(e.getAttribute("source") and e.getAttribute("target") for e in edges)
    # Poster-PDF: eine Seite A1; gekachelt: mehrere A4-Seiten
    pdf = PdfReader(io.BytesIO(cl.get(f"{P}/export/netplan.pdf?paper=a1").content))
    assert len(pdf.pages) == 1 and sorted((_mm(pdf.pages[0].mediabox.width), _mm(pdf.pages[0].mediabox.height))) == [594, 841]
    pdf = PdfReader(io.BytesIO(cl.get(f"{P}/export/netplan.pdf?paper=a2&tiles=1").content))
    assert len(pdf.pages) == 8 and (_mm(pdf.pages[0].mediabox.width), _mm(pdf.pages[0].mediabox.height)) == (210, 297)
    assert "Blatt 1/8" in pdf.pages[0].extract_text()
    # Fehlerfälle
    assert cl.get(f"{P}/export/netplan.pdf?paper=b5").status_code == 400
    assert cl.get(f"{P}/export/netplan.gif").status_code == 404
    empty = cl.post("/api/profiles", json={"name": "Leer"}, headers=H).json()["profile"]["id"]
    assert cl.get(f"/api/profiles/{empty}/export/netplan.svg").status_code == 400
