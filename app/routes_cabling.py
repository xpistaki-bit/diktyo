"""API: Kabel und Patchpanels (Patchfelder, Dosen, Kabelwege)."""
from fastapi import APIRouter, Body, Depends, HTTPException

from . import auth, cabling
from .auth import profile_access, require_user
from .db import db

router = APIRouter(prefix="/api/profiles/{pid}")


def _edit(fn, pid, user):
    with db() as c:
        profile_access(c, user, pid, "edit")
        try:
            fn(c)
        except cabling.CablingError as ex:
            raise HTTPException(400, str(ex))
        auth.touch(c, pid, user)
        return cabling.overview(c, pid)


@router.get("/cabling")
def cabling_get(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return cabling.overview(c, pid)


@router.get("/devices/{did}/cabling")
def cabling_device(pid: int, did: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(runs=cabling.for_device(c, pid, did))


@router.post("/cabling/panels")
def panel_add(pid: int, body: dict = Body(...), user=Depends(require_user)):
    return _edit(lambda c: cabling.save_panel(c, pid, body), pid, user)


@router.put("/cabling/panels/{panel_id}")
def panel_put(pid: int, panel_id: int, body: dict = Body(...), user=Depends(require_user)):
    return _edit(lambda c: cabling.save_panel(c, pid, body, panel_id), pid, user)


@router.delete("/cabling/panels/{panel_id}")
def panel_del(pid: int, panel_id: int, user=Depends(require_user)):
    return _edit(lambda c: cabling.delete_panel(c, pid, panel_id), pid, user)


@router.post("/cabling/runs")
def run_add(pid: int, body: dict = Body(...), user=Depends(require_user)):
    return _edit(lambda c: cabling.save_run(c, pid, body), pid, user)


@router.put("/cabling/runs/{run_id}")
def run_put(pid: int, run_id: int, body: dict = Body(...), user=Depends(require_user)):
    return _edit(lambda c: cabling.save_run(c, pid, body, run_id), pid, user)


@router.delete("/cabling/runs/{run_id}")
def run_del(pid: int, run_id: int, user=Depends(require_user)):
    return _edit(lambda c: cabling.delete_run(c, pid, run_id), pid, user)
