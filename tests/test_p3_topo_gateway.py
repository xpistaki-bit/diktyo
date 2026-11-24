"""Topologie hängt am Internet-Gateway: Hat die Erkennung die FRITZ!Box als Gerät am Switch-Port eingetragen (Switch sieht
dort nur ihre Adresse), zeigt die Topologie trotzdem Internet → FRITZ!Box → Switch → Router dahinter."""
import json

from app import integrations, topology
from app.db import db, now
from tests.test_m6 import H, login


def test_tree_rooted_at_gateway():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Gateway-Wurzel"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    mk = lambda **kw: cl.post(f"{P}/devices", json={"status": "confirmed", **kw}, headers=H).json()["id"]  # noqa: E731
    fb = mk(name="FRITZ!Box", type="router", ports=[{"count": 4, "kind": "rj45", "speed": "1G", "label": "LAN"}])
    sw = mk(name="XGS", type="switch", ports=[{"count": 24, "kind": "rj45", "speed": "1G"}])
    ebm = mk(name="EBM68-Main", type="mesh", ports=[{"count": 1, "kind": "rj45", "speed": "2.5G", "label": "WAN"}])
    with db() as c:
        port = lambda d, no: c.execute("SELECT id FROM interfaces WHERE device_id=? AND port_no=?", (d, no)).fetchone()["id"]  # noqa: E731
        # so hat es die SNMP-Erkennung eingetragen: FRITZ!Box (LAN 1) hängt an Switch-Port 21, EBM68 (WAN) an Port 2
        integrations.set_auto_uplink(c, pid, fb, sw, "lan", port_id=port(sw, 21), local_port_id=port(fb, 1), source="snmp")
        integrations.set_auto_uplink(c, pid, ebm, sw, "lan", port_id=port(sw, 2), local_port_id=port(ebm, 1), source="snmp")
        c.execute("INSERT INTO integrations(profile_id, driver, name, host, secret, options, device_id, state, created) VALUES(?,?,?,?,?,?,?,?,?)",
                  (pid, "fritzbox", "FRITZ!Box", "192.0.2.1", "", "{}", fb, json.dumps({"result": {"wan": {"connected": True}}}), now()))
        t = topology.build(c, pid)
    nodes = {n["id"]: n for n in t["nodes"]}
    assert nodes[f"d{fb}"]["depth"] == 1 and nodes[f"d{sw}"]["depth"] == 2 and nodes[f"d{ebm}"]["depth"] == 3
    edge = next(e for e in t["edges"] if {e["source"], e["target"]} == {f"d{fb}", f"d{sw}"})
    assert (edge["source"], edge["target"]) == (f"d{fb}", f"d{sw}")
    assert (edge["label"], edge["child_label"]) == ("LAN 1", "21")  # Port an der FRITZ!Box oben, Switch-Port beim Switch
    assert any(e["source"] == "internet" and e["target"] == f"d{fb}" for e in t["edges"])
    # die gespeicherte Verbindung bleibt unverändert
    assert cl.get(f"{P}/devices/{fb}").json()["uplink"]["device_id"] == sw
