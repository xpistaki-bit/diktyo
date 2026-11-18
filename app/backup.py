"""Sicherung (wie PanelAtlas): ZIP mit allen Daten -> lokaler Ordner / WebDAV / rclone. Dazu Import und Wiederherstellung.

Zugangsdaten (SMTP, Sicherungsziele, später Geräte) liegen in der Datenbank mit dem Schlüssel dieser Installation verschlüsselt.
Für die Sicherung werden sie mit einer Backup-Passphrase neu verschlüsselt; ohne Passphrase bleiben sie draußen.
"""
import base64
import datetime
import hashlib
import io
import json
import pathlib
import secrets
import shutil
import subprocess
import tempfile
import zipfile

import httpx
from cryptography.fernet import Fernet, InvalidToken

from . import export, security
from .db import get_setting, now, set_setting
from .version import VERSION

FORMAT = "diktyo-backup"
PROFILE_TABLES = ("locations", "devices", "vlans", "subnets", "ip_addresses", "links")


class BackupError(Exception):
    pass


# ------------------------------------------------------------ Passphrase
def _pp_fernet(passphrase, salt):
    key = hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
    return Fernet(base64.urlsafe_b64encode(key))


def backup_passphrase(c):
    enc = (get_setting(c, "backup", {}) or {}).get("passphrase")
    return security.decrypt(enc) if enc else ""


def _settings_for_export(c, f):
    """Einstellungen mit umverschlüsselten Geheimnissen (f = Fernet der Passphrase oder None)."""
    def move(enc):
        if not enc or not f:
            return ""
        try:
            return "pp:" + f.encrypt(security.decrypt(enc).encode()).decode()
        except ValueError:
            return ""

    smtp = dict(get_setting(c, "smtp", {}) or {})
    if smtp.get("password"):
        smtp["password"] = move(smtp["password"])
    bk = dict(get_setting(c, "backup", {}) or {})
    bk.pop("passphrase", None)
    bk["targets"] = [dict(t, password=move(t["password"])) if t.get("password") else dict(t) for t in bk.get("targets", [])]
    return dict(registration_open=get_setting(c, "registration_open", False), smtp=smtp, backup=bk)


# ------------------------------------------------------------ Export
def export_data(c):
    pp = backup_passphrase(c)
    salt = secrets.token_bytes(16)
    f = _pp_fernet(pp, salt) if pp else None
    q = lambda sql, *a: [dict(r) for r in c.execute(sql, a)]  # noqa: E731
    devices = q("SELECT * FROM devices")
    used_models = {d["model_id"] for d in devices if d["model_id"]}
    models = q("SELECT * FROM device_models")
    return dict(
        format=FORMAT, version=1, app_version=VERSION, created=now(),
        secrets=dict(kdf="scrypt", salt=salt.hex()) if f else None,
        users=q("SELECT id, email, pw_hash, is_admin, lang, created, last_login FROM users"),
        profiles=q("SELECT * FROM profiles"), profile_members=q("SELECT * FROM profile_members"),
        locations=q("SELECT * FROM locations"), devices=devices,
        interfaces=q("SELECT * FROM interfaces"), links=q("SELECT * FROM links"),
        vlans=q("SELECT * FROM vlans"), subnets=q("SELECT * FROM subnets"), ip_addresses=q("SELECT * FROM ip_addresses"),
        port_vlans=q("SELECT * FROM port_vlans"),
        device_models=[m for m in models if m["custom"]],
        ident_rules=q("SELECT * FROM ident_rules WHERE custom=1"),
        model_keys={str(m["id"]): [m["manufacturer"], m["model"]] for m in models if m["id"] in used_models or m["custom"]},
        settings=_settings_for_export(c, f),
    )


def _safe(s):
    return "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in str(s)).strip() or "unbenannt"


def build_zip(c, with_documents=True):
    buf = io.BytesIO()
    data = export_data(c)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("export.json", json.dumps(data, ensure_ascii=False, indent=1))
        if with_documents:
            for p in data["profiles"]:
                base = f'dokumente/{_safe(p["name"])}-{p["id"]}/'
                try:
                    z.writestr(base + "netzwerk.pdf", export.profile_pdf(c, p["id"]))
                    z.writestr(base + "geraete.csv", export.devices_csv(c, p["id"]))
                    z.writestr(base + "ip-adressen.csv", export.ips_csv(c, p["id"]))
                except Exception as ex:  # ein defekter Eintrag darf die Sicherung nicht verhindern
                    z.writestr(base + "FEHLER.txt", str(ex))
    return buf.getvalue()


