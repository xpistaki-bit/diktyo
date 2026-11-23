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
from .db import DATA, get_setting, now, set_setting
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


def _move_secret(enc, f):
    if not enc or not f:
        return ""
    try:
        return "pp:" + f.encrypt(security.decrypt(enc).encode()).decode()
    except ValueError:
        return ""


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
    aiset = dict(get_setting(c, "ai", {}) or {})
    if aiset.get("key"):
        aiset["key"] = move(aiset["key"])
    oid = dict(get_setting(c, "oidc", {}) or {})
    if oid.get("client_secret"):
        oid["client_secret"] = move(oid["client_secret"])
    return dict(registration_open=get_setting(c, "registration_open", False), smtp=smtp, backup=bk, ai=aiset, oidc=oid)


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
        users=q("SELECT id, email, pw_hash, is_admin, lang, created, last_login, oidc_sub FROM users"),
        profiles=q("SELECT * FROM profiles"), profile_members=q("SELECT * FROM profile_members"),
        locations=q("SELECT * FROM locations"), devices=devices,
        interfaces=q("SELECT * FROM interfaces"), links=q("SELECT * FROM links"),
        vlans=q("SELECT * FROM vlans"), subnets=q("SELECT * FROM subnets"), ip_addresses=q("SELECT * FROM ip_addresses"),
        port_vlans=q("SELECT * FROM port_vlans"), port_vlans_plan=q("SELECT * FROM port_vlans_plan"), topo_positions=q("SELECT * FROM topo_positions"),
        changes=q("SELECT * FROM changes"),
        patch_panels=q("SELECT * FROM patch_panels"), cable_runs=q("SELECT * FROM cable_runs"), watch=q("SELECT * FROM watch"),
        device_models=[m for m in models if m["custom"]],
        ident_rules=q("SELECT * FROM ident_rules WHERE custom=1"),
        integrations=[dict(r, secret=_move_secret(r["secret"], f), state="{}") for r in q("SELECT * FROM integrations")],
        model_keys={str(m["id"]): [m["manufacturer"], m["model"]] for m in models if m["id"] in used_models or m["custom"]},
        settings=_settings_for_export(c, f),
    )


def _safe(s):
    return "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in str(s)).strip() or "unbenannt"


def _config_files(c, data):
    """Neueste Konfiguration je Gerät, nur mit Backup-Passphrase (verschlüsselt). -> [(Pfad im ZIP, Inhalt)]"""
    from . import configbackup
    if not data.get("secrets"):
        return []
    f = _pp_fernet(backup_passphrase(c), bytes.fromhex(data["secrets"]["salt"]))
    out, meta = [], []
    for r in c.execute("""SELECT * FROM config_backups WHERE id IN (SELECT MAX(id) FROM config_backups GROUP BY integration_id, device_id)"""):
        try:
            blob = f.encrypt(configbackup.read(r["id"]))
        except (OSError, ValueError):
            continue
        meta.append({k: r[k] for k in r.keys()})
        out.append((f"geraete-konfiguration/{r['id']}.enc", blob))
    data["config_backups"] = meta
    return out


def build_zip(c, with_documents=True):
    buf = io.BytesIO()
    data = export_data(c)
    files = _config_files(c, data)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("export.json", json.dumps(data, ensure_ascii=False, indent=1))
        for name, blob in files:
            z.writestr(name, blob)
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
                    cp = subprocess.run(["rclone", "--config", str(RCLONE_CONF), "copy", str(p), t["remote"]], capture_output=True, text=True, timeout=600)
                    if cp.returncode:
                        raise RuntimeError(rclone_error(cp.stderr, t["remote"]))
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
    exp["_config_blobs"] = {n.split("/")[-1].split(".")[0]: z.read(n) for n in z.namelist() if n.startswith("geraete-konfiguration/")}
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


