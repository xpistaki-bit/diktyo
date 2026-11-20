"""Firmware lesbar (ASUS, FRITZ!Box) und auch für AiMesh-Knoten; Formatwechsel erzeugt keinen Verlaufseintrag."""
import json

from app import health, integrations
from app.db import db, now
from app.drivers import asuswrt, fritzbox
from tests.test_m6 import H, login


def test_formatters():
    assert asuswrt.fw_version("3006_102_46475-ga27e679_498-g0e4e1_sec") == "3.0.0.6.102_46475"
    assert asuswrt.fw_version("3.0.0.6_102_46475-g1") == "3.0.0.6.102_46475"
    assert fritzbox.fw_version("161.08.25") == "8.25" and fritzbox.fw_version("8.25") == "8.25"
    assert health._same_version("161.08.25", "8.25") and not health._same_version("161.08.25", "8.30")


def test_mesh_nodes_get_firmware_and_no_history_noise():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Firmware"}, headers=H).json()["profile"]["id"]
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, options, created) VALUES(?,?,?,?,?,?)",
                        (pid, "asuswrt", "ASUS", "192.0.2.1", "{}", now())).lastrowid
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
    node = lambda mac, ip, name, model, level: dict(mac=mac, ip=ip, name=name, model=model, firmware="3.0.0.6.102_46475", online=True,  # noqa: E731
                                                    level=level, parent_ap="", aps=[], wired_backhaul=level > 0)
    res = dict(info=dict(model="EBM68", firmware="3.0.0.6.102", mac="02:00:00:00:01:01", ip="192.0.2.1"),
               nodes=[node("02:00:00:00:01:01", "192.0.2.1", "EBM68", "EBM68", 0),
                      node("02:00:00:00:01:02", "192.0.2.95", "EBM68 Küche", "ExpertWiFi EBM68", 1),
                      node("02:00:00:00:01:03", "192.0.2.96", "RT-AX58U", "RT-AX58U", 1)],
               clients=[], firmware=dict(installed="3.0.0.6.102_46475", latest="3.0.0.6.102_47000", update=True))
    with db() as c:
        summary = integrations.APPLY["asuswrt"](c, row, res)
        health.apply_result(c, row, res, summary)
    devs = {d["name"]: d for d in cl.get(f"/api/profiles/{pid}/devices").json()["devices"]}
    fw = lambda n: json.loads(db_one("SELECT data FROM devices WHERE id=?", devs[n]["id"]))["firmware"]  # noqa: E731
    assert fw("EBM68 Küche") == {**fw("EBM68 Küche"), "installed": "3.0.0.6.102_46475", "latest": "3.0.0.6.102_47000", "update": True}
    assert fw("RT-AX58U")["installed"] == "3.0.0.6.102_46475" and fw("RT-AX58U")["update"] is False and fw("RT-AX58U")["latest"] == ""
    # alter Rohwert -> lesbarer Wert: kein Eintrag „Firmware geändert“
    main = summary.get("device_id") or row["device_id"] or devs["EBM68"]["id"]
    with db() as c:
        d = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (main,)).fetchone()["data"])
        d["firmware"]["installed"] = "3006_102_46475-ga27e679_498-g0e4e1_sec"
        c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(d), main))
        health.apply_firmware(c, pid, main, res["firmware"], "asuswrt")
        assert c.execute("SELECT COUNT(*) FROM changes WHERE device_id=? AND field='firmware'", (main,)).fetchone()[0] == 0


def db_one(q, *a):
    with db() as c:
        return c.execute(q, a).fetchone()[0]
