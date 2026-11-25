"""Grundriss/Raumplan und Rack-Ansicht je Standort.

Ein Standort ist entweder ein Bereich (Haus, Etage, Raum – kind „area“) oder ein Rack (kind „rack“, mit Höheneinheiten).

Grundriss (Bereich): wahlweise ein hochgeladenes Bild (PNG, JPEG, WebP, GIF – kein SVG, damit kein Skript mitkommt)
oder ein leeres Raster mit wählbarem Seitenverhältnis. Darauf liegen Geräte, Patchfelder/Dosen (als Punkt) und die
direkten Unterstandorte (als Rechteck, z. B. Räume oder ein Rack). Koordinaten sind relativ (0…1), damit sie zum Bild
in jeder Größe passen. Wird ein Gerät ohne Standort platziert, bekommt es diesen Standort.

Rack (Vorderansicht): Geräte, Patchfelder und Sonstiges (USV, Blende, Ablage …) belegen Höheneinheiten; gezählt wird
von unten (HE 1 unten), u ist die unterste belegte Einheit. Ein Gerät oder Patchfeld steckt in höchstens einem Rack;
beim Einbau bekommt es das Rack als Standort.
"""
import base64
import json

from .db import now
from .pdf import FONT, MONO, esc

KINDS = ("area", "rack")
RACK_MAX = 60
IMG_MAX = 8 * 1024 * 1024
TALL = {"server": 2, "nas": 2, "hypervisor": 2}  # Vorgabe Höheneinheiten nach Gerätetyp


class PlanError(Exception):
    pass