def _import_profiles(c, exp, umap, rename, fernet=None):
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
    import re as _re
    for x in exp.get("topo_positions", []):  # Knoten-IDs enthalten Geräte-IDs -> umschlüsseln
        m = _re.fullmatch(r"([dg])(\d+)(:\w+)?", x["node"])
        if x["profile_id"] not in pmap or (m and int(m.group(2)) not in dmap):
            continue
        node = f"{m.group(1)}{dmap[int(m.group(2))]}{m.group(3) or ''}" if m else x["node"]
        c.execute("INSERT OR REPLACE INTO topo_positions(profile_id, node, x, y) VALUES(?,?,?,?)", (pmap[x["profile_id"]], node, x["x"], x["y"]))
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
    imap_int = {}
    for x in exp.get("integrations", []):
        if x["profile_id"] in pmap:
            sec = ""
            if x.get("secret", "").startswith("pp:") and fernet:
                try:
                    sec = security.encrypt(fernet.decrypt(x["secret"][3:].encode()).decode())
                except InvalidToken:
                    sec = ""
            imap_int[x["id"]] = _insert(c, "integrations", dict(x, profile_id=pmap[x["profile_id"]], device_id=dmap.get(x["device_id"]), secret=sec,
                                                               state="{}", last_poll=None))
    if fernet:
        from . import configbackup
        for m in exp.get("config_backups", []):
            blob = exp.get("_config_blobs", {}).get(str(m["id"]))
            if not blob or m["profile_id"] not in pmap:
                continue
            try:
                data = fernet.decrypt(blob)
            except InvalidToken:
                continue
            cid = _insert(c, "config_backups", dict(m, profile_id=pmap[m["profile_id"]], device_id=dmap.get(m["device_id"]),
                                                    integration_id=imap_int.get(m["integration_id"])))
            configbackup.DIR.mkdir(parents=True, exist_ok=True)
            configbackup.path(cid).write_bytes(security.encrypt_bytes(data))
    for x in exp.get("port_vlans", []):
        if x["interface_id"] in imap and x["vlan_id"] in vmap:
            c.execute("INSERT OR IGNORE INTO port_vlans(interface_id, vlan_id, tagged, source) VALUES(?,?,?,?)",
                      (imap[x["interface_id"]], vmap[x["vlan_id"]], x["tagged"], x.get("source", "manual")))
    for x in exp.get("port_vlans_plan", []):
        if x["interface_id"] in imap and x["vlan_id"] in vmap:
            c.execute("INSERT OR IGNORE INTO port_vlans_plan(interface_id, vlan_id, tagged) VALUES(?,?,?)",
                      (imap[x["interface_id"]], vmap[x["vlan_id"]], x["tagged"]))
    for x in exp.get("changes", []):  # Änderungsverlauf mitnehmen
        if x["profile_id"] in pmap:
            c.execute("INSERT INTO changes(profile_id, device_id, ts, kind, field, old, new, source, user_id, detail) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (pmap[x["profile_id"]], dmap.get(x["device_id"]), x["ts"], x["kind"], x["field"], x["old"], x["new"], x["source"],
                       umap.get(x["user_id"]), x["detail"]))
    panmap = {}
    for x in exp.get("patch_panels", []):  # Kabel und Patchpanels
        if x["profile_id"] in pmap:
            panmap[x["id"]] = _insert(c, "patch_panels", dict(x, profile_id=pmap[x["profile_id"]], location_id=lmap.get(x["location_id"])))
    for x in exp.get("cable_runs", []):
        if x["profile_id"] in pmap:
            _insert(c, "cable_runs", dict(x, profile_id=pmap[x["profile_id"]], switch_id=dmap.get(x["switch_id"]), device_id=dmap.get(x["device_id"]),
                                          panel_id=panmap.get(x["panel_id"]), outlet_id=panmap.get(x["outlet_id"]),
                                          panel_port=x["panel_port"] if x["panel_id"] in panmap else None,
                                          outlet_port=x["outlet_port"] if x["outlet_id"] in panmap else None))
    for x in exp.get("watch", []):  # Wachliste (beim Import gilt alles bis jetzt als gesehen)
        if x["device_id"] in dmap and x["profile_id"] in pmap:
            c.execute("INSERT OR IGNORE INTO watch(device_id, profile_id, created, ack, ack_change, ack_status, note) VALUES(?,?,?,?,"
                      "(SELECT COALESCE(MAX(id), 0) FROM changes), (SELECT COALESCE(MAX(id), 0) FROM status_events), ?)",
                      (dmap[x["device_id"]], pmap[x["profile_id"]], x["created"], x["ack"], x.get("note", "")))
    for new_pid in pmap.values():  # erster Abgleich nach dem Import still (sonst stünde jedes Gerät als „neu“ im Verlauf)
        st = json.loads(c.execute("SELECT settings FROM profiles WHERE id=?", (new_pid,)).fetchone()["settings"] or "{}")
        if st.pop("history_since", None) is not None:
            c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), new_pid))
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
    res, _ = _import_profiles(c, exp, umap, rename=False, fernet=f)
    set_setting(c, "registration_open", bool(st.get("registration_open")))
    set_setting(c, "smtp", smtp)
    set_setting(c, "backup", bk)
    aiset = dict(st.get("ai") or {})
    if aiset.get("key"):
        aiset["key"] = back(aiset["key"], "Claude API")
    if aiset:
        set_setting(c, "ai", aiset)
    oid = dict(st.get("oidc") or {})
    if oid.get("client_secret"):
        oid["client_secret"] = back(oid["client_secret"], "OIDC")
    if oid:
        set_setting(c, "oidc", oid)
    return dict(res, users=len(umap), secrets_dropped=sorted(set(dropped)))


