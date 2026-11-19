"""API: Schaltaktionen (nur Besitzer des Profils)."""
from fastapi import APIRouter, Body, Depends, HTTPException

from . import actions
from .auth import profile_access, require_user
from .db import db

router = APIRouter(prefix="/api/profiles/{pid}")


@router.get("/devices/{did}/actions")
def device_actions(pid: int, did: int, port: int = 0, user=Depends(require_user)):
    with db() as c:
        _, role = profile_access(c, user, pid)
        if role != "owner":
            return dict(actions=[], allowed=False)
        return dict(actions=actions.available(c, pid, did, port or None), allowed=True)


@router.post("/devices/{did}/actions")
def device_action_run(pid: int, did: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "owner")
    try:
        res = actions.run(pid, user["id"], did, str(body.get("key") or ""), undo=body.get("undo") or None, port_no=int(body.get("port") or 0) or None)
    except actions.ActionError as ex:
        raise HTTPException(400, str(ex))
    if res["status"] == "error":
        raise HTTPException(400, res["message"])
    return res


@router.get("/actions")
def actions_recent(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(actions=actions.recent(c, pid))


@router.delete("/actions/{aid}/undo")
def action_cancel_undo(pid: int, aid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "owner")
        if not actions.cancel_undo(c, pid, aid):
            raise HTTPException(404, "Kein geplantes Zurückschalten")
    return dict(ok=True)
