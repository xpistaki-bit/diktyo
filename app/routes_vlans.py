"""API: VLAN-Plan (produktiver Stand und Plan je Port)."""
from fastapi import APIRouter, Body, Depends, HTTPException

from . import vlanplan
from .auth import profile_access, require_user, touch
from .db import audit, db

router = APIRouter(prefix="/api/profiles/{pid}/vlanplan")


def _edit(pid, user, fn, action=None):
    with db() as c:
        profile_access(c, user, pid, "edit")
        try:
            res = fn(c)
        except vlanplan.VlanError as ex:
            raise HTTPException(400, str(ex))
        if action:
            audit(c, action, user["id"], pid)
        touch(c, pid, user)
        out = vlanplan.state(c, pid)
        if isinstance(res, int):
            out["result"] = res
        return out


@router.get("")
def get(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return vlanplan.state(c, pid)


@router.put("/ports")
def ports(pid: int, body: dict = Body(...), user=Depends(require_user)):
    u = body.get("untagged", "keep")
    u = "keep" if u == "keep" else (int(u) if u else None)
    return _edit(pid, user, lambda c: vlanplan.set_ports(c, pid, body.get("mode"), [int(x) for x in body.get("ports") or []], u, body.get("tagged") or {}))


@router.post("/plan")
def plan_start(pid: int, body: dict = Body(default={}), user=Depends(require_user)):
    return _edit(pid, user, lambda c: vlanplan.plan_start(c, pid, body.get("note", "")), "vlanplan.start")


@router.delete("/plan")
def plan_discard(pid: int, user=Depends(require_user)):
    return _edit(pid, user, lambda c: vlanplan.plan_discard(c, pid), "vlanplan.discard")


@router.post("/plan/finish")
def plan_finish(pid: int, user=Depends(require_user)):
    return _edit(pid, user, lambda c: vlanplan.plan_finish(c, pid), "vlanplan.finish")


@router.post("/plan/adopt/{iid}")
def plan_adopt(pid: int, iid: int, user=Depends(require_user)):
    return _edit(pid, user, lambda c: vlanplan.adopt_port(c, pid, iid))
