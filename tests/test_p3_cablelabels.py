"""Kabel-Etiketten: Kabel mit Nummer und ihren Enden, Sortierung, PDF je Format, je Ende ein Etikett, Fehlerfälle."""
import io

from pypdf import PdfReader

from app import actions, cablelabels
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


def test_cable_labels(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Kabel-Etiketten")
    pp = cl.post(f"{P}/cabling/panels", json={"name": "PP1", "ports": 24}, headers=H).json()["panels"][0]
    dose = [x for x in cl.post(f"{P}/cabling/panels", json={"kind": "outlet", "name": "Dose WZ"}, headers=H).json()["panels"] if x["kind"] == "outlet"][0]
    # voller Weg und ein Weg ohne Patchfeld (Patchkabel reicht dann vom Switch bis zur Dose), ein Weg ohne Nummern
    cl.post(f"{P}/cabling/runs", json=dict(switch_id=d["sw"], switch_port=5, cable_a="P-10", panel_id=pp["id"], panel_port=12, cable_b="K-2",
                                           outlet_id=dose["id"], outlet_port=1, cable_c="A-1", device_id=d["tv"]), headers=H)
    cl.post(f"{P}/cabling/runs", json=dict(switch_id=d["sw"], switch_port=6, cable_a="P-9", outlet_id=dose["id"], outlet_port=2), headers=H)
    cl.post(f"{P}/cabling/runs", json=dict(panel_id=pp["id"], panel_port=3), headers=H)
    info = cl.get(f"{P}/export/cable-labels").json()
    assert {f["key"] for f in info["formats"]} == set(cablelabels.FORMATS_CABLE)
    cab = info["cables"]
    assert [x["number"] for x in cab] == ["A-1", "K-2", "P-9", "P-10"]  # natürliche Sortierung
    by = {x["number"]: x for x in cab}
    assert (by["P-10"]["a"], by["P-10"]["b"], by["P-10"]["kind"]) == ("Switch · Port 5", "PP1 · 12", "Patchkabel")
    assert (by["K-2"]["a"], by["K-2"]["b"]) == ("PP1 · 12", "Dose WZ · 1")
    assert (by["A-1"]["a"], by["A-1"]["b"]) == ("Dose WZ · 1", "Fernseher")
    assert (by["P-9"]["a"], by["P-9"]["b"]) == ("Switch · Port 6", "Dose WZ · 2")
    assert cl.get(f"{P}/export/cable-labels?lang=en").json()["cables"][0]["kind"] == "Device cable"
    # alle (leer = alle), 65 je Bogen -> eine Seite; je Ende ein Etikett auf Schriftband -> 2 Seiten je Kabel
    r = cl.get(f"{P}/export/cable-labels.pdf?fmt=a4-38x21")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and len(PdfReader(io.BytesIO(r.content)).pages) == 1
    pdf = PdfReader(io.BytesIO(cl.get(f"{P}/export/cable-labels.pdf?fmt=tape-12&both=1&keys={by['P-10']['key']},{by['A-1']['key']}").content))
    assert len(pdf.pages) == 4 and round(float(pdf.pages[0].mediabox.height) / 72 * 25.4) == 12
    assert len(PdfReader(io.BytesIO(cl.get(f"{P}/export/cable-labels.pdf?fmt=a4-38x21&skip=63").content)).pages) == 2
    # Fehler: Format, fremde/ungültige Schlüssel
    assert cl.get(f"{P}/export/cable-labels.pdf?fmt=quatsch").status_code == 400
    assert cl.get(f"{P}/export/cable-labels.pdf?keys=999999a,../x").status_code == 400
    other = cl.post("/api/profiles", json={"name": "Leer"}, headers=H).json()["profile"]["id"]
    assert cl.get(f"/api/profiles/{other}/export/cable-labels.pdf").status_code == 400
    assert cl.get(f"/api/profiles/{other}/export/cable-labels.pdf?keys={by['P-10']['key']}").status_code == 400


def test_cable_label_svg():
    cab = dict(key="7a", number="P-05", kind="Patchkabel", a="Core-Switch · Port 5", b="PP1 Keller · 12")
    svg = cablelabels._label(cab, 38.1, 21.2, False)
    assert "P-05" in svg and "Core-Switch" in svg and "PP1 Keller" in svg and svg.count("<path") == 1 and "#0091A8" in svg
    end_b = cablelabels._label(cab, 38.1, 21.2, True, 1)  # Etikett am Patchfeld-Ende nennt den Switch als Gegenstelle
    assert end_b.index("PP1 Keller") < end_b.index("Core-Switch") and "stroke-dasharray" in end_b
    tape = cablelabels._label(dict(cab, number="K-1234567890", a="", b=""), 60, 12, False)
    assert "K-1234567890" in tape and "–" in tape and "díktyo" not in tape  # Nummer nie gekürzt
