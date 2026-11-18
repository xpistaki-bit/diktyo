"""Herstellerliste (IEEE OUI). Wird zur Laufzeit geladen und zwischengespeichert, nicht mit dem Repository verteilt."""
import csv
import io
import threading
import time

import httpx

from ..db import DATA

URLS = [  # MA-L (24 Bit), MA-M (28 Bit), MA-S (36 Bit)
    ("https://standards-oui.ieee.org/oui/oui.csv", 6),
    ("https://standards-oui.ieee.org/oui28/mam.csv", 7),
    ("https://standards-oui.ieee.org/oui36/oui36.csv", 9),
]
PATH = DATA / "oui.csv"
MAX_AGE = 30 * 86400
_cache = None
_lock = threading.Lock()


def _parse(text, hexlen):
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 3 and row[0] != "Registry":
            out[row[1].strip().upper()[:hexlen]] = row[2].strip()
    return out


def update(timeout=60):
    """Lädt die Listen von der IEEE und speichert sie zusammengeführt. -> Anzahl Einträge."""
    rows = {}
    for url, n in URLS:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": "diktyo"})
        r.raise_for_status()
        rows.update(_parse(r.text, n))
    if len(rows) < 1000:
        raise RuntimeError("Herstellerliste unvollständig")
    buf = io.StringIO()
    w = csv.writer(buf)
    for k in sorted(rows):
        w.writerow([k, rows[k]])
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    tmp.replace(PATH)
    global _cache
    with _lock:
        _cache = None
    return len(rows)


def status():
    if not PATH.exists():
        return dict(entries=0, updated=None)
    return dict(entries=len(_load()), updated=time.strftime("%Y-%m-%d %H:%M", time.localtime(PATH.stat().st_mtime)))


def ensure(log=print):
    """Lädt die Liste, wenn sie fehlt oder älter als 30 Tage ist. Fehler sind nicht fatal."""
    if PATH.exists() and time.time() - PATH.stat().st_mtime < MAX_AGE:
        return
    try:
        n = update()
        log(f"Herstellerliste aktualisiert ({n} Einträge)")
    except Exception as ex:
        log(f"Herstellerliste nicht geladen: {ex}")


def _load():
    global _cache
    with _lock:
        if _cache is None:
            _cache = {}
            if PATH.exists():
                for row in csv.reader(io.StringIO(PATH.read_text(encoding="utf-8"))):
                    if len(row) == 2:
                        _cache[row[0]] = row[1]
        return _cache


def is_random(mac):
    """Lokal verwaltete MAC (zweites Bit des ersten Bytes): typisch für die Privatsphäre-Funktion von Smartphones."""
    try:
        return bool(int(mac.replace(":", "")[:2], 16) & 0x02)
    except ValueError:
        return False


def vendor(mac):
    h = mac.replace(":", "").replace("-", "").upper()
    if len(h) != 12 or is_random(mac):
        return ""
    db = _load()
    return db.get(h[:9]) or db.get(h[:7]) or db.get(h[:6]) or ""
