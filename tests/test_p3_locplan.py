"""Grundriss/Raumplan und Rack-Ansicht: Art des Standorts, Rack-Belegung mit Prüfungen, Grundriss-Bild, Platzierungen,
Sicherung/Import, PDF-Abschnitt, Rechte."""
import io
import json

from PIL import Image
from pypdf import PdfReader

from app import actions, backup, locplan
from app.db import db
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


def _png(w=40, h=30):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (200, 220, 240)).save(b, "PNG")
    return b.getvalue()


def _lid(locs, name):
    return next(x["id"] for x in locs if x["name"] == name)


def test_rack(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Rack-Ansicht")
    locs = cl.post(f"{P}/locations", json={"name": "Keller"}, headers=H).json()["locations"]
    keller = _lid(locs, "Keller")
    assert cl.post(f"{P}/locations", json={"name": "Rack 1", "parent_id": keller, "kind": "rack", "rack_units": 0}, headers=H).status_code == 400
    locs = cl.post(f"{P}/locations", json={"name": "Rack 1", "parent_id": keller, "kind": "rack", "rack_units": 12}, headers=H).json()["locations"]
    rack = next(x for x in locs if x["name"] == "Rack 1")
    assert (rack["kind"], rack["rack_units"], rack["rack_used"]) == ("rack", 12, 0)
    R = f"{P}/locations/{rack['id']}"
    pp = cl.post(f"{P}/cabling/panels", json={"name": "PP1", "ports": 24}, headers=H).json()["panels"][0]
    v = cl.post(f"{R}/rack", json={"kind": "device", "ref_id": d["sw"], "u": 10, "height": 1}, headers=H).json()
    v = cl.post(f"{R}/rack", json={"kind": "panel", "ref_id": pp["id"], "u": 11, "height": 1}, headers=H).json()
    v = cl.post(f"{R}/rack", json={"kind": "other", "label": "USV", "u": 1, "height": 2}, headers=H).json()
    assert [(x["kind"], x["u"]) for x in v["rack"]] == [("panel", 11), ("device", 10), ("other", 1)]  # von oben nach unten
    sw = next(x for x in v["devices"] if x["id"] == d["sw"])
    assert sw["rack"] == rack["id"] and sw["location"] == "Keller › Rack 1" and sw["ports"] == 8
    # Prüfungen: belegt, außerhalb, ohne Bezeichnung, fremdes Gerät, Dose statt Patchfeld
    bad = [{"kind": "device", "ref_id": d["tv"], "u": 10}, {"kind": "device", "ref_id": d["tv"], "u": 12, "height": 2},
           {"kind": "other", "u": 5}, {"kind": "device", "ref_id": 999999, "u": 5}, {"kind": "quatsch", "u": 5}]
    for b in bad:
        assert cl.post(f"{R}/rack", json=b, headers=H).status_code == 400, b
    dose = [x for x in cl.post(f"{P}/cabling/panels", json={"kind": "outlet", "name": "Dose"}, headers=H).json()["panels"] if x["kind"] == "outlet"][0]
    assert cl.post(f"{R}/rack", json={"kind": "panel", "ref_id": dose["id"], "u": 5}, headers=H).status_code == 400
    # verschieben, Höhe ändern, Konflikt
    it = next(x for x in v["rack"] if x["kind"] == "device")
    assert cl.put(f"{R}/rack/{it['id']}", json={"u": 1}, headers=H).status_code == 400
    v = cl.put(f"{R}/rack/{it['id']}", json={"u": 5, "height": 2}, headers=H).json()
    assert next(x for x in v["rack"] if x["kind"] == "device")[("u")] == 5
    # Rack verkleinern unter belegte HE / Art ändern geht nicht
    assert cl.put(f"{P}/locations/{rack['id']}", json={"name": "Rack 1", "parent_id": keller, "kind": "rack", "rack_units": 10}, headers=H).status_code == 400
    assert cl.put(f"{P}/locations/{rack['id']}", json={"name": "Rack 1", "parent_id": keller, "kind": "area"}, headers=H).status_code == 400
    # in ein zweites Rack: aus dem ersten verschwunden
    locs = cl.post(f"{P}/locations", json={"name": "Rack 2", "kind": "rack", "rack_units": 6}, headers=H).json()["locations"]
    r2 = _lid(locs, "Rack 2")
    v2 = cl.post(f"{P}/locations/{r2}/rack", json={"kind": "device", "ref_id": d["sw"], "u": 1}, headers=H).json()
    assert len(v2["rack"]) == 1 and len(cl.get(f"{R}/view").json()["rack"]) == 2
    # ausbauen; ein Rack hat keinen Grundriss
    assert cl.delete(f"{P}/locations/{r2}/rack/{v2['rack'][0]['id']}", headers=H).json()["rack"] == []
    assert cl.put(f"{R}/plan/image", content=_png(), headers=H).status_code == 400
    # PDF-Abschnitt
    txt = PdfReader(io.BytesIO(cl.get(f"{P}/export/report.pdf?sections=plans").content)).pages[0].extract_text()
    assert "Rack 1" in txt and "USV" in txt and "PP1" in txt
    # Standort löschen: Einbauten weg, Patchfeld rückt nach oben
    cl.delete(f"{P}/locations/{rack['id']}", headers=H)
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM rack_items WHERE location_id=?", (rack["id"],)).fetchone()[0] == 0
        assert c.execute("SELECT location_id FROM patch_panels WHERE id=?", (pp["id"],)).fetchone()[0] == keller


def test_floor_plan(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Grundriss")
    locs = cl.post(f"{P}/locations", json={"name": "Erdgeschoss"}, headers=H).json()["locations"]
    eg = _lid(locs, "Erdgeschoss")
    locs = cl.post(f"{P}/locations", json={"name": "Büro", "parent_id": eg}, headers=H).json()["locations"]
    buero = _lid(locs, "Büro")
    other = _lid(cl.post(f"{P}/locations", json={"name": "Garten"}, headers=H).json()["locations"], "Garten")
    E = f"{P}/locations/{eg}"
    # Bild: PNG ja, SVG/Text nein, zu groß nein
    assert cl.put(f"{E}/plan/image", content=b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", headers=H).status_code == 400
    assert cl.put(f"{E}/plan/image", content=b"\x89PNG\r\n\x1a\n" + b"0" * (locplan.IMG_MAX + 1), headers=H).status_code == 400
    v = cl.put(f"{E}/plan/image", content=_png(), headers=H).json()
    assert v["plan"]["image"] and v["plan"]["ver"]
    r = cl.get(f"{E}/plan/image")
    assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff" and r.content[:4] == b"\x89PNG"
    # Platzieren: Gerät ohne Standort bekommt ihn, Raum = direkter Unterstandort, Koordinaten begrenzt
    v = cl.put(f"{E}/plan/items", json={"kind": "device", "ref_id": d["tv"], "x": 0.3, "y": 1.7}, headers=H).json()
    assert v["items"][0]["y"] == 1.0 and next(x for x in v["devices"] if x["id"] == d["tv"])["here"]
    v = cl.put(f"{E}/plan/items", json={"kind": "room", "ref_id": buero, "x": 0.9, "y": 0.1, "w": 0.3, "h": 0.4}, headers=H).json()
    room = next(x for x in v["items"] if x["kind"] == "room")
    assert abs(room["x"] - 0.7) < 1e-9 and room["w"] == 0.3  # im Bild gehalten
    assert cl.put(f"{E}/plan/items", json={"kind": "room", "ref_id": other, "x": 0.1, "y": 0.1}, headers=H).status_code == 400
    assert cl.put(f"{E}/plan/items", json={"kind": "device", "ref_id": 999999, "x": 0.1, "y": 0.1}, headers=H).status_code == 400
    v = cl.put(f"{E}/plan/items", json={"kind": "device", "ref_id": d["tv"], "x": 0.5, "y": 0.5}, headers=H).json()  # verschieben
    assert len([x for x in v["items"] if x["kind"] == "device"]) == 1
    v = cl.put(f"{E}/plan", json={"ratio": 9}, headers=H).json()
    assert v["plan"]["ratio"] == 4
    lst = cl.get(f"{P}/locations").json()["locations"]
    assert next(x for x in lst if x["id"] == eg)["has_plan"] and next(x for x in lst if x["id"] == buero)["kind"] == "area"
    assert v["chain"] == [] and [k["name"] for k in v["children"]] == ["Büro"]
    assert cl.get(f"{P}/locations/{buero}/view").json()["chain"] == [{"id": eg, "name": "Erdgeschoss"}]
    # PDF mit Bild
    txt = PdfReader(io.BytesIO(cl.get(f"{P}/export/report.pdf?sections=plans").content)).pages[0].extract_text()
    assert "Erdgeschoss" in txt and "Fernseher" in txt and "Büro" in txt
    # Sicherung: Import nimmt Bild und Platzierungen mit
    with db() as c:
        exp = json.loads(json.dumps(backup.export_data(c)))
        uid = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        backup.import_profiles(c, {**exp, "profiles": [p for p in exp["profiles"] if p["id"] == pid]}, uid)
        new = c.execute("SELECT id FROM profiles WHERE name='Grundriss (importiert)'").fetchone()[0]
    nl = cl.get(f"/api/profiles/{new}/locations").json()["locations"]
    v2 = cl.get(f"/api/profiles/{new}/locations/{_lid(nl, 'Erdgeschoss')}/view").json()
    assert v2["plan"]["image"] and sorted(x["kind"] for x in v2["items"]) == ["device", "room"]
    # entfernen, Bild löschen, fremdes Profil
    v = cl.delete(f"{E}/plan/items/device/{d['tv']}", headers=H).json()
    assert [x["kind"] for x in v["items"]] == ["room"]
    assert not cl.delete(f"{E}/plan/image", headers=H).json()["plan"]["image"]
    assert cl.get(f"{E}/plan/image").status_code == 404
    assert cl.get(f"/api/profiles/{new}/locations/{eg}/view").status_code == 404


def test_rack_svg_and_mime():
    assert locplan.image_mime(b"\xff\xd8\xff\xe0") == "image/jpeg" and locplan.image_mime(b"RIFF1234WEBPVP8 ") == "image/webp"
    assert locplan.image_mime(b"GIF89a") == "image/gif" and locplan.image_mime(b"<svg") is None
    v = dict(location=dict(rack_units=4), rack=[dict(kind="other", ref_id=None, u=1, height=2, label="USV <1500>")], devices=[], panels=[])
    inner, w, h = locplan.rack_svg(v)
    assert "USV &lt;1500&gt;" in inner and h == 4 * 6 + 8
