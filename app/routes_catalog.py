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
