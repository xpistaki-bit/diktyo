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
        touch(c, pid)
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
        if not c.execute("SELECT 1 FROM devices WHERE id=? AND profile_id=?", (did, pid)).fetchone():
            raise HTTPException(404, "Gerät nicht gefunden")
        inventory.save_device(c, pid, body, did)
        audit(c, "device.update", user["id"], pid, dict(id=did, name=body.get("name")))
        touch(c, pid)
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
        touch(c, pid)
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
        touch(c, pid)
        return dict(locations=_locations(c, pid))


@router.put("/locations/{lid}")
def location_update(pid: int, lid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        name, parent = _location_body(c, pid, body, lid)
        if not c.execute("UPDATE locations SET name=?, parent_id=? WHERE id=? AND profile_id=?", (name, parent, lid, pid)).rowcount:
            raise HTTPException(404, "Standort nicht gefunden")
        touch(c, pid)
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
        touch(c, pid)
        return dict(locations=_locations(c, pid))


# ------------------------------------------------------------ VLANs
def _vlans(c, pid):
    subs = {}
    for s in c.execute("SELECT vlan_id, cidr FROM subnets WHERE profile_id=? AND vlan_id IS NOT NULL", (pid,)):
        subs.setdefault(s["vlan_id"], []).append(s["cidr"])
    return [dict(id=r["id"], vid=r["vid"], name=r["name"], description=r["description"], subnets=subs.get(r["id"], []))
            for r in c.execute("SELECT * FROM vlans WHERE profile_id=? ORDER BY vid", (pid,))]


def _vlan_save(c, pid, body, vid_id=None):
    v = ipam.clean_vlan(body)
    dup = c.execute("SELECT id FROM vlans WHERE profile_id=? AND vid=?", (pid, v["vid"])).fetchone()
    if dup and dup["id"] != vid_id:
        raise HTTPException(409, f"VLAN {v['vid']} gibt es schon")
    if vid_id:
        if not c.execute("UPDATE vlans SET vid=?, name=?, description=? WHERE id=? AND profile_id=?",
                         (v["vid"], v["name"], v["description"], vid_id, pid)).rowcount:
            raise HTTPException(404, "VLAN nicht gefunden")
    else:
        c.execute("INSERT INTO vlans(profile_id, vid, name, description) VALUES(?,?,?,?)", (pid, v["vid"], v["name"], v["description"]))


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
        touch(c, pid)
        return dict(vlans=_vlans(c, pid))


@router.put("/vlans/{vid_id}")
def vlan_update(pid: int, vid_id: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        _vlan_save(c, pid, body, vid_id)
        touch(c, pid)
        return dict(vlans=_vlans(c, pid))


@router.delete("/vlans/{vid_id}")
def vlan_delete(pid: int, vid_id: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        if not c.execute("DELETE FROM vlans WHERE id=? AND profile_id=?", (vid_id, pid)).rowcount:
            raise HTTPException(404, "VLAN nicht gefunden")
        touch(c, pid)
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
        c.execute("""INSERT INTO subnets(profile_id, vlan_id, cidr, name, gateway, dns, dhcp_start, dhcp_end, description)
                     VALUES(?,?,?,?,?,?,?,?,?)""", (pid, s["vlan_id"], s["cidr"], s["name"], s["gateway"], s["dns"], s["dhcp_start"],
                                                    s["dhcp_end"], s["description"]))
        touch(c, pid)
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
        if not c.execute("""UPDATE subnets SET vlan_id=?, cidr=?, name=?, gateway=?, dns=?, dhcp_start=?, dhcp_end=?, description=?
                            WHERE id=? AND profile_id=?""", (s["vlan_id"], s["cidr"], s["name"], s["gateway"], s["dns"], s["dhcp_start"],
                                                             s["dhcp_end"], s["description"], sid, pid)).rowcount:
            raise HTTPException(404, "Subnetz nicht gefunden")
        touch(c, pid)
        return dict(subnets=ipam.list_subnets(c, pid), conflicts=ipam.conflicts(c, pid))


@router.delete("/subnets/{sid}")
def subnet_delete(pid: int, sid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        if not c.execute("DELETE FROM subnets WHERE id=? AND profile_id=?", (sid, pid)).rowcount:
            raise HTTPException(404, "Subnetz nicht gefunden")
        touch(c, pid)
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


@router.get("/meta")
def meta(pid: int, request: Request, user=Depends(require_user)):
    """Auswahllisten für die Oberfläche."""
    lang = lang_of(request)
    with db() as c:
        profile_access(c, user, pid)
    return dict(types=[dict(key=k, name=catalog.type_name(k, lang)) for k in catalog.TYPES], media=list(catalog.MEDIA),
                port_kinds=list(catalog.PORT_KINDS), sections=list(export.SECTIONS))