def filename():
    return "diktyo-sicherung-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip"


def run(c, targets):
    data = build_zip(c)
    fname = filename()
    results = []
    for t in targets:
        kind = t.get("type")
        try:
            if kind == "local":
                d = pathlib.Path(t["path"])
                d.mkdir(parents=True, exist_ok=True)
                (d / fname).write_bytes(data)
                results.append(dict(target=f"Ordner {d}", ok=True, detail=fname))
            elif kind == "webdav":
                url = t["url"].rstrip("/") + "/" + fname
                pw = security.decrypt(t["password"]) if t.get("password") else ""
                auth = (t.get("user", ""), pw) if t.get("user") else None
                r = httpx.put(url, content=data, auth=auth, timeout=120)
                r.raise_for_status()
                results.append(dict(target=f"WebDAV {t['url']}", ok=True, detail=fname))
            elif kind == "rclone":
                if not shutil.which("rclone"):
                    raise RuntimeError("rclone ist nicht installiert (apt install rclone, danach 'rclone config')")
                with tempfile.TemporaryDirectory() as td:
                    p = pathlib.Path(td) / fname
                    p.write_bytes(data)
                    cp = subprocess.run(["rclone", "copy", str(p), t["remote"]], capture_output=True, text=True, timeout=600)
                    if cp.returncode:
                        raise RuntimeError(cp.stderr.strip()[-400:] or "rclone-Fehler")
                results.append(dict(target=f"rclone {t['remote']}", ok=True, detail=fname))
            else:
                raise RuntimeError("unbekannter Zieltyp")
        except Exception as ex:
            results.append(dict(target=f"{kind} {t.get('path') or t.get('url') or t.get('remote') or ''}", ok=False, detail=str(ex)))
    return results, len(data)


# ------------------------------------------------------------ Import / Wiederherstellung
def read_zip(raw):
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        exp = json.loads(z.read("export.json"))
    except Exception:
        raise BackupError("Keine gültige Sicherungsdatei")
    if exp.get("format") != FORMAT:
        raise BackupError("Keine gültige Sicherungsdatei")
    return exp


def _insert(c, table, row, skip=("id",)):
    cols = [k for k in row if k not in skip]
    cur = c.execute(f"INSERT INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", [row[k] for k in cols])
    return cur.lastrowid


def _model_map(c, exp):
    """Alte Katalog-IDs -> IDs dieser Installation (Abgleich über Hersteller + Modell, eigene Einträge werden angelegt)."""
    have = {(r["manufacturer"], r["model"]): r["id"] for r in c.execute("SELECT id, manufacturer, model FROM device_models")}
    for m in exp.get("device_models", []):
        if (m["manufacturer"], m["model"]) not in have:
            have[(m["manufacturer"], m["model"])] = _insert(c, "device_models", dict(m, custom=1))
    return {int(k): have.get(tuple(v)) for k, v in exp.get("model_keys", {}).items()}


def _import_rules(c, exp):
    have = {r["key"] for r in c.execute("SELECT key FROM ident_rules")}
    for r in exp.get("ident_rules", []):
        if r["key"] not in have:
            _insert(c, "ident_rules", dict(r, custom=1))


