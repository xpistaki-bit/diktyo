"""Kabel und Patchpanels: Patchfelder/Dosen, Kabelwege mit Kabelnummern, Abgleich mit dem Netz, Belegung, PDF, Sicherung."""
import io

from pypdf import PdfReader

from app import actions, backup
from app.db import db
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


def test_cabling(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Verkabelung")  # Fernseher hängt an Switch-Port 5
    pp = cl.post(f"{P}/cabling/panels", json={"name": "PP1 Keller", "ports": 24}, headers=H).json()["panels"][0]
    dose = [x for x in cl.post(f"{P}/cabling/panels", json={"kind": "outlet", "name": "Dose WZ-2"}, headers=H).json()["panels"] if x["kind"] == "outlet"][0]
    assert (pp["kind"], pp["ports"], dose["ports"]) == ("panel", 24, 2)
    o = cl.get(f"{P}/cabling").json()
    assert [s["name"] for s in o["switches"]] == ["Switch"]
    assert next(p for p in o["switches"][0]["ports"] if p["no"] == 5)["peers"] == ["Fernseher"]
    # Kabelweg Switch-Port 5 -> PP1/12 -> Dose WZ-2/1 -> Fernseher: passt zum Netz
    run = dict(switch_id=d["sw"], switch_port=5, cable_a="P-05", panel_id=pp["id"], panel_port=12, cable_b="K-012", outlet_id=dose["id"], outlet_port=1,
               cable_c="A-1", device_id=d["tv"])
    o = cl.post(f"{P}/cabling/runs", json=run, headers=H).json()
    r = o["runs"][0]
    assert (r["switch"], r["port_name"], r["panel"], r["outlet"], r["device"], r["check"]) == ("Switch", "5", "PP1 Keller", "Dose WZ-2", "Fernseher", "ok")
    assert o["panels"][[x["id"] for x in o["panels"]].index(pp["id"])]["used"]["12"]["check"] == "ok"
    # doppelte Belegung, falsche Ports, falsche Art abgelehnt
    bad = [dict(run, cable_a=""), dict(switch_id=d["sw"], switch_port=6, panel_id=pp["id"], panel_port=12), dict(panel_id=pp["id"], panel_port=25),
           dict(switch_id=d["sw"], switch_port=99), dict(panel_id=dose["id"], panel_port=1), dict(note="leer")]
    for b in bad:
        assert cl.post(f"{P}/cabling/runs", json=b, headers=H).status_code == 400, b
    # anderes Gerät eingetragen als laut Netz: Abweichung
    o = cl.put(f"{P}/cabling/runs/{r['id']}", json=dict(run, device_id=d["fb"]), headers=H).json()
    assert o["runs"][0]["check"] == "mismatch" and o["runs"][0]["peers"][0]["name"] == "Fernseher"
    cl.put(f"{P}/cabling/runs/{r['id']}", json=run, headers=H)
    # Patchfeld lässt sich nicht unter einen belegten Port verkleinern
    assert cl.put(f"{P}/cabling/panels/{pp['id']}", json={"name": "PP1", "ports": 8}, headers=H).status_code == 400
    # Gerätedialog: Kabelweg beim Gerät und beim Switch
    assert len(cl.get(f"{P}/devices/{d['tv']}/cabling").json()["runs"]) == 1 and len(cl.get(f"{P}/devices/{d['sw']}/cabling").json()["runs"]) == 1
    # PDF-Abschnitt
    txt = PdfReader(io.BytesIO(cl.get(f"{P}/export/report.pdf?sections=cabling").content)).pages[0].extract_text()
    assert "Verkabelung" in txt and "K-012" in txt and "PP1 Keller" in txt
    # Sicherung: Profil importieren nimmt Patchfelder und Kabelwege mit
    with db() as c:
        exp = backup.export_data(c)
        uid = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        backup.import_profiles(c, {**exp, "profiles": [p for p in exp["profiles"] if p["id"] == pid]}, uid)
        new = c.execute("SELECT id FROM profiles WHERE name='Verkabelung (importiert)'").fetchone()[0]
    o2 = cl.get(f"/api/profiles/{new}/cabling").json()
    assert len(o2["panels"]) == 2 and o2["runs"][0]["cable_b"] == "K-012" and o2["runs"][0]["device"] == "Fernseher"
    # Lesende dürfen nichts ändern
    with db() as c:
        from app import users
        if not users.by_email(c, "leser@x.de"):
            users.create(c, "leser@x.de", "passwort123")
        c.execute("INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?,'view')", (pid, users.by_email(c, "leser@x.de")["id"]))
    rd = login("leser@x.de")
    assert rd.get(f"{P}/cabling").status_code == 200
    assert rd.post(f"{P}/cabling/panels", json={"name": "X"}, headers=H).status_code == 403
    # Patchfeld löschen: Kabelweg bleibt (ohne Patchfeld), Dose löschen ebenso
    o = cl.delete(f"{P}/cabling/panels/{pp['id']}", headers=H).json()
    assert o["runs"][0]["panel_id"] is None and o["runs"][0]["panel_port"] is None and o["runs"][0]["outlet"] == "Dose WZ-2"
    assert cl.delete(f"{P}/cabling/runs/{r['id']}", headers=H).json()["runs"] == []
