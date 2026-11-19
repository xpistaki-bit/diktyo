"""M5: ASUS AiMesh, Proxmox, Home Assistant (Namen/Bereiche, MQTT), Ereignisse."""
import json

from fastapi.testclient import TestClient

from app import integrations, main, mqtt, users
from app.db import db, now
from app.drivers import asuswrt, homeassistant, proxmox

H = {"X-Requested-With": "diktyo"}


def login(email="m5@x.de"):
    with db() as c:
        if not users.by_email(c, email):
            users.create(c, email, "passwort123", is_admin=True)
    cl = TestClient(main.app)
    cl.post("/api/auth/login", json={"email": email, "password": "passwort123"}, headers=H)
    return cl


def profile(cl, name):
    pid = cl.post("/api/profiles", json={"name": name}, headers=H).json()["profile"]["id"]
    return pid, f"/api/profiles/{pid}"


def add_integration(pid, driver, host, secret="", options=None):
    with db() as c:
        return c.execute("INSERT INTO integrations(profile_id, driver, name, host, secret, options, created) VALUES(?,?,?,?,?,?,?)",
                         (pid, driver, driver, host, integrations.security.encrypt(json.dumps(secret)) if secret else "",
                          json.dumps(options or {}), now())).lastrowid


# Antwort von appGet.cgi im Format der ASUS-Weboberfläche (gekürzt, mit Komma am Ende wie bei manchen Firmwares)
ASUS_JSON = """{
"get_clientlist":{"maclist":["F0:2F:74:00:00:95","44:00:49:00:00:01","D8:BB:C1:00:00:02","AA:00:00:00:00:09"],
 "F0:2F:74:00:00:95":{"name":"EBM68","nickName":"","ip":"192.168.50.95","mac":"F0:2F:74:00:00:95","isOnline":"1","isWL":"0","amesh_isRe":"1"},
 "44:00:49:00:00:01":{"name":"amazon-123","nickName":"Echo Küche","ip":"192.168.50.120","mac":"44:00:49:00:00:01","isOnline":"1","isWL":"2","amesh_papMac":"F0:2F:74:00:00:9A","rssi":"-55"},
 "D8:BB:C1:00:00:02":{"name":"nas","nickName":"","ip":"192.168.50.20","mac":"D8:BB:C1:00:00:02","isOnline":"1","isWL":"0","amesh_papMac":"E8:9C:25:24:B6:60"},
 "AA:00:00:00:00:09":{"name":"alt","ip":"192.168.50.99","mac":"AA:00:00:00:00:09","isOnline":"0","isWL":"1"},
},
"get_cfg_clientlist":[{"alias":"EBM68 Wohnzimmer","model_name":"EBM68","ui_model_name":"ExpertWiFi_EBM68","ip":"192.168.50.1","mac":"E8:9C:25:24:B6:60","level":"0","online":"1"},
 {"alias":"EBM68 OG","model_name":"EBM68","ui_model_name":"ExpertWiFi_EBM68","ip":"192.168.50.95","mac":"F0:2F:74:00:00:95","level":"1","online":"1","pap5g":"E8:9C:25:24:B6:64","ap5g":"F0:2F:74:00:00:9A"}],
"productid":"EBM68","firmver":"3.0.0.6","buildno":"102_21000","lan_ipaddr":"192.168.50.1","label_mac":"E8:9C:25:24:B6:60"}"""


