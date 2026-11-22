"""Anpassbare Übersicht: Layout speichern, Felder ausblenden/verschieben, Diagramme anheften."""
from app import actions, metrics
from app.db import db
from tests.test_m6 import H, login
from tests.test_p2_actions import _setup


def test_layout_and_pins(monkeypatch):
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid, P, d = _setup(cl, "Anpassbar")
    with db() as c:
        metrics.put(c, pid, {f"i{d['fiid']}:wan:rx": 1e6, f"i{d['fiid']}:wan:tx": 2e5, f"i{d['siid']}:port:5:rx": 1e5, f"i{d['siid']}:port:5:tx": 3e6})
        metrics.put(c, pid, {f"d{d['fb']}:rtt": 1.5}, unit="ms")
    r = cl.get(f"{P}/dashboard/layout").json()
    assert not r["customized"] and [x["id"] for x in r["items"]][:3] == ["wan", "speed", "issues"]
    cand = {x["title"]: x for x in r["candidates"]}
    port = cand["Switch · Port 5 → Fernseher"]
    assert port["keys"] == [f"i{d['siid']}:port:5:tx", f"i{d['siid']}:port:5:rx"] and port["mirror"]
    assert "WAN · FRITZ!Box" in cand and cand["FRITZ!Box · Antwortzeit"]["unit"] == "ms"
    # anheften, doppelt abgelehnt, fremde Messreihe abgelehnt
    r = cl.post(f"{P}/dashboard/pins", json={"pin": port, "size": 8}, headers=H).json()
    pin = r["items"][-1]
    assert r["customized"] and pin["pin"]["title"] == port["title"] and pin["size"] == 8 and pin["id"].startswith("p_")
    assert cl.post(f"{P}/dashboard/pins", json={"pin": port}, headers=H).status_code == 400
    assert cl.post(f"{P}/dashboard/pins", json={"pin": {"keys": ["i999:wan:rx"]}}, headers=H).status_code == 400
    # umordnen, ausblenden, Breite; unbekannte Felder fallen weg, fehlende eingebaute kommen hinter ihren Vorgänger
    items = [pin, {"id": "rtt", "size": 12}, {"id": "wan", "hidden": True}, {"id": "quatsch"}]
    r = cl.put(f"{P}/dashboard/layout", json={"items": items}, headers=H).json()
    ids = [x["id"] for x in r["items"]]
    assert ids[:3] == [pin["id"], "rtt", "infra"] and "quatsch" not in ids and ids.index("speed") == ids.index("wan") + 1
    assert r["items"][1]["size"] == 12 and r["items"][ids.index("wan")]["hidden"]
    assert cl.get(f"{P}/dashboard").json()["layout"]["items"][0]["id"] == pin["id"]
    # Lesende dürfen nicht ändern
    with db() as c:
        from app import users
        if not users.by_email(c, "leser@x.de"):
            users.create(c, "leser@x.de", "passwort123")
        uid = users.by_email(c, "leser@x.de")["id"]
        c.execute("INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?,'view')", (pid, uid))
    rd = login("leser@x.de")
    assert rd.get(f"{P}/dashboard/layout").status_code == 200
    assert rd.put(f"{P}/dashboard/layout", json={"reset": True}, headers=H).status_code == 403
    # zurücksetzen
    r = cl.put(f"{P}/dashboard/layout", json={"reset": True}, headers=H).json()
    assert not r["customized"] and not any(x.get("pin") for x in r["items"])
