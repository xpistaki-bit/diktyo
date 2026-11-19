"""OPNsense (REST-API) und Docker (Engine-API) gegen nachgebildete APIs."""
import json

import httpx

from app import actions, integrations, topology
from app.db import db, now
from app.drivers import docker, opnsense
from tests.test_m6 import H, login

OPN = {"rx": 10_000_000, "posted": []}


def opn_handler(req):
    assert req.headers["authorization"].startswith("Basic ")
    p = req.url.path.removeprefix("/api/")
    if req.method == "POST":
        OPN["posted"].append((p, json.loads(req.content or b"{}")))
        return httpx.Response(200, json={"status": "done"})
    if p == "core/backup/download/this":
        return httpx.Response(200, content=b"<?xml version=\"1.0\"?>\n<opnsense><revision><time>1</time></revision><system><hostname>fw</hostname></system></opnsense>",
                              headers={"content-type": "application/xml"})
    data = {
        "core/firmware/status": {"status": "update", "product": {"product_version": "25.1.4", "product_latest": "25.1.6", "product_series": "25.1"}},
        "diagnostics/system/system_information": {"name": "fw.home.arpa"},
        "interfaces/overview/export": [
            {"identifier": "wan", "description": "WAN", "device": "igb0", "status": "up", "addr4": "203.0.113.5/24", "macaddr": "00:0D:B9:00:00:01",
             "enabled": True, "statistics": {"bytes received": str(OPN["rx"]), "bytes transmitted": "1000"}},
            {"identifier": "lan", "description": "LAN", "device": "igb1", "status": "up", "addr4": "192.168.1.1/24", "macaddr": "00:0D:B9:00:00:02",
             "enabled": True, "statistics": {"bytes received": "5000", "bytes transmitted": "9000"}},
        ],
        "diagnostics/interface/search_arp": {"rows": [{"ip": "192.168.1.20", "mac": "aa:bb:cc:00:00:20", "hostname": "?", "intf": "igb1"},
                                                      {"ip": "192.168.1.30", "mac": "aa:bb:cc:00:00:30", "hostname": "drucker.home.arpa", "intf": "igb1"}]},
        "kea/leases4/search": {"rows": [{"address": "192.168.1.20", "hwaddr": "aa:bb:cc:00:00:20", "hostname": "laptop", "if_name": "lan"}]},
    }.get(p)
    if data is None:
        return httpx.Response(404)
    return httpx.Response(200, json=data)


def mock(monkeypatch, module, handler):
    real = module._client
    monkeypatch.setattr(module, "_client", lambda conf: httpx.Client(base_url=real(conf).base_url, auth=getattr(real(conf), "auth", None),
                                                                      transport=httpx.MockTransport(handler)))


def test_opnsense_poll_actions_backup(monkeypatch):
    mock(monkeypatch, opnsense, opn_handler)
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    t = opnsense.test(dict(host="192.168.1.1", username="k", password="s"))
    assert t == {"name": "fw.home.arpa", "model": "OPNsense", "version": "25.1.4", "ports": 2, "clients": 2, "wifi": 0}
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "OPNsense"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, username, secret, options, created) VALUES(?,?,?,?,?,?,?,?)",
                        (pid, "opnsense", "OPNsense", "192.168.1.1", "k", integrations.security.encrypt(json.dumps({"password": "s"})),
                         json.dumps({"block_alias": "diktyo_block", "cfg_schedule": "no"}), now())).lastrowid
    s = integrations.poll(iid)
    OPN["rx"] += 25_000_000
    integrations.poll(iid)
    assert s["clients"] == 2 and s["device_id"]
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
        res = json.loads(row["state"])["result"]
        fw_dev = json.loads(c.execute("SELECT data, type FROM devices WHERE id=?", (row["device_id"],)).fetchone()["data"])["firmware"]
        t = topology.build(c, pid, status=None)
    assert res["wan"]["rx_bps"] > 0 and res["wan"]["connected"] is True
    assert fw_dev == {**fw_dev, "installed": "25.1.4", "latest": "25.1.6", "update": True}
    names = {n.get("name") for n in t["nodes"]}
    assert {"laptop", "drucker"} <= names and any(n["id"] == "internet" for n in t["nodes"])
    # Internetsperre über den Alias, Neustart am Gerät der Integration
    laptop = next(n["device_id"] for n in t["nodes"] if n.get("name") == "laptop")
    acts = {a["label"]: a for a in cl.get(f"{P}/devices/{laptop}/actions").json()["actions"]}
    r = cl.post(f"{P}/devices/{laptop}/actions", json={"key": acts["Internetzugang sperren (OPNsense)"]["key"]}, headers=H).json()
    assert r["status"] == "done" and OPN["posted"][-1] == ("firewall/alias_util/add/diktyo_block", {"address": "192.168.1.20"})
    own = {a["label"] for a in cl.get(f"{P}/devices/{row['device_id']}/actions").json()["actions"]}
    assert "OPNsense neu starten" in own
    # Backup: config.xml, Revision entfernt (sonst wäre jeder Stand „neu“)
    name, data, is_text = opnsense.backup(dict(host="h", username="k", password="s"), {})
    assert name == "config-opnsense.xml" and is_text and b"<hostname>fw</hostname>" in data and b"<time>1</time>" not in data


