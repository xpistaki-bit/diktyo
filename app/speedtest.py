"""Geschwindigkeitsmessungen: Internet-Speedtest (Cloudflare) und iperf3 zwischen díktyo und einem Gerät.

Internet: misst vom Rechner, auf dem díktyo läuft, gegen speed.cloudflare.com – Ping/Jitter (kleine Anfragen, abzüglich
der Bearbeitungszeit des Servers), Download und Upload mit mehreren parallelen Verbindungen für je einige Sekunden.
Die Datenmenge ist begrenzt (MAX_DOWN/MAX_UP). Ergebnis gilt für díktyos Weg ins Internet (inkl. Router dazwischen).

iperf3: díktyo ist Client, das Gerät braucht einen laufenden Server („iperf3 -s“, Port 5201). Gemessen wird in beide
Richtungen; down = Gerät → díktyo, up = díktyo → Gerät.

Ergebnisse liegen in der Tabelle speedtests (dauerhaft, nicht in den kurzlebigen Messwerten).
"""
import json
import re
import shutil
import statistics
import subprocess
import threading
import time

import httpx

from .db import db, now

BASE = "https://speed.cloudflare.com"
SCHEDULES = (0, 24, 12, 6, 3)            # Stunden zwischen automatischen Internet-Messungen (0 = aus)
DEFAULTS = dict(schedule_hours=0, streams=4, seconds=8)
MAX_DOWN, MAX_UP = 600_000_000, 150_000_000   # Obergrenzen je Messung (Bytes)
CHUNK_DOWN, CHUNK_UP = 25_000_000, 4_000_000
KEEP_DAYS = 730
UA = "diktyo-speedtest"


class SpeedError(Exception):
    pass


def settings(profile_row):
    s = json.loads(profile_row["settings"] or "{}").get("speedtest") or {}
    out = {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}
    if out["schedule_hours"] not in SCHEDULES:
        out["schedule_hours"] = 0
    out["streams"] = max(1, min(int(out["streams"] or 4), 8))
    out["seconds"] = max(3, min(int(out["seconds"] or 8), 20))
    return out


def _client():
    return httpx.Client(base_url=BASE, timeout=httpx.Timeout(15, read=30), headers={"User-Agent": UA}, http2=False)


# ------------------------------------------------------------ Internet
def _server_ms(r):
    """Bearbeitungszeit auf dem Server aus „Server-Timing“ (z. B. „cfSpeedEdge;dur=7, cfSpeedWorker;dur=30“): der größte Wert,
    die Teile überlappen sich."""
    vals = [float(x) for x in re.findall(r"dur=([\d.]+)", r.headers.get("server-timing", ""))]
    return max(vals) if vals else 0.0


def _colo(r):
    """Rechenzentrum aus „cf-ray: 8e12…-FRA“."""
    m = re.search(r"-([A-Z]{3})$", r.headers.get("cf-ray", ""))
    return m.group(1) if m else ""


def latency(cl, n=10, info=None):
    vals = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = cl.get("/__down", params={"bytes": 0})
        dt = (time.perf_counter() - t0) * 1000 - _server_ms(r)
        if r.status_code == 200:
            vals.append(max(0.1, dt))
            if info is not None and not info.get("colo"):
                info["colo"] = _colo(r)
    if not vals:
        raise SpeedError("Keine Antwort von speed.cloudflare.com")
    vals.sort()
    ping = statistics.median(vals)
    jitter = statistics.mean(abs(a - b) for a, b in zip(vals, vals[1:])) if len(vals) > 1 else 0.0
    return round(ping, 1), round(jitter, 1)


def _measure(work, streams, seconds, limit):
    """Startet streams Threads, die bis zum Zeitende arbeiten; zählt Bytes laufend. -> bit/s (ohne die erste Anlaufsekunde)"""
    lock, total, samples = threading.Lock(), [0], []
    t_start = time.perf_counter()
    end = t_start + seconds
    errors = []

    def add(n):
        with lock:
            total[0] += n
            samples.append((time.perf_counter(), total[0]))

    def run():
        try:
            while time.perf_counter() < end and total[0] < limit:
                work(add, end, limit, total)
        except Exception as ex:  # einzelne Verbindung abgebrochen
            errors.append(ex)

    th = [threading.Thread(target=run, daemon=True) for _ in range(streams)]
    for t in th:
        t.start()
    for t in th:
        t.join(seconds + 30)
    if not samples:
        raise SpeedError(f"Messung fehlgeschlagen: {errors[0] if errors else 'keine Daten'}")
    warm = t_start + min(1.0, seconds / 4)
    base = next(((t, b) for t, b in samples if t >= warm), samples[0])
    last = samples[-1]
    dt = last[0] - base[0]
    if dt <= 0.2:
        dt, base = last[0] - t_start, (t_start, 0)
    return round((last[1] - base[1]) * 8 / max(dt, 0.001)), total[0]


