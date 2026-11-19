"""Konfigurations-Backups von Geräten (FRITZ!Box, ASUS, Switch per SSH). Dateien liegen verschlüsselt unter DATA/configs."""
import difflib
import hashlib
import json
import time

from . import security
from .db import DATA, db, now, parse_ts
from .drivers import DRIVERS, ERRORS

DIR = DATA / "configs"
KEEP = 30  # Stände je Gerät
PERIOD = {"daily": 86400, "weekly": 7 * 86400}


def path(cid):
    return DIR / f"{cid}.bin"


def can_backup(row):
    return getattr(DRIVERS.get(row["driver"]), "CAN_BACKUP", False)


def due(row, t=None):
    if not can_backup(row) or not row["enabled"]:
        return False
    sched = json.loads(row["options"] or "{}").get("cfg_schedule", "weekly")
    if sched not in PERIOD:
        return False
    st = json.loads(row["state"] or "{}")
    last = st.get("cfg_try", 0)
    return (t or time.time()) - last >= PERIOD[sched]


def run(iid, interactive=False, totp=None):
    """Sichert die Konfiguration des Geräts einer Integration. -> dict(status=new|unchanged|error|second_factor, …)

    Verlangt das Gerät einen zweiten Faktor (FRITZ!Box), wird bei einer Sicherung per Knopf die Bestätigung gestartet
    (status=second_factor mit Hinweisen); nach der Bestätigung ruft die Oberfläche run() erneut auf. Beim Zeitplan
    lässt sich das nicht bestätigen – dann gibt es einen Hinweis."""
    from .integrations import conf_of
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (iid,)).fetchone()
    if not row or not can_backup(row):
        return dict(status="error", message="Diese Integration unterstützt kein Konfigurations-Backup")
    state = json.loads(row["state"] or "{}")
    drv = DRIVERS[row["driver"]]
    if totp:
        state.pop("sf_token", None)
        state["totp"] = totp
    try:
        filename, data, is_text = drv.backup(conf_of(row), state)
    except ERRORS as ex:
        res = dict(status="error", message=str(ex))
        if type(ex).__name__ == "SecondFactorRequired":
            if interactive and hasattr(drv, "second_factor_start"):
                try:
                    res = dict(status="second_factor", **drv.second_factor_start(conf_of(row), state))
                except ERRORS as ex2:
                    res = dict(status="error", message=str(ex2))
            else:
                res = dict(status="error", second_factor=True,
                           message="Die FRITZ!Box verlangt für den Export eine Bestätigung (zweiter Faktor). "
                                   "Automatisch geht das nicht – bitte „Konfiguration sichern“ von Hand auslösen und an der FRITZ!Box bestätigen.")
    except Exception as ex:
        res = dict(status="error", message=f"{type(ex).__name__}: {ex}")
    else:
        sha = hashlib.sha256(data).hexdigest()
        with db() as c:
            last = c.execute("SELECT * FROM config_backups WHERE integration_id=? ORDER BY id DESC LIMIT 1", (iid,)).fetchone()
            if last and last["sha256"] == sha:
                res = dict(status="unchanged", id=last["id"], size=len(data))
            else:
                stamp = time.strftime("%Y-%m-%d_%H%M")
                stem, _, ext = filename.rpartition(".")
                fname = f"{stem}_{stamp}.{ext}" if stem else f"{filename}_{stamp}"
                cid = c.execute("""INSERT INTO config_backups(profile_id, device_id, integration_id, created, kind, filename, size, sha256, is_text)
                                   VALUES(?,?,?,?,?,?,?,?,?)""", (row["profile_id"], row["device_id"], iid, now(), row["driver"], fname, len(data),
                                                                  sha, 1 if is_text else 0)).lastrowid
                DIR.mkdir(parents=True, exist_ok=True)
                path(cid).write_bytes(security.encrypt_bytes(data))
                _prune(c, row["device_id"], iid)
                res = dict(status="new", id=cid, size=len(data), filename=fname)
    with db() as c:
        row = c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()
        st = {**json.loads(row["state"] or "{}"), **{k: v for k, v in state.items() if k in ("token", "ssh_hostkey", "sf_token")}}
        if "sf_token" not in state:
            st.pop("sf_token", None)
        if res["status"] == "second_factor":  # Ergebnis erst nach der Bestätigung
            c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st, ensure_ascii=False), iid))
            return res
        st.update(cfg_try=time.time(), cfg_result=dict(res, ts=now()))
        if res["status"] != "error":
            st["cfg_ok"] = now()
        c.execute("UPDATE integrations SET state=? WHERE id=?", (json.dumps(st, ensure_ascii=False), iid))
    return res


def _prune(c, device_id, iid):
    rows = c.execute("SELECT id FROM config_backups WHERE integration_id=? ORDER BY id DESC", (iid,)).fetchall()
    for r in rows[KEEP:]:
        path(r["id"]).unlink(missing_ok=True)
        c.execute("DELETE FROM config_backups WHERE id=?", (r["id"],))


def read(cid):
    return security.decrypt_bytes(path(cid).read_bytes())


def listing(c, pid, device_id=None):
    q = "SELECT * FROM config_backups WHERE profile_id=?" + (" AND device_id=?" if device_id else "") + " ORDER BY id DESC LIMIT 200"
    rows = c.execute(q, (pid, device_id) if device_id else (pid,)).fetchall()
    out = []
    for i, r in enumerate(rows):
        prev = next((x for x in rows[i + 1:] if x["integration_id"] == r["integration_id"]), None)
        out.append(dict(id=r["id"], device_id=r["device_id"], created=r["created"], kind=r["kind"], filename=r["filename"], size=r["size"],
                        is_text=bool(r["is_text"]), prev_id=prev["id"] if prev and r["is_text"] else None))
    return out


def diff(c, pid, cid, other):
    a = c.execute("SELECT * FROM config_backups WHERE id=? AND profile_id=?", (other, pid)).fetchone()
    b = c.execute("SELECT * FROM config_backups WHERE id=? AND profile_id=?", (cid, pid)).fetchone()
    if not a or not b or not (a["is_text"] and b["is_text"]):
        return None
    old = read(a["id"]).decode("utf-8", "replace").splitlines()
    new = read(b["id"]).decode("utf-8", "replace").splitlines()
    lines = list(difflib.unified_diff(old, new, a["filename"], b["filename"], n=2, lineterm=""))
    return dict(old=a["filename"], new=b["filename"], lines=lines[:4000], changed=sum(1 for x in lines if x[:1] in "+-" and x[:3] not in ("+++", "---")))


def last_ok_age(row):
    st = json.loads(row["state"] or "{}")
    return parse_ts(st["cfg_ok"]) if st.get("cfg_ok") else None
