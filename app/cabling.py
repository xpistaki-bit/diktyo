"""Kabel und Patchpanels: Patchfelder, Netzwerkdosen und Kabelwege mit Kabelnummern.

Ein Kabelweg beschreibt die physische Strecke eines Anschlusses:
  Switch-Port ─(Patchkabel cable_a)─ Patchfeld-Port ─(Verlegekabel cable_b)─ Dose ─(Anschlusskabel cable_c)─ Gerät
Jeder Teil ist optional (z. B. Switch direkt auf Dose, oder Patchfeld direkt auf ein Gerät im Rack). Der Switch-Port
wird über Gerät und Portnummer referenziert, damit Kabelwege das Bearbeiten der Ports überstehen. Patchfelder und
Dosen sind keine Geräte (keine Online-Überwachung, nicht in der Topologie).

Abgleich mit dem Netz: Sind Switch-Port und Gerät eingetragen, wird mit den Verbindungen am Switch-Port verglichen
(aus Integrationen, Scan oder von Hand) – „ok“, „mismatch“ (laut Netz hängt dort etwas anderes) oder „unknown“.
"""
from .db import now

KINDS = ("panel", "outlet")
MAX_PORTS = 96


class CablingError(Exception):
    pass


def _txt(v, n=60):
    return str(v or "").strip()[:n]


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        raise CablingError("Ungültige Zahl")


# ------------------------------------------------------------ Patchfelder und Dosen
def save_panel(c, pid, body, panel_id=None):
    kind = body.get("kind") if body.get("kind") in KINDS else "panel"
    name = _txt(body.get("name"), 80)
    if not name:
        raise CablingError("Name fehlt")
    ports = _int(body.get("ports")) or (24 if kind == "panel" else 2)
    if not 1 <= ports <= MAX_PORTS:
        raise CablingError(f"Ports: 1 bis {MAX_PORTS}")
    loc = _int(body.get("location_id"))
    if loc and not c.execute("SELECT 1 FROM locations WHERE id=? AND profile_id=?", (loc, pid)).fetchone():
        loc = None
    vals = (kind, name, loc, ports, _txt(body.get("note"), 500))
    if panel_id:
        row = _panel(c, pid, panel_id)
        used = [r["p"] for r in c.execute("SELECT panel_port AS p FROM cable_runs WHERE panel_id=? UNION SELECT outlet_port FROM cable_runs WHERE outlet_id=?",
                                           (panel_id, panel_id)) if r["p"]]
        if used and max(used) > ports:
            raise CablingError(f"Port {max(used)} ist noch belegt – erst den Kabelweg ändern")
        if row["kind"] != kind and c.execute("SELECT 1 FROM cable_runs WHERE panel_id=? OR outlet_id=?", (panel_id, panel_id)).fetchone():
            raise CablingError("Art lässt sich nur ändern, solange keine Kabelwege daran hängen")
        c.execute("UPDATE patch_panels SET kind=?, name=?, location_id=?, ports=?, note=? WHERE id=?", vals + (panel_id,))
        return panel_id
    return c.execute("INSERT INTO patch_panels(profile_id, kind, name, location_id, ports, note, created) VALUES(?,?,?,?,?,?,?)",
                     (pid,) + vals + (now(),)).lastrowid


def _panel(c, pid, panel_id):
    r = c.execute("SELECT * FROM patch_panels WHERE id=? AND profile_id=?", (panel_id, pid)).fetchone()
    if not r:
        raise CablingError("Patchfeld/Dose nicht gefunden")
    return r


def delete_panel(c, pid, panel_id):
    _panel(c, pid, panel_id)
    c.execute("UPDATE cable_runs SET panel_id=NULL, panel_port=NULL WHERE panel_id=?", (panel_id,))
    c.execute("UPDATE cable_runs SET outlet_id=NULL, outlet_port=NULL WHERE outlet_id=?", (panel_id,))
    c.execute("DELETE FROM patch_panels WHERE id=?", (panel_id,))
    # Kabelwege, die danach leer sind, mit entfernen
    c.execute("""DELETE FROM cable_runs WHERE profile_id=? AND switch_id IS NULL AND panel_id IS NULL AND outlet_id IS NULL AND device_id IS NULL""", (pid,))


