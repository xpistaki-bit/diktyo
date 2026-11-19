"""Messwerte (WAN-Traffic, Port-Traffic) als Zeitreihen in SQLite. Aufbewahrung: Standard 2 Tage, höchstens 14."""
import time

from .db import get_setting

DEFAULT_DAYS, MAX_DAYS = 2, 14


def retention_days(c):
    try:
        return max(1, min(int(get_setting(c, "metrics_days", DEFAULT_DAYS)), MAX_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_DAYS


def _series(c, pid, key, unit):
    r = c.execute("SELECT id FROM series WHERE profile_id=? AND key=?", (pid, key)).fetchone()
    if r:
        return r["id"]
    return c.execute("INSERT INTO series(profile_id, key, unit) VALUES(?,?,?)", (pid, key, unit)).lastrowid


def put(c, pid, values, ts=None, unit="bps"):
    ts = int(ts or time.time())
    for key, v in values.items():
        if v is None:
            continue
        c.execute("INSERT INTO metrics(series_id, ts, value) VALUES(?,?,?)", (_series(c, pid, key, unit), ts, float(v)))


def query(c, pid, keys, since_s=7200, points=240):
    """-> {key: [[ts, mittelwert], ...]} in gleich großen Zeitfenstern."""
    since_s = max(300, min(int(since_s), MAX_DAYS * 86400))
    step = max(60, since_s // max(points, 1))
    t0 = int(time.time()) - since_s
    out = {}
    for k in keys:
        r = c.execute("SELECT id FROM series WHERE profile_id=? AND key=?", (pid, k)).fetchone()
        if not r:
            out[k] = []
            continue
        rows = c.execute("SELECT (ts / ?) * ? AS b, AVG(value) AS v FROM metrics WHERE series_id=? AND ts>=? GROUP BY b ORDER BY b",
                         (step, step, r["id"], t0)).fetchall()
        out[k] = [[row["b"], round(row["v"], 1)] for row in rows]
    return dict(step=step, since=since_s, series=out)


def prune(c):
    cut = int(time.time()) - retention_days(c) * 86400
    n = c.execute("DELETE FROM metrics WHERE ts<?", (cut,)).rowcount
    c.execute("DELETE FROM status_events WHERE ts < datetime('now', '-90 days')")
    return n
