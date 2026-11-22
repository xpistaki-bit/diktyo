"""QR-Etiketten: PDF je Format, Seitenzahl, freie Plätze am Bogenanfang, Link im QR-Code, Fehlerfälle."""
import io

from pypdf import PdfReader

from app import labels
from tests.test_m6 import H, login


def _pid(cl, name):
    pid = cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    ids = [cl.post(f"{P}/devices", json={"status": "confirmed", "name": f"Gerät {n}", "type": "switch", "ips": [{"address": f"192.0.2.{n}"}]},
                   headers=H).json()["id"] for n in range(1, 27)]
    return pid, P, ids


def test_labels_pdf():
    cl = login()
    pid, P, ids = _pid(cl, "Etiketten")
    info = cl.get(f"{P}/export/labels").json()
    assert {f["key"] for f in info["formats"]} == set(labels.FORMATS) and not info["configured"]
    q = f"ids={','.join(map(str, ids))}&base=http://192.0.2.50:8090"
    r = cl.get(f"{P}/export/labels.pdf?{q}&fmt=a4-70x37")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    pdf = PdfReader(io.BytesIO(r.content))
    assert len(pdf.pages) == 2  # 26 Etiketten, 24 je Bogen
    assert round(float(pdf.pages[0].mediabox.width) / 72 * 25.4) == 210
    # 22 freie Plätze am Anfang: 22 + 3 Etiketten passen nicht mehr auf einen Bogen
    assert len(PdfReader(io.BytesIO(cl.get(f"{P}/export/labels.pdf?ids={ids[0]},{ids[1]},{ids[2]}&base=http://x.example&skip=22").content)).pages) == 2
    # Etikettendrucker: eine Seite je Etikett, 62 × 29 mm
    pdf = PdfReader(io.BytesIO(cl.get(f"{P}/export/labels.pdf?ids={ids[0]},{ids[1]}&fmt=roll-62x29&base=http://x.example").content))
    assert len(pdf.pages) == 2 and round(float(pdf.pages[0].mediabox.width) / 72 * 25.4) == 62
    # Fehler: unbekanntes Format, ungültige Adresse, keine (fremden) Geräte
    assert cl.get(f"{P}/export/labels.pdf?{q}&fmt=quatsch").status_code == 400
    assert cl.get(f"{P}/export/labels.pdf?ids={ids[0]}&base=ftp://x").status_code == 400
    other, _, oids = _pid(cl, "Fremd")
    assert cl.get(f"{P}/export/labels.pdf?ids={oids[0]}&base=http://x.example").status_code == 400


def test_label_link_and_qr():
    assert labels.device_url("http://192.0.2.50:8090/", 3, 17) == "http://192.0.2.50:8090/#/p/3/geraete/17"
    dev = dict(id=17, name="Proxmox pve2 (Quorum-Knoten im Keller)", type="hypervisor", ips=[{"address": "192.0.2.11"}], mac="AA:BB:CC:DD:EE:11",
               location="Keller")
    svg = labels._label(dev, labels.device_url("http://192.0.2.50:8090", 3, 17), 70, 37, labels.FIELDS, "de", False)
    assert "192.0.2.11" in svg and "AA:BB:CC:DD:EE:11" in svg and "Keller · Hypervisor" in svg and "<path d=\"M" in svg
    assert "…" in svg  # langer Name gekürzt
    svg = labels._label(dev, "http://x", 70, 37, [], "en", False)
    assert "192.0.2.11" not in svg and "Keller" not in svg
