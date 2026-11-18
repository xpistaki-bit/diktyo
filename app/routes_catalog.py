"""API: Gerätekatalog. Lesen dürfen alle Angemeldeten, ändern nur Administratoren."""
import json

from fastapi import APIRouter, Body, Depends, File, HTTPException, Response, UploadFile

from . import catalog
from .auth import require_admin, require_user, touch
from .db import audit, db

router = APIRouter(prefix="/api/catalog")


@router.get("")
def catalog_list(user=Depends(require_user)):
    with db() as c:
        rows = c.execute("SELECT * FROM device_models ORDER BY manufacturer COLLATE NOCASE, model COLLATE NOCASE").fetchall()
        used = {r["model_id"]: r["n"] for r in c.execute("SELECT model_id, COUNT(*) AS n FROM devices WHERE model_id IS NOT NULL GROUP BY model_id")}
        return dict(models=[dict(catalog.row(r), used=used.get(r["id"], 0)) for r in rows])


def _body(body):
    typ = body.get("type") if body.get("type") in catalog.TYPES else "other"
    man, model = str(body.get("manufacturer") or "").strip()[:80], str(body.get("model") or "").strip()[:120]
    if not man or not model:
        raise HTTPException(400, "Hersteller und Modell sind erforderlich")
    return typ, man, model, catalog.clean_data(body)


