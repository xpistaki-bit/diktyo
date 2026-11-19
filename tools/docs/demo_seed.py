"""Demo-Heimnetz für die Bilder der Einstiegsanleitung. Nur Dokumentationsadressen (192.0.2.0/24), keine echten Geräte.
Aufruf über tools/docs/make-guide-images.sh (setzt DIKTYO_DATA und DEMO_LANG)."""
import json
import math
import random
import time

from fastapi.testclient import TestClient

from app import catalog, main, metrics, users
from app.db import db, migrate, now, set_setting
from app.scan import ident, runner

random.seed(7)
import os
EN = os.environ.get("DEMO_LANG") == "en"
NAMES = {"Zuhause": "Home", "Wohnung, 2 Etagen": "Flat, 2 floors", "Ferienhaus": "Holiday home", "Switch Keller": "Switch basement",
         "EBM68 Wohnzimmer": "EBM68 living room", "EBM68 Büro": "EBM68 office", "Drucker": "Printer", "Fernseher": "TV",
         "Handy Anna": "Anna's phone", "Handy Ben": "Ben's phone", "Echo Küche": "Echo kitchen", "Shelly Flur": "Shelly hallway",
         "Saugroboter": "Robot vacuum", "Heimnetz": "Home network"}


def N(x):
    return NAMES.get(x, x) if EN else x
H = {"X-Requested-With": "diktyo"}
EMAIL, PW = "admin@example.com", "passwort123"

migrate()
with db() as c:
    catalog.merge_seed(c)
    ident.merge_seed(c)
    users.create(c, EMAIL, PW, is_admin=True)
    # Hintergrunddienst „läuft“, mit einer Demo-Schnittstelle
    set_setting(c, "worker", dict(ts=time.time() + 10 ** 7, pid=1, raw=True, nmap=True, gateway="192.0.2.1",
                                  interfaces=[dict(ifname="eth0", ip="192.0.2.5", prefix=24, cidr="192.0.2.0/24")]))
cl = TestClient(main.app)
assert cl.post("/api/auth/login", json={"email": EMAIL, "password": PW}, headers=H).status_code == 200
pid = cl.post("/api/profiles", json={"name": N("Zuhause"), "description": N("Wohnung, 2 Etagen")}, headers=H).json()["profile"]["id"]
cl.post("/api/profiles", json={"name": N("Ferienhaus")}, headers=H)
P = f"/api/profiles/{pid}"
models = cl.get("/api/catalog").json()["models"]


def model(*names):
    for n in names:
        m = next((m for m in models if m["model"].lower() == n.lower()), None) or next((m for m in models if n.lower() in m["model"].lower()), None)
        if m:
            return m
    return None


