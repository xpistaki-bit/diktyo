"""Geschwindigkeitsmessungen: Internet-Speedtest und iperf3 zu einem Gerät (laufen im Hintergrunddienst)."""
import ipaddress
import json

from fastapi import APIRouter, Body, Depends, HTTPException

from . import notify, speedtest
from .auth import profile_access, require_user, touch
from .db import audit, db
from .routes_scan import _job_out
from .worker import worker_status

router = APIRouter()


def _running(c, pid, kind=None, device_id=None):
    for j in c.execute("SELECT * FROM jobs WHERE profile_id=? AND kind='speedtest' AND status IN ('queued','running') ORDER BY id", (pid,)):
        p = json.loads(j["params"] or "{}")
        if (kind is None or p.get("kind") == kind) and (device_id is None or p.get("device_id") == device_id):
            return _job_out(j)
    return None


@router.get("/api/profiles/{pid}/speedtest")
def overview(pid: int, user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid)
        return dict(settings=speedtest.settings(p), schedules=list(speedtest.SCHEDULES), history=speedtest.history(c, pid, limit=500),
                    job=_running(c, pid, "internet"), worker=worker_status(c)["running"], iperf=speedtest.iperf_available())


@router.put("/api/profiles/{pid}/speedtest")
def settings_put(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid, "edit")
        st = json.loads(p["settings"] or "{}")
        s = speedtest.settings(p)
        if int(body.get("schedule_hours", -1)) in speedtest.SCHEDULES:
            s["schedule_hours"] = int(body["schedule_hours"])
        for k, lo, hi in (("streams", 1, 8), ("seconds", 3, 20)):
            if str(body.get(k, "")).isdigit():
                s[k] = max(lo, min(int(body[k]), hi))
        st["speedtest"] = s
        c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
        touch(c, pid, user)
        return s


@router.post("/api/profiles/{pid}/speedtest/run")
def run(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        jid = speedtest.enqueue(c, pid, "internet", user["id"])
        audit(c, "speedtest.run", user["id"], pid, {})
        return dict(job=_job_out(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()), worker=worker_status(c)["running"])


@router.get("/api/profiles/{pid}/notify")
def notify_get(pid: int, user=Depends(require_user)):
    from . import mailer
    with db() as c:
        p, _ = profile_access(c, user, pid)
        return dict(settings=notify.settings(p), kinds=list(notify.KINDS), mail_enabled=mailer.enabled(c), **notify.state(c, pid))


@router.put("/api/profiles/{pid}/notify")
def notify_put(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid, "edit")
        try:
            s = notify.save_settings(c, p, body)
        except notify.NotifyError as ex:
            raise HTTPException(400, str(ex))
        touch(c, pid, user)
        return s


@router.post("/api/profiles/{pid}/notify/test")
def notify_test(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        return notify.test(c, pid, body)


@router.get("/api/profiles/{pid}/devices/{did}/iperf")
def iperf_list(pid: int, did: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(history=speedtest.history(c, pid, "iperf", did, limit=50), job=_running(c, pid, "iperf", did),
                    available=speedtest.iperf_available())


@router.post("/api/profiles/{pid}/devices/{did}/iperf")
def iperf_run(pid: int, did: int, body: dict = Body(default={}), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        ips = [r["address"] for r in c.execute("""SELECT a.address FROM ip_addresses a JOIN devices d ON d.id=a.device_id
                                                  WHERE a.device_id=? AND d.profile_id=? ORDER BY a.id""", (did, pid))]
        ips = [x for x in ips if ipaddress.ip_address(x).version == 4]
        if not ips:
            raise HTTPException(400, "Das Gerät hat keine IPv4-Adresse")
        host = body.get("host") if body.get("host") in ips else ips[0]
        try:
            port = int(body.get("port") or 5201)
        except ValueError:
            port = 5201
        if not 1 <= port <= 65535:
            raise HTTPException(400, "Ungültiger Port")
        jid = speedtest.enqueue(c, pid, "iperf", user["id"], device_id=did, host=host, port=port)
        audit(c, "speedtest.iperf", user["id"], pid, dict(id=did, host=host, port=port))
        return dict(job=_job_out(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()), worker=worker_status(c)["running"])
