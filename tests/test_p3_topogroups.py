"""Gruppen in der Topologie: eigene Gruppen, Gruppieren nach Standort/Tag/VLAN, Schwellwerte, Aufklappen, Positionen,
Export (draw.io/PDF), Sicherung und Rechte."""
import io
import json

from pypdf import PdfReader

from app import actions, backup, integrations
from app.db import db
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


def _clients(cl, P, d):
    """Access Point am Switch mit sechs WLAN-Geräten; drei davon im Subnetz von VLAN 30."""
    mk = lambda **kw: cl.post(f"{P}/devices", json={"status": "confirmed", **kw}, headers=H).json()["id"]  # noqa: E731
    ap = mk(name="AP Flur", type="ap", ips=[{"address": "192.168.178.30"}])
    cams = [mk(name=f"Kamera {i}", type="camera", ips=[{"address": f"192.168.30.{10 + i}"}], tags=["Kameras"]) for i in range(3)]
    phones = [mk(name=f"Handy {i}", type="phone", ips=[{"address": f"192.168.178.{60 + i}"}]) for i in range(3)]
    with db() as c:
        integrations.set_auto_uplink(c, d["pid"], ap, d["sw"], "lan")
        for x in cams + phones:
            integrations.set_auto_uplink(c, d["pid"], x, ap, "wlan")
    return ap, cams, phones


def _groups(topo):
    return {n["id"]: n for n in topo["nodes"] if n["kind"] == "group"}