# ------------------------------------------------------------ Kabelwege
def save_run(c, pid, body, run_id=None):
    if run_id and not c.execute("SELECT 1 FROM cable_runs WHERE id=? AND profile_id=?", (run_id, pid)).fetchone():
        raise CablingError("Kabelweg nicht gefunden")
    dev = lambda k: _int(body.get(k))  # noqa: E731
    sw, port, did = dev("switch_id"), dev("switch_port"), dev("device_id")
    pan, pport, out, oport = dev("panel_id"), dev("panel_port"), dev("outlet_id"), dev("outlet_port")
    for x in (sw, did):
        if x and not c.execute("SELECT 1 FROM devices WHERE id=? AND profile_id=?", (x, pid)).fetchone():
            raise CablingError("Gerät nicht gefunden")
    if sw:
        if not port:
            raise CablingError("Bitte den Switch-Port wählen")
        if not c.execute("SELECT 1 FROM interfaces WHERE device_id=? AND role='port' AND port_no=?", (sw, port)).fetchone():
            raise CablingError(f"Port {port} gibt es an diesem Gerät nicht")
    else:
        port = None
    for pnl, pp, kind, label in ((pan, pport, "panel", "Patchfeld"), (out, oport, "outlet", "Dose")):
        if not pnl:
            continue
        r = _panel(c, pid, pnl)
        if r["kind"] != kind:
            raise CablingError(f"„{r['name']}“ ist kein {label}")
        if not pp or not 1 <= pp <= r["ports"]:
            raise CablingError(f"{label} „{r['name']}“: Port 1 bis {r['ports']} wählen")
    pport = pport if pan else None
    oport = oport if out else None
    if not any((sw, pan, out, did)):
        raise CablingError("Mindestens Switch-Port, Patchfeld, Dose oder Gerät angeben")
    # jeder Port nur in einem Kabelweg
    other = " AND id<>?" if run_id else ""
    extra = (run_id,) if run_id else ()
    checks = [("switch_id=? AND switch_port=?", (sw, port), "Dieser Switch-Port"), ("panel_id=? AND panel_port=?", (pan, pport), "Dieser Patchfeld-Port"),
              ("outlet_id=? AND outlet_port=?", (out, oport), "Dieser Dosen-Anschluss")]
    for cond, args, label in checks:
        if args[0] and c.execute(f"SELECT 1 FROM cable_runs WHERE profile_id=? AND {cond}{other}", (pid, *args, *extra)).fetchone():
            raise CablingError(f"{label} ist schon in einem anderen Kabelweg eingetragen")
    vals = (sw, port, pan, pport, out, oport, did, _txt(body.get("cable_a")), _txt(body.get("cable_b")), _txt(body.get("cable_c")),
            _txt(body.get("note"), 500), now())
    if run_id:
        c.execute("""UPDATE cable_runs SET switch_id=?, switch_port=?, panel_id=?, panel_port=?, outlet_id=?, outlet_port=?, device_id=?,
                     cable_a=?, cable_b=?, cable_c=?, note=?, updated=? WHERE id=?""", vals + (run_id,))
        return run_id
    return c.execute("""INSERT INTO cable_runs(profile_id, switch_id, switch_port, panel_id, panel_port, outlet_id, outlet_port, device_id,
                        cable_a, cable_b, cable_c, note, updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (pid,) + vals).lastrowid


def delete_run(c, pid, run_id):
    c.execute("DELETE FROM cable_runs WHERE id=? AND profile_id=?", (run_id, pid))


def _peers(c, did, port_no):
    from .dashboard import _port_peer
    return _port_peer(c, did, port_no)["peers"]


def overview(c, pid):
    """Alles für den Reiter Verkabelung: Patchfelder/Dosen mit Belegung, Kabelwege mit Namen und Abgleich, Auswahllisten."""
    from .inventory import location_paths
    locs = location_paths(c, pid)
    names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM devices WHERE profile_id=?", (pid,))}
    panels = {r["id"]: dict(id=r["id"], kind=r["kind"], name=r["name"], location_id=r["location_id"], location=locs.get(r["location_id"], ""),
                            ports=r["ports"], note=r["note"], used={})
              for r in c.execute("SELECT * FROM patch_panels WHERE profile_id=? ORDER BY kind, name COLLATE NOCASE", (pid,))}
    pnames = {}
    for r in c.execute("SELECT device_id, port_no, name FROM interfaces WHERE role='port' AND device_id IN (SELECT id FROM devices WHERE profile_id=?)", (pid,)):
        pnames[(r["device_id"], r["port_no"])] = r["name"]
    runs = []
    for r in c.execute("SELECT * FROM cable_runs WHERE profile_id=? ORDER BY id", (pid,)):
        x = dict(r)
        x["switch"] = names.get(r["switch_id"], "")
        x["port_name"] = pnames.get((r["switch_id"], r["switch_port"]), str(r["switch_port"] or ""))
        x["panel"] = panels[r["panel_id"]]["name"] if r["panel_id"] in panels else ""
        x["outlet"] = panels[r["outlet_id"]]["name"] if r["outlet_id"] in panels else ""
        x["device"] = names.get(r["device_id"], "")
        peers = _peers(c, r["switch_id"], r["switch_port"]) if r["switch_id"] else []
        x["peers"] = peers
        x["check"] = "unknown" if not (r["switch_id"] and r["device_id"] and peers) else \
            "ok" if any(p["id"] == r["device_id"] for p in peers) else "mismatch"
        for pnl, pp in ((r["panel_id"], r["panel_port"]), (r["outlet_id"], r["outlet_port"])):
            if pnl in panels and pp:
                panels[pnl]["used"][str(pp)] = dict(run=r["id"], check=x["check"], label=_short(x))
        runs.append(x)
    switches = []
    for d in c.execute("""SELECT d.id, d.name FROM devices d WHERE d.profile_id=? AND d.status='confirmed'
                          AND EXISTS(SELECT 1 FROM interfaces i WHERE i.device_id=d.id AND i.role='port') ORDER BY d.name COLLATE NOCASE""", (pid,)):
        ports = [dict(no=p["port_no"], name=p["name"] or str(p["port_no"]), peers=[x["name"] for x in _peers(c, d["id"], p["port_no"])])
                 for p in c.execute("SELECT port_no, name FROM interfaces WHERE device_id=? AND role='port' ORDER BY port_no", (d["id"],))]
        switches.append(dict(id=d["id"], name=d["name"], ports=ports))
    devices = [dict(id=r["id"], name=r["name"]) for r in
               c.execute("SELECT id, name FROM devices WHERE profile_id=? AND status='confirmed' ORDER BY name COLLATE NOCASE", (pid,))]
    return dict(panels=list(panels.values()), runs=runs, switches=switches, devices=devices)


def _short(x):
    parts = []
    if x["switch"]:
        parts.append(f"{x['switch']} · Port {x['port_name']}")
    if x["device"]:
        parts.append(x["device"])
    return " → ".join(parts)


def for_device(c, pid, did):
    """Kabelwege, in denen ein Gerät als Endgerät oder als Switch vorkommt."""
    return [r for r in overview(c, pid)["runs"] if did in (r["device_id"], r["switch_id"])]


def pdf_rows(c, pid, lang="de"):
    o = overview(c, pid)
    rows = []
    for r in sorted(o["runs"], key=lambda x: (x["switch"].lower(), x["switch_port"] or 0, x["panel"].lower(), x["panel_port"] or 0)):
        rows.append([f"{r['switch']} · {r['port_name']}" if r["switch"] else "", r["cable_a"],
                     f"{r['panel']} · {r['panel_port']}" if r["panel"] else "", r["cable_b"],
                     f"{r['outlet']} · {r['outlet_port']}" if r["outlet"] else "", r["cable_c"], r["device"]])
    return rows
