"""API: Integrationen (FRITZ!Box, SNMP), Ping-Überwachung, Messwerte."""
import json

from fastapi import APIRouter, Body, Depends, HTTPException

from . import integrations, metrics, monitor, security
from .auth import profile_access, require_admin, require_user, text, touch
from .db import audit, db, now, set_setting
from .drivers import DRIVERS, ERRORS, schema

router = APIRouter()


def _out(r):
    st = json.loads(r["state"] or "{}")
    return dict(id=r["id"], driver=r["driver"], name=r["name"], host=r["host"], port=r["port"], username=r["username"],
                password=security.MASK if r["secret"] else "", device_id=r["device_id"], interval_s=r["interval_s"], enabled=bool(r["enabled"]),
                last_poll=r["last_poll"], last_ok=r["last_ok"], last_error=r["last_error"], summary=st.get("summary"), result=st.get("result"))


def _body(body, old=None):
    drv = body.get("driver") if not old else old["driver"]
    if drv not in DRIVERS:
        raise HTTPException(400, "Unbekannter Treiber")
    host = text(body, "host", 120)
    if not host:
        raise HTTPException(400, "Adresse fehlt")
    try:
        interval = max(15, min(int(body.get("interval_s") or DRIVERS[drv].DEFAULT_INTERVAL), 3600))
    except ValueError:
        interval = DRIVERS[drv].DEFAULT_INTERVAL
    pw = body.get("password") or ""
    if pw == security.MASK and old:
        secret = old["secret"]
    else:
        secret = security.encrypt(pw) if pw else ""
    port = body.get("port")
    return dict(driver=drv, name=text(body, "name", 80) or DRIVERS[drv].NAME, host=host, port=int(port) if str(port or "").isdigit() else None,
                username=text(body, "username", 80), secret=secret, interval_s=interval, enabled=1 if body.get("enabled", True) else 0,
                device_id=int(body["device_id"]) if body.get("device_id") else None)


@router.get("/api/profiles/{pid}/integrations")
def list_(pid: int, user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid)
        rows = c.execute("SELECT * FROM integrations WHERE profile_id=? ORDER BY id", (pid,)).fetchall()
        return dict(integrations=[_out(r) for r in rows], drivers=schema(), monitor=monitor.settings(p), intervals=list(monitor.INTERVALS),
                    metrics_days=metrics.retention_days(c))


@router.post("/api/profiles/{pid}/integrations")
def create(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        v = _body(body)
        if v["device_id"] and not c.execute("SELECT 1 FROM devices WHERE id=? AND profile_id=?", (v["device_id"], pid)).fetchone():
            raise HTTPException(400, "Gerät gehört nicht zu diesem Profil")
        cur = c.execute("""INSERT INTO integrations(profile_id, driver, name, host, port, username, secret, interval_s, enabled, device_id, created)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (pid, v["driver"], v["name"], v["host"], v["port"], v["username"], v["secret"],
                                                            v["interval_s"], v["enabled"], v["device_id"], now()))
        audit(c, "integration.create", user["id"], pid, dict(driver=v["driver"], host=v["host"]))
        touch(c, pid)
        return _out(c.execute("SELECT * FROM integrations WHERE id=?", (cur.lastrowid,)).fetchone())


def _get(c, pid, iid):
    r = c.execute("SELECT * FROM integrations WHERE id=? AND profile_id=?", (iid, pid)).fetchone()
    if not r:
        raise HTTPException(404, "Integration nicht gefunden")
    return r


@router.put("/api/profiles/{pid}/integrations/{iid}")
def update(pid: int, iid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        old = _get(c, pid, iid)
        v = _body(body, old)
        c.execute("""UPDATE integrations SET name=?, host=?, port=?, username=?, secret=?, interval_s=?, enabled=?, device_id=?, last_poll=NULL
                     WHERE id=?""", (v["name"], v["host"], v["port"], v["username"], v["secret"], v["interval_s"], v["enabled"], v["device_id"], iid))
        touch(c, pid)
        return _out(_get(c, pid, iid))


@router.delete("/api/profiles/{pid}/integrations/{iid}")
def delete(pid: int, iid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        _get(c, pid, iid)
        c.execute("DELETE FROM integrations WHERE id=?", (iid,))
        c.execute("DELETE FROM series WHERE profile_id=? AND key LIKE ?", (pid, f"i{iid}:%"))
        touch(c, pid)
    return dict(ok=True)


@router.post("/api/profiles/{pid}/integrations/test")
def test(pid: int, body: dict = Body(...), user=Depends(require_user)):
    """Verbindung prüfen, ohne zu speichern (Passwort-Platzhalter nimmt das gespeicherte)."""
    with db() as c:
        profile_access(c, user, pid, "edit")
        old = _get(c, pid, int(body["id"])) if body.get("id") else None
        v = _body(body, old)
    conf = dict(host=v["host"], port=v["port"], username=v["username"], password=security.decrypt(v["secret"]) if v["secret"] else "")
    try:
        return dict(ok=True, result=DRIVERS[v["driver"]].test(conf))
    except ERRORS as ex:
        raise HTTPException(400, str(ex))
    except Exception as ex:
        raise HTTPException(400, f"{type(ex).__name__}: {ex}")


@router.post("/api/profiles/{pid}/integrations/{iid}/poll")
def poll_now(pid: int, iid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        _get(c, pid, iid)
    integrations.poll(iid)
    with db() as c:
        return _out(_get(c, pid, iid))


@router.put("/api/profiles/{pid}/monitor")
def monitor_put(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid, "edit")
        st = json.loads(p["settings"] or "{}")
        m = monitor.settings(p)
        if "enabled" in body:
            m["enabled"] = bool(body["enabled"])
        if int(body.get("interval_s") or 0) in monitor.INTERVALS:
            m["interval_s"] = int(body["interval_s"])
        st["monitor"] = m
        c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
        touch(c, pid)
        return m


@router.get("/api/profiles/{pid}/metrics")
def metrics_get(pid: int, keys: str, since: int = 7200, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return metrics.query(c, pid, [k for k in keys.split(",") if k][:20], since)


@router.put("/api/settings/metrics")
def metrics_days_put(body: dict = Body(...), admin=Depends(require_admin)):
    try:
        days = max(1, min(int(body.get("days") or metrics.DEFAULT_DAYS), metrics.MAX_DAYS))
    except ValueError:
        raise HTTPException(400, "Ungültige Angabe")
    with db() as c:
        set_setting(c, "metrics_days", days)
    return dict(days=days)