def test_topology_groups(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Topologie-Gruppen")
    d["pid"] = pid
    ap, cams, phones = _clients(cl, P, d)
    # Vorgabe: sechs WLAN-Geräte als eine Box
    t = cl.get(f"{P}/topology").json()
    g = _groups(t)
    assert list(g) == [f"g{ap}:wlan"] and g[f"g{ap}:wlan"]["count"] == 6 and g[f"g{ap}:wlan"]["label"] == ""
    s = cl.get(f"{P}/topology/groups").json()
    assert s == {"groups": [], "settings": {"group_by": "medium", "min_wlan": 4, "min_virtual": 5, "min_group": 2}}

    # eigene Gruppe „Kameras“: eigene Box, die Handys fallen unter die Schwelle für WLAN (3 < 4) und stehen einzeln
    r = cl.post(f"{P}/topology/groups", json={"name": "Kameras", "color": "#ff8800", "members": cams + [999999]}, headers=H).json()
    gid = r["groups"][0]["id"]
    assert r["groups"][0]["members"] == sorted(cams)  # fremde IDs fallen weg
    assert cl.put(f"{P}/topology/settings", json={"group_by": "custom"}, headers=H).json()["settings"]["group_by"] == "custom"
    t = cl.get(f"{P}/topology").json()
    g = _groups(t)
    assert list(g) == [f"g{ap}:c{gid}"]
    cg = g[f"g{ap}:c{gid}"]
    assert (cg["label"], cg["color"], cg["count"], cg["medium"], cg["group_kind"]) == ("Kameras", "#ff8800", 3, "wlan", "custom")
    assert {n["name"] for n in t["nodes"] if n["kind"] == "device"} >= {"Handy 0", "Handy 1", "Handy 2"}
    # Schwellwert WLAN auf 3: die Handys bilden wieder eine WLAN-Box neben der Gruppe
    cl.put(f"{P}/topology/settings", json={"min_wlan": 3}, headers=H)
    assert set(_groups(cl.get(f"{P}/topology").json())) == {f"g{ap}:c{gid}", f"g{ap}:wlan"}
    # aufklappen: Kameras einzeln, der AP merkt sich die offene Gruppe
    t = cl.get(f"{P}/topology?expanded={ap}:c{gid}").json()
    assert set(_groups(t)) == {f"g{ap}:wlan"}
    assert next(n for n in t["nodes"] if n.get("device_id") == ap)["expanded_groups"] == [f"c{gid}"]
    # Schwelle für Gruppen höher als die Mitgliederzahl: keine Gruppen-Box
    cl.put(f"{P}/topology/settings", json={"min_group": 4}, headers=H)
    assert set(_groups(cl.get(f"{P}/topology").json())) == {f"g{ap}:wlan"}  # alle sechs als WLAN-Box
    cl.put(f"{P}/topology/settings", json={"min_group": 2, "min_wlan": 4}, headers=H)

    # ein Gerät gehört nur zu einer Gruppe
    r = cl.post(f"{P}/topology/groups", json={"name": "Alles", "members": [cams[0]]}, headers=H).json()
    by = {x["name"]: x for x in r["groups"]}
    assert by["Alles"]["members"] == [cams[0]] and cams[0] not in by["Kameras"]["members"]
    cl.delete(f"{P}/topology/groups/{by['Alles']['id']}", headers=H)
    cl.put(f"{P}/topology/groups/{gid}", json={"name": "Kameras", "color": "#ff8800", "members": cams}, headers=H)

    # Position der Gruppen-Box speichern
    assert cl.put(f"{P}/topology/positions", json={"positions": {f"g{ap}:c{gid}": [500, 300]}}, headers=H).status_code == 200
    with db() as c:
        assert c.execute("SELECT x FROM topo_positions WHERE profile_id=? AND node=?", (pid, f"g{ap}:c{gid}")).fetchone()[0] == 500

    # nach Tag
    cl.put(f"{P}/topology/settings", json={"group_by": "tag"}, headers=H)
    tg = [n for n in _groups(cl.get(f"{P}/topology").json()).values() if n["group_kind"] == "tag"]
    assert len(tg) == 1 and tg[0]["label"] == "Kameras" and tg[0]["key"].startswith("t")
    # nach Standort
    locs = cl.post(f"{P}/locations", json={"name": "Garten"}, headers=H).json()["locations"]
    garten = next(x["id"] for x in locs if x["name"] == "Garten")
    for x in cams[:2]:
        dev = cl.get(f"{P}/devices/{x}").json()
        assert cl.put(f"{P}/devices/{x}", json={"name": dev["name"], "type": dev["type"], "location_id": garten, "tags": ["Kameras"]}, headers=H).status_code == 200
    cl.put(f"{P}/topology/settings", json={"group_by": "location"}, headers=H)
    g = _groups(cl.get(f"{P}/topology").json())
    assert g[f"g{ap}:l{garten}"]["label"] == "Garten" and g[f"g{ap}:l{garten}"]["count"] == 2
    # nach VLAN (aus dem Subnetz der IP)
    v = cl.post(f"{P}/vlans", json={"vid": 30, "name": "Kameras"}, headers=H).json()["vlans"][0]
    cl.post(f"{P}/subnets", json={"cidr": "192.168.30.0/24", "vlan_id": v["id"]}, headers=H)
    cl.put(f"{P}/topology/settings", json={"group_by": "vlan"}, headers=H)
    g = _groups(cl.get(f"{P}/topology").json())
    assert g[f"g{ap}:v30"]["label"] == "VLAN 30 · Kameras" and g[f"g{ap}:v30"]["count"] == 3 and g[f"g{ap}:v30"]["color"]

    # Exporte zeigen die Bezeichnung
    cl.put(f"{P}/topology/settings", json={"group_by": "custom"}, headers=H)
    assert "Kameras (3)" in cl.get(f"{P}/export/netplan.drawio").text
    txt = PdfReader(io.BytesIO(cl.get(f"{P}/export/report.pdf?sections=topology").content)).pages[0].extract_text()
    assert "Kameras (3)" in txt

    # Prüfungen und Rechte
    for body in ({"group_by": "quatsch"}, {"min_wlan": -1}, {"min_group": "x"}):
        assert cl.put(f"{P}/topology/settings", json=body, headers=H).status_code == 400
    assert cl.post(f"{P}/topology/groups", json={"name": ""}, headers=H).status_code == 400
    assert cl.post(f"{P}/topology/groups", json={"name": "X", "color": "red"}, headers=H).status_code == 400
    assert cl.put(f"{P}/topology/groups/999999", json={"name": "X"}, headers=H).status_code == 400

    # Sicherung: Gruppen, Mitglieder, Einstellung und Position der Box kommen mit
    with db() as c:
        exp = json.loads(json.dumps(backup.export_data(c)))
        uid = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        backup.import_profiles(c, {**exp, "profiles": [p for p in exp["profiles"] if p["id"] == pid]}, uid)
        new = c.execute("SELECT id FROM profiles WHERE name='Topologie-Gruppen (importiert)'").fetchone()[0]
        node = c.execute("SELECT node FROM topo_positions WHERE profile_id=? AND node LIKE 'g%:c%'", (new,)).fetchone()[0]
    s2 = cl.get(f"/api/profiles/{new}/topology/groups").json()
    assert s2["settings"]["group_by"] == "custom" and s2["groups"][0]["name"] == "Kameras" and len(s2["groups"][0]["members"]) == 3
    assert node.endswith(f":c{s2['groups'][0]['id']}")
    t2 = cl.get(f"/api/profiles/{new}/topology").json()
    box = next(n for n in t2["nodes"] if n["kind"] == "group")
    assert box["label"] == "Kameras" and box.get("pinned") and box["x"] == 500

    # Löschen entfernt auch die gespeicherte Position
    cl.delete(f"{P}/topology/groups/{gid}", headers=H)
    with db() as c:
        assert not c.execute("SELECT 1 FROM topo_positions WHERE profile_id=? AND node LIKE 'g%:c%'", (pid,)).fetchone()
