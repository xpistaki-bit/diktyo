"""API: Sicherung, Profil-Import und vollständige Wiederherstellung."""
import threading
import time

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Response, UploadFile

from . import backup, security
from .auth import require_admin, touch
from .db import audit, db, get_setting, now, set_setting

router = APIRouter()
TARGET_TYPES = ("local", "webdav", "rclone")


def _settings(c):
    s = dict(get_setting(c, "backup", {}) or {})
    s.setdefault("targets", [])
    s.setdefault("auto_hours", 0)
    return s


def _out(c):
    s = _settings(c)
    return dict(settings=dict(targets=[dict(t, password=security.MASK) if t.get("password") else t for t in s["targets"]],
                              auto_hours=s["auto_hours"], passphrase=security.MASK if s.get("passphrase") else ""),
                last=get_setting(c, "backup_last"))


@router.get("/api/backup/rclone")
def rclone_get(admin=Depends(require_admin)):
    return dict(remotes=backup.rclone_remotes(), config=str(backup.RCLONE_CONF))


@router.post("/api/backup/rclone/drive")
def rclone_drive(body: dict = Body(...), admin=Depends(require_admin)):
    try:
        res = backup.rclone_drive(str(body.get("name") or "gdrive").strip(), str(body.get("token") or ""))
    except backup.BackupError as ex:
        raise HTTPException(400, str(ex))
    with db() as c:
        audit(c, "backup.rclone_drive", admin["id"], detail=dict(name=res["name"]))
    return res


@router.get("/api/backup")
def backup_get(admin=Depends(require_admin)):
    with db() as c:
        return _out(c)


@router.put("/api/backup")
def backup_put(body: dict = Body(...), admin=Depends(require_admin)):
    with db() as c:
        old = _settings(c)
        targets = []
        for i, t in enumerate(body.get("targets") or []):
            kind = t.get("type")
            if kind not in TARGET_TYPES:
                continue
            n = dict(type=kind, path=str(t.get("path") or "").strip(), url=str(t.get("url") or "").strip(),
                     user=str(t.get("user") or "").strip(), remote=str(t.get("remote") or "").strip())
            pw = t.get("password") or ""
            if pw == security.MASK and i < len(old["targets"]):
                n["password"] = old["targets"][i].get("password", "")
            elif pw:
                n["password"] = security.encrypt(pw)
            targets.append({k: v for k, v in n.items() if v})
        pp = body.get("passphrase", security.MASK)
        new = dict(targets=targets, auto_hours=max(0, min(int(body.get("auto_hours") or 0), 24 * 7)))
        if pp == security.MASK:
            if old.get("passphrase"):
                new["passphrase"] = old["passphrase"]
        elif pp:
            if len(pp) < 8:
                raise HTTPException(400, "Die Backup-Passphrase muss mindestens 8 Zeichen haben")
            new["passphrase"] = security.encrypt(pp)
        set_setting(c, "backup", new)
        audit(c, "backup.settings", admin["id"])
        return _out(c)


def run_backup():
    with db() as c:
        results, size = backup.run(c, _settings(c)["targets"])
        last = dict(time=now(), ts=time.time(), results=results, size=size)
        set_setting(c, "backup_last", last)
    return last


@router.post("/api/backup/run")
def backup_run(admin=Depends(require_admin)):
    with db() as c:
        if not _settings(c)["targets"]:
            raise HTTPException(400, "Kein Sicherungsziel eingerichtet")
    return run_backup()


@router.get("/api/backup/download")
def backup_download(admin=Depends(require_admin)):
    with db() as c:
        data = backup.build_zip(c)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{backup.filename()}"'})


@router.post("/api/backup/import")
async def backup_import(file: UploadFile = File(...), admin=Depends(require_admin)):
    try:
        exp = backup.read_zip(await file.read())
    except backup.BackupError as ex:
        raise HTTPException(400, str(ex))
    with db() as c:
        res = backup.import_profiles(c, exp, admin["id"])
        audit(c, "backup.import", admin["id"], detail=res)
        touch(c)
    return res


@router.post("/api/restore")
async def restore(file: UploadFile = File(...), passphrase: str = Form("")):
    """Nur in einer leeren Installation (noch kein Konto): alles aus der Sicherung übernehmen."""
    with db() as c:
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise HTTPException(403, "Wiederherstellen ist nur in einer leeren Installation möglich")
    try:
        exp = backup.read_zip(await file.read())
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            res = backup.restore_all(c, exp, passphrase)
            audit(c, "backup.restore", None, detail=res)
            touch(c)
    except backup.BackupError as ex:
        raise HTTPException(400, str(ex))
    return res


def _auto_backup_loop():
    while True:
        time.sleep(600)
        try:
            with db() as c:
                s = _settings(c)
                last = get_setting(c, "backup_last") or {}
                changed = get_setting(c, "last_change", 0)
            if s.get("auto_hours") and s["targets"] and changed > last.get("ts", 0) and time.time() - last.get("ts", 0) > s["auto_hours"] * 3600:
                run_backup()
        except Exception as ex:  # Hintergrundsicherung darf den Dienst nicht beenden
            print("auto-backup:", ex)


def start_auto_backup():
    threading.Thread(target=_auto_backup_loop, daemon=True).start()
