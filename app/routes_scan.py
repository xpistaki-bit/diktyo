"""API: Netzscan-Einstellungen, Scans starten und verfolgen, Posteingang, Erkennungs-Einstellungen."""
import ipaddress
import json

from fastapi import APIRouter, Body, Depends, HTTPException

from . import security
from .auth import profile_access, require_admin, require_user, touch
from .db import audit, db, get_setting, now, set_setting
from .scan import oui, runner
from .worker import worker_status

router = APIRouter()
SCHEDULES = (0, 1, 6, 12, 24, 168)


def _jobs(c, pid, limit=10):
    out = []
    for j in c.execute("SELECT * FROM jobs WHERE profile_id=? AND kind='scan' ORDER BY id DESC LIMIT ?", (pid, limit)):
        out.append(_job_out(j))
    return out


def _job_out(j):
    return dict(id=j["id"], status=j["status"], progress=j["progress"], message=j["message"], created=j["created"], started=j["started"],
                finished=j["finished"], params=json.loads(j["params"] or "{}"), result=json.loads(j["result"] or "{}"))


def _cidr(x):
    try:
        net = ipaddress.ip_network(str(x).strip(), strict=False)
    except ValueError:
        raise HTTPException(400, f"Ungültiges Netz: {x}")
    if net.version != 4:
        raise HTTPException(400, "Gescannt werden IPv4-Netze")
    if net.prefixlen < 20:
        raise HTTPException(400, f"Netz {net} ist zu groß zum Scannen (höchstens /20)")
    return str(net)


@router.get("/api/profiles/{pid}/scan")
def scan_get(pid: int, user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid)
        s = runner.settings(p)
        w = worker_status(c)
        subnets = [dict(cidr=r["cidr"], name=r["name"]) for r in c.execute("SELECT cidr, name FROM subnets WHERE profile_id=?", (pid,))
                   if ipaddress.ip_network(r["cidr"]).version == 4]
        local = [i for i in (w.get("interfaces") or []) if i["cidr"] not in {x["cidr"] for x in subnets}]
        return dict(settings=s, worker=w, subnets=subnets, local=local, jobs=_jobs(c, pid), oui=oui.status(),
                    fingerbank_configured=bool(get_setting(c, "fingerbank_key")),
                    default_targets=runner.resolve_targets(c, pid, dict(s, targets=[])))


@router.put("/api/profiles/{pid}/scan")
def scan_put(pid: int, body: dict = Body(...), user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid, "edit")
        s = runner.settings(p)
        if body.get("mode") in runner.MODES:
            s["mode"] = body["mode"]
        if "targets" in body:
            s["targets"] = sorted({_cidr(x) for x in body.get("targets") or [] if str(x).strip()})
        if "exclude" in body:
            ex = []
            for x in body.get("exclude") or []:
                x = str(x).strip()
                if not x:
                    continue
                try:
                    ex.append(str(ipaddress.ip_network(x, strict=False)))
                except ValueError:
                    raise HTTPException(400, f"Ungültige Adresse: {x}")
            s["exclude"] = ex
        if "schedule_hours" in body:
            h = int(body.get("schedule_hours") or 0)
            s["schedule_hours"] = h if h in SCHEDULES else 0
        if "fingerbank" in body:
            s["fingerbank"] = bool(body["fingerbank"])
        settings = json.loads(p["settings"] or "{}")
        settings["scan"] = s
        c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(settings, ensure_ascii=False), pid))
        audit(c, "scan.settings", user["id"], pid, s)
        touch(c, pid)
    return scan_get(pid, user)


@router.post("/api/profiles/{pid}/scan/run")
def scan_run(pid: int, body: dict = Body(default={}), user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "edit")
        if c.execute("SELECT 1 FROM jobs WHERE profile_id=? AND kind='scan' AND status IN ('queued','running')", (pid,)).fetchone():
            raise HTTPException(409, "Für dieses Profil läuft schon ein Scan")
        # Modus und Netze beim Start festhalten, damit der Verlauf auch bei Fehlern stimmt
        p = c.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
        s = runner.settings(p)
        params = dict(mode=body["mode"] if body.get("mode") in runner.MODES else s["mode"],
                      targets=[_cidr(x) for x in body["targets"]] if body.get("targets") else runner.resolve_targets(c, pid, s))
        cur = c.execute("INSERT INTO jobs(profile_id, kind, params, user_id, created) VALUES(?, 'scan', ?, ?, ?)",
                        (pid, json.dumps(params), user["id"], now()))
        audit(c, "scan.run", user["id"], pid, params)
        w = worker_status(c)
        return dict(job=_job_out(c.execute("SELECT * FROM jobs WHERE id=?", (cur.lastrowid,)).fetchone()), worker=w)