def test_opnsense_without_alias_blocks_action(monkeypatch):
    mock(monkeypatch, opnsense, opn_handler)
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "OPNsense-ohne-Alias"}, headers=H).json()["profile"]["id"]
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, username, secret, options, created) VALUES(?,?,?,?,?,?,?,?)",
                        (pid, "opnsense", "OPNsense", "192.168.1.1", "k", integrations.security.encrypt(json.dumps({"password": "s"})),
                         json.dumps({"cfg_schedule": "no"}), now())).lastrowid
    integrations.poll(iid)
    with db() as c:
        laptop = c.execute("SELECT id FROM devices WHERE profile_id=? AND name='laptop'", (pid,)).fetchone()["id"]
    a = next(x for x in cl.get(f"/api/profiles/{pid}/devices/{laptop}/actions").json()["actions"] if x["label"] == "Internetzugang sperren (OPNsense)")
    assert "kein Alias" in a["blocked"]


DK = {"posted": []}


def dk_handler(req):
    p = req.url.path
    if req.method == "POST":
        DK["posted"].append(p)
        return httpx.Response(204)
    data = {
        "/version": {"Version": "27.3.1", "Os": "linux", "ApiVersion": "1.47"},
        "/info": {"Name": "nas", "OperatingSystem": "Debian GNU/Linux 12", "Containers": 3, "ContainersRunning": 2},
        "/containers/json": [
            {"Id": "a" * 64, "Names": ["/homeassistant"], "Image": "ghcr.io/home-assistant/home-assistant:stable", "State": "running", "Status": "Up 3 days",
             "HostConfig": {"NetworkMode": "host"}, "NetworkSettings": {"Networks": {"host": {"IPAddress": "", "MacAddress": ""}}}, "Ports": []},
            {"Id": "b" * 64, "Names": ["/pihole"], "Image": "pihole/pihole:2024.07.0", "State": "running", "Status": "Up 3 days",
             "HostConfig": {"NetworkMode": "macvlan_lan"}, "NetworkSettings": {"Networks": {"macvlan_lan": {"IPAddress": "192.168.1.53", "MacAddress": "02:42:c0:a8:01:35"}}},
             "Ports": []},
            {"Id": "c" * 64, "Names": ["/socket-proxy"], "Image": "tecnativa/docker-socket-proxy", "State": "running", "Status": "Up 3 days",
             "HostConfig": {"NetworkMode": "bridge"}, "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.17.0.2", "MacAddress": "02:42:ac:11:00:02"}}},
             "Ports": [{"PrivatePort": 2375, "PublicPort": 2375, "Type": "tcp"}]},
            {"Id": "d" * 64, "Names": ["/backup"], "Image": "restic/restic", "State": "exited", "Status": "Exited (0) 2 hours ago",
             "HostConfig": {"NetworkMode": "bridge"}, "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "", "MacAddress": ""}}}, "Ports": []},
        ],
    }.get(p)
    return httpx.Response(200, json=data) if data is not None else httpx.Response(404)


def test_docker_containers_and_actions(monkeypatch):
    mock(monkeypatch, docker, dk_handler)
    monkeypatch.setattr(actions, "_own_addresses", lambda: (set(), set()))
    assert docker.test(dict(host="192.168.1.20", port=2375)) == {"version": "27.3.1", "os": "Debian GNU/Linux 12", "containers": 4, "running": 3}
    lan = docker.normalize(docker.collect(dict(host="h")), dict(host="192.168.1.20", only_lan="lan"))[1]
    assert {x["name"] for x in lan} == {"homeassistant", "pihole"}
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Docker"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    host = cl.post(f"{P}/devices", json={"name": "NAS", "type": "nas", "status": "confirmed", "ips": [{"address": "192.168.1.20"}]}, headers=H).json()["id"]
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, port, secret, options, created) VALUES(?,?,?,?,?,?,?,?)",
                        (pid, "docker", "Docker", "192.168.1.20", 2375, "", json.dumps({"only_lan": "all"}), now())).lastrowid
    s = integrations.poll(iid)
    assert s["device_id"] == host and s["containers"] == 4 and s["running"] == 3
    integrations.poll(iid)  # zweite Abfrage legt nichts doppelt an
    with db() as c:
        devs = {r["name"]: r for r in c.execute("SELECT * FROM devices WHERE profile_id=? AND type='container'", (pid,))}
        t = topology.build(c, pid, status=None)
    assert set(devs) == {"homeassistant", "pihole", "socket-proxy", "backup"} and devs["backup"]["online"] == 0
    assert devs["pihole"]["model"].startswith("pihole/pihole")
    by = {n["id"]: n for n in t["nodes"]}
    parents = {by[e["target"]].get("name") for e in t["edges"] if by[e["source"]].get("name") == "NAS"}
    assert parents == {"homeassistant", "pihole", "socket-proxy", "backup"} or any(n["kind"] == "group" for n in t["nodes"])
    # Aktionen: am Container und am Host; Socket-Proxy geschützt
    pi = devs["pihole"]["id"]
    acts = {a["label"]: a for a in cl.get(f"{P}/devices/{pi}/actions").json()["actions"]}
    assert set(acts) == {"Stoppen", "Neu starten"}
    assert cl.post(f"{P}/devices/{pi}/actions", json={"key": acts["Neu starten"]["key"]}, headers=H).json()["status"] == "done"
    assert DK["posted"][-1] == f"/containers/{'b' * 64}/restart"
    hacts = {a["label"]: a for a in cl.get(f"{P}/devices/{host}/actions").json()["actions"]}
    assert "„backup“ starten" in hacts and "socket-proxy" in "".join(hacts) and hacts["„socket-proxy“ stoppen"]["blocked"]