def test_asus_parse_and_apply(monkeypatch):
    data = asuswrt.parse_json(ASUS_JSON)
    info, nodes, clients = asuswrt.normalize(data)
    assert info["model"] == "EBM68" and len(nodes) == 2 and [x["name"] for x in clients] == ["Echo Küche", "nas", "alt"]
    assert nodes[1]["parent_ap"] == "E8:9C:25:24:B6:64" and not nodes[1]["wired_backhaul"]
    assert clients[0]["medium"] == "wlan" and clients[0]["band"] == "5 GHz" and clients[1]["medium"] == "lan"

    cl = login()
    pid, P = profile(cl, "ASUS")
    iid = add_integration(pid, "asuswrt", "192.168.50.1", {"password": "x"})
    monkeypatch.setattr(asuswrt, "poll", lambda conf, state: (dict(info=info, nodes=nodes, clients=clients), {}, dict(state, token="t")))
    s = integrations.poll(iid)
    assert s["nodes"] == 2 and s["new"] == 3  # Knoten OG + Echo + NAS (das inaktive Gerät nicht)
    devs = {d["name"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    main_name = next(n for n in devs if devs[n]["mac"] == "E8:9C:25:24:B6:60")
    assert devs[main_name]["model"] == "ExpertWiFi EBM68"
    assert devs["EBM68 OG"]["uplink"]["device_name"] == main_name and devs["EBM68 OG"]["uplink"]["medium"] == "mesh"
    assert devs["Echo Küche"]["uplink"]["device_name"] == "EBM68 OG" and devs["Echo Küche"]["uplink"]["medium"] == "wlan"
    assert devs["nas"]["uplink"]["device_name"] == main_name and devs["nas"]["uplink"]["medium"] == "lan"
    assert "alt" not in devs
    with db() as c:
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()["state"])
    assert st["token"] == "t" and st["result"]["wlan"] == 1


class FakeProxmox:
    """Antworten der Proxmox-API (gekürzt)."""
    DATA = {
        "/version": {"version": "9.2.28"},
        "/cluster/status": [{"type": "cluster", "name": "home"}, {"type": "node", "name": "proxmoxone", "ip": "192.168.50.12", "online": 1},
                            {"type": "node", "name": "proxmoxtwo", "ip": "192.168.50.13", "online": 1}],
        "/cluster/resources?type=vm": [{"vmid": 101, "name": "homeassistant", "node": "proxmoxone", "type": "qemu", "status": "running"},
                                       {"vmid": 103, "name": "diktyo", "node": "proxmoxtwo", "type": "lxc", "status": "running"},
                                       {"vmid": 104, "name": "alt", "node": "proxmoxtwo", "type": "lxc", "status": "stopped"},
                                       {"vmid": 900, "name": "vorlage", "node": "proxmoxone", "type": "qemu", "template": 1}],
        "/nodes/proxmoxone/qemu/101/config": {"net0": "virtio=02:8F:B9:9E:84:82,bridge=vmbr0,firewall=1", "agent": "1"},
        "/nodes/proxmoxone/qemu/101/agent/network-get-interfaces": {"result": [
            {"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}]},
            {"name": "enp0s18", "hardware-address": "02:8f:b9:9e:84:82", "ip-addresses": [{"ip-address": "192.168.50.9", "ip-address-type": "ipv4"},
                                                                                           {"ip-address": "fe80::1", "ip-address-type": "ipv6"}]}]},
        "/nodes/proxmoxtwo/lxc/103/config": {"net0": "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:01:03,ip=dhcp,tag=10,type=veth"},
        "/nodes/proxmoxtwo/lxc/103/interfaces": [{"name": "eth0", "hwaddr": "bc:24:11:00:01:03", "inet": "192.168.50.223/24"}],
        "/nodes/proxmoxtwo/lxc/104/config": {"net0": "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:01:04,ip=192.168.50.240/24"},
    }


def test_proxmox_parse_and_apply(monkeypatch):
    assert proxmox.parse_net("name=eth0,bridge=vmbr0,hwaddr=bc:24:11:00:01:03,ip=192.168.50.5/24,tag=20") == \
        dict(mac="BC:24:11:00:01:03", bridge="vmbr0", tag="20", name="eth0", ip="192.168.50.5", ip_mode="192.168.50.5/24")
    monkeypatch.setattr(proxmox, "_get", lambda cl, path: FakeProxmox.DATA.get(path))
    res, _, _ = proxmox.poll(dict(host="192.168.50.12", username="diktyo@pve!diktyo", password="s"), {})
    g = {x["name"]: x for x in res["guests"]}
    assert set(g) == {"homeassistant", "diktyo", "alt"} and g["homeassistant"]["ips"] == ["192.168.50.9"]
    assert g["diktyo"]["ips"] == ["192.168.50.223"] and g["diktyo"]["nets"][0]["tag"] == "10" and g["alt"]["ips"] == ["192.168.50.240"]

    cl = login()
    pid, P = profile(cl, "PVE")
    cl.post(f"{P}/devices", json={"name": "Proxmox Eins", "type": "hypervisor", "ips": [{"address": "192.168.50.12"}]}, headers=H)  # vorhanden
    iid = add_integration(pid, "proxmox", "192.168.50.12", {"password": "s"})
    monkeypatch.setattr(proxmox, "poll", lambda conf, state: (res, {}, state))
    s = integrations.poll(iid)
    assert s["nodes"] == 2 and s["guests"] == 3 and s["running"] == 2 and s["new"] == 4 and s["links"] == 3
    devs = {d["name"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    assert devs["homeassistant"]["type"] == "vm" and devs["homeassistant"]["uplink"]["device_name"] == "Proxmox Eins"
    assert devs["homeassistant"]["uplink"]["medium"] == "virtual" and devs["homeassistant"]["online"] == 1
    assert devs["diktyo"]["type"] == "container" and devs["diktyo"]["uplink"]["device_name"] == "proxmoxtwo" and devs["alt"]["online"] == 0
    assert devs["diktyo"]["mac"] == "BC:24:11:00:01:03"
    with db() as c:
        assert c.execute("SELECT device_id FROM integrations WHERE id=?", (iid,)).fetchone()["device_id"] == devs["Proxmox Eins"]["id"]


def test_homeassistant_import_mqtt_and_events(monkeypatch):
    cl = login()
    pid, P = profile(cl, "HA")
    sw = cl.post(f"{P}/devices", json={"name": "Switch", "type": "switch", "mac": "70:49:A2:55:28:34", "ips": [{"address": "127.0.0.1"}]}, headers=H).json()
    sh = cl.post(f"{P}/devices", json={"name": "shelly1pmminig3-5432044ee238", "type": "iot", "mac": "54:32:04:4E:E2:38",
                                        "ips": [{"address": "192.0.2.10"}]}, headers=H).json()
    mine = cl.post(f"{P}/devices", json={"name": "Mein NAS", "type": "nas", "mac": "D8:BB:C1:00:00:02"}, headers=H).json()
    monkeypatch.setattr(homeassistant, "_devices", lambda conf: [
        {"name": "Heizung", "area": "Keller", "manufacturer": "Shelly", "model": "Shelly 1PM Mini Gen3", "macs": ["54:32:04:4e:e2:38"]},
        {"name": "Speicher", "area": "Büro", "macs": ["d8:bb:c1:00:00:02"]}, {"name": "Unbekannt", "area": None, "macs": ["00:11:22:33:44:55"]}])
    sent = []
    monkeypatch.setattr(mqtt, "publish", lambda conf, msgs: sent.extend(msgs) or len(msgs))
    iid = add_integration(pid, "homeassistant", "http://ha:8123", {"password": "tok", "mqtt_pass": "m"},
                          dict(mqtt_host="ha", mqtt_user="diktyo", publish="infra", import_names="new", import_areas="yes"))
    # Ereignisse: Switch geht offline, neues Gerät
    with db() as c:
        from app.scan import runner
        runner._set_online(c, sw["id"], 1, now())   # erstes Sehen: kein Ereignis
        runner._set_online(c, sw["id"], 0, now())   # Wechsel: Ereignis
        assert c.execute("SELECT kind FROM events WHERE profile_id=?", (pid,)).fetchall()[0]["kind"] == "device_offline"
    s = integrations.poll(iid)
    assert s["matched"] == 2 and s["renamed"] == 1 and s["located"] == 2 and s["events"] == 1 and s["published"] == 2  # Switch + NAS
    devs = {d["id"]: d for d in cl.get(f"{P}/devices").json()["devices"]}
    assert devs[sh["id"]]["name"] == "Heizung" and devs[sh["id"]]["location"] == "Keller"
    assert devs[mine["id"]]["name"] == "Mein NAS" and devs[mine["id"]]["location"] == "Büro"  # eigener Name bleibt
    topics = {t: p for t, p, _ in sent}
    cfg = topics[f"homeassistant/binary_sensor/diktyo_{pid}_{sw['id']}/config"]
    assert cfg["device_class"] == "connectivity" and cfg["device"]["connections"] == [["mac", "70:49:a2:55:28:34"]]
    assert topics[f"diktyo/{pid}/device/{sw['id']}"] == "OFF"
    assert topics[f"diktyo/{pid}/event"]["event_type"] == "device_offline" and topics[f"diktyo/{pid}/event"]["device"] == "Switch"
    assert topics[f"homeassistant/event/diktyo_{pid}_events/config"]["event_types"] == ["device_offline", "device_online", "new_device"]
    assert f"homeassistant/sensor/diktyo_{pid}_inbox/config" in topics
    # zweite Abfrage: Ereignis wird nicht doppelt gemeldet
    sent.clear()
    assert integrations.poll(iid)["events"] == 0
    # Gerät nicht mehr gemeldet -> Konfiguration wird in HA gelöscht
    cl.put(f"{P}/devices/{sw['id']}", json={"name": "Switch", "type": "iot"}, headers=H)
    sent.clear()
    integrations.poll(iid)
    assert (f"homeassistant/binary_sensor/diktyo_{pid}_{sw['id']}/config", "", True) in sent