def download(cl, streams=4, seconds=8, limit=MAX_DOWN):
    def work(add, end, limit, total):
        with cl.stream("GET", "/__down", params={"bytes": CHUNK_DOWN}) as r:
            if r.status_code != 200:
                raise SpeedError(f"HTTP {r.status_code}")
            for chunk in r.iter_bytes(65536):
                add(len(chunk))
                if time.perf_counter() >= end or total[0] >= limit:
                    break
    return _measure(work, streams, seconds, limit)


def upload(cl, streams=4, seconds=8, limit=MAX_UP):
    block = b"0" * 65536

    def work(add, end, limit, total):
        def body():
            sent = 0
            while sent < CHUNK_UP and time.perf_counter() < end and total[0] < limit:
                yield block
                sent += len(block)
                add(len(block))
        r = cl.post("/__up", content=body(), headers={"Content-Type": "application/octet-stream"})
        if r.status_code >= 400:
            raise SpeedError(f"HTTP {r.status_code}")
    return _measure(work, streams, seconds, limit)


def internet(streams=4, seconds=8, progress=lambda p, m: None):
    """-> dict(down_bps, up_bps, ping_ms, jitter_ms, server, detail)"""
    info = {}
    with _client() as cl:
        progress(5, "Antwortzeit")
        ping, jitter = latency(cl, info=info)
        progress(20, "Download")
        down, dbytes = download(cl, streams, seconds, MAX_DOWN)
        progress(60, "Upload")
        up, ubytes = upload(cl, streams, seconds, MAX_UP)
    return dict(down_bps=down, up_bps=up, ping_ms=ping, jitter_ms=jitter, server=" ".join(x for x in ("Cloudflare", info.get("colo")) if x),
                detail=dict(bytes_down=dbytes, bytes_up=ubytes, streams=streams, seconds=seconds))


# ------------------------------------------------------------ iperf3
def iperf_available():
    return shutil.which("iperf3") is not None


def _iperf_once(host, port, seconds, streams, reverse):
    cmd = ["iperf3", "-c", host, "-p", str(port), "-t", str(seconds), "-P", str(streams), "-J", "--connect-timeout", "4000"]
    if reverse:
        cmd.append("-R")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 25)
    except FileNotFoundError:
        raise SpeedError("iperf3 ist auf dem díktyo-Rechner nicht installiert (apt install iperf3)")
    except subprocess.TimeoutExpired:
        raise SpeedError("iperf3 hat nicht rechtzeitig geantwortet")
    try:
        j = json.loads(p.stdout or "{}")
    except ValueError:
        raise SpeedError((p.stderr or p.stdout or "iperf3 ohne Ergebnis").strip()[:200])
    if j.get("error"):
        msg = j["error"]
        if "connect" in msg.lower() or "refused" in msg.lower():
            msg += f" – läuft auf dem Gerät ein iperf3-Server (iperf3 -s, Port {port})?"
        elif "busy" in msg.lower():
            msg += " – der Server misst gerade mit jemand anderem, später erneut versuchen"
        raise SpeedError(msg)
    end = j.get("end") or {}
    recv, sent = end.get("sum_received") or {}, end.get("sum_sent") or {}
    return dict(bps=round(recv.get("bits_per_second") or 0), retransmits=sent.get("retransmits"),
                rtt_ms=round(((end.get("streams") or [{}])[0].get("sender") or {}).get("mean_rtt", 0) / 1000, 2) or None)


def iperf(host, port=5201, seconds=5, streams=4, progress=lambda p, m: None):
    """-> dict(down_bps (Gerät → díktyo), up_bps (díktyo → Gerät), ping_ms, server, detail)"""
    progress(10, "díktyo → Gerät")
    up = _iperf_once(host, port, seconds, streams, reverse=False)
    progress(55, "Gerät → díktyo")
    down = _iperf_once(host, port, seconds, streams, reverse=True)
    return dict(down_bps=down["bps"], up_bps=up["bps"], ping_ms=up["rtt_ms"], jitter_ms=None, server=f"{host}:{port}",
                detail=dict(retransmits_up=up["retransmits"], retransmits_down=down["retransmits"], streams=streams, seconds=seconds))