@router.post("")
def catalog_create(body: dict = Body(...), admin=Depends(require_admin)):
    typ, man, model, data = _body(body)
    with db() as c:
        if c.execute("SELECT 1 FROM device_models WHERE manufacturer=? AND model=?", (man, model)).fetchone():
            raise HTTPException(409, "Diesen Katalogeintrag gibt es schon")
        cur = c.execute("INSERT INTO device_models(type, manufacturer, model, data, custom) VALUES(?,?,?,?,1)",
                        (typ, man, model, json.dumps(data, ensure_ascii=False)))
        audit(c, "catalog.create", admin["id"], detail=dict(manufacturer=man, model=model))
        touch(c)
        return catalog.row(c.execute("SELECT * FROM device_models WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/{mid}")
def catalog_update(mid: int, body: dict = Body(...), admin=Depends(require_admin)):
    typ, man, model, data = _body(body)
    with db() as c:
        dup = c.execute("SELECT id FROM device_models WHERE manufacturer=? AND model=?", (man, model)).fetchone()
        if dup and dup["id"] != mid:
            raise HTTPException(409, "Diesen Katalogeintrag gibt es schon")
        # Geänderte Einträge des Startkatalogs gelten danach als eigene und werden bei Updates nicht überschrieben.
        if not c.execute("UPDATE device_models SET type=?, manufacturer=?, model=?, data=?, custom=1 WHERE id=?",
                         (typ, man, model, json.dumps(data, ensure_ascii=False), mid)).rowcount:
            raise HTTPException(404, "Katalogeintrag nicht gefunden")
        audit(c, "catalog.update", admin["id"], detail=dict(id=mid))
        touch(c)
        return catalog.row(c.execute("SELECT * FROM device_models WHERE id=?", (mid,)).fetchone())


@router.delete("/{mid}")
def catalog_delete(mid: int, admin=Depends(require_admin)):
    with db() as c:
        if not c.execute("DELETE FROM device_models WHERE id=?", (mid,)).rowcount:
            raise HTTPException(404, "Katalogeintrag nicht gefunden")
        audit(c, "catalog.delete", admin["id"], detail=dict(id=mid))
        touch(c)
    return dict(ok=True)


@router.get("/export.csv")
def catalog_export(template: int = 0, user=Depends(require_user)):
    with db() as c:
        if template:
            rows = c.execute("SELECT * FROM device_models WHERE model IN ('XGS1935-28', 'FRITZ!Box 6591 Cable', 'ExpertWiFi EBM68') ORDER BY id").fetchall()
        else:
            rows = c.execute("SELECT * FROM device_models ORDER BY manufacturer COLLATE NOCASE, model COLLATE NOCASE").fetchall()
    fn = "diktyo-katalog-vorlage.csv" if template else "diktyo-katalog.csv"
    return Response(catalog.export_csv(rows), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@router.post("/import/csv")
async def catalog_import(file: UploadFile = File(...), admin=Depends(require_admin)):
    entries, errs = catalog.parse_csv(await file.read())
    new = upd = 0
    with db() as c:
        have = {(r["manufacturer"], r["model"]): r["id"] for r in c.execute("SELECT id, manufacturer, model FROM device_models")}
        for e in entries:
            data = json.dumps(e["data"], ensure_ascii=False)
            if (e["manufacturer"], e["model"]) in have:
                c.execute("UPDATE device_models SET type=?, data=?, custom=1 WHERE id=?", (e["type"], data, have[(e["manufacturer"], e["model"])]))
                upd += 1
            else:
                c.execute("INSERT INTO device_models(type, manufacturer, model, data, custom) VALUES(?,?,?,?,1)", (e["type"], e["manufacturer"], e["model"], data))
                new += 1
        audit(c, "catalog.import", admin["id"], detail=dict(new=new, updated=upd))
        touch(c)
    return dict(new=new, updated=upd, errors=errs)


# ------------------------------------------------------------ Erkennungsregeln
rules_router = APIRouter(prefix="/api/rules")
RULE_TEXT = ("vendor", "hostname", "mdns", "ssdp", "http")
RULE_COLS = ["key", "label", "label_en", "type", "weight", *RULE_TEXT, "ports", "any_ports", "random"]


def _rule_out(r):
    return dict(id=r["id"], key=r["key"], label=r["label"], label_en=r["label_en"], type=r["type"], weight=r["weight"],
                cond=json.loads(r["cond"] or "{}"), custom=bool(r["custom"]))


def _ports(v):
    if isinstance(v, list):
        return [int(x) for x in v if str(x).strip().isdigit()]
    return [int(x) for x in str(v or "").replace(";", ",").split(",") if x.strip().isdigit()]


def _rule_body(body):
    import re as _re
    cond = {}
    src = body.get("cond") if isinstance(body.get("cond"), dict) else body
    for k in RULE_TEXT:
        v = str(src.get(k) or "").strip()
        if v:
            try:
                _re.compile(v)
            except _re.error:
                raise HTTPException(400, f"Ungültiger Ausdruck: {v}")
            cond[k] = v[:200]
    for k in ("ports", "any_ports"):
        p = _ports(src.get(k))
        if p:
            cond[k] = p[:20]
    if str(src.get("random", "")).lower() in ("1", "true", "ja", "yes", "on") or src.get("random") is True:
        cond["random"] = True
    label = str(body.get("label") or "").strip()[:120]
    if not label or not cond:
        raise HTTPException(400, "Bezeichnung und mindestens eine Bedingung sind erforderlich")
    typ = body.get("type") if body.get("type") in catalog.TYPES else "other"
    try:
        weight = max(1, min(int(body.get("weight") or 50), 99))
    except ValueError:
        weight = 50
    return dict(label=label, label_en=str(body.get("label_en") or "").strip()[:120], type=typ, weight=weight,
                cond=json.dumps(cond, ensure_ascii=False))


@rules_router.get("")
def rules_list(user=Depends(require_user)):
    with db() as c:
        return dict(rules=[_rule_out(r) for r in c.execute("SELECT * FROM ident_rules ORDER BY weight DESC, label")])


@rules_router.post("")
def rule_create(body: dict = Body(...), admin=Depends(require_admin)):
    import secrets as _s
    r = _rule_body(body)
    with db() as c:
        cur = c.execute("INSERT INTO ident_rules(key, label, label_en, type, weight, cond, custom) VALUES(?,?,?,?,?,?,1)",
                        ("eigen-" + _s.token_hex(4), r["label"], r["label_en"], r["type"], r["weight"], r["cond"]))
        touch(c)
        return _rule_out(c.execute("SELECT * FROM ident_rules WHERE id=?", (cur.lastrowid,)).fetchone())


@rules_router.put("/{rid}")
def rule_update(rid: int, body: dict = Body(...), admin=Depends(require_admin)):
    r = _rule_body(body)
    with db() as c:
        if not c.execute("UPDATE ident_rules SET label=?, label_en=?, type=?, weight=?, cond=?, custom=1 WHERE id=?",
                         (r["label"], r["label_en"], r["type"], r["weight"], r["cond"], rid)).rowcount:
            raise HTTPException(404, "Regel nicht gefunden")
        touch(c)
        return _rule_out(c.execute("SELECT * FROM ident_rules WHERE id=?", (rid,)).fetchone())


@rules_router.delete("/{rid}")
def rule_delete(rid: int, admin=Depends(require_admin)):
    with db() as c:
        if not c.execute("DELETE FROM ident_rules WHERE id=?", (rid,)).rowcount:
            raise HTTPException(404, "Regel nicht gefunden")
        touch(c)
    return dict(ok=True)


@rules_router.get("/export.csv")
def rules_export(user=Depends(require_user)):
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, delimiter=";")
    w.writerow(RULE_COLS)
    with db() as c:
        for r in c.execute("SELECT * FROM ident_rules ORDER BY weight DESC, label"):
            cd = json.loads(r["cond"] or "{}")
            w.writerow([r["key"], r["label"], r["label_en"], r["type"], r["weight"], *[cd.get(k, "") for k in RULE_TEXT],
                        ",".join(map(str, cd.get("ports", []))), ",".join(map(str, cd.get("any_ports", []))), "1" if cd.get("random") else ""])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="diktyo-erkennungsregeln.csv"'})


@rules_router.post("/import/csv")
async def rules_import(file: UploadFile = File(...), admin=Depends(require_admin)):
    import csv as _csv
    import io as _io
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text.strip() else ""
    rows = list(_csv.DictReader(_io.StringIO(text), delimiter=";" if first.count(";") >= first.count(",") else ","))
    new = upd = 0
    errs = []
    with db() as c:
        for n, row in enumerate(rows, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            try:
                r = _rule_body(row)
            except HTTPException as ex:
                errs.append(f"Zeile {n}: {ex.detail}")
                continue
            key = row.get("key") or ""
            if key and c.execute("SELECT 1 FROM ident_rules WHERE key=?", (key,)).fetchone():
                c.execute("UPDATE ident_rules SET label=?, label_en=?, type=?, weight=?, cond=?, custom=1 WHERE key=?",
                          (r["label"], r["label_en"], r["type"], r["weight"], r["cond"], key))
                upd += 1
            else:
                import secrets as _s
                c.execute("INSERT INTO ident_rules(key, label, label_en, type, weight, cond, custom) VALUES(?,?,?,?,?,?,1)",
                          (key or "eigen-" + _s.token_hex(4), r["label"], r["label_en"], r["type"], r["weight"], r["cond"]))
                new += 1
        touch(c)
    return dict(new=new, updated=upd, errors=errs)
