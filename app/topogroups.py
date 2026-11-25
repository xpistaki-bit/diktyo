"""Gruppen in der Topologie: eigene Gruppen und die Einstellung, wonach zusammengefasst wird.

Eigene Gruppen („IoT“, „Kameras“, „Kinderzimmer“) haben einen Namen, eine Farbe und Mitglieder; ein Gerät gehört zu
höchstens einer Gruppe. In der Topologie erscheinen die Mitglieder unter ihrem Access Point/Switch als eigene Box.

Einstellung (profiles.settings["topology"]):
- group_by: medium (nur WLAN/VMs wie bisher), custom (eigene Gruppen), location (Standort), tag (erster Tag), vlan
- min_wlan / min_virtual: ab so vielen WLAN-Geräten bzw. VMs an einem Gerät zusammenfassen (0 = nie)
- min_group: ab so vielen Mitgliedern unter einem Gerät eine Box für Gruppe/Standort/Tag/VLAN bilden (0 = nie)
Geräte ohne passende Angabe fallen auf die Zusammenfassung nach Verbindungsart zurück.
"""
import hashlib
import ipaddress
import json
import re


GROUP_BY = ("medium", "custom", "location", "tag", "vlan")
DEFAULTS = dict(group_by="medium", min_wlan=4, min_virtual=5, min_group=2)
LIMITS = dict(min_wlan=(0, 500), min_virtual=(0, 500), min_group=(0, 500))
COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")
MAX_GROUPS = 100


class GroupError(Exception):
    pass


def settings(c, pid):
    r = c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()
    st = (json.loads(r["settings"] or "{}") if r else {}).get("topology") or {}
    out = dict(DEFAULTS)
    if st.get("group_by") in GROUP_BY:
        out["group_by"] = st["group_by"]
    for k, (lo, hi) in LIMITS.items():
        if isinstance(st.get(k), int) and lo <= st[k] <= hi:
            out[k] = st[k]
    return out


def save_settings(c, pid, body):
    cur = settings(c, pid)
    if "group_by" in body:
        if body["group_by"] not in GROUP_BY:
            raise GroupError("Unbekannte Gruppierung")
        cur["group_by"] = body["group_by"]
    for k, (lo, hi) in LIMITS.items():
        if k in body:
            try:
                v = int(body[k])
            except (TypeError, ValueError):
                raise GroupError("Ungültiger Schwellwert")
            if not lo <= v <= hi:
                raise GroupError("Ungültiger Schwellwert")
            cur[k] = v
    r = c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()
    st = json.loads(r["settings"] or "{}")
    st["topology"] = cur
    c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
    return cur


def list_groups(c, pid):
    members = {}
    for r in c.execute("""SELECT m.group_id, m.device_id FROM topo_group_members m JOIN topo_groups g ON g.id=m.group_id
                          WHERE g.profile_id=?""", (pid,)):
        members.setdefault(r["group_id"], []).append(r["device_id"])
    return [dict(id=r["id"], name=r["name"], color=r["color"], members=sorted(members.get(r["id"], [])))
            for r in c.execute("SELECT * FROM topo_groups WHERE profile_id=? ORDER BY name COLLATE NOCASE", (pid,))]


def _clean(body):
    name = str(body.get("name") or "").strip()[:60]
    if not name:
        raise GroupError("Name fehlt")
    color = str(body.get("color") or "").strip()
    if color and not COLOR_RE.fullmatch(color):
        raise GroupError("Ungültige Farbe")
    return name, color


def _set_members(c, pid, gid, ids):
    if not isinstance(ids, list):
        raise GroupError("Ungültige Mitglieder")
    try:
        ids = sorted({int(x) for x in ids})[:2000]
    except (TypeError, ValueError):
        raise GroupError("Ungültige Mitglieder")
    c.execute("DELETE FROM topo_group_members WHERE group_id=?", (gid,))
    if not ids:
        return
    own = {r["id"] for r in c.execute(f"SELECT id FROM devices WHERE profile_id=? AND id IN ({','.join('?' * len(ids))})", [pid, *ids])}
    for did in ids:
        if did in own:  # ein Gerät gehört zu höchstens einer Gruppe: aus der bisherigen herausnehmen
            c.execute("INSERT OR REPLACE INTO topo_group_members(device_id, group_id) VALUES(?,?)", (did, gid))


def _group(c, pid, gid):
    r = c.execute("SELECT * FROM topo_groups WHERE id=? AND profile_id=?", (gid, pid)).fetchone()
    if not r:
        raise GroupError("Gruppe nicht gefunden")
    return r


