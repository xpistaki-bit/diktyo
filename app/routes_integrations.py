"""API: Integrationen (FRITZ!Box, SNMP), Ping-Überwachung, Messwerte."""
import json

from fastapi import APIRouter, Body, Depends, HTTPException

from fastapi.responses import Response

from . import configbackup, integrations, metrics, monitor, security
from .auth import profile_access, require_admin, require_user, text, touch
from .db import audit, db, now, set_setting
from .drivers import DRIVERS, ERRORS, schema

router = APIRouter()


CORE = ("host", "port", "username")


def _out(r):
    st = json.loads(r["state"] or "{}")
    sec = integrations.secrets_of(r)
    return dict(can_backup=configbackup.can_backup(r), cfg_result=st.get("cfg_result"), cfg_ok=st.get("cfg_ok"),
                id=r["id"], driver=r["driver"], name=r["name"], host=r["host"], port=r["port"], username=r["username"],
                options=json.loads(r["options"] or "{}"), secrets={k: security.MASK for k, v in sec.items() if v},
                password=security.MASK if sec.get("password") else "", device_id=r["device_id"], interval_s=r["interval_s"],
                enabled=bool(r["enabled"]), last_poll=r["last_poll"], last_ok=r["last_ok"], last_error=r["last_error"],
                summary=st.get("summary"), result=st.get("result"))


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
    old_sec = integrations.secrets_of(old) if old else {}
    secrets, options = {}, {}
    for f in DRIVERS[drv].FIELDS:
        k = f["key"]
        if k in CORE:
            continue
        v = body.get(k)
        if f.get("secret"):
            v = str(v or "")
            if v == security.MASK:
                v = old_sec.get(k, "")
            if v:
                secrets[k] = v
        elif f.get("type") == "select":
            allowed = [o[0] for o in f.get("options", [])]
            options[k] = v if v in allowed else f.get("default")
        elif v not in (None, ""):
            options[k] = str(v).strip()[:120]
    port = body.get("port")
    return dict(driver=drv, name=text(body, "name", 80) or DRIVERS[drv].NAME, host=host, port=int(port) if str(port or "").isdigit() else None,
                username=text(body, "username", 80), secret=security.encrypt(json.dumps(secrets)) if secrets else "",
                options=json.dumps(options), interval_s=interval, enabled=1 if body.get("enabled", True) else 0,
                device_id=int(body["device_id"]) if body.get("device_id") else None, _secrets=secrets, _options=options)


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
        cur = c.execute("""INSERT INTO integrations(profile_id, driver, name, host, port, username, secret, options, interval_s, enabled, device_id, created)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (pid, v["driver"], v["name"], v["host"], v["port"], v["username"], v["secret"],
                                                               v["options"], v["interval_s"], v["enabled"], v["device_id"], now()))
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
        c.execute("""UPDATE integrations SET name=?, host=?, port=?, username=?, secret=?, options=?, interval_s=?, enabled=?, device_id=?, last_poll=NULL
                     WHERE id=?""", (v["name"], v["host"], v["port"], v["username"], v["secret"], v["options"], v["interval_s"], v["enabled"],
                                    v["device_id"], iid))
        st = json.loads(old["state"] or "{}")
        if st.pop("ssh_hostkey", None) is not None or st.pop("token", None) is not None:  # nach dem Speichern neu anmelden / Schlüssel neu lernen
            c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st, ensure_ascii=False), iid))
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
    conf = {**v["_options"], **v["_secrets"], "host": v["host"], "port": v["port"], "username": v["username"]}
    try:
        return dict(ok=True, result=DRIVERS[v["driver"]].test(conf))
    except ERRORS as ex:
        raise HTTPException(400, str(ex))
    except Exception as ex:
        raise HTTPException(400, f"{type(ex).__name__}: {ex}")


@router.post("/api/profiles/{pid}/integrations/diagnose")
def diagnose(pid: int, body: dict = Body(...), user=Depends(require_user)):
    """Schrittweise Fehlersuche (bisher für SNMP): Netzweg, Erreichbarkeit, SNMP-Dienst, Anmeldung."""
    import ipaddress
    with db() as c:
        profile_access(c, user, pid, "edit")
        old = _get(c, pid, int(body["id"])) if body.get("id") else None
        v = _body(body, old)
        drv = DRIVERS[v["driver"]]
        if not hasattr(drv, "diagnose"):
            raise HTTPException(400, "Für diese Integration gibt es keine Diagnose")
        # Router zwischen díktyo und Gerät: ein Gerät mit Adressen in díktyos Netz und im Netz des Ziels
        hint = None
        try:
            from .scan import netinfo
            tgt = ipaddress.ip_network(f'{v["host"]}/24', strict=False)
            local = [ipaddress.ip_network(i["cidr"]) for i in netinfo.interfaces()]
            by_dev = {}
            for r in c.execute("""SELECT a.device_id, a.address, d.name, d.type FROM ip_addresses a JOIN devices d ON d.id=a.device_id
                                  WHERE a.profile_id=? AND d.type IN ('router','mesh','firewall')""", (pid,)):
                by_dev.setdefault(r["device_id"], []).append(r)
            for rows in by_dev.values():
                ips = [ipaddress.ip_address(r["address"]) for r in rows]
                wan = next((ip for ip in ips if ip in tgt and str(ip) != v["host"]), None)
                if wan and any(ip in n for ip in ips for n in local):
                    hint = (str(wan), rows[0]["name"])
                    break
        except ValueError:
            pass
    conf = {**v["_options"], **v["_secrets"], "host": v["host"], "port": v["port"], "username": v["username"]}
    try:
        return drv.diagnose(conf, hint)
    except ERRORS as ex:
        raise HTTPException(400, str(ex))


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


@router.get("/api/profiles/{pid}/events")
def events_list(pid: int, limit: int = 30, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        rows = c.execute("SELECT * FROM events WHERE profile_id=? ORDER BY id DESC LIMIT ?", (pid, max(1, min(limit, 200)))).fetchall()
        return dict(events=[dict(id=r["id"], ts=r["ts"], kind=r["kind"], device_id=r["device_id"], data=json.loads(r["data"] or "{}"),
                                 delivered=r["delivered"]) for r in rows])


# ------------------------------------------------------------ Konfigurations-Backups
@router.post("/api/profiles/{pid}/integrations/{iid}/config-backup")
def config_backup_now(pid: int, iid: int, body: dict = Body(default={}), user=Depends(require_user)):
    import re
    totp = str(body.get("totp") or "").replace(" ", "")
    if totp and not re.fullmatch(r"\d{6,8}", totp):
        raise HTTPException(400, "Der Code aus der App hat 6 Ziffern")
    with db() as c:
        profile_access(c, user, pid, "edit")
        _get(c, pid, iid)
    res = configbackup.run(iid, interactive=True, totp=totp or None)
    if res["status"] == "error":
        raise HTTPException(400, res["message"])
    return res


def _sf(pid, iid, user, action):
    from .drivers import DRIVERS, ERRORS
    with db() as c:
        profile_access(c, user, pid, "edit")
        row = _get(c, pid, iid)
    drv = DRIVERS[row["driver"]]
    if not hasattr(drv, "second_factor_state"):
        raise HTTPException(400, "Diese Integration kennt keinen zweiten Faktor")
    state = json.loads(row["state"] or "{}")
    try:
        if action == "state":
            out = dict(state=drv.second_factor_state(integrations.conf_of(row), state))
        else:
            drv.second_factor_stop(integrations.conf_of(row), state)
            out = dict(state="stopped")
    except ERRORS as ex:
        raise HTTPException(400, str(ex))
    with db() as c:
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()["state"] or "{}")
        if "sf_token" not in state:
            st.pop("sf_token", None)
        c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st, ensure_ascii=False), iid))
    return out


@router.get("/api/profiles/{pid}/integrations/{iid}/second-factor")
def second_factor_state(pid: int, iid: int, user=Depends(require_user)):
    return _sf(pid, iid, user, "state")


@router.delete("/api/profiles/{pid}/integrations/{iid}/second-factor")
def second_factor_stop(pid: int, iid: int, user=Depends(require_user)):
    return _sf(pid, iid, user, "stop")


@router.get("/api/profiles/{pid}/configs")
def configs_list(pid: int, device_id: int = 0, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return dict(configs=configbackup.listing(c, pid, device_id or None))


def _cfg(c, pid, cid):
    r = c.execute("SELECT * FROM config_backups WHERE id=? AND profile_id=?", (cid, pid)).fetchone()
    if not r:
        raise HTTPException(404, "Konfigurations-Backup nicht gefunden")
    return r


@router.get("/api/profiles/{pid}/configs/{cid}/download")
def config_download(pid: int, cid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        r = _cfg(c, pid, cid)
        audit(c, "config.download", user["id"], pid, dict(id=cid))
    data = configbackup.read(cid)
    return Response(data, media_type="text/plain; charset=utf-8" if r["is_text"] else "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{r["filename"]}"'})


@router.get("/api/profiles/{pid}/configs/{cid}/diff")
def config_diff(pid: int, cid: int, other: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        d = configbackup.diff(c, pid, cid, other)
    if d is None:
        raise HTTPException(400, "Nur Text-Konfigurationen lassen sich vergleichen")
    return d


@router.delete("/api/profiles/{pid}/configs/{cid}")
def config_delete(pid: int, cid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        _cfg(c, pid, cid)
        c.execute("DELETE FROM config_backups WHERE id=?", (cid,))
    configbackup.path(cid).unlink(missing_ok=True)
    return dict(ok=True)
