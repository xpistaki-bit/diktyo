"""díktyo-Hintergrunddienst: arbeitet Aufträge ab (Netzscan) und startet geplante Scans.

Start: python -m app.worker   (LXC: systemd-Dienst diktyo-worker, Docker: neben der Web-App im selben Container)
"""
import datetime
import json
import os
import signal
import time
import traceback

import threading

from . import catalog, configbackup, integrations, metrics, monitor
from .db import db, get_setting, migrate, now, parse_ts, set_setting
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
            if last and parse_ts(last["created"]) > datetime.datetime.now().astimezone() - datetime.timedelta(hours=hours):
                continue
            s = runner.settings(p)
            c.execute("INSERT INTO jobs(profile_id, kind, params, created) VALUES(?, 'scan', ?, ?)",
                      (p["id"], json.dumps(dict(scheduled=True, mode=s["mode"], targets=runner.resolve_targets(c, p["id"], s))), now()))
            log(f"geplanter Scan für Profil {p['id']} eingereiht")
        from . import speedtest
        for p in c.execute("SELECT * FROM profiles").fetchall():
            if speedtest.due(c, p):
                speedtest.enqueue(c, p["id"], "internet", scheduled=True)
                log(f"geplante Internet-Messung für Profil {p['id']} eingereiht")


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
        elif j["kind"] == "services":
            from .scan import services
            res = services.run(j["id"], log)
        elif j["kind"] == "speedtest":
            from . import speedtest
            res = speedtest.run_job(j["id"], log)
        else:
            raise RuntimeError(f"unbekannter Auftrag {j['kind']}")
        with db() as c:
            c.execute("UPDATE jobs SET status='done', progress=100, message='', result=?, finished=? WHERE id=?",
                      (json.dumps(res, ensure_ascii=False), now(), j["id"]))
        if j["kind"] == "scan":
            log(f"Auftrag {j['id']} fertig: {res.get('hosts')} Geräte, {res.get('new')} neu, {res.get('duration')} s")
    except Exception as ex:
        traceback.print_exc()
        with db() as c:
            c.execute("UPDATE jobs SET status='error', message=?, finished=? WHERE id=?", (str(ex)[:500], now(), j["id"]))


def beat_loop():
    """Lebenszeichen aus einem eigenen Thread, damit der Dienst auch während eines langen Scans als laufend gilt."""
    while not _stop:
        try:
            heartbeat()
        except Exception as ex:
            log("Lebenszeichen:", ex)
        time.sleep(10)


def poller():
    """Eigener Thread: Integrationen und Ping-Überwachung laufen weiter, auch während ein langer Scan läuft."""
    last_mon, last_prune, last_sync = {}, 0, {}
    while not _stop:
        t = time.time()
        try:
            with db() as c:
                due = [r["id"] for r in c.execute("SELECT id, interval_s, last_poll FROM integrations WHERE enabled=1").fetchall()
                       if not r["last_poll"] or t - parse_ts(r["last_poll"]).timestamp() >= max(15, r["interval_s"])]
                profiles = c.execute("SELECT * FROM profiles").fetchall()
            for iid in due:
                integrations.poll(iid, log)
            with db() as c:
                cfg_due = [r["id"] for r in c.execute("SELECT * FROM integrations").fetchall() if configbackup.due(r, t)]
            try:
                from . import actions
                actions.run_due_undos(log)
            except Exception as ex:  # Rückschaltungen dürfen den Hintergrunddienst nicht anhalten
                log(f"Zurückschalten: {type(ex).__name__}: {ex}")
            if t - last_sync.get("t", 0) >= 300:  # Änderungsverlauf: Abgleich alle 5 Minuten, Aufräumen täglich
                last_sync["t"] = t
                try:
                    from . import changes
                    with db() as c:
                        for p in profiles:
                            changes.sync(c, p["id"], "")
                        if t - last_sync.get("prune", 0) >= 86400:
                            last_sync["prune"] = t
                            changes.prune(c)
                except Exception as ex:
                    log(f"Änderungsverlauf: {type(ex).__name__}: {ex}")
            try:
                from . import quarantine, schedules
                schedules.run_due(log)
                for p in profiles:
                    quarantine.process(p["id"], log)
            except Exception as ex:
                log(f"Zeitpläne/Quarantäne: {type(ex).__name__}: {ex}")
            for iid in cfg_due:
                res = configbackup.run(iid)
                log(f"Konfigurations-Backup Integration {iid}: {res['status']} {res.get('message', '')}".strip())
            try:
                from . import notify
                for p in profiles:
                    notify.deliver(p["id"], log)
            except Exception as ex:  # Benachrichtigungen dürfen den Dienst nicht anhalten
                log(f"Benachrichtigungen: {type(ex).__name__}: {ex}")
            for p in profiles:
                ms = monitor.settings(p)
                if ms["enabled"] and t - last_mon.get(p["id"], 0) >= ms["interval_s"]:
                    last_mon[p["id"]] = t
                    monitor.run(p["id"])
            if t - last_prune > 3600:
                with db() as c:
                    n = metrics.prune(c)
                if n:
                    log(f"{n} alte Messwerte gelöscht")
                last_prune = t
        except Exception as ex:
            log("Abfrage:", type(ex).__name__, ex)
        time.sleep(5)


def main():
    def stop(*_):
        global _stop
        _stop = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:  # weiche Grenze für offene Dateien auf das Maximum anheben (Scans öffnen viele Verbindungen)
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(hard, 65536) if hard != resource.RLIM_INFINITY else 65536, hard))
    except (ValueError, OSError, ImportError):
        pass
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
    threading.Thread(target=beat_loop, daemon=True, name="beat").start()
    threading.Thread(target=poller, daemon=True, name="poller").start()
    last_sched = 0
    while not _stop:
        t = time.time()
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
    return dict(running=bool(w) and time.time() - w.get("ts", 0) < 60, **{k: w.get(k) for k in ("raw", "nmap", "interfaces", "gateway")})


if __name__ == "__main__":
    main()
