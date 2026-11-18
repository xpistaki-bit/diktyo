"""díktyo-Hintergrunddienst: arbeitet Aufträge ab (Netzscan) und startet geplante Scans.

Start: python -m app.worker   (LXC: systemd-Dienst diktyo-worker, Docker: neben der Web-App im selben Container)
"""
import datetime
import json
import os
import signal
import time
import traceback

from . import catalog
from .db import db, get_setting, migrate, now, set_setting
from .scan import discover, ident, netinfo, runner

POLL_S = 2
SCHEDULE_EVERY_S = 60
_stop = False


def log(*a):
    print(datetime.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def heartbeat():
    with db() as c:
        set_setting(c, "worker", dict(ts=time.time(), pid=os.getpid(), raw=netinfo.has_raw(), nmap=discover.nmap_available(),
                                      interfaces=netinfo.interfaces(), gateway=netinfo.default_gateway()))


def enqueue_scheduled():
    with db() as c:
        for p in c.execute("SELECT * FROM profiles").fetchall():
            hours = runner.settings(p).get("schedule_hours") or 0
            if not hours:
                continue
            busy = c.execute("SELECT 1 FROM jobs WHERE profile_id=? AND kind='scan' AND status IN ('queued','running')", (p["id"],)).fetchone()
            if busy:
                continue
            last = c.execute("SELECT created FROM jobs WHERE profile_id=? AND kind='scan' ORDER BY id DESC LIMIT 1", (p["id"],)).fetchone()
            if last and datetime.datetime.fromisoformat(last["created"]) > datetime.datetime.now() - datetime.timedelta(hours=hours):
                continue
            c.execute("INSERT INTO jobs(profile_id, kind, params, created) VALUES(?, 'scan', ?, ?)",
                      (p["id"], json.dumps(dict(scheduled=True)), now()))
            log(f"geplanter Scan für Profil {p['id']} eingereiht")


def next_job():
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        j = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if j:
            c.execute("UPDATE jobs SET status='running', started=?, progress=0, message='' WHERE id=?", (now(), j["id"]))
        return j


def run_job(j):
    log(f"Auftrag {j['id']} ({j['kind']}, Profil {j['profile_id']}) startet")
    try:
        if j["kind"] == "scan":
            res = runner.run(j["id"], log)
        else:
            raise RuntimeError(f"unbekannter Auftrag {j['kind']}")
        with db() as c:
            c.execute("UPDATE jobs SET status='done', progress=100, message='', result=?, finished=? WHERE id=?",
                      (json.dumps(res, ensure_ascii=False), now(), j["id"]))
        log(f"Auftrag {j['id']} fertig: {res.get('hosts')} Geräte, {res.get('new')} neu, {res.get('duration')} s")
    except Exception as ex:
        traceback.print_exc()
        with db() as c:
            c.execute("UPDATE jobs SET status='error', message=?, finished=? WHERE id=?", (str(ex)[:500], now(), j["id"]))


def main():
    def stop(*_):
        global _stop
        _stop = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    migrate()
    with db() as c:
        catalog.merge_seed(c)
        ident.merge_seed(c)
        n = c.execute("UPDATE jobs SET status='error', message='Abgebrochen: Hintergrunddienst wurde neu gestartet', finished=? "
                      "WHERE status='running'", (now(),)).rowcount
    if n:
        log(f"{n} abgebrochene Aufträge markiert")
    log(f"Hintergrunddienst läuft (nmap: {'ja' if discover.nmap_available() else 'nein'}, "
        f"Betriebssystem-Erkennung: {'ja' if netinfo.has_raw() else 'nein, CAP_NET_RAW fehlt'})")
    last_beat = last_sched = 0
    while not _stop:
        t = time.time()
        if t - last_beat > 10:
            heartbeat()
            last_beat = t
        if t - last_sched > SCHEDULE_EVERY_S:
            try:
                enqueue_scheduled()
            except Exception as ex:
                log("Zeitplan:", ex)
            last_sched = t
        j = next_job()
        if j:
            run_job(j)
            continue
        time.sleep(POLL_S)
    log("Hintergrunddienst beendet")


def worker_status(c):
    w = get_setting(c, "worker") or {}
    return dict(running=bool(w) and time.time() - w.get("ts", 0) < 45, **{k: w.get(k) for k in ("raw", "nmap", "interfaces", "gateway")})


if __name__ == "__main__":
    main()
