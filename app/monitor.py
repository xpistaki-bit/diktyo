"""Online-Überwachung: pingt die bestätigten Geräte eines Profils im eingestellten Intervall."""
import asyncio
import json

from .db import db, now
from .scan import discover, runner

INTERVALS = (30, 60, 300)
DEFAULTS = dict(enabled=True, interval_s=60)


def settings(profile_row):
    s = json.loads(profile_row["settings"] or "{}").get("monitor") or {}
    out = {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}
    if out["interval_s"] not in INTERVALS:
        out["interval_s"] = 60
    return out


async def _check(targets, concurrency=64):
    """targets: [(device_id, ip, fallback_port|None)] -> {device_id: (online, antwortzeit_ms|None)}"""
    import time
    sem = asyncio.Semaphore(concurrency)
    out = {}

    async def one(did, ip, port):
        async with sem:
            rtt = await discover.ping_rtt(ip, 1.0)
            ok = rtt is not None
            if not ok and port:  # Geräte, die Ping verwerfen, über einen bekannten offenen Port prüfen
                t0 = time.perf_counter()
                ok = await discover.tcp(ip, port, 1.0)
                rtt = round((time.perf_counter() - t0) * 1000, 1) if ok else None
            prev = out.get(did)
            if not prev or not prev[0] or (ok and rtt is not None and (prev[1] is None or rtt < prev[1])):
                out[did] = (ok or bool(prev and prev[0]), rtt if ok else (prev[1] if prev else None))

    await asyncio.gather(*(one(*t) for t in targets))
    return out


def run(pid):
    with db() as c:
        rows = c.execute("""SELECT d.id, d.data, a.address FROM devices d JOIN ip_addresses a ON a.device_id=d.id
                            WHERE d.profile_id=? AND d.status='confirmed'""", (pid,)).fetchall()
    targets = []
    for r in rows:
        ports = (json.loads(r["data"] or "{}").get("seen") or {}).get("ports") or []
        targets.append((r["id"], r["address"], ports[0] if ports else None))
    if not targets:
        return dict(checked=0, online=0)
    res = asyncio.run(_check(targets))
    ts = now()
    from . import metrics
    with db() as c:
        for did, (ok, _) in res.items():
            runner._set_online(c, did, 1 if ok else 0, ts, "ping")
        metrics.put(c, pid, {f"d{did}:rtt": rtt for did, (ok, rtt) in res.items() if ok and rtt is not None}, unit="ms")
    return dict(checked=len(res), online=sum(1 for ok, _ in res.values() if ok))
