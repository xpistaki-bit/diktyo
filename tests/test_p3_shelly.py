"""Shelly (Gen1, Gen2+) und Tasmota direkt: Erkennen, Lesen, Zuordnen, Leistung, Firmware, Schalten."""
import json

import httpx

from app import actions, integrations
from app.db import db, now
from app.drivers import shelly
from tests.test_m6 import H, login

DEV = {
    "192.0.2.40": {"/shelly": {"type": "SHSW-PM", "mac": "AABBCC000040", "auth": False, "fw": "20230913-114008/v1.14.0-gcb84623"},
                   "/status": {"relays": [{"ison": True}], "meters": [{"power": 41.5, "total": 120000}],
                               "update": {"has_update": True, "new_version": "20240101-000000/v1.14.1-gabc", "old_version": "x/v1.14.0-g"},
                               "wifi_sta": {"rssi": -61}}},
    "192.0.2.41": {"/shelly": {"gen": 2, "id": "shellypro3em-x", "mac": "AABBCC000041", "model": "SPEM-003CEBEU", "app": "Pro3EM", "ver": "1.4.4"},
                   "rpc": {"em:0": {"id": 0, "total_act_power": 1234.5, "a_act_power": 400}, "emdata:0": {"total_act": 456789.0},
                           "sys": {"available_updates": {}}, "wifi": {"rssi": -55}}},
    "192.0.2.42": {"/shelly": {"gen": 3, "id": "shelly1pmminig3-x", "mac": "AABBCC000042", "model": "S3SW-001P8EU", "app": "Mini1PMG3", "ver": "1.3.3"},
                   "rpc": {"switch:0": {"id": 0, "output": False, "apower": 0.0, "voltage": 231.2, "aenergy": {"total": 5100.0}},
                           "sys": {"available_updates": {"stable": {"version": "1.4.0"}}}, "wifi": {"rssi": -70}}},
    "192.0.2.43": {"tasmota": {"Status": {"DeviceName": "Gosund SP111", "FriendlyName": ["Steckdose TV"]}, "StatusFWR": {"Version": "14.2.0(release-tasmota)"},
                               "StatusNET": {"Mac": "AA:BB:CC:00:00:43", "IPAddress": "192.0.2.43"}, "StatusSTS": {"POWER": "ON", "Wifi": {"RSSI": 80}},
                               "StatusSNS": {"ENERGY": {"Power": 87, "Total": 12.345, "Voltage": 229}}}},
}
SENT = []


def fake_get(url, params=None, auth=None, timeout=None):
    ip, path = url.split("//")[1].split("/", 1)
    path = "/" + path
    d = DEV.get(ip)
    if d is None:
        raise httpx.ConnectTimeout("timeout")
    if path == "/cm" and "tasmota" in d:
        if params["cmnd"] != "Status 0":
            SENT.append((ip, params["cmnd"]))
            return httpx.Response(200, json={"POWER": "OFF"})
        return httpx.Response(200, json=d["tasmota"])
    if path in ("/relay/0", "/ota"):
        SENT.append((ip, path, dict(params)))
        return httpx.Response(200, json={})
    if path in d:
        return httpx.Response(200, json=d[path])
    return httpx.Response(404, text="")


def fake_post(url, json=None, auth=None, timeout=None):
    ip = url.split("//")[1].split("/")[0]
    if json["method"] == "Shelly.GetStatus":
        return httpx.Response(200, json={"id": 1, "result": DEV[ip]["rpc"]})
    SENT.append((ip, json["method"], json["params"]))
    return httpx.Response(200, json={"id": 1, "result": {}})


def mock(monkeypatch):
    SENT.clear()
    monkeypatch.setattr(shelly.httpx, "get", fake_get)
    monkeypatch.setattr(shelly.httpx, "post", fake_post)