def dev(name, typ, mdl=None, ip=None, mac="", **kw):
    m = model(*mdl) if mdl else None
    body = dict(name=name, type=typ, model_id=m and m["id"], ports=m["ports"] if m else [], mac=mac, **kw)
    if ip:
        body["ips"] = [{"address": ip, "kind": "static" if typ in ("router", "switch", "mesh", "hypervisor", "nas", "printer") else "dhcp"}]
    r = cl.post(f"{P}/devices", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def port(d, no):
    return next(p for p in d["ports"] if p.get("port_no") == no) if any(p.get("port_no") for p in d["ports"]) else d["ports"][no - 1]


cl.post(f"{P}/subnets", json={"cidr": "192.0.2.0/24", "name": N("Heimnetz"), "gateway": "192.0.2.1", "dhcp_start": "192.0.2.100", "dhcp_end": "192.0.2.199"}, headers=H)
fb = dev("FRITZ!Box", "router", ["FRITZ!Box 6591 Cable"], "192.0.2.1", "02:00:5E:00:00:01")
sw = dev(N("Switch Keller"), "switch", ["XGS1935-28"], "192.0.2.2", "02:00:5E:00:00:02", uplink=dict(device_id=fb["id"], port_id=port(fb, 1)["id"], medium="lan"))
mesh = dev(N("EBM68 Wohnzimmer"), "mesh", ["ExpertWiFi EBM68", "EBM68"], "192.0.2.3", "02:00:5E:00:00:03", uplink=dict(device_id=sw["id"], port_id=port(sw, 1)["id"], medium="lan"))
mesh2 = dev(N("EBM68 Büro"), "mesh", ["ExpertWiFi EBM68", "EBM68"], "192.0.2.4", "02:00:5E:00:00:04", uplink=dict(device_id=mesh["id"], medium="mesh"))
pve = dev("Proxmox", "hypervisor", None, "192.0.2.10", "02:00:5E:00:00:10", manufacturer="Intel", model="NUC 13 Pro",
          uplink=dict(device_id=sw["id"], port_id=port(sw, 5)["id"], medium="lan"))
nas = dev("NAS", "nas", ["DS923+", "DS220+", "DS"], "192.0.2.11", "02:00:5E:00:00:11", uplink=dict(device_id=sw["id"], port_id=port(sw, 3)["id"], medium="lan"))
dev(N("Drucker"), "printer", None, "192.0.2.12", "02:00:5E:00:00:12", manufacturer="Brother", model="HL-L2350DW",
    uplink=dict(device_id=sw["id"], port_id=port(sw, 7)["id"], medium="lan"))
tv = dev(N("Fernseher"), "tv", None, "192.0.2.13", "02:00:5E:00:00:13", manufacturer="LG", model="OLED55",
         uplink=dict(device_id=sw["id"], port_id=port(sw, 9)["id"], medium="lan"))
vms = [dev(n, t, None, ip, mac, uplink=dict(device_id=pve["id"], medium="virtual")) for n, t, ip, mac in (
    ("Home Assistant", "vm", "192.0.2.20", "02:00:5E:00:00:20"), ("díktyo", "container", "192.0.2.5", "02:00:5E:00:00:21"),
    ("Pi-hole", "container", "192.0.2.22", "02:00:5E:00:00:22"))]
wl = [dev(n, t, None, f"192.0.2.{ip}", f"02:00:5E:00:01:{ip:02X}", uplink=dict(device_id=mesh["id"] if i % 3 else mesh2["id"], medium="wlan"))
      for i, (n, t, ip) in enumerate(((N("Handy Anna"), "phone", 101), (N("Handy Ben"), "phone", 102), ("Laptop", "laptop", 103), ("Tablet", "tablet", 104),
                                      (N("Echo Küche"), "speaker", 105), (N("Shelly Flur"), "iot", 106), (N("Saugroboter"), "iot", 107)))]

# Neue Geräte im Posteingang wie nach einem Scan
hosts = [dict(ip="192.0.2.120", mac="02:00:5E:00:02:01", vendor="Shelly", random=False, hostname="shellyplus1pm-a8032ab1c2d4", netbios="",
              mdns=dict(names=["shellyplus1pm-a8032ab1c2d4"], services=["_http._tcp", "_shelly._tcp"], txt={"gen": "2"}), ssdp=None,
              http=dict(title="Shelly Plus 1PM"), ports=[80], services={}, os=""),
         dict(ip="192.0.2.121", mac="02:00:5E:00:02:02", vendor="Sonos, Inc.", random=False, hostname="Sonos-Wohnzimmer", netbios="",
              mdns=dict(names=["Sonos-Wohnzimmer"], services=["_sonos._tcp", "_spotify-connect._tcp"], txt={}), ssdp=dict(manufacturer="Sonos, Inc.", modelName="Sonos One"),
              http=None, ports=[1400], services={}, os=""),
         dict(ip="192.0.2.122", mac="02:00:5E:00:02:03", vendor="Raspberry Pi Trading Ltd", random=False, hostname="raspberrypi", netbios="",
              mdns=None, ssdp=None, http=None, ports=[22], services={"22": "ssh OpenSSH 9.2p1 Debian"}, os="Linux"),
         dict(ip="192.0.2.150", mac="DA:00:5E:00:02:04", vendor="", random=True, hostname="", netbios="", mdns=None, ssdp=None, http=None,
              ports=[], services={}, os="")]
with db() as c:
    rules, index = ident.load_rules(c), ident.catalog_index(c)
    for h in hosts:
        h["ident"] = ident.identify(rules, index, h)
    jid = c.execute("INSERT INTO jobs(profile_id, kind, params, status, progress, result, created, started, finished) VALUES(?,?,?,?,?,?,?,?,?)",
                    (pid, "scan", json.dumps(dict(mode="normal", targets=["192.0.2.0/24"])), "done", 100,
                     json.dumps(dict(mode="normal", targets=["192.0.2.0/24"], duration=48, hosts=27, new=4, offline=0)), now(), now(), now())).lastrowid
    runner.merge(c, pid, jid, hosts, record=False)
    c.execute("UPDATE devices SET status='confirmed', online=1, last_seen=? WHERE profile_id=? AND status<>'discovered'", (now(), pid))
    c.execute("UPDATE devices SET online=0 WHERE id=?", (wl[6]["id"],))
    ids = {r["id"] for r in c.execute("SELECT id FROM devices WHERE profile_id=? AND status='confirmed'", (pid,))}

    t = time.time()
    # Verfügbarkeit: seit 8 Tagen online (Saugroboter seit 2 Stunden offline)
    for did in ids:
        c.execute("INSERT INTO status_events(device_id, ts, online, source) VALUES(?,?,1,'ping')",
                  (did, time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t - 8 * 86400))))
    c.execute("INSERT INTO status_events(device_id, ts, online, source) VALUES(?,?,0,'ping')",
              (wl[6]["id"], time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t - 7200))))

    def integ(driver, name, host, device, state, interval=60):
        return c.execute("""INSERT INTO integrations(profile_id, driver, name, host, options, device_id, interval_s, state, last_poll, last_ok, created)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (pid, driver, name, host, json.dumps({"cfg_schedule": "no"}), device, interval,
                                                                json.dumps(dict(state, ts=time.time())), now(), now(), now())).lastrowid

    fbi = integ("fritzbox", "FRITZ!Box", "192.0.2.1", fb["id"], dict(summary=dict(hosts=23, new=0, links=12), result=dict(
        info=dict(model="FRITZ!Box 6591 Cable", firmware="8.02"), auth=True, hosts=23, active=19,
        wan=dict(connected=True, rx_bps=38_400_000, tx_bps=4_100_000, max_down=1_000_000_000, max_up=50_000_000, uptime=6 * 86400 + 5 * 3600),
        wlan=[dict(ssid=N("Heimnetz"), channel="36", enabled=True)])))
    swports = []
    live = {1: (46e6, 6e6), 3: (12e6, 2e6), 5: (8e6, 22e6), 7: (0, 0), 9: (24e6, 1e6)}
    for no in range(1, 29):
        up = no in live
        rx, tx = live.get(no, (None, None))
        swports.append(dict(port_no=no, ifindex=no, name=str(no), alias="", oper="up" if up else "down", admin="up", speed=1000 if up else 0,
                            in_bps=round(tx) if up else None, out_bps=round(rx) if up else None, macs=["x"] * (12 if no == 1 else 1) if up else [], lldp=None))
    swi = integ("snmp", N("Switch Keller"), "192.0.2.2", sw["id"], dict(result=dict(info=dict(name=N("Switch Keller"), descr="XGS1935-28", uptime=12 * 86400),
                                                                                    ports=swports, fdb_size=27)))
    pvi = integ("proxmox", "Proxmox", "192.0.2.10", pve["id"], dict(summary=dict(new=0, links=3), result=dict(
        info=dict(version="9.1.4", nodes=1), nodes=[dict(name="pve", ip="192.0.2.10", online=True)], guests=3, running=3,
        rates={"02:00:5E:00:00:20": [2_400_000, 900_000], "02:00:5E:00:00:22": [300_000, 150_000]})))
    asi = integ("asuswrt", "ASUS EBM68", "192.0.2.3", mesh["id"], dict(summary=dict(new=0, links=7), result=dict(
        info=dict(model="EBM68", firmware="3.0.0.6.102", ip="192.0.2.3"), clients=7, online=6, wlan=7,
        nodes=[dict(name=N("EBM68 Wohnzimmer"), model="EBM68", ip="192.0.2.3", online=True, wired_backhaul=True),
               dict(name=N("EBM68 Büro"), model="EBM68", ip="192.0.2.4", online=True, wired_backhaul=False)],
        traffic={"wan": dict(name="WAN", rx_bps=38_000_000, tx_bps=4_000_000, rx_total=812e9, tx_total=96e9),
                 "lan": dict(name="LAN", rx_bps=3_000_000, tx_bps=30_000_000, rx_total=101e9, tx_total=640e9),
                 "wl0": dict(name="2,4 GHz", rx_bps=200_000, tx_bps=900_000, rx_total=4e9, tx_total=21e9),
                 "wl1": dict(name="5 GHz-1", rx_bps=1_800_000, tx_bps=26_000_000, rx_total=60e9, tx_total=480e9)},
        analyzer=dict(clients=[dict(mac="02:00:5E:00:01:67", rx=11_200_000_000, tx=263_000_000), dict(mac="02:00:5E:00:01:65", rx=4_800_000_000, tx=610_000_000),
                               dict(mac="02:00:5E:00:01:66", rx=2_500_000_000, tx=470_000_000), dict(mac="02:00:5E:00:01:68", rx=900_000_000, tx=120_000_000),
                               dict(mac="02:00:5E:00:01:6B", rx=120_000_000, tx=40_000_000)], wan_hours=[], source="getAppTraffic", ts=time.time()),
)))
    # Messwerte: WAN, Ports, Antwortzeiten der letzten 2 Tage
    for i in range(0, 2 * 86400, 300):
        ts = t - 2 * 86400 + i
        day = 0.55 + 0.45 * math.sin((ts % 86400) / 86400 * 2 * math.pi - 1.9)
        vals = {f"i{fbi}:wan:rx": max(1e6, day * 60e6 * (0.6 + 0.8 * random.random())), f"i{fbi}:wan:tx": max(2e5, day * 6e6 * (0.5 + random.random())),
                f"i{asi}:wan:rx": max(1e6, day * 58e6 * (0.6 + 0.8 * random.random())), f"i{asi}:wan:tx": max(2e5, day * 6e6 * (0.5 + random.random()))}
        for no, (rx, tx) in live.items():
            vals[f"i{swi}:port:{no}:rx"] = max(0, tx * day * (0.5 + random.random()))
            vals[f"i{swi}:port:{no}:tx"] = max(0, rx * day * (0.5 + random.random()))
        for d_, base in ((fb, 1.2), (sw, 0.8), (mesh, 2.4), (mesh2, 6.5), (pve, 0.6), (nas, 0.9)):
            vals[f"d{d_['id']}:rtt"] = base * (0.7 + 0.6 * random.random()) + (8 if random.random() < 0.01 else 0)
        metrics.put(c, pid, vals, ts=ts)
print(json.dumps(dict(pid=pid, switch=sw["id"], fritz=fb["id"])))
