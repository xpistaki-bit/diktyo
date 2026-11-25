"""API: Grundriss/Raumplan und Rack-Ansicht je Standort."""
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from . import auth, locplan
from .auth import profile_access, require_user
from .db import db

router = APIRouter(prefix="/api/profiles/{pid}/locations/{lid}")


def _edit(pid, lid, user, fn):
    with db() as c:
        profile_access(c, user, pid, "edit")
        try:
            fn(c)
        except locplan.PlanError as ex:
            raise HTTPException(400, str(ex))
        auth.touch(c, pid, user)
        return locplan.view(c, pid, lid)


@router.get("/view")
def view(pid: int, lid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        try:
            return locplan.view(c, pid, lid)
        except locplan.PlanError as ex:
            raise HTTPException(404, str(ex))


@router.put("/plan")
def plan_put(pid: int, lid: int, body: dict = Body(...), user=Depends(require_user)):
    return _edit(pid, lid, user, lambda c: locplan.set_plan(c, pid, lid, body))


@router.get("/plan/image")
def image_get(pid: int, lid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        try:
            r = locplan.get_image(c, pid, lid)
        except locplan.PlanError as ex:
            raise HTTPException(404, str(ex))
    if not r:
        raise HTTPException(404, "Kein Grundriss-Bild")
    return Response(bytes(r["data"]), media_type=r["mime"], headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.put("/plan/image")
async def image_put(pid: int, lid: int, request: Request, user=Depends(require_user)):
    data = await request.body()
    return _edit(pid, lid, user, lambda c: locplan.set_image(c, pid, lid, data))


@router.delete("/plan/image")
def image_del(pid: int, lid: int, user=Depends(require_user)):
    return _edit(pid, lid, user, lambda c: locplan.delete_image(c, pid, lid))


@router.put("/plan/items")
def item_put(pid: int, lid: int, body: dict = Body(...), user=Depends(require_user)):
    return _edit(pid, lid, user, lambda c: locplan.save_item(c, pid, lid, body))


@router.delete("/plan/items/{kind}/{ref}")
def item_del(pid: int, lid: int, kind: str, ref: int, user=Depends(require_user)):
    return _edit(pid, lid, user, lambda c: locplan.delete_item(c, pid, lid, kind, ref))


@router.post("/rack")
def rack_add(pid: int, lid: int, body: dict = Body(...), user=Depends(require_user)):
    return _edit(pid, lid, user, lambda c: locplan.save_rack_item(c, pid, lid, body))


@router.put("/rack/{item_id}")
def rack_put(pid: int, lid: int, item_id: int, body: dict = Body(...), user=Depends(require_user)):
    return _edit(pid, lid, user, lambda c: locplan.save_rack_item(c, pid, lid, body, item_id))


@router.delete("/rack/{item_id}")
def rack_del(pid: int, lid: int, item_id: int, user=Depends(require_user)):
    return _edit(pid, lid, user, lambda c: locplan.delete_rack_item(c, pid, lid, item_id))