def test_read_families(monkeypatch):
    mock(monkeypatch)
    g1 = shelly.read("192.0.2.40", {})
    assert g1["kind"] == "shelly" and g1["gen"] == 1 and g1["channels"] == [dict(id=0, name="Ausgang", on=True, power_w=41.5)]
    assert g1["power_w"] == 41.5 and g1["energy_kwh"] == 2.0 and g1["firmware"] == dict(installed="1.14.0", latest="1.14.1", update=True)
    em = shelly.read("192.0.2.41", {})
    assert em["power_w"] == 1234.5 and em["energy_kwh"] == 456.789 and em["channels"] == [] and em["firmware"]["update"] is False
    mini = shelly.read("192.0.2.42", {})
    assert mini["gen"] == 3 and mini["channels"][0]["on"] is False and mini["voltage"] == 231.2 and mini["firmware"]["latest"] == "1.4.0"
    ta = shelly.read("192.0.2.43", {})
    assert ta["kind"] == "tasmota" and ta["name"] == "Steckdose TV" and ta["power_w"] == 87 and ta["firmware"]["installed"] == "14.2.0"
    assert ta["channels"] == [dict(id=1, name="Ausgang", on=True, power_w=87)]


def test_poll_apply_actions(monkeypatch):
    mock(monkeypatch)
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Shelly"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    # vorhandenes Gerät (vom Scan erkannt) wird zugeordnet, die anderen kommen in den Posteingang
    rack = cl.post(f"{P}/devices", json=dict(name="ServerRackShelly", type="iot", manufacturer="Shelly", ips=[{"address": "192.0.2.42"}]), headers=H).json()
    cl.post(f"{P}/devices", json=dict(name="ESP", type="iot", ips=[{"address": "192.0.2.99"}], hostname="espressif"), headers=H)
    r = cl.post(f"{P}/integrations", json=dict(driver="shelly", host="auto, 192.0.2.40, 192.0.2.41, 192.0.2.43"), headers=H)
    assert r.status_code == 200, r.text
    iid = r.json()["id"]
    with db() as c:
        assert integrations.smart_targets(c, pid, {"host": "auto"}) == ["192.0.2.42", "192.0.2.99"]
    t = cl.post(f"{P}/integrations/test", json=dict(driver="shelly", host="auto, 192.0.2.40, 192.0.2.41, 192.0.2.43"), headers=H).json()["result"]
    assert t["devices"] == 4 and t["tasmota"] == 1
    s = integrations.poll(iid)
    assert s["devices"] == 4 and s["new"] == 3
    with db() as c:
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()["state"])
        assert "192.0.2.99" in st["skip"]  # antwortet nicht: wird eine Weile übersprungen
        d = json.loads(c.execute("SELECT data FROM devices WHERE id=?", (rack["id"],)).fetchone()["data"])
        assert d["smart"]["gen"] == 3 and d["firmware"]["update"] is True
        acts = {a["label"]: a for a in actions.available(c, pid, rack["id"])}
    assert set(acts) == {"Ausgang einschalten", "Firmware aktualisieren (1.3.3 → 1.4.0)"}
    m = cl.get(f"{P}/metrics?keys=d{rack['id']}:power&since=3600").json()
    assert m["series"][f"d{rack['id']}:power"][0][1] == 0.0
    actions.run(pid, 1, rack["id"], acts["Ausgang einschalten"]["key"])
    assert SENT[-1] == ("192.0.2.42", "Switch.Set", {"id": 0, "on": True})
    actions.run(pid, 1, rack["id"], acts["Firmware aktualisieren (1.3.3 → 1.4.0)"]["key"])
    assert SENT[-1] == ("192.0.2.42", "Shelly.Update", {"stage": "stable"})
    devs = {x["name"]: x for x in cl.get(f"{P}/devices").json()["devices"]}
    tv = devs["Steckdose TV"]["id"]
    with db() as c:
        off = next(a for a in actions.available(c, pid, tv) if a["kind"] == "relay")
        g1 = next(a for a in actions.available(c, pid, devs["Shelly SHSW-PM"]["id"]) if a["kind"] == "relay")
    assert off["label"] == "Ausgang ausschalten" and off["danger"] and off["undo"]
    actions.run(pid, 1, tv, off["key"], undo="15")
    assert SENT[-1] == ("192.0.2.43", "Power1 Off")
    actions.run(pid, 1, devs["Shelly SHSW-PM"]["id"], g1["key"])
    assert SENT[-1] == ("192.0.2.40", "/relay/0", {"turn": "off"})


def test_auth_required_message(monkeypatch):
    monkeypatch.setattr(shelly.httpx, "get", lambda url, **k: httpx.Response(401))
    try:
        shelly.read("192.0.2.50", {})
        raise AssertionError
    except shelly.DriverError as ex:
        assert "Anmeldung" in str(ex)
