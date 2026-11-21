"""Selbst vergebene Gerätenamen überschreibt keine Integration (z. B. Home Assistant mit „alle Namen übernehmen“)."""
import json

from app import integrations
from app.db import db, now
from tests.test_m6 import H, login


def test_home_assistant_keeps_manual_names():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Namensschutz"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    a = cl.post(f"{P}/devices", json=dict(name="shellyplus1-abc", type="iot", mac="02:00:00:00:0D:01"), headers=H).json()["id"]
    b = cl.post(f"{P}/devices", json=dict(name="shelly1-def", type="iot", mac="02:00:00:00:0D:02"), headers=H).json()["id"]
    cl.put(f"{P}/devices/{a}", json=dict(name="ServerRackShelly", type="iot"), headers=H)  # von Hand umbenannt
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, created) VALUES(?,?,?,?,?,?)",
                        (pid, "homeassistant", "HA", "192.0.2.9", json.dumps({"import_names": "all"}), now())).lastrowid
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
        res = dict(ha_devices=[dict(name="ServerRack", macs=["02:00:00:00:0D:01"]), dict(name="Küchentisch", macs=["02:00:00:00:0D:02"])])
        s = integrations.APPLY["homeassistant"](c, row, res)
    devs = {d["id"]: d["name"] for d in cl.get(f"{P}/devices").json()["devices"]}
    assert devs[a] == "ServerRackShelly" and devs[b] == "Küchentisch" and s["renamed"] == 1