@router.post("/api/profiles/{pid}/devices/{did}/services-scan")
def services_scan(pid: int, did: int, body: dict = Body(default={}), user=Depends(require_user)):
    """Dienste-Scan (nmap) eines Geräts im Hintergrunddienst starten."""
    from .scan import services
    depth = body.get("depth") if body.get("depth") in services.DEPTHS else "standard"
    with db() as c:
        profile_access(c, user, pid, "edit")
        if not c.execute("SELECT 1 FROM devices WHERE id=? AND profile_id=?", (did, pid)).fetchone():
            raise HTTPException(404, "Gerät nicht gefunden")
        ips = [r["address"] for r in c.execute("SELECT address FROM ip_addresses WHERE device_id=? ORDER BY id", (did,))]
        ips = [x for x in ips if ipaddress.ip_address(x).version == 4][:4]
        if not ips:
            raise HTTPException(400, "Das Gerät hat keine IPv4-Adresse")
        for j in c.execute("SELECT * FROM jobs WHERE profile_id=? AND kind='services' AND status IN ('queued','running')", (pid,)):
            if json.loads(j["params"] or "{}").get("device_id") == did:
                return dict(job=_job_out(j))
        w = worker_status(c)
        jid = c.execute("INSERT INTO jobs(profile_id, kind, params, user_id, created) VALUES(?, 'services', ?, ?, ?)",
                        (pid, json.dumps(dict(device_id=did, ips=ips, depth=depth)), user["id"], now())).lastrowid
        audit(c, "device.services_scan", user["id"], pid, dict(id=did, depth=depth))
        return dict(job=_job_out(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()), worker=w,
                    nmap=services.available())


@router.get("/api/jobs/{jid}")
def job_get(jid: int, user=Depends(require_user)):
    with db() as c:
        j = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not j:
            raise HTTPException(404, "Auftrag nicht gefunden")
        profile_access(c, user, j["profile_id"])
        return _job_out(j)


# ------------------------------------------------------------ Posteingang
@router.post("/api/profiles/{pid}/inbox")
def inbox_action(pid: int, body: dict = Body(...), user=Depends(require_user)):
    action, ids = body.get("action"), [int(x) for x in body.get("ids") or []]
    status = {"confirm": "confirmed", "ignore": "ignored", "restore": "discovered"}.get(action)
    if action not in ("confirm", "ignore", "restore", "delete") or not ids:
        raise HTTPException(400, "Unbekannte Aktion")
    with db() as c:
        profile_access(c, user, pid, "edit")
        q = f"id IN ({','.join('?' * len(ids))}) AND profile_id=?"
        if action == "delete":
            n = c.execute(f"DELETE FROM devices WHERE {q} AND status<>'confirmed'", (*ids, pid)).rowcount
        else:
            n = c.execute(f"UPDATE devices SET status=?, updated=? WHERE {q}", (status, now(), *ids, pid)).rowcount
        audit(c, f"inbox.{action}", user["id"], pid, dict(ids=ids))
        touch(c, pid)
    return dict(ok=True, changed=n)


# ------------------------------------------------------------ Erkennung (Admin)
@router.get("/api/settings/detection")
def detection_get(admin=Depends(require_admin)):
    with db() as c:
        from . import metrics
        return dict(fingerbank_key=security.MASK if get_setting(c, "fingerbank_key") else "", oui=oui.status(), worker=worker_status(c),
                    metrics_days=metrics.retention_days(c))


@router.put("/api/settings/detection")
def detection_put(body: dict = Body(...), admin=Depends(require_admin)):
    key = str(body.get("fingerbank_key") or "").strip()
    with db() as c:
        if key != security.MASK:
            set_setting(c, "fingerbank_key", security.encrypt(key) if key else None)
        audit(c, "settings.detection", admin["id"])
    return detection_get(admin)


@router.post("/api/settings/oui/update")
def oui_update(admin=Depends(require_admin)):
    try:
        n = oui.update()
    except Exception as ex:
        raise HTTPException(502, f"Herstellerliste konnte nicht geladen werden: {ex}")
    return dict(entries=n, oui=oui.status())
