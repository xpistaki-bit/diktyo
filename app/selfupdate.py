"""Updates aus der Oberfläche: neue Version auf GitHub erkennen und das Update im Container anstoßen.

Erkennen: app/version.py des Zweigs auf GitHub (raw) – dazu die Versions-Commits („v0.33.1: …“) als Änderungsliste.
Anstoßen (nur Installation per install/setup.sh, z. B. Proxmox-LXC): díktyo legt /var/lib/diktyo/update/request.json
ab; die systemd-Pfad-Einheit diktyo-update.path startet daraufhin /opt/diktyo/self-update.sh als root (Datenbank
sichern, Stand laden, setup.sh). Die Web-App selbst führt nichts als root aus. Docker: Hinweis zum Neubauen.
"""
import json
import os
import pathlib
import re
import time

import httpx

from .db import DATA, get_setting, now, set_setting
from .version import REPO_URL, VERSION

UPDATE_DIR = DATA / "update"
PATH_UNIT = pathlib.Path("/etc/systemd/system/diktyo-update.path")
CONF = pathlib.Path("/opt/diktyo/update.conf")
LOG = pathlib.Path("/var/log/diktyo-update.log")
CHECK_EVERY_S = 12 * 3600


class UpdateError(Exception):
    pass


def _vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:4])


def source():
    repo, branch = REPO_URL.removeprefix("https://github.com/").strip("/"), "main"
    try:
        for line in CONF.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "REPO" and re.fullmatch(r"[\w.-]+/[\w.-]+", v.strip()):
                repo = v.strip()
            if k.strip() == "BRANCH" and re.fullmatch(r"[\w./-]+", v.strip()):
                branch = v.strip()
    except OSError:
        pass
    return repo, branch


def install_kind():
    """systemd (Update per Knopf möglich), docker (neu bauen) oder manual (z. B. Entwicklung)."""
    if PATH_UNIT.exists() and UPDATE_DIR.is_dir() and os.access(UPDATE_DIR, os.W_OK):
        return "systemd"
    if pathlib.Path("/.dockerenv").exists() or os.environ.get("DIKTYO_DOCKER"):
        return "docker"
    return "manual"


def check(c, force=False):
    """Neueste Version auf GitHub (höchstens alle 12 Stunden, außer force). -> gespeichertes Ergebnis"""
    last = get_setting(c, "update_check", {}) or {}
    if not force and last.get("ts") and time.time() - last["ts"] < CHECK_EVERY_S:
        return last
    repo, branch = source()
    try:
        r = httpx.get(f"https://raw.githubusercontent.com/{repo}/{branch}/app/version.py", timeout=10, follow_redirects=True)
        r.raise_for_status()
        m = re.search(r'^VERSION = "([^"]+)"', r.text, re.M)
        if not m:
            raise UpdateError("Versionsangabe auf GitHub nicht gefunden")
        latest = m.group(1)
    except (httpx.HTTPError, UpdateError) as ex:
        out = dict(last, ts=time.time(), checked=now(), error=f"GitHub nicht erreichbar: {ex}"[:200])
        set_setting(c, "update_check", out)
        return out
    notes = []
    if _vt(latest) > _vt(VERSION):
        try:  # Versions-Commits zwischen installierter und neuer Version
            cr = httpx.get(f"https://api.github.com/repos/{repo}/commits", params=dict(sha=branch, per_page=40), timeout=10,
                           headers={"Accept": "application/vnd.github+json"})
            for x in cr.json() if cr.status_code == 200 else []:
                title = (x.get("commit", {}).get("message") or "").split("\n", 1)[0]
                mv = re.match(r"v(\d+(?:\.\d+){1,3}):\s*(.+)", title)
                if mv and _vt(VERSION) < _vt(mv.group(1)) <= _vt(latest):
                    notes.append(dict(version=mv.group(1), title=mv.group(2)[:200]))
        except (httpx.HTTPError, ValueError):
            pass
    out = dict(ts=time.time(), checked=now(), latest=latest, installed=VERSION, available=_vt(latest) > _vt(VERSION), notes=notes[:20],
               repo=repo, branch=branch, error="")
    set_setting(c, "update_check", out)
    return out


def info(c):
    last = get_setting(c, "update_check", {}) or {}
    if last.get("latest"):
        last = dict(last, installed=VERSION, available=_vt(last["latest"]) > _vt(VERSION))
    repo, branch = source()
    return dict(installed=VERSION, kind=install_kind(), check=last, status=status(), repo=repo, branch=branch)


def request(c, user):
    if install_kind() != "systemd":
        raise UpdateError("Diese Installation lässt sich nicht aus der Oberfläche aktualisieren")
    st = status()
    if st.get("state") in ("queued", "running") and time.time() - st.get("ts", 0) < 1800:
        raise UpdateError("Es läuft bereits ein Update")
    tmp = UPDATE_DIR / "request.tmp"
    tmp.write_text(json.dumps(dict(user=user["email"], ts=time.time(), from_version=VERSION)))
    (UPDATE_DIR / "status.json").write_text(json.dumps(dict(state="queued", message="Update angefordert", ts=time.time())))
    tmp.replace(UPDATE_DIR / "request.json")  # erst jetzt sieht die Pfad-Einheit die Anfrage


def status():
    try:
        st = json.loads((UPDATE_DIR / "status.json").read_text())
    except (OSError, ValueError):
        return {}
    if st.get("state") == "queued" and time.time() - st.get("ts", 0) > 120 and (UPDATE_DIR / "request.json").exists():
        st = dict(st, state="error", message="Der Update-Dienst hat die Anfrage nicht übernommen (diktyo-update.path aktiv?)")
    return st


def log_tail(lines=40):
    try:
        return LOG.read_text(errors="replace").splitlines()[-lines:]
    except OSError:
        return []