# ------------------------------------------------------------ rclone (Google Drive, OneDrive, S3 …)
RCLONE_CONF = DATA / ".config" / "rclone" / "rclone.conf"


def rclone_error(stderr, remote=""):
    msg = (stderr or "").strip()
    if "didn't find section in config file" in msg or "not found - using defaults" in msg and "Failed to create file system" in msg:
        name = remote.split(":")[0]
        return (f"Das rclone-Ziel „{name}“ ist noch nicht eingerichtet. Unter dem Ziel „Google Drive verbinden“ wählen "
                f"(oder im Container: rclone --config {RCLONE_CONF} config).")
    if "invalid_grant" in msg or "token expired" in msg.lower():
        return "Die Anmeldung bei Google ist abgelaufen oder wurde widerrufen – „Google Drive verbinden“ erneut ausführen."
    return msg[-400:] or "rclone-Fehler"


def rclone_remotes():
    import shutil
    import subprocess
    if not shutil.which("rclone"):
        return None
    cp = subprocess.run(["rclone", "--config", str(RCLONE_CONF), "listremotes", "--long"], capture_output=True, text=True, timeout=20)
    out = []
    for line in cp.stdout.splitlines():
        if ":" in line:
            name, _, typ = line.partition(":")
            out.append(dict(name=name.strip(), type=typ.strip()))
    return out


def rclone_drive(name, token_text):
    """Google-Drive-Remote mit einem Token aus „rclone authorize "drive"“ anlegen (Zugriff nur auf von rclone angelegte Dateien)."""
    import json as _json
    import re
    import shutil
    import subprocess
    if not shutil.which("rclone"):
        raise BackupError("rclone ist nicht installiert")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", name or ""):
        raise BackupError("Name nur aus Buchstaben, Ziffern, - und _")
    m = re.search(r"\{.*\}", token_text or "", re.S)
    try:
        tok = _json.loads(m.group(0)) if m else None
    except ValueError:
        tok = None
    if not tok or not tok.get("access_token"):
        raise BackupError("Kein gültiges Token – die ganze Zeile {\"access_token\": …} aus „rclone authorize“ einfügen")
    RCLONE_CONF.parent.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["rclone", "--config", str(RCLONE_CONF), "config", "create", name, "drive", "scope=drive.file",
                         f"token={_json.dumps(tok)}", "--non-interactive"], capture_output=True, text=True, timeout=60)
    if cp.returncode:
        raise BackupError(f"rclone: {(cp.stderr or cp.stdout).strip()[-300:]}")
    t = subprocess.run(["rclone", "--config", str(RCLONE_CONF), "lsd", f"{name}:"], capture_output=True, text=True, timeout=60)
    if t.returncode:
        raise BackupError(f"Verbindung angelegt, aber Google Drive antwortet nicht: {rclone_error(t.stderr, name)}")
    return dict(name=name, remote=f"{name}:diktyo")
