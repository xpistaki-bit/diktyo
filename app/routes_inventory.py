"""API: Geräte, Standorte, VLANs, Subnetze, Konflikte und Ausgabe eines Profils."""
import re

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from . import catalog, export, inventory, ipam
from .auth import lang_of, profile_access, require_user, text, touch
from .db import audit, db

router = APIRouter(prefix="/api/profiles/{pid}")


def _fname(name, suffix):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") + suffix


# ------------------------------------------------------------ Geräte
@router.get("/devices")
def devices(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(devices=inventory.list_devices(c, pid))


@router.post("/devices")
def device_create(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        did = inventory.save_device(c, pid, body)
        audit(c, "device.create", user["id"], pid, dict(id=did, name=body.get("name")))
        touch(c, pid, user)
        return inventory.device_detail(c, pid, did)


@router.get("/devices/{did}")
def device_get(pid: int, did: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return inventory.device_detail(c, pid, did)


@router.put("/devices/{did}")
def device_update(pid: int, did: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        old = c.execute("SELECT name FROM devices WHERE id=? AND profile_id=?", (did, pid)).fetchone()
        if not old:
            raise HTTPException(404, "Gerät nicht gefunden")
        inventory.save_device(c, pid, body, did)
        if str(body.get("name") or "").strip()[:120] != old["name"]:  # selbst vergebener Name: Integrationen überschreiben ihn nicht mehr
            inventory.lock_name(c, did)
        audit(c, "device.update", user["id"], pid, dict(id=did, name=body.get("name")))
        touch(c, pid, user)
        return inventory.device_detail(c, pid, did)


@router.delete("/devices/{did}")
def device_delete(pid: int, did: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        r = c.execute("SELECT name FROM devices WHERE id=? AND profile_id=?", (did, pid)).fetchone()
        if not r:
            raise HTTPException(404, "Gerät nicht gefunden")
        c.execute("DELETE FROM devices WHERE id=?", (did,))
        audit(c, "device.delete", user["id"], pid, dict(id=did, name=r["name"]))
        touch(c, pid, user)
    return dict(ok=True)


@router.get("/devices/{did}/ports")
def device_ports(pid: int, did: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(ports=inventory.ports_of(c, pid, did))


# ------------------------------------------------------------ Standorte
def _locations(c, pid):
    paths = inventory.location_paths(c, pid)
    n = {r["location_id"]: r["n"] for r in c.execute("SELECT location_id, COUNT(*) AS n FROM devices WHERE profile_id=? GROUP BY location_id", (pid,))}
    rows = [dict(id=r["id"], name=r["name"], parent_id=r["parent_id"], path=paths.get(r["id"], r["name"]), devices=n.get(r["id"], 0))
            for r in c.execute("SELECT * FROM locations WHERE profile_id=?", (pid,))]
    return sorted(rows, key=lambda x: x["path"].lower())


def _location_body(c, pid, body, lid=None):
    name = text(body, "name", 80)
    if not name:
        raise HTTPException(400, "Name fehlt")
    parent = inventory.check_location(c, pid, body.get("parent_id"))
    if lid and parent:  # kein Standort darf in sich selbst oder einem eigenen Unterstandort liegen
        cur, seen = parent, set()
        while cur and cur not in seen:
            if cur == lid:
                raise HTTPException(400, "Ein Standort kann nicht in sich selbst liegen")
            seen.add(cur)
            r = c.execute("SELECT parent_id FROM locations WHERE id=?", (cur,)).fetchone()
            cur = r["parent_id"] if r else None
    return name, parent


@router.get("/locations")
def locations(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(locations=_locations(c, pid))


@router.post("/locations")
def location_create(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        name, parent = _location_body(c, pid, body)
        c.execute("INSERT INTO locations(profile_id, parent_id, name) VALUES(?,?,?)", (pid, parent, name))
        touch(c, pid, user)
        return dict(locations=_locations(c, pid))


@router.put("/locations/{lid}")
def location_update(pid: int, lid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        name, parent = _location_body(c, pid, body, lid)
        if not c.execute("UPDATE locations SET name=?, parent_id=? WHERE id=? AND profile_id=?", (name, parent, lid, pid)).rowcount:
            raise HTTPException(404, "Standort nicht gefunden")
        touch(c, pid, user)
        return dict(locations=_locations(c, pid))


@router.delete("/locations/{lid}")
def location_delete(pid: int, lid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        r = c.execute("SELECT parent_id FROM locations WHERE id=? AND profile_id=?", (lid, pid)).fetchone()
        if not r:
            raise HTTPException(404, "Standort nicht gefunden")
        # Unterstandorte und Geräte rücken eine Ebene nach oben
        c.execute("UPDATE locations SET parent_id=? WHERE parent_id=?", (r["parent_id"], lid))
        c.execute("UPDATE devices SET location_id=? WHERE location_id=?", (r["parent_id"], lid))
        c.execute("DELETE FROM locations WHERE id=?", (lid,))
        touch(c, pid, user)
        return dict(locations=_locations(c, pid))


# ------------------------------------------------------------ VLANs
def _vlans(c, pid):
    subs = {}
    for s in c.execute("SELECT vlan_id, cidr FROM subnets WHERE profile_id=? AND vlan_id IS NOT NULL", (pid,)):
        subs.setdefault(s["vlan_id"], []).append(s["cidr"])
    from .vlanplan import color_of
    return [dict(id=r["id"], vid=r["vid"], name=r["name"], description=r["description"], subnets=subs.get(r["id"], []), color=color_of(r),
                 planned=bool(r["planned"])) for r in c.execute("SELECT * FROM vlans WHERE profile_id=? ORDER BY vid", (pid,))]


def _vlan_save(c, pid, body, vid_id=None):
    v = ipam.clean_vlan(body)
    dup = c.execute("SELECT id FROM vlans WHERE profile_id=? AND vid=?", (pid, v["vid"])).fetchone()
    if dup and dup["id"] != vid_id:
        raise HTTPException(409, f"VLAN {v['vid']} gibt es schon")
    import re as _re
    color = str(body.get("color") or "").strip()
    color = color if _re.fullmatch(r"#[0-9A-Fa-f]{6}", color) else ""
    if vid_id:
        if not c.execute("UPDATE vlans SET vid=?, name=?, description=?, color=? WHERE id=? AND profile_id=?",
                         (v["vid"], v["name"], v["description"], color, vid_id, pid)).rowcount:
            raise HTTPException(404, "VLAN nicht gefunden")
    else:
        from .vlanplan import plan_info
        planned = 1 if body.get("planned") and plan_info(c, pid) else 0
        c.execute("INSERT INTO vlans(profile_id, vid, name, description, color, planned) VALUES(?,?,?,?,?,?)",
                  (pid, v["vid"], v["name"], v["description"], color, planned))


@router.get("/vlans")
def vlans(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(vlans=_vlans(c, pid))


@router.post("/vlans")
def vlan_create(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        _vlan_save(c, pid, body)
        touch(c, pid, user)
        return dict(vlans=_vlans(c, pid))


@router.put("/vlans/{vid_id}")
def vlan_update(pid: int, vid_id: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        _vlan_save(c, pid, body, vid_id)
        touch(c, pid, user)
        return dict(vlans=_vlans(c, pid))


@router.delete("/vlans/{vid_id}")
def vlan_delete(pid: int, vid_id: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        if not c.execute("DELETE FROM vlans WHERE id=? AND profile_id=?", (vid_id, pid)).rowcount:
            raise HTTPException(404, "VLAN nicht gefunden")
        touch(c, pid, user)
        return dict(vlans=_vlans(c, pid))


# ------------------------------------------------------------ Subnetze
@router.get("/subnets")
def subnets(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(subnets=ipam.list_subnets(c, pid), conflicts=ipam.conflicts(c, pid))


@router.post("/subnets")
def subnet_create(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        s = ipam.clean_subnet(c, pid, body)
        if c.execute("SELECT 1 FROM subnets WHERE profile_id=? AND cidr=?", (pid, s["cidr"])).fetchone():
            raise HTTPException(409, f"Das Subnetz {s['cidr']} gibt es schon")
        c.execute("""INSERT INTO subnets(profile_id, vlan_id, cidr, name, gateway, dns, dhcp_start, dhcp_end, description)
                     VALUES(?,?,?,?,?,?,?,?,?)""", (pid, s["vlan_id"], s["cidr"], s["name"], s["gateway"], s["dns"], s["dhcp_start"],
                                                    s["dhcp_end"], s["description"]))
        ipam.reclassify(c, pid)
        touch(c, pid, user)
        return dict(subnets=ipam.list_subnets(c, pid), conflicts=ipam.conflicts(c, pid))


@router.get("/subnets/{sid}")
def subnet_get(pid: int, sid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return ipam.subnet_detail(c, pid, sid)


@router.put("/subnets/{sid}")
def subnet_update(pid: int, sid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        s = ipam.clean_subnet(c, pid, body)
        dup = c.execute("SELECT id FROM subnets WHERE profile_id=? AND cidr=?", (pid, s["cidr"])).fetchone()
        if dup and dup["id"] != sid:
            raise HTTPException(409, f"Das Subnetz {s['cidr']} gibt es schon")
        if not c.execute("""UPDATE subnets SET vlan_id=?, cidr=?, name=?, gateway=?, dns=?, dhcp_start=?, dhcp_end=?, description=?
                            WHERE id=? AND profile_id=?""", (s["vlan_id"], s["cidr"], s["name"], s["gateway"], s["dns"], s["dhcp_start"],
                                                             s["dhcp_end"], s["description"], sid, pid)).rowcount:
            raise HTTPException(404, "Subnetz nicht gefunden")
        ipam.reclassify(c, pid)
        touch(c, pid, user)
        return dict(subnets=ipam.list_subnets(c, pid), conflicts=ipam.conflicts(c, pid))


@router.post("/hints/ack")
def hints_ack(pid: int, body: dict = Body(...), user=Depends(require_user)):
    """Hinweise als gelesen markieren (ack=true) oder wieder einblenden (ack=false)."""
    import json as _json
    with db() as c:
        p, _ = profile_access(c, user, pid, "edit")
        st = _json.loads(p["settings"] or "{}")
        keys = set(st.get("ack_hints", []))
        sel = [str(k) for k in body.get("keys") or []]
        keys = keys | set(sel) if body.get("ack", True) else keys - set(sel)
        current = {x["key"] for x in ipam.conflicts(c, pid)}
        st["ack_hints"] = sorted(keys & current)  # erledigte Hinweise nicht ewig mitschleppen
        c.execute("UPDATE profiles SET settings=? WHERE id=?", (_json.dumps(st, ensure_ascii=False), pid))
        return dict(subnets=ipam.list_subnets(c, pid), conflicts=ipam.conflicts(c, pid))


@router.delete("/subnets/{sid}")
def subnet_delete(pid: int, sid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        if not c.execute("DELETE FROM subnets WHERE id=? AND profile_id=?", (sid, pid)).rowcount:
            raise HTTPException(404, "Subnetz nicht gefunden")
        ipam.reclassify(c, pid)
        touch(c, pid, user)
        return dict(subnets=ipam.list_subnets(c, pid), conflicts=ipam.conflicts(c, pid))


# ------------------------------------------------------------ Ausgabe
@router.get("/export/devices.csv")
def export_devices(pid: int, request: Request, user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid)
        data = export.devices_csv(c, pid, lang_of(request))
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(p["name"], "-geraete.csv")}"'})


@router.get("/export/ips.csv")
def export_ips(pid: int, request: Request, user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid)
        data = export.ips_csv(c, pid, lang_of(request))
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(p["name"], "-ip-adressen.csv")}"'})


@router.get("/export/report.pdf")
def export_pdf(pid: int, request: Request, sections: str = "", user=Depends(require_user)):
    secs = [s for s in sections.split(",") if s in export.SECTIONS] or list(export.SECTIONS)
    with db() as c:
        p, _ = profile_access(c, user, pid)
        data = export.profile_pdf(c, pid, secs, lang_of(request))
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_fname(p["name"], "-netzwerk.pdf")}"'})


@router.get("/export/labels")
def labels_info(pid: int, request: Request, user=Depends(require_user)):
    """Formate und Vorschlag für die Adresse im QR-Code (Einstellung „Adresse der Weboberfläche“ oder die aufgerufene)."""
    from . import labels, mailer
    with db() as c:
        profile_access(c, user, pid)
        app_url = (mailer.smtp_config(c).get("app_url") or "").rstrip("/")
    return dict(formats=labels.formats(lang_of(request)), base=app_url, configured=bool(app_url))


@router.get("/export/labels.pdf")
def labels_pdf(pid: int, request: Request, ids: str = "", fmt: str = "a4-70x37", fields: str = "ip,mac,loc", base: str = "", skip: int = 0,
               outline: int = 0, user=Depends(require_user)):
    from . import labels, mailer
    with db() as c:
        p, _ = profile_access(c, user, pid)
        base = (base or mailer.smtp_config(c).get("app_url") or str(request.base_url)).strip()
        try:
            data = labels.render(c, pid, [int(x) for x in ids.split(",") if x.strip().isdigit()], fmt,
                                 [f for f in fields.split(",") if f in labels.FIELDS], base, skip, bool(outline), lang_of(request))
        except labels.LabelError as ex:
            raise HTTPException(400, str(ex))
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_fname(p["name"], "-qr-etiketten.pdf")}"'})


@router.get("/meta")
def meta(pid: int, request: Request, user=Depends(require_user)):
    """Auswahllisten für die Oberfläche."""
    lang = lang_of(request)
    with db() as c:
        profile_access(c, user, pid)
    return dict(types=[dict(key=k, name=catalog.type_name(k, lang)) for k in catalog.sorted_types(lang)], media=list(catalog.MEDIA),
                port_kinds=list(catalog.PORT_KINDS), sections=list(export.SECTIONS))


# ------------------------------------------------------------ Topologie und Schnell-Ping
@router.get("/topology")
def topology_get(pid: int, expanded: str = "", traffic: int = 0, user=Depends(require_user)):
    from . import topology
    with db() as c:
        profile_access(c, user, pid)
        return topology.build(c, pid, [x for x in expanded.split(",") if x], traffic=bool(traffic))


@router.put("/topology/positions")
def topology_positions(pid: int, body: dict = Body(...), user=Depends(require_user)):
    from . import topology
    with db() as c:
        profile_access(c, user, pid, "edit")
        try:
            topology.save_positions(c, pid, body.get("positions") or {})
        except (TypeError, ValueError):
            raise HTTPException(400, "Ungültige Positionen")
    return dict(ok=True)


@router.delete("/topology/positions")
def topology_positions_reset(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        c.execute("DELETE FROM topo_positions WHERE profile_id=?", (pid,))
        audit(c, "topology.reset_layout", user["id"], pid)
    return dict(ok=True)


@router.post("/ping")
def quick_ping(pid: int, body: dict = Body(default={}), user=Depends(require_user)):
    """Pingt sofort die angegebenen (sonst alle bestätigten) Geräte und aktualisiert ihren Online-Status."""
    import asyncio
    import json as _json

    from . import monitor
    from .db import now
    from .scan import runner
    ids = {int(x) for x in body.get("device_ids") or []}
    with db() as c:
        profile_access(c, user, pid)
        rows = c.execute("""SELECT d.id, d.data, a.address FROM devices d JOIN ip_addresses a ON a.device_id=d.id
                            WHERE d.profile_id=? AND d.status='confirmed'""", (pid,)).fetchall()
    targets = []
    for r in rows:
        if ids and r["id"] not in ids:
            continue
        ports = (_json.loads(r["data"] or "{}").get("seen") or {}).get("ports") or []
        targets.append((r["id"], r["address"], ports[0] if ports else None))
    from .scan import discover
    can_ping = asyncio.run(discover.ping_works())
    full = asyncio.run(monitor._check(targets)) if targets else {}
    # Wer online war und in der Lastspitze nicht antwortete, wird einzeln mit mehr Geduld nachgeprüft
    with db() as c:
        was = {r["id"]: r["online"] for r in c.execute("SELECT id, online FROM devices WHERE profile_id=?", (pid,))}
    again = [tg for tg in targets if not full.get(tg[0], (True,))[0] and was.get(tg[0]) == 1]
    if again:
        for did, res in asyncio.run(monitor.recheck(again)).items():
            if res[0]:
                full[did] = res
    res = {did: ok for did, (ok, _) in full.items()}
    rtt = {did: r for did, (ok, r) in full.items() if ok and r is not None}
    ts = now()
    with db() as c:
        others = monitor.seen_by_others(c, pid, max(600, 3 * monitor.settings_of(pid)["interval_s"]))
        for did, ok in res.items():
            if ok or (can_ping and did not in others):  # von anderer Quelle gesehen bzw. Ping hier nicht erlaubt: nicht offline setzen
                runner._set_online(c, did, 1 if ok else 0, ts, "ping")
    with db() as c:
        from . import metrics
        metrics.put(c, pid, {f"d{did}:rtt": v for did, v in rtt.items()}, unit="ms")
    return dict(results={str(k): v for k, v in res.items()}, rtt={str(k): v for k, v in rtt.items()}, checked=len(res), online=sum(res.values()),
                ping_unavailable=not can_ping)
