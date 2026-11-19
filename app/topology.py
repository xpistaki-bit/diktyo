"""Topologie: Baum aus den Verbindungen (Uplinks) mit Positionen für Oberfläche und PDF.

Darstellung von links nach rechts: Spalte = Tiefe im Baum, Zeile = Reihenfolge der Blätter. WLAN-Clients und VMs eines
Geräts werden ab einer Mindestzahl zu einer Gruppe zusammengefasst, die sich aufklappen lässt.
"""
from . import inventory

COLW, ROWH = 280, 64           # Abstand der Spalten und Zeilen (Einheiten der Zeichnung)
NODE_W, NODE_H = 220, 48
INET_GAP = 110                 # zusätzlicher Platz für die Traffic-Anzeige an der Internet-Leitung
COLLAPSE = {"wlan": 4, "virtual": 5}  # ab so vielen Kindern derselben Art zusammenfassen
ROOT_ORDER = ("modem", "router", "firewall", "switch", "mesh", "ap", "hypervisor", "server", "nas")


def _rank(d):
    return (ROOT_ORDER.index(d["type"]) if d["type"] in ROOT_ORDER else len(ROOT_ORDER), inventory.natural(d["name"]))


def build(c, pid, expanded=(), status="confirmed"):
    devs = {d["id"]: d for d in inventory.list_devices(c, pid, status)}
    children = {}
    for d in devs.values():
        u = d.get("uplink")
        if u and u["device_id"] in devs:
            children.setdefault(u["device_id"], []).append(d)
    roots = [d for d in devs.values() if not (d.get("uplink") and d["uplink"]["device_id"] in devs)]
    linked = [d for d in roots if children.get(d["id"])] + [d for d in roots if not children.get(d["id"]) and d["type"] in ROOT_ORDER[:5]]
    loose = [d for d in roots if d not in linked]
    expanded = {str(x) for x in expanded}

    nodes, edges = [], []
    row = [0]

    def node_of(d, depth):
        return dict(id=f"d{d['id']}", device_id=d["id"], kind="device", name=d["name"], type=d["type"], ip=(d["ips"] or [{}])[0].get("address", ""),
                    mac=d["mac"], online=d["online"], last_seen=d["last_seen"], model=" ".join(x for x in (d["manufacturer"], d["model"]) if x),
                    ports_total=d["ports_total"], ports_used=d["ports_used"], location=d["location"], depth=depth, fw_update=d.get("fw_update", False))

    def place(d, depth):
        n = node_of(d, depth)
        nodes.append(n)
        kids = sorted(children.get(d["id"], []), key=_rank)
        groups = {}
        for k in kids:
            m = k["uplink"]["medium"]
            groups.setdefault(m if m in COLLAPSE else "other", []).append(k)
        ys = []
        for k in kids:
            m = k["uplink"]["medium"]
            g = groups.get(m)
            if m in COLLAPSE and len(g) >= COLLAPSE[m] and f"{d['id']}:{m}" not in expanded:
                if k is g[0]:  # die Gruppe einmal anstelle ihrer Mitglieder
                    gid = f"g{d['id']}:{m}"
                    on = sum(1 for x in g if x["online"] == 1)
                    gn = dict(id=gid, kind="group", medium=m, parent=d["id"], count=len(g), online_count=on, depth=depth + 1,
                              names=[x["name"] for x in g][:40], x=(depth + 1) * COLW, y=row[0] * ROWH)
                    row[0] += 1
                    nodes.append(gn)
                    edges.append(dict(source=n["id"], target=gid, medium=m, label=""))
                    ys.append(gn["y"])
                continue
            child = place(k, depth + 1)
            u = k["uplink"]
            edges.append(dict(source=n["id"], target=child["id"], medium=u["medium"], label=u["port_name"] or "",
                              child_label=u["local_port_name"] or ""))
            ys.append(child["y"])
        n["x"] = depth * COLW
        if ys:
            n["y"] = (min(ys) + max(ys)) / 2
        else:
            n["y"] = row[0] * ROWH
            row[0] += 1
        n["children"] = len(kids)
        return n

    for r in sorted(linked, key=_rank):
        place(r, 0)
        row[0] += 0.4  # etwas Luft zwischen getrennten Bäumen
    loose_start = row[0]
    if loose:
        row[0] += 0.6
        for d in sorted(loose, key=_rank):
            place(d, 0)
    internet = _internet(c, pid, devs, [d for d in linked if d["type"] in ("modem", "router", "firewall")])
    if internet:
        # Internet als eigene Spalte vor dem WAN-Router; alles andere rückt eine Spalte nach rechts
        for n in nodes:
            n["x"] += COLW + INET_GAP
            n["depth"] += 1
        wan_nodes = [n for n in nodes if n.get("device_id") in internet["routers"]]
        y = (min(n["y"] for n in wan_nodes) + max(n["y"] for n in wan_nodes)) / 2 if wan_nodes else 0
        nodes.insert(0, dict(id="internet", kind="internet", name="Internet", x=0, y=y, depth=0, online=internet["connected"],
                             rx_bps=internet["rx_bps"], tx_bps=internet["tx_bps"], max_down=internet["max_down"], max_up=internet["max_up"],
                             source=internet["source"], uptime=internet["uptime"], updated=internet["updated"]))
        for n in wan_nodes:
            edges.insert(0, dict(source="internet", target=n["id"], medium="wan", label="", connected=internet["connected"],
                                 rx_bps=internet["rx_bps"], tx_bps=internet["tx_bps"]))
    width = (max([n["depth"] for n in nodes] or [0]) + 1) * COLW + (INET_GAP if internet else 0)
    height = max(row[0], 1) * ROWH
    # von Hand verschobene Knoten
    pos = {r["node"]: (r["x"], r["y"]) for r in c.execute("SELECT node, x, y FROM topo_positions WHERE profile_id=?", (pid,))}
    for n in nodes:
        if n["id"] in pos:
            n["x"], n["y"] = pos[n["id"]]
            n["pinned"] = True
    if pos:
        width = max(width, max(n["x"] for n in nodes) + COLW)
        height = max(height, max(n["y"] for n in nodes) + ROWH)
    # tatsächlich belegte Fläche (verschobene Knoten können links/oberhalb des Ursprungs liegen)
    bbox = [min([n["x"] for n in nodes] or [0]), min([n["y"] - NODE_H / 2 for n in nodes] or [0]),
            max([n["x"] + NODE_W for n in nodes] or [0]), max([n["y"] + NODE_H / 2 for n in nodes] or [0])]
    return dict(nodes=nodes, edges=edges, width=width, height=height, node_w=NODE_W, node_h=NODE_H,
                loose_from=(loose_start + 0.6) * ROWH if loose and not any(n.get("pinned") for n in nodes) else None, total=len(devs),
                pinned=sum(1 for n in nodes if n.get("pinned")), bbox=bbox)