def image_mime(data):
    """Bildformat nach den ersten Bytes (nicht nach Dateiname oder Angabe des Browsers)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def _loc(c, pid, lid):
    r = c.execute("SELECT * FROM locations WHERE id=? AND profile_id=?", (lid, pid)).fetchone()
    if not r:
        raise PlanError("Standort nicht gefunden")
    return r


def _plan(r):
    try:
        p = json.loads(r["plan"] or "{}")
    except ValueError:
        p = {}
    ratio = p.get("ratio")
    return dict(ratio=float(ratio) if isinstance(ratio, (int, float)) and 0.25 <= ratio <= 4 else 4 / 3)


def _f(v, lo=0.0, hi=1.0):
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        raise PlanError("Ungültige Zahl")


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise PlanError("Ungültige Zahl")


# ------------------------------------------------------------ Standort: Art und Höheneinheiten
def check_kind(c, lid, kind, units):
    """Prüft Art/Höheneinheiten beim Speichern eines Standorts -> (kind, units)."""
    kind = kind if kind in KINDS else "area"
    units = _i(units or 0) if kind == "rack" else 0
    if kind == "rack" and not 1 <= units <= RACK_MAX:
        raise PlanError(f"Höheneinheiten: 1 bis {RACK_MAX}")
    if lid:
        top = c.execute("SELECT MAX(u + height - 1) AS top, COUNT(*) AS n FROM rack_items WHERE location_id=?", (lid,)).fetchone()
        if top["n"] and kind != "rack":
            raise PlanError("Im Rack ist noch etwas eingebaut – erst ausbauen, dann die Art ändern")
        if top["n"] and units < top["top"]:
            raise PlanError(f"Höheneinheit {top['top']} ist noch belegt")
    return kind, units


# ------------------------------------------------------------ Ansicht
def _subtree(c, pid, lid):
    kids = {}
    for r in c.execute("SELECT id, parent_id FROM locations WHERE profile_id=?", (pid,)):
        kids.setdefault(r["parent_id"], []).append(r["id"])
    out, todo = set(), [lid]
    while todo:
        x = todo.pop()
        if x in out:
            continue
        out.add(x)
        todo += kids.get(x, [])
    return out


def view(c, pid, lid):
    from .inventory import location_paths
    r = _loc(c, pid, lid)
    paths = location_paths(c, pid)
    chain, cur, seen = [], r["parent_id"], set()
    while cur and cur not in seen:
        seen.add(cur)
        p = c.execute("SELECT id, name, parent_id FROM locations WHERE id=?", (cur,)).fetchone()
        if not p:
            break
        chain.insert(0, dict(id=p["id"], name=p["name"]))
        cur = p["parent_id"]
    sub = _subtree(c, pid, lid)
    # „in der Nähe“: beim Rack alles im selben Raum (Unterbaum des übergeordneten Standorts), sonst wie „hier“
    near = _subtree(c, pid, r["parent_id"]) if r["kind"] == "rack" and r["parent_id"] else sub
    children = [dict(id=x["id"], name=x["name"], kind=x["kind"], rack_units=x["rack_units"]) for x in
                c.execute("SELECT * FROM locations WHERE parent_id=? AND profile_id=? ORDER BY name COLLATE NOCASE", (lid, pid))]
    racked = {(x["kind"], x["ref_id"]): x["location_id"] for x in c.execute("SELECT kind, ref_id, location_id FROM rack_items WHERE profile_id=? AND ref_id IS NOT NULL", (pid,))}
    ports = {}
    for x in c.execute("""SELECT i.device_id, COUNT(*) AS n, SUM(CASE WHEN EXISTS(SELECT 1 FROM links l WHERE l.a_if=i.id OR l.b_if=i.id) THEN 1 ELSE 0 END) AS used
                          FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND i.role='port' GROUP BY i.device_id""", (pid,)):
        ports[x["device_id"]] = (x["n"], x["used"] or 0)
    devices = []
    for d in c.execute("SELECT id, name, type, online, location_id, model_id FROM devices WHERE profile_id=? AND status='confirmed' ORDER BY name COLLATE NOCASE", (pid,)):
        n, used = ports.get(d["id"], (0, 0))
        rack = racked.get(("device", d["id"]))
        devices.append(dict(id=d["id"], name=d["name"], type=d["type"], online=d["online"], location=paths.get(d["location_id"], ""),
                            here=d["location_id"] in sub, near=d["location_id"] in near, rack=rack, rack_name=paths.get(rack, "") if rack else "", ports=n, ports_used=used,
                            height=_default_height(c, d)))
    used_pp = {}
    for x in c.execute("SELECT panel_id, outlet_id FROM cable_runs WHERE profile_id=?", (pid,)):
        for k in (x["panel_id"], x["outlet_id"]):
            if k:
                used_pp[k] = used_pp.get(k, 0) + 1
    panels = []
    for p in c.execute("SELECT * FROM patch_panels WHERE profile_id=? ORDER BY kind, name COLLATE NOCASE", (pid,)):
        rack = racked.get(("panel", p["id"]))
        panels.append(dict(id=p["id"], name=p["name"], kind=p["kind"], ports=p["ports"], ports_used=used_pp.get(p["id"], 0), location=paths.get(p["location_id"], ""),
                           here=p["location_id"] in sub, near=p["location_id"] in near, rack=rack, rack_name=paths.get(rack, "") if rack else "", height=2 if p["ports"] > 24 else 1))
    dev_ids, pan_ids, kid_ids = {d["id"] for d in devices}, {p["id"] for p in panels}, {k["id"] for k in children}
    items = [dict(x) for x in c.execute("SELECT id, kind, ref_id, x, y, w, h FROM plan_items WHERE location_id=?", (lid,))
             if x["ref_id"] in {"device": dev_ids, "panel": pan_ids, "room": kid_ids}[x["kind"]]]
    rack = [dict(x) for x in c.execute("SELECT id, kind, ref_id, u, height, label FROM rack_items WHERE location_id=? ORDER BY u DESC", (lid,))
            if x["kind"] == "other" or x["ref_id"] in (dev_ids if x["kind"] == "device" else pan_ids)]
    img = c.execute("SELECT mime, updated FROM location_images WHERE location_id=?", (lid,)).fetchone()
    return dict(location=dict(id=r["id"], name=r["name"], kind=r["kind"], rack_units=r["rack_units"], parent_id=r["parent_id"], path=paths.get(r["id"], r["name"])),
                chain=chain, children=children, plan=dict(_plan(r), image=bool(img), ver=img["updated"] if img else ""),
                items=items, rack=rack, devices=devices, panels=panels)


def _default_height(c, d):
    if d["model_id"]:
        m = c.execute("SELECT data FROM device_models WHERE id=?", (d["model_id"],)).fetchone()
        try:
            u = json.loads(m["data"] or "{}").get("rack_u") if m else None
        except ValueError:
            u = None
        if isinstance(u, int) and 1 <= u <= 10:
            return u
    return TALL.get(d["type"], 1)


# ------------------------------------------------------------ Grundriss
def set_plan(c, pid, lid, body):
    r = _loc(c, pid, lid)
    p = _plan(r)
    if "ratio" in body:
        p["ratio"] = _f(body["ratio"], 0.25, 4)
    c.execute("UPDATE locations SET plan=? WHERE id=?", (json.dumps(p), lid))


def set_image(c, pid, lid, data):
    r = _loc(c, pid, lid)
    if r["kind"] == "rack":
        raise PlanError("Ein Rack hat keinen Grundriss")
    if not data:
        raise PlanError("Keine Datei")
    if len(data) > IMG_MAX:
        raise PlanError("Bild zu groß (höchstens 8 MB)")
    mime = image_mime(data)
    if not mime:
        raise PlanError("Bitte ein Bild als PNG, JPEG, WebP oder GIF hochladen")
    c.execute("INSERT OR REPLACE INTO location_images(location_id, mime, data, updated) VALUES(?,?,?,?)", (lid, mime, data, now()))


def get_image(c, pid, lid):
    _loc(c, pid, lid)
    return c.execute("SELECT mime, data, updated FROM location_images WHERE location_id=?", (lid,)).fetchone()


def delete_image(c, pid, lid):
    _loc(c, pid, lid)
    c.execute("DELETE FROM location_images WHERE location_id=?", (lid,))


def save_item(c, pid, lid, body):
    r = _loc(c, pid, lid)
    if r["kind"] == "rack":
        raise PlanError("Ein Rack hat keinen Grundriss")
    kind, ref = body.get("kind"), _i(body.get("ref_id"))
    if kind == "device":
        t = c.execute("SELECT location_id FROM devices WHERE id=? AND profile_id=? AND status='confirmed'", (ref, pid)).fetchone()
    elif kind == "panel":
        t = c.execute("SELECT location_id FROM patch_panels WHERE id=? AND profile_id=?", (ref, pid)).fetchone()
    elif kind == "room":
        t = c.execute("SELECT 1 FROM locations WHERE id=? AND profile_id=? AND parent_id=?", (ref, pid, lid)).fetchone()
    else:
        raise PlanError("Unbekannte Art")
    if not t:
        raise PlanError("Nicht gefunden" if kind != "room" else "Nur direkte Unterstandorte lassen sich als Raum einzeichnen")
    w, h = (_f(body.get("w", 0.2), 0.02), _f(body.get("h", 0.2), 0.02)) if kind == "room" else (0, 0)
    x, y = _f(body.get("x")), _f(body.get("y"))
    if kind == "room":
        x, y = min(x, 1 - w), min(y, 1 - h)
    c.execute("""INSERT INTO plan_items(profile_id, location_id, kind, ref_id, x, y, w, h) VALUES(?,?,?,?,?,?,?,?)
                 ON CONFLICT(location_id, kind, ref_id) DO UPDATE SET x=excluded.x, y=excluded.y, w=excluded.w, h=excluded.h""",
              (pid, lid, kind, ref, x, y, w, h))
    if kind in ("device", "panel") and t["location_id"] is None:  # ohne Standort -> liegt jetzt hier
        c.execute(f"UPDATE {'devices' if kind == 'device' else 'patch_panels'} SET location_id=? WHERE id=?", (lid, ref))


def delete_item(c, pid, lid, kind, ref):
    _loc(c, pid, lid)
    c.execute("DELETE FROM plan_items WHERE location_id=? AND kind=? AND ref_id=?", (lid, kind, ref))


# ------------------------------------------------------------ Rack
def save_rack_item(c, pid, lid, body, item_id=None):
    r = _loc(c, pid, lid)
    if r["kind"] != "rack":
        raise PlanError("Dieser Standort ist kein Rack")
    units = r["rack_units"]
    old = None
    if item_id:
        old = c.execute("SELECT * FROM rack_items WHERE id=? AND location_id=?", (item_id, lid)).fetchone()
        if not old:
            raise PlanError("Nicht gefunden")
    kind = old["kind"] if old else body.get("kind")
    ref = old["ref_id"] if old else (_i(body["ref_id"]) if body.get("ref_id") not in (None, "") else None)
    if kind == "device":
        if not c.execute("SELECT 1 FROM devices WHERE id=? AND profile_id=? AND status='confirmed'", (ref, pid)).fetchone():
            raise PlanError("Gerät nicht gefunden")
    elif kind == "panel":
        p = c.execute("SELECT kind FROM patch_panels WHERE id=? AND profile_id=?", (ref, pid)).fetchone()
        if not p or p["kind"] != "panel":
            raise PlanError("Patchfeld nicht gefunden")
    elif kind == "other":
        ref = None
    else:
        raise PlanError("Unbekannte Art")
    label = str(body.get("label", old["label"] if old else "") or "").strip()[:60]
    if kind == "other" and not label:
        raise PlanError("Bitte eine Bezeichnung angeben (z. B. USV, Blende, Ablage)")
    u = _i(body.get("u", old["u"] if old else 0))
    height = _i(body.get("height", old["height"] if old else 1))
    if not 1 <= height <= units:
        raise PlanError(f"Höhe: 1 bis {units} HE")
    if not 1 <= u or u + height - 1 > units:
        raise PlanError(f"Passt nicht ins Rack (HE 1 bis {units})")
    for x in c.execute("SELECT u, height, label, kind, ref_id FROM rack_items WHERE location_id=? AND id<>?", (lid, item_id or 0)):
        if u <= x["u"] + x["height"] - 1 and x["u"] <= u + height - 1:
            raise PlanError(f"HE {max(u, x['u'])} ist schon belegt")
    if item_id:
        c.execute("UPDATE rack_items SET u=?, height=?, label=? WHERE id=?", (u, height, label, item_id))
        return item_id
    if ref is not None:  # steckt in höchstens einem Rack: woanders ausbauen
        c.execute("DELETE FROM rack_items WHERE profile_id=? AND kind=? AND ref_id=?", (pid, kind, ref))
        c.execute(f"UPDATE {'devices' if kind == 'device' else 'patch_panels'} SET location_id=? WHERE id=?", (lid, ref))
    return c.execute("INSERT INTO rack_items(profile_id, location_id, kind, ref_id, u, height, label) VALUES(?,?,?,?,?,?,?)",
                     (pid, lid, kind, ref, u, height, label)).lastrowid


def delete_rack_item(c, pid, lid, item_id):
    _loc(c, pid, lid)
    c.execute("DELETE FROM rack_items WHERE id=? AND location_id=?", (item_id, lid))


# ------------------------------------------------------------ PDF
def _names(v):
    return {("device", d["id"]): d for d in v["devices"]} | {("panel", p["id"]): p for p in v["panels"]}


def rack_svg(v, lang="de"):
    """Vorderansicht eines Racks als SVG (mm) -> (inner, w, h)."""
    units = v["location"]["rack_units"]
    uh, w, side = 6.0, 96.0, 10.0
    H = units * uh + 8
    names = _names(v)
    out = [f'<rect x="{side}" y="4" width="{w}" height="{units * uh}" fill="#F6FAFC" stroke="#0A1A33" stroke-width="0.5"/>']
    for n in range(1, units + 1):
        y = 4 + (units - n) * uh
        out.append(f'<text x="{side - 1.5}" y="{y + uh * 0.68:.2f}" font-size="2.4" font-family="{MONO}" fill="#56708A" text-anchor="end">{n}</text>')
        out.append(f'<line x1="{side}" y1="{y:.2f}" x2="{side + w}" y2="{y:.2f}" stroke="#C9D6E3" stroke-width="0.15"/>')
    for it in v["rack"]:
        ref = names.get((it["kind"], it["ref_id"]))
        y = 4 + (units - (it["u"] + it["height"] - 1)) * uh
        hh = it["height"] * uh
        fill = {"device": "#E8F4F8", "panel": "#FFF4E0", "other": "#EEF1F4"}[it["kind"]]
        out.append(f'<rect x="{side + 0.8}" y="{y + 0.4:.2f}" width="{w - 1.6}" height="{hh - 0.8:.2f}" rx="0.8" fill="{fill}" stroke="#56708A" stroke-width="0.25"/>')
        name = it["label"] if it["kind"] == "other" else (ref["name"] if ref else "?")
        sub = ""
        if ref and ref.get("ports"):
            sub = (f"{ref['ports_used']}/{ref['ports']} Ports" if lang != "en" else f"{ref['ports_used']}/{ref['ports']} ports")
        out.append(f'<text x="{side + 3}" y="{y + hh / 2 + 1.1:.2f}" font-size="3" font-family="{FONT}" font-weight="bold" fill="#0A1A33">{esc(name[:48])}</text>')
        if sub:
            out.append(f'<text x="{side + w - 3}" y="{y + hh / 2 + 1.1:.2f}" font-size="2.5" font-family="{FONT}" fill="#56708A" text-anchor="end">{esc(sub)}</text>')
    return "".join(out), side + w + 4, H


def plan_svg(c, v, lang="de"):
    """Grundriss mit Bild und Markierungen als SVG (mm) -> (inner, w, h) oder None ohne Inhalt."""
    lid = v["location"]["id"]
    if not v["items"] and not v["plan"]["image"]:
        return None
    img = c.execute("SELECT mime, data FROM location_images WHERE location_id=?", (lid,)).fetchone()
    ratio = v["plan"]["ratio"]
    if img:
        try:
            from PIL import Image
            import io
            with Image.open(io.BytesIO(img["data"])) as im:
                ratio = im.width / im.height
        except Exception:  # Bild unlesbar: mit dem eingestellten Verhältnis weiter
            pass
    W = 180.0
    H = W / ratio
    out = [f'<rect width="{W}" height="{H:.2f}" fill="#fff" stroke="#C9D6E3" stroke-width="0.3"/>']
    if img:
        out.append(f'<image href="data:{img["mime"]};base64,{base64.b64encode(img["data"]).decode()}" width="{W}" height="{H:.2f}" preserveAspectRatio="none"/>')
    names = _names(v)
    kids = {k["id"]: k for k in v["children"]}
    for it in sorted(v["items"], key=lambda x: x["kind"] != "room"):
        x, y = it["x"] * W, it["y"] * H
        if it["kind"] == "room":
            k = kids.get(it["ref_id"])
            out.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{it["w"] * W:.2f}" height="{it["h"] * H:.2f}" fill="#0091A8" fill-opacity="0.08" stroke="#0091A8" stroke-width="0.4"/>')
            out.append(f'<text x="{x + 1.5:.2f}" y="{y + 4:.2f}" font-size="3" font-family="{FONT}" font-weight="bold" fill="#00707F">{esc(k["name"] if k else "")}</text>')
            continue
        ref = names.get((it["kind"], it["ref_id"]))
        if not ref:
            continue
        col = "#2E9E5B" if ref.get("online") == 1 else "#C0392B" if ref.get("online") == 0 else "#56708A"
        if it["kind"] == "panel":
            col = "#E08A00"
            out.append(f'<rect x="{x - 1.6:.2f}" y="{y - 1.6:.2f}" width="3.2" height="3.2" fill="#fff" stroke="{col}" stroke-width="0.6"/>')
        else:
            out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.8" fill="#fff" stroke="{col}" stroke-width="0.7"/>')
        name = ref["name"][:40]
        out.append(f'<rect x="{x + 2.2:.2f}" y="{y - 1.4:.2f}" width="{len(name) * 1.45 + 1:.2f}" height="3.3" rx="0.5" fill="#fff" fill-opacity="0.88"/>')
        out.append(f'<text x="{x + 2.7:.2f}" y="{y + 0.9:.2f}" font-size="2.5" font-family="{FONT}" fill="#0A1A33">{esc(name)}</text>')
    return "".join(out), W, H


# ------------------------------------------------------------ Sicherung
def export_rows(c):
    imgs = [dict(location_id=r["location_id"], mime=r["mime"], updated=r["updated"], data=base64.b64encode(r["data"]).decode())
            for r in c.execute("SELECT * FROM location_images")]
    return dict(location_images=imgs, plan_items=[dict(r) for r in c.execute("SELECT * FROM plan_items")],
                rack_items=[dict(r) for r in c.execute("SELECT * FROM rack_items")])


def import_rows(c, exp, pmap, lmap, dmap, panmap):
    for x in exp.get("location_images", []):
        if x["location_id"] in lmap:
            try:
                data = base64.b64decode(x["data"])
            except ValueError:
                continue
            if image_mime(data):
                c.execute("INSERT OR REPLACE INTO location_images(location_id, mime, data, updated) VALUES(?,?,?,?)",
                          (lmap[x["location_id"]], image_mime(data), data, x.get("updated") or now()))
    refs = {"device": dmap, "panel": panmap, "room": lmap}
    for x in exp.get("plan_items", []):
        m = refs.get(x["kind"], {})
        if x["profile_id"] in pmap and x["location_id"] in lmap and x["ref_id"] in m:
            c.execute("INSERT OR IGNORE INTO plan_items(profile_id, location_id, kind, ref_id, x, y, w, h) VALUES(?,?,?,?,?,?,?,?)",
                      (pmap[x["profile_id"]], lmap[x["location_id"]], x["kind"], m[x["ref_id"]], x["x"], x["y"], x["w"], x["h"]))
    for x in exp.get("rack_items", []):
        if x["profile_id"] not in pmap or x["location_id"] not in lmap:
            continue
        ref = None if x["kind"] == "other" else refs[x["kind"]].get(x["ref_id"])
        if x["kind"] != "other" and ref is None:
            continue
        c.execute("INSERT INTO rack_items(profile_id, location_id, kind, ref_id, u, height, label) VALUES(?,?,?,?,?,?,?)",
                  (pmap[x["profile_id"]], lmap[x["location_id"]], x["kind"], ref, x["u"], x["height"], x["label"]))