# ------------------------------------------------------------ Auftrag, Speicherung
def save(c, pid, kind, res, device_id=None, scheduled=False):
    return c.execute("""INSERT INTO speedtests(profile_id, kind, device_id, ts, down_bps, up_bps, ping_ms, jitter_ms, server, detail, scheduled)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                     (pid, kind, device_id, now(), res.get("down_bps"), res.get("up_bps"), res.get("ping_ms"), res.get("jitter_ms"),
                      res.get("server", ""), json.dumps(res.get("detail") or {}, ensure_ascii=False), 1 if scheduled else 0)).lastrowid


def run_job(job_id, log=print):
    """Hintergrundauftrag kind='speedtest' (params: kind internet|iperf, device_id, host, port, scheduled)."""
    with db() as c:
        j = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        prof = c.execute("SELECT * FROM profiles WHERE id=?", (j["profile_id"],)).fetchone()
    params = json.loads(j["params"] or "{}")
    s = settings(prof)

    def progress(p, msg):
        with db() as c:
            c.execute("UPDATE jobs SET progress=?, message=? WHERE id=?", (p, msg, job_id))

    if params.get("kind") == "iperf":
        res = iperf(params["host"], int(params.get("port") or 5201), seconds=min(s["seconds"], 10), streams=s["streams"], progress=progress)
    else:
        res = internet(streams=s["streams"], seconds=s["seconds"], progress=progress)
    with db() as c:
        sid = save(c, j["profile_id"], params.get("kind") or "internet", res, params.get("device_id"), params.get("scheduled"))
        if (params.get("kind") or "internet") == "internet":
            line = line_rate(c, j["profile_id"])
            if line and res["down_bps"] < 0.5 * line:
                from .scan import runner
                runner.event(c, j["profile_id"], "speed_slow", None, down=f"{res['down_bps'] / 1e6:.0f} Mbit/s", line=f"{line / 1e6:.0f} Mbit/s")
        c.execute("DELETE FROM speedtests WHERE profile_id=? AND ts<?", (j["profile_id"], _days_ago(KEEP_DAYS)))
    log(f"Messung {sid}: ↓ {res['down_bps'] / 1e6:.1f} Mbit/s ↑ {res['up_bps'] / 1e6:.1f} Mbit/s")
    return dict(id=sid, **{k: res[k] for k in ("down_bps", "up_bps", "ping_ms", "jitter_ms", "server")})


def line_rate(c, pid):
    """Gebuchte/synchronisierte Download-Rate laut Router (FRITZ!Box u. a.) oder None."""
    for r in c.execute("SELECT state FROM integrations WHERE profile_id=? AND enabled=1 ORDER BY driver<>'fritzbox', id", (pid,)):
        w = (json.loads(r["state"] or "{}").get("result") or {}).get("wan") or {}
        if w.get("max_down"):
            return w["max_down"]
    return None


def _days_ago(n):
    import datetime as dt
    return (dt.datetime.now().astimezone() - dt.timedelta(days=n)).isoformat(timespec="seconds")


def enqueue(c, pid, kind="internet", user_id=None, **params):
    """Auftrag einreihen, sofern nicht schon einer derselben Art für dasselbe Ziel wartet. -> job_id"""
    for j in c.execute("SELECT id, params FROM jobs WHERE profile_id=? AND kind='speedtest' AND status IN ('queued','running')", (pid,)):
        p = json.loads(j["params"] or "{}")
        if p.get("kind") == kind and p.get("device_id") == params.get("device_id"):
            return j["id"]
    return c.execute("INSERT INTO jobs(profile_id, kind, params, user_id, created) VALUES(?, 'speedtest', ?, ?, ?)",
                     (pid, json.dumps(dict(kind=kind, **params)), user_id, now())).lastrowid


def due(c, prof, t=None):
    """Steht eine geplante Internet-Messung an?"""
    h = settings(prof)["schedule_hours"]
    if not h:
        return False
    import datetime as dt
    last = c.execute("SELECT created FROM jobs WHERE profile_id=? AND kind='speedtest' AND params LIKE '%\"internet\"%' ORDER BY id DESC LIMIT 1",
                     (prof["id"],)).fetchone()
    if not last:
        return True
    from .db import parse_ts
    return parse_ts(last["created"]) <= dt.datetime.now().astimezone() - dt.timedelta(hours=h)


def history(c, pid, kind="internet", device_id=None, limit=200):
    q = "SELECT * FROM speedtests WHERE profile_id=? AND kind=?" + (" AND device_id=?" if device_id else "") + " ORDER BY ts DESC, id DESC LIMIT ?"
    args = (pid, kind, device_id, limit) if device_id else (pid, kind, limit)
    return [dict(id=r["id"], ts=r["ts"], down_bps=r["down_bps"], up_bps=r["up_bps"], ping_ms=r["ping_ms"], jitter_ms=r["jitter_ms"],
                 server=r["server"], scheduled=bool(r["scheduled"]), detail=json.loads(r["detail"] or "{}")) for r in c.execute(q, args)]