def save_positions(c, pid, positions):
    """positions = {knoten_id: [x, y]}; null entfernt die Position eines Knotens."""
    import re
    for node, xy in list(positions.items())[:2000]:
        if not re.fullmatch(r"d\d+|g\d+:(wlan|virtual)|internet", str(node)):
            continue
        if xy is None:
            c.execute("DELETE FROM topo_positions WHERE profile_id=? AND node=?", (pid, node))
            continue
        x, y = (max(-100000.0, min(100000.0, float(v))) for v in xy[:2])
        c.execute("INSERT INTO topo_positions(profile_id, node, x, y) VALUES(?,?,?,?) "
                  "ON CONFLICT(profile_id, node) DO UPDATE SET x=excluded.x, y=excluded.y", (pid, node, x, y))


def _internet(c, pid, devs, root_routers):
    """Internet-Knoten: verbunden mit dem Gerät der FRITZ!Box-Integration bzw. dem Gateway von UniFi (mit WAN-Status und Traffic),
    sonst mit den Routern/Modems ohne Uplink (Status unbekannt)."""
    import json
    for r in c.execute("""SELECT * FROM integrations WHERE profile_id=? AND driver IN ('fritzbox','unifi','omada','mikrotik','opnsense') AND enabled=1
                          ORDER BY driver<>'fritzbox', id""", (pid,)):
        st = json.loads(r["state"] or "{}")
        wan = (st.get("result") or {}).get("wan") or {}
        target = r["device_id"]
        if wan.get("mac") and r["driver"] in ("unifi", "omada"):  # Controller: WAN hängt am Gateway, nicht am Controller selbst
            m = c.execute("SELECT i.device_id FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND i.mac=?",
                          (pid, wan["mac"])).fetchone()
            target = m["device_id"] if m else None
        if r["driver"] != "fritzbox" and not wan:
            continue
        if target in devs:
            return dict(routers={target}, connected=1 if wan.get("connected") else (0 if wan.get("connected") is False else None),
                        rx_bps=wan.get("rx_bps"), tx_bps=wan.get("tx_bps"), max_down=wan.get("max_down"), max_up=wan.get("max_up"),
                        uptime=wan.get("uptime"), source=r["name"], updated=r["last_ok"])
    if root_routers:
        return dict(routers={d["id"] for d in root_routers}, connected=None, rx_bps=None, tx_bps=None, max_down=None, max_up=None,
                    uptime=None, source="", updated=None)
    return None
