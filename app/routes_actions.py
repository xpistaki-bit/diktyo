"""API: Schaltaktionen (nur Besitzer des Profils)."""
from fastapi import APIRouter, Body, Depends, HTTPException

from . import actions, quarantine, schedules
from .auth import profile_access, require_user
from .db import audit, db, now

router = APIRouter(prefix="/api/profiles/{pid}")


@router.get("/devices/{did}/actions")
def device_actions(pid: int, did: int, port: int = 0, user=Depends(require_user)):
    with db() as c:
        _, role = profile_access(c, user, pid)
        if role != "owner":
            return dict(actions=[], allowed=False)
        return dict(actions=actions.available(c, pid, did, port or None), allowed=True,
                    ports=None if port else actions.switch_ports(c, pid, did))


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


# ------------------------------------------------------------ Zeitpläne
@router.get("/schedules")
def schedules_list(pid: int, device_id: int = 0, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(schedules=schedules.listing(c, pid, device_id or None))


@router.post("/devices/{did}/schedules")
def schedule_create(pid: int, did: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "owner")
        try:
            sid = schedules.create(c, pid, user["id"], did, str(body.get("key") or ""), body.get("days"), body.get("start"), body.get("end"),
                                   int(body.get("port") or 0))
        except schedules.ScheduleError as ex:
            raise HTTPException(400, str(ex))
        audit(c, "schedule.create", user["id"], pid, dict(id=sid, device=did))
        return next(s for s in schedules.listing(c, pid) if s["id"] == sid)


@router.put("/schedules/{sid}")
def schedule_toggle(pid: int, sid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "owner")
        if not c.execute("UPDATE schedules SET enabled=?, last_check=? WHERE id=? AND profile_id=?",
                         (1 if body.get("enabled") else 0, now(), sid, pid)).rowcount:
            raise HTTPException(404, "Zeitplan nicht gefunden")
        return next(s for s in schedules.listing(c, pid) if s["id"] == sid)


@router.delete("/schedules/{sid}")
def schedule_delete(pid: int, sid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "owner")
        if not c.execute("DELETE FROM schedules WHERE id=? AND profile_id=?", (sid, pid)).rowcount:
            raise HTTPException(404, "Zeitplan nicht gefunden")
        audit(c, "schedule.delete", user["id"], pid, dict(id=sid))
    return dict(ok=True)


# ------------------------------------------------------------ Quarantäne
@router.get("/quarantine")
def quarantine_get(pid: int, user=Depends(require_user)):
    with db() as c:
        p, role = profile_access(c, user, pid)
        has_fritz = bool(quarantine._fritz(c, pid))
        return dict(settings=quarantine.settings(p), available=has_fritz, devices=quarantine.listing(c, pid), owner=role == "owner")


@router.put("/quarantine")
def quarantine_put(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "owner")
        if body.get("enabled") and not quarantine._fritz(c, pid):
            raise HTTPException(400, "Für die Quarantäne wird eine FRITZ!Box-Integration mit Benutzer gebraucht")
        q = quarantine.save(c, pid, bool(body.get("enabled")), body.get("random", True) is not False)
        audit(c, "quarantine.settings", user["id"], pid, q)
        return q


@router.post("/quarantine/{qid}/release")
def quarantine_release(pid: int, qid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "owner")
    res = quarantine.release(pid, qid)
    if res is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    if res["status"] == "error":
        raise HTTPException(400, res["message"])
    return res


# ------------------------------------------------------------ Änderungsverlauf
@router.get("/history")
def history(pid: int, device_id: int = 0, days: int = 7, kinds: str = "", q: str = "", user=Depends(require_user)):
    import datetime as dt
    from . import changes
    days = max(1, min(365, days))
    since = (dt.datetime.now().astimezone() - dt.timedelta(days=days)).isoformat(timespec="seconds")
    with db() as c:
        profile_access(c, user, pid)
        items = changes.timeline(c, pid, device_id or None, since, [k for k in kinds.split(",") if k] or None, q[:80], limit=500)
        return dict(items=items, summary=changes.summary(c, pid) if not device_id else None)


@router.get("/history.csv")
def history_csv(pid: int, days: int = 30, user=Depends(require_user)):
    import csv
    import datetime as dt
    import io
    from fastapi import Response
    from . import changes
    since = (dt.datetime.now().astimezone() - dt.timedelta(days=max(1, min(365, days)))).isoformat(timespec="seconds")
    with db() as c:
        profile_access(c, user, pid)
        items = changes.timeline(c, pid, None, since, limit=20000)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Zeit", "Art", "Gerät", "Feld", "Vorher", "Nachher", "Quelle", "Benutzer"])
    for x in items:
        w.writerow([x["ts"], f'{x["cat"]}:{x["kind"]}', x.get("device") or "", x.get("field") or "", x.get("old") or "", x.get("new") or "",
                    x.get("source") or "", x.get("user") or ""])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="diktyo-verlauf-{pid}.csv"'})