def _import_profiles(c, exp, umap, rename):
    """Importiert alle Profile samt Inhalt. umap: alte Benutzer-ID -> neue ID (oder None)."""
    mmap = _model_map(c, exp)
    _import_rules(c, exp)
    names = {r["name"] for r in c.execute("SELECT name FROM profiles")}
    pmap, lmap, dmap, imap, vmap = {}, {}, {}, {}, {}
    for p in exp.get("profiles", []):
        name = p["name"] + (" (importiert)" if rename and p["name"] in names else "")
        pmap[p["id"]] = _insert(c, "profiles", dict(p, name=name))
    for m in exp.get("profile_members", []):
        uid = umap.get(m["user_id"])
        if uid and m["profile_id"] in pmap:
            c.execute("INSERT OR IGNORE INTO profile_members(profile_id, user_id, role) VALUES(?,?,?)", (pmap[m["profile_id"]], uid, m["role"]))
    locs = [x for x in exp.get("locations", []) if x["profile_id"] in pmap]
    for x in locs:
        lmap[x["id"]] = _insert(c, "locations", dict(x, profile_id=pmap[x["profile_id"]], parent_id=None))
    for x in locs:
        if x["parent_id"] in lmap:
            c.execute("UPDATE locations SET parent_id=? WHERE id=?", (lmap[x["parent_id"]], lmap[x["id"]]))
    for x in exp.get("devices", []):
        if x["profile_id"] in pmap:
            dmap[x["id"]] = _insert(c, "devices", dict(x, profile_id=pmap[x["profile_id"]], model_id=mmap.get(x["model_id"]),
                                                      location_id=lmap.get(x["location_id"])))
    for x in exp.get("interfaces", []):
        if x["device_id"] in dmap:
            imap[x["id"]] = _insert(c, "interfaces", dict(x, device_id=dmap[x["device_id"]]))
    for x in exp.get("links", []):
        if x["a_if"] in imap and x["b_if"] in imap and x["profile_id"] in pmap:
            _insert(c, "links", dict(x, profile_id=pmap[x["profile_id"]], a_if=imap[x["a_if"]], b_if=imap[x["b_if"]]))
    for x in exp.get("vlans", []):
        if x["profile_id"] in pmap:
            vmap[x["id"]] = _insert(c, "vlans", dict(x, profile_id=pmap[x["profile_id"]]))
    for x in exp.get("subnets", []):
        if x["profile_id"] in pmap:
            _insert(c, "subnets", dict(x, profile_id=pmap[x["profile_id"]], vlan_id=vmap.get(x["vlan_id"])))
    for x in exp.get("ip_addresses", []):
        if x["profile_id"] in pmap and (x["device_id"] is None or x["device_id"] in dmap):
            _insert(c, "ip_addresses", dict(x, profile_id=pmap[x["profile_id"]], device_id=dmap.get(x["device_id"]),
                                            interface_id=imap.get(x["interface_id"])))
    for x in exp.get("port_vlans", []):
        if x["interface_id"] in imap and x["vlan_id"] in vmap:
            c.execute("INSERT OR IGNORE INTO port_vlans(interface_id, vlan_id, tagged) VALUES(?,?,?)",
                      (imap[x["interface_id"]], vmap[x["vlan_id"]], x["tagged"]))
    return dict(profiles=len(pmap), devices=len(dmap)), list(pmap.values())


def import_profiles(c, exp, owner_id):
    """Profile aus einer Sicherung in diese Installation übernehmen. Besitzer wird owner_id; Mitglieder, deren
    E-Mail-Adresse es hier gibt, behalten ihre Rolle."""
    by_email = {r["email"]: r["id"] for r in c.execute("SELECT id, email FROM users")}
    umap = {u["id"]: by_email.get(u["email"]) for u in exp.get("users", [])}
    res, new_ids = _import_profiles(c, exp, umap, rename=True)
    for pid in new_ids:
        c.execute("""INSERT INTO profile_members(profile_id, user_id, role) VALUES(?,?,'owner')
                     ON CONFLICT(profile_id, user_id) DO UPDATE SET role='owner'""", (pid, owner_id))
    return res


def restore_all(c, exp, passphrase=""):
    """Vollständige Wiederherstellung in eine leere Installation (Konten, Profile, Einstellungen)."""
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        raise BackupError("Wiederherstellen ist nur in einer leeren Installation möglich")
    f = None
    if exp.get("secrets") and passphrase:
        f = _pp_fernet(passphrase, bytes.fromhex(exp["secrets"]["salt"]))
    dropped = []

    def back(val, label):
        if not val:
            return ""
        if not str(val).startswith("pp:") or not f:
            dropped.append(label)
            return ""
        try:
            return security.encrypt(f.decrypt(val[3:].encode()).decode())
        except InvalidToken:
            raise BackupError("Die Backup-Passphrase ist falsch")

    st = exp.get("settings", {})
    smtp = dict(st.get("smtp") or {})
    if smtp.get("password"):
        smtp["password"] = back(smtp["password"], "SMTP")
    bk = dict(st.get("backup") or {})
    bk["targets"] = [dict(t, password=back(t.get("password"), t.get("type", ""))) for t in bk.get("targets", [])]
    umap = {u["id"]: _insert(c, "users", u) for u in exp.get("users", [])}
    res, _ = _import_profiles(c, exp, umap, rename=False)
    set_setting(c, "registration_open", bool(st.get("registration_open")))
    set_setting(c, "smtp", smtp)
    set_setting(c, "backup", bk)
    return dict(res, users=len(umap), secrets_dropped=sorted(set(dropped)))
