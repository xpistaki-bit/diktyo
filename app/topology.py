"""Topologie: Baum aus den Verbindungen (Uplinks) mit Positionen für Oberfläche und PDF.

Darstellung von links nach rechts: Spalte = Tiefe im Baum, Zeile = Reihenfolge der Blätter. WLAN-Clients und VMs eines
Geräts werden ab einer Mindestzahl zu einer Gruppe zusammengefasst, die sich aufklappen lässt.
"""
from . import inventory

COLW, ROWH = 280, 64           # Abstand der Spalten und Zeilen (Einheiten der Zeichnung)
NODE_W, NODE_H = 220, 48
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
                    ports_total=d["ports_total"], ports_used=d["ports_used"], location=d["location"], depth=depth)

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
    width = (max([n["depth"] for n in nodes] or [0]) + 1) * COLW
    height = max(row[0], 1) * ROWH
    return dict(nodes=nodes, edges=edges, width=width, height=height, node_w=NODE_W, node_h=NODE_H,
                loose_from=(loose_start + 0.6) * ROWH if loose else None, total=len(devs))