def create_group(c, pid, body):
    name, color = _clean(body)
    if c.execute("SELECT COUNT(*) FROM topo_groups WHERE profile_id=?", (pid,)).fetchone()[0] >= MAX_GROUPS:
        raise GroupError("Zu viele Gruppen")
    gid = c.execute("INSERT INTO topo_groups(profile_id, name, color) VALUES(?,?,?)", (pid, name, color)).lastrowid
    _set_members(c, pid, gid, body.get("members") or [])
    return gid


def update_group(c, pid, gid, body):
    _group(c, pid, gid)
    name, color = _clean(body)
    c.execute("UPDATE topo_groups SET name=?, color=? WHERE id=?", (name, color, gid))
    if "members" in body:
        _set_members(c, pid, gid, body["members"])


def delete_group(c, pid, gid):
    _group(c, pid, gid)
    c.execute("DELETE FROM topo_groups WHERE id=?", (gid,))
    c.execute("DELETE FROM topo_positions WHERE profile_id=? AND node LIKE ?", (pid, f"g%:c{gid}"))


def tag_key(tag):
    return "t" + hashlib.sha1(tag.strip().lower().encode()).hexdigest()[:10]


def keys(c, pid, devs, mode):
    """device_id -> (Schlüssel, Bezeichnung, Farbe) für die gewählte Gruppierung; fehlt ein Gerät, hat es keine Angabe."""
    out = {}
    if mode == "custom":
        groups = {g["id"]: g for g in list_groups(c, pid)}
        for g in groups.values():
            for did in g["members"]:
                out[did] = (f"c{g['id']}", g["name"], g["color"])
    elif mode == "location":
        for d in devs.values():
            if d.get("location_id"):
                out[d["id"]] = (f"l{d['location_id']}", d["location"], "")
    elif mode == "tag":
        for d in devs.values():
            tags = [x for x in d.get("tags") or [] if str(x).strip()]
            if tags:
                out[d["id"]] = (tag_key(tags[0]), tags[0], "")
    elif mode == "vlan":
        from .vlanplan import color_of
        vl = {r["id"]: r for r in c.execute("SELECT * FROM vlans WHERE profile_id=? AND planned=0", (pid,))}
        by_vid = {r["vid"]: r for r in vl.values()}
        untagged = {r["interface_id"]: r["vlan_id"] for r in c.execute(
            """SELECT pv.interface_id, pv.vlan_id FROM port_vlans pv JOIN interfaces i ON i.id=pv.interface_id
               JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND pv.tagged=0""", (pid,))}
        nets = [(n, s["vlan_id"]) for n, s in ((ipaddress.ip_network(s["cidr"], strict=False), s) for s in c.execute(
            "SELECT cidr, vlan_id FROM subnets WHERE profile_id=? AND vlan_id IS NOT NULL", (pid,)))]
        for d in devs.values():
            v = None
            u = d.get("uplink") or {}
            if u.get("port_id") in untagged:  # 1. VLAN des Switch-Ports, an dem das Gerät hängt
                v = vl.get(untagged[u["port_id"]])
            if v is None and u.get("medium") == "virtual":  # 2. VLAN-Tag der VM/des Containers (Proxmox)
                tag = str((json.loads(c.execute("SELECT data FROM devices WHERE id=?", (d["id"],)).fetchone()["data"] or "{}")
                           .get("proxmox") or {}).get("tag") or "").strip()
                v = by_vid.get(int(tag)) if tag.isdigit() else None
            if v is None:  # 3. Subnetz der IP-Adresse
                for ip in d.get("ips") or []:
                    try:
                        a = ipaddress.ip_address(ip["address"])
                    except ValueError:
                        continue
                    hit = next((vid for n, vid in nets if a.version == n.version and a in n), None)
                    if hit in vl:
                        v = vl[hit]
                        break
            if v is not None:
                out[d["id"]] = (f"v{v['vid']}", f"VLAN {v['vid']}" + (f" · {v['name']}" if v["name"] else ""), color_of(v))
    return out


def export_rows(c):
    return dict(topo_groups=[dict(r) for r in c.execute("SELECT * FROM topo_groups")],
                topo_group_members=[dict(r) for r in c.execute("SELECT * FROM topo_group_members")])


def import_rows(c, exp, pmap, dmap):
    """-> alte Gruppen-ID -> neue ID (für die gespeicherten Positionen der Gruppen-Boxen)."""
    gmap = {}
    for x in exp.get("topo_groups", []):
        if x["profile_id"] in pmap:
            gmap[x["id"]] = c.execute("INSERT INTO topo_groups(profile_id, name, color) VALUES(?,?,?)",
                                      (pmap[x["profile_id"]], x["name"], x.get("color") or "")).lastrowid
    for x in exp.get("topo_group_members", []):
        if x["group_id"] in gmap and x["device_id"] in dmap:
            c.execute("INSERT OR REPLACE INTO topo_group_members(device_id, group_id) VALUES(?,?)", (dmap[x["device_id"]], gmap[x["group_id"]]))
    return gmap
