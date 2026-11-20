"""Online-Überwachung: pingt die bestätigten Geräte eines Profils im eingestellten Intervall."""
import asyncio
import json

from .db import db, now
from .scan import discover, runner

INTERVALS = (30, 60, 300)
DEFAULTS = dict(enabled=True, interval_s=60)
OFFLINE_AFTER = 2   # so viele Runden ohne Antwort hintereinander, bevor ein Gerät als offline gilt
_misses = {}        # device_id -> Runden ohne Antwort (lebt im Hintergrunddienst)


def settings(profile_row):
    s = json.loads(profile_row["settings"] or "{}").get("monitor") or {}
    out = {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}
    if out["interval_s"] not in INTERVALS:
        out["interval_s"] = 60
    return out


async def recheck(targets):
    """Einzeln und nacheinander noch einmal prüfen (nach einer Lastspitze verwerfen manche Router/Mesh-Knoten Pings).
    targets: [(device_id, ip, port)] -> {device_id: (online, rtt)}"""
    out = {}
    for did, ip, port in targets[:30]:
        rtt = await discover.ping_rtt(ip, 2.0)
        if rtt is None:
            rtt = await discover.ping_rtt(ip, 3.0)
        if rtt is None and await discover.tcp(ip, port or 80, 2.0):
            rtt = 0.0
        if rtt is not None or did not in out:
            out[did] = (rtt is not None, rtt)
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
            if not ok:  # Geräte, die Ping verwerfen, über einen bekannten offenen Port prüfen (sonst Weboberfläche)
                t0 = time.perf_counter()
                ok = await discover.tcp(ip, port or 80, 1.5)
                rtt = round((time.perf_counter() - t0) * 1000, 1) if ok else None
            if not ok:  # WLAN-Geräte im Stromsparmodus verschlucken gern einen einzelnen Ping: noch einmal mit mehr Geduld
                rtt = await discover.ping_rtt(ip, 2.0)
                ok = rtt is not None
            prev = out.get(did)
            if not prev or not prev[0] or (ok and rtt is not None and (prev[1] is None or rtt < prev[1])):
                out[did] = (ok or bool(prev and prev[0]), rtt if ok else (prev[1] if prev else None))

    await asyncio.gather(*(one(*t) for t in targets))
    return out


def seen_by_others(c, pid, grace):
    """Geräte, die eine andere Quelle als der Ping (FRITZ!Box, Router, SNMP, Scan …) kürzlich online sah. „Kürzlich“ richtet
    sich nach dem Abfrageintervall der Integration (2,5 Intervalle), mindestens grace Sekunden – sonst fiele z. B. ein
    ASUS mit 15-Minuten-Intervall zwischen zwei Abfragen aus der Frist."""
    import time as _t
    per = {}
    for r in c.execute("SELECT driver, MAX(interval_s) AS iv FROM integrations WHERE profile_id=? AND enabled=1 GROUP BY driver", (pid,)):
        per[r["driver"]] = max(grace, 2.5 * (r["iv"] or 0))
    t = _t.time()
    return {r["device_id"] for r in c.execute("""SELECT s.device_id, s.source, s.ts FROM device_seen s JOIN devices d ON d.id=s.device_id
                                                  WHERE d.profile_id=? AND s.source<>'ping'""", (pid,))
            if t - r["ts"] < per.get(r["source"], grace)}


def settings_of(pid):
    with db() as c:
        r = c.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
    return settings(r) if r else dict(DEFAULTS)


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
    grace = max(600, 3 * settings_of(pid)["interval_s"])
    with db() as c:
        was = {r["id"]: r["online"] for r in c.execute("SELECT id, online FROM devices WHERE profile_id=?", (pid,))}
        # Andere Quellen, die das Gerät gerade erst gesehen haben: dann ist es online, auch wenn der Ping nicht durchkommt
        # (z. B. Gerät hinter NAT oder einer Firewall, die ICMP verwirft)
        others = seen_by_others(c, pid, grace)
        for did, (ok, _) in res.items():
            if ok:
                _misses.pop(did, None)
                runner._set_online(c, did, 1, ts, "ping")
                continue
            if did in others:
                _misses.pop(did, None)
                continue
            _misses[did] = _misses.get(did, 0) + 1
            # war es online, erst nach mehreren Runden ohne Antwort als offline melden (einzelne verlorene Pings bei WLAN)
            if was.get(did) != 1 or _misses[did] >= OFFLINE_AFTER:
                runner._set_online(c, did, 0, ts, "ping")
        metrics.put(c, pid, {f"d{did}:rtt": rtt for did, (ok, rtt) in res.items() if ok and rtt is not None}, unit="ms")
    return dict(checked=len(res), online=sum(1 for ok, _ in res.values() if ok))
