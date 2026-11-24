"""VLAN-Plan: welcher Port in welchem VLAN – produktiv (Ist) und geplant (Soll), mit Umstellungsliste und Prüfungen.

Produktiv steht in port_vlans. Bei Switches mit SNMP-Integration kommt der Stand vom Switch (Q-BRIDGE-MIB, nur lesend,
source='snmp') und wird bei jeder Abfrage ersetzt; bei anderen Geräten pflegt man ihn von Hand (source='manual').
Der Plan ist eine eigene vollständige Kopie (port_vlans_plan), angelegt aus dem produktiven Stand. Abweichungen ergeben
die Umstellungsliste; bei SNMP-Switches erledigt sie sich, sobald der Switch den neuen Stand meldet, bei anderen Geräten
übernimmt man einen Port mit „umgesetzt“. VLANs, die es nur im Plan gibt, haben planned=1.

díktyo schreibt nichts auf die Switches – umgestellt wird am Gerät.
"""
import ipaddress
import json

from .db import now

PALETTE = ["#00E5FF", "#FFB020", "#2EE59D", "#FF4D6A", "#4D8CFF", "#C77DFF", "#19F5C8", "#FF7A45", "#E6E600", "#FF66C4", "#8FB4FF", "#A3E635"]
# Netzwerkgeräte im VLAN-Plan; Endgeräte (PC, Laptop …) stehen getrennt darunter – ihr VLAN legt meist der Switch-Port fest
VLAN_TYPES = ("router", "switch", "ap", "mesh", "firewall", "modem", "repeater", "powerline", "hypervisor", "server", "nas")


class VlanError(Exception):
    pass


def color_of(v):
    return v["color"] or PALETTE[v["vid"] % len(PALETTE)]


def _settings(c, pid):
    r = c.execute("SELECT settings FROM profiles WHERE id=?", (pid,)).fetchone()
    return json.loads(r["settings"] or "{}") if r else {}


def _save_settings(c, pid, st):
    c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))


def plan_info(c, pid):
    return _settings(c, pid).get("vlan_plan")


# ------------------------------------------------------------ vom Switch gelesen (SNMP)
def apply_switch(c, pid, did, vres):
    """Produktiven Stand eines Switches aus der SNMP-Abfrage übernehmen. vres = {"vlans": [{vid, name}], "ports": {no: {untagged, tagged}}}"""
    if not vres or not vres.get("ports"):
        return 0
    have = {r["vid"]: r["id"] for r in c.execute("SELECT id, vid FROM vlans WHERE profile_id=?", (pid,))}
    names = {int(v["vid"]): v.get("name") or "" for v in vres.get("vlans", [])}
    used = {int(x) for p in vres["ports"].values() for x in ([p.get("untagged")] if p.get("untagged") else []) + list(p.get("tagged") or [])}
    for vid in sorted(used):
        if vid not in have and 1 <= vid <= 4094:
            have[vid] = c.execute("INSERT INTO vlans(profile_id, vid, name, description) VALUES(?,?,?,?)",
                                  (pid, vid, names.get(vid, "")[:80], "vom Switch gelesen")).lastrowid
        elif vid in have:  # VLAN gibt es am Switch: nicht mehr nur geplant
            c.execute("UPDATE vlans SET planned=0 WHERE id=? AND planned=1", (have[vid],))
    ports = {r["port_no"]: r["id"] for r in c.execute("SELECT id, port_no FROM interfaces WHERE device_id=? AND role='port'", (did,))}
    c.execute(f"DELETE FROM port_vlans WHERE interface_id IN ({','.join('?' * len(ports))})", list(ports.values())) if ports else None
    n = 0
    for no, p in vres["ports"].items():
        iid = ports.get(int(no))
        if not iid:
            continue
        u = p.get("untagged")
        if u and u in have:
            c.execute("INSERT OR REPLACE INTO port_vlans(interface_id, vlan_id, tagged, source) VALUES(?,?,0,'snmp')", (iid, have[u]))
        for t in p.get("tagged") or []:
            if t in have and t != u:
                c.execute("INSERT OR REPLACE INTO port_vlans(interface_id, vlan_id, tagged, source) VALUES(?,?,1,'snmp')", (iid, have[t]))
        n += 1
    return n


# ------------------------------------------------------------ Zuordnung ändern
def _table(mode):
    if mode not in ("prod", "plan"):
        raise VlanError("Unbekannter Modus")
    return "port_vlans" if mode == "prod" else "port_vlans_plan"


def snmp_devices(c, pid):
    return {r["device_id"] for r in c.execute("""SELECT DISTINCT i.device_id FROM port_vlans pv JOIN interfaces i ON i.id=pv.interface_id
                                                 JOIN devices d ON d.id=i.device_id WHERE d.profile_id=? AND pv.source='snmp'""", (pid,))}


def set_ports(c, pid, mode, iface_ids, untagged="keep", tagged=None):
    """Mehrere Ports auf einmal: untagged = "keep" | None (kein VLAN) | vlan_id; tagged = {vlan_id: True/False} (fehlend = unverändert)."""
    tbl = _table(mode)
    if mode == "plan" and not plan_info(c, pid):
        raise VlanError("Es gibt noch keinen Plan")
    vlans = {r["id"] for r in c.execute("SELECT id FROM vlans WHERE profile_id=?", (pid,))}
    if mode == "prod":
        if untagged not in ("keep", None) and c.execute("SELECT planned FROM vlans WHERE id=?", (untagged,)).fetchone()["planned"]:
            raise VlanError("Geplante VLANs gibt es nur im Plan")
    rows = c.execute(f"""SELECT i.id, i.device_id FROM interfaces i JOIN devices d ON d.id=i.device_id
                         WHERE d.profile_id=? AND i.role='port' AND i.id IN ({','.join('?' * len(iface_ids)) or 'NULL'})""",
                     (pid, *iface_ids)).fetchall()
    if not rows:
        raise VlanError("Keine Ports gewählt")
    if mode == "prod" and {r["device_id"] for r in rows} & snmp_devices(c, pid):
        raise VlanError("Dieser Switch meldet seine VLANs selbst (SNMP) – der produktive Stand lässt sich hier nicht ändern")
    tagged = {int(k): bool(v) for k, v in (tagged or {}).items()}
    for k in list(tagged) + ([untagged] if untagged not in ("keep", None) else []):
        if k not in vlans:
            raise VlanError("VLAN nicht gefunden")
    ins = (f"INSERT OR REPLACE INTO {tbl}(interface_id, vlan_id, tagged, source) VALUES(?,?,?,'manual')" if mode == "prod"
           else f"INSERT OR REPLACE INTO {tbl}(interface_id, vlan_id, tagged) VALUES(?,?,?)")
    for r in rows:
        iid = r["id"]
        if untagged != "keep":
            c.execute(f"DELETE FROM {tbl} WHERE interface_id=? AND tagged=0", (iid,))
            if untagged:
                c.execute(f"DELETE FROM {tbl} WHERE interface_id=? AND vlan_id=?", (iid, untagged))
                c.execute(ins, (iid, untagged, 0))
        cur_u = c.execute(f"SELECT vlan_id FROM {tbl} WHERE interface_id=? AND tagged=0", (iid,)).fetchone()
        for vid, on in tagged.items():
            if on and not (cur_u and cur_u["vlan_id"] == vid):
                c.execute(ins, (iid, vid, 1))
            elif not on:
                c.execute(f"DELETE FROM {tbl} WHERE interface_id=? AND vlan_id=? AND tagged=1", (iid, vid))
    return len(rows)


# ------------------------------------------------------------ Plan
def plan_start(c, pid, note=""):
    if plan_info(c, pid):
        raise VlanError("Es gibt schon einen Plan")
    c.execute("""DELETE FROM port_vlans_plan WHERE interface_id IN (SELECT i.id FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=?)""", (pid,))
    c.execute("""INSERT INTO port_vlans_plan(interface_id, vlan_id, tagged) SELECT pv.interface_id, pv.vlan_id, pv.tagged FROM port_vlans pv
                 JOIN interfaces i ON i.id=pv.interface_id JOIN devices d ON d.id=i.device_id WHERE d.profile_id=?""", (pid,))
    st = _settings(c, pid)
    st["vlan_plan"] = dict(created=now(), note=str(note or "")[:300])
    _save_settings(c, pid, st)


def _drop_plan(c, pid):
    c.execute("""DELETE FROM port_vlans_plan WHERE interface_id IN (SELECT i.id FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE d.profile_id=?)""", (pid,))
    st = _settings(c, pid)
    st.pop("vlan_plan", None)
    _save_settings(c, pid, st)


def plan_discard(c, pid):
    """Plan verwerfen; VLANs, die es nur im Plan gab, fallen weg."""
    _drop_plan(c, pid)
    c.execute("DELETE FROM vlans WHERE profile_id=? AND planned=1", (pid,))


def adopt_port(c, pid, iid):
    """Einen Port als umgesetzt markieren: Plan -> produktiv (nur Geräte ohne SNMP-VLANs)."""
    r = c.execute("SELECT i.device_id FROM interfaces i JOIN devices d ON d.id=i.device_id WHERE i.id=? AND d.profile_id=?", (iid, pid)).fetchone()
    if not r:
        raise VlanError("Port nicht gefunden")
    if r["device_id"] in snmp_devices(c, pid):
        raise VlanError("Dieser Switch meldet seine VLANs selbst – der Port gilt als umgesetzt, sobald der Switch den neuen Stand meldet")
    _copy_port(c, iid)


def _copy_port(c, iid):
    planned = [x for x in c.execute("SELECT pv.vlan_id FROM port_vlans_plan pv JOIN vlans v ON v.id=pv.vlan_id WHERE pv.interface_id=? AND v.planned=1", (iid,))]
    for x in planned:  # ein geplantes VLAN, das jetzt auf einem Port produktiv ist, gibt es
        c.execute("UPDATE vlans SET planned=0 WHERE id=?", (x["vlan_id"],))
    c.execute("DELETE FROM port_vlans WHERE interface_id=?", (iid,))
    c.execute("INSERT INTO port_vlans(interface_id, vlan_id, tagged, source) SELECT interface_id, vlan_id, tagged, 'manual' FROM port_vlans_plan WHERE interface_id=?", (iid,))


def plan_finish(c, pid):
    """Plan abschließen: bei Geräten ohne SNMP-VLANs wird der Plan produktiv, geplante VLANs werden normale VLANs.
    -> Anzahl offener Ports an SNMP-Switches (die am Switch noch nicht umgesetzt sind)."""
    snmp = snmp_devices(c, pid)
    open_snmp = 0
    for d in diff(c, pid):
        if d["device_id"] in snmp:
            open_snmp += 1
        else:
            _copy_port(c, d["interface_id"])
    c.execute("UPDATE vlans SET planned=0 WHERE profile_id=? AND planned=1", (pid,))
    _drop_plan(c, pid)
    return open_snmp


# ------------------------------------------------------------ Lesen
def _members(c, pid, tbl):
    out = {}
    for r in c.execute(f"""SELECT pv.interface_id, pv.vlan_id, pv.tagged FROM {tbl} pv JOIN interfaces i ON i.id=pv.interface_id
                           JOIN devices d ON d.id=i.device_id WHERE d.profile_id=?""", (pid,)):
        m = out.setdefault(r["interface_id"], dict(u=None, t=[]))
        if r["tagged"]:
            m["t"].append(r["vlan_id"])
        else:
            m["u"] = r["vlan_id"]
    for m in out.values():
        m["t"].sort()
    return out


def _same(a, b):
    a, b = a or dict(u=None, t=[]), b or dict(u=None, t=[])
    return a["u"] == b["u"] and sorted(a["t"]) == sorted(b["t"])


def diff(c, pid):
    if not plan_info(c, pid):
        return []
    prod, plan = _members(c, pid, "port_vlans"), _members(c, pid, "port_vlans_plan")
    out = []
    for r in c.execute("""SELECT i.id, i.device_id, i.port_no, i.name, d.name AS dname FROM interfaces i JOIN devices d ON d.id=i.device_id
                          WHERE d.profile_id=? AND i.role='port' ORDER BY d.name COLLATE NOCASE, i.port_no""", (pid,)):
        if not _same(prod.get(r["id"]), plan.get(r["id"])):
            out.append(dict(interface_id=r["id"], device_id=r["device_id"], device=r["dname"], port_no=r["port_no"], port=r["name"] or str(r["port_no"]),
                            prod=prod.get(r["id"]) or dict(u=None, t=[]), plan=plan.get(r["id"]) or dict(u=None, t=[])))
    return out


def _peers_all(c, pid):
    """interface_id (Port) -> [{id, name, type}] der angeschlossenen Geräte."""
    out = {}
    for r in c.execute("""SELECT l.a_if, l.b_if, ai.device_id AS ad, bi.device_id AS bd, ai.role AS ar, bi.role AS br
                          FROM links l JOIN interfaces ai ON ai.id=l.a_if JOIN interfaces bi ON bi.id=l.b_if WHERE l.profile_id=?""", (pid,)):
        if r["br"] == "port":
            out.setdefault(r["b_if"], []).append(r["ad"])
        if r["ar"] == "port":
            out.setdefault(r["a_if"], []).append(r["bd"])
    return out


def state(c, pid):
    plan = plan_info(c, pid)
    subs = {}
    for s in c.execute("SELECT vlan_id, cidr FROM subnets WHERE profile_id=? AND vlan_id IS NOT NULL", (pid,)):
        subs.setdefault(s["vlan_id"], []).append(s["cidr"])
    vlans = [dict(id=r["id"], vid=r["vid"], name=r["name"], description=r["description"], color=color_of(r), planned=bool(r["planned"]),
                  subnets=subs.get(r["id"], [])) for r in c.execute("SELECT * FROM vlans WHERE profile_id=? ORDER BY vid", (pid,))]
    if not plan:
        vlans = [v for v in vlans if not v["planned"]]
    devs = {r["id"]: dict(r) for r in c.execute("SELECT id, name, type, status FROM devices WHERE profile_id=?", (pid,))}
    prod, planm = _members(c, pid, "port_vlans"), (_members(c, pid, "port_vlans_plan") if plan else {})
    peers = _peers_all(c, pid)
    snmp = snmp_devices(c, pid)
    switches = []
    for d in c.execute(f"""SELECT d.id, d.name, d.type FROM devices d WHERE d.profile_id=? AND d.status='confirmed'
                          AND EXISTS(SELECT 1 FROM interfaces i WHERE i.device_id=d.id AND i.role='port')
                          ORDER BY CASE d.type WHEN 'router' THEN 0 WHEN 'firewall' THEN 0 WHEN 'switch' THEN 1 ELSE 2 END, d.name COLLATE NOCASE""", (pid,)):
        ports = []
        for p in c.execute("SELECT id, port_no, name FROM interfaces WHERE device_id=? AND role='port' ORDER BY port_no", (d["id"],)):
            pr = [dict(id=x, name=devs[x]["name"], type=devs[x]["type"]) for x in peers.get(p["id"], []) if x in devs and x != d["id"]]
            ports.append(dict(id=p["id"], no=p["port_no"], name=p["name"] or str(p["port_no"]), peers=pr,
                              prod=prod.get(p["id"]) or dict(u=None, t=[]), plan=(planm.get(p["id"]) or dict(u=None, t=[])) if plan else None))
        switches.append(dict(id=d["id"], name=d["name"], type=d["type"], snmp=d["id"] in snmp, ports=ports, infra=d["type"] in VLAN_TYPES))
    # VMs und Container (Proxmox): VLAN-Tag aus der Netzwerkkarte des Gasts, angezeigt beim Host
    by_vid = {v["vid"]: v["id"] for v in vlans}
    guests = {}
    for r in c.execute("""SELECT gd.id, gd.name, gd.type, gd.data, bi.device_id AS host FROM links l JOIN interfaces ai ON ai.id=l.a_if
                          JOIN interfaces bi ON bi.id=l.b_if JOIN devices gd ON gd.id=ai.device_id
                          WHERE l.profile_id=? AND l.medium='virtual' AND gd.status='confirmed' ORDER BY gd.name COLLATE NOCASE""", (pid,)):
        px = json.loads(r["data"] or "{}").get("proxmox")
        if not px:
            continue
        tag = str(px.get("tag") or "").strip()
        vid = int(tag) if tag.isdigit() else None
        guests.setdefault(r["host"], []).append(dict(id=r["id"], name=r["name"], kind=px.get("kind") or "", vmid=px.get("vmid"), vid=vid,
                                                     vlan_id=by_vid.get(vid), bridge=px.get("bridge") or ""))
    have = {s["id"] for s in switches}
    for hid in guests:
        if hid not in have and hid in devs and devs[hid]["status"] == "confirmed":
            switches.append(dict(id=hid, name=devs[hid]["name"], type=devs[hid]["type"], snmp=False, ports=[], infra=devs[hid]["type"] in VLAN_TYPES))
    for s in switches:
        s["guests"] = guests.get(s["id"], [])
    out = dict(vlans=vlans, switches=switches, plan=plan, diff=diff(c, pid) if plan else [])
    out["warnings"] = dict(prod=checks(c, pid, out, "prod"), plan=checks(c, pid, out, "plan") if plan else [])
    return out


def checks(c, pid, st, mode):
    """Hinweise: Adresse passt nicht zum Netz des VLANs, Uplink führt ein VLAN nicht weiter, VLAN ohne Subnetz."""
    key = "prod" if mode == "prod" else "plan"
    vl = {v["id"]: v for v in st["vlans"]}
    nets = {v["id"]: [ipaddress.ip_network(s, strict=False) for s in v["subnets"]] for v in st["vlans"]}
    ips = {}
    for r in c.execute("SELECT device_id, address, kind FROM ip_addresses WHERE profile_id=? AND device_id IS NOT NULL", (pid,)):
        try:
            ips.setdefault(r["device_id"], []).append((ipaddress.ip_address(r["address"]), r["kind"]))
        except ValueError:
            pass
    sw_by_id = {s["id"]: s for s in st["switches"] if s.get("infra", True)}  # Netzwerkgeräte (für Uplink-Prüfung)
    used = set()
    out = []
    lab = lambda v: f"VLAN {vl[v]['vid']}" + (f" ({vl[v]['name']})" if vl[v]["name"] else "")  # noqa: E731
    for s in st["switches"]:
        for p in s["ports"]:
            m = p[key] or dict(u=None, t=[])
            used.update(([m["u"]] if m["u"] else []) + m["t"])
            # 1) Endgerät: Adresse passt nicht zum Netz des untagged VLANs
            if m["u"] in nets and nets[m["u"]] and len(p["peers"]) == 1 and p["peers"][0]["id"] not in sw_by_id:
                peer = p["peers"][0]
                addrs = [a for a in ips.get(peer["id"], []) if a[0].version == 4]
                if addrs and not any(a[0] in n for a in addrs for n in nets[m["u"]]):
                    static = any(k == "static" for _, k in addrs)
                    out.append(dict(level="warn" if static else "info", device_id=s["id"], interface_id=p["id"],
                                    text=f"{s['name']} · Port {p['name']} → {peer['name']}: Adresse {addrs[0][0]} liegt nicht im Netz von {lab(m['u'])} "
                                         f"({', '.join(str(n) for n in nets[m['u']])})" + (" – statische Adresse anpassen" if static else " – bekommt per DHCP eine neue Adresse"),
                                    code="ip_static" if static else "ip_dhcp"))
            # 2) Verbindung zu einem anderen Switch/Router/AP mit VLAN-Daten: alle dort genutzten VLANs müssen hier ankommen
            for peer in p["peers"]:
                other = sw_by_id.get(peer["id"])
                if not other:
                    continue
                back = {q["id"] for q in other["ports"] if any(x["id"] == s["id"] for x in q["peers"])}
                need = set()
                for q in other["ports"]:
                    if q["id"] in back:
                        continue
                    mq = q[key] or dict(u=None, t=[])
                    need.update(([mq["u"]] if mq["u"] else []) + mq["t"])
                have = set(([m["u"]] if m["u"] else []) + m["t"])
                miss = sorted(need - have, key=lambda v: vl[v]["vid"] if v in vl else 0)
                if miss and have:  # nur wenn der Port überhaupt VLANs hat (sonst unbekannt)
                    out.append(dict(level="warn", device_id=s["id"], interface_id=p["id"], code="trunk",
                                    text=f"{s['name']} · Port {p['name']} → {other['name']}: führt {', '.join(lab(v) for v in miss if v in vl)} nicht weiter, "
                                         f"obwohl es auf {other['name']} genutzt wird (als tagged eintragen)"))
    # Switch-Port zu einem Hypervisor: muss die VLANs seiner VMs/Container führen (tagged)
    guests_of = {s["id"]: s.get("guests") or [] for s in st["switches"]}
    for s in st["switches"]:
        for p in s["ports"]:
            m = p[key] or dict(u=None, t=[])
            have = set(([m["u"]] if m["u"] else []) + m["t"])
            for peer in p["peers"]:
                need = {g["vlan_id"] for g in guests_of.get(peer["id"], []) if g["vlan_id"]}
                miss = sorted(need - have, key=lambda v: vl[v]["vid"] if v in vl else 0)
                if miss and have:
                    names = ", ".join(g["name"] for g in guests_of[peer["id"]] if g["vlan_id"] in miss)[:120]
                    out.append(dict(level="warn", device_id=s["id"], interface_id=p["id"], code="guest_vlan",
                                    text=f"{s['name']} · Port {p['name']} → {peer['name']}: führt {', '.join(lab(v) for v in miss if v in vl)} nicht, "
                                         f"das VMs/Container nutzen ({names}) – als tagged eintragen"))
    seen_vid = set()
    for gl in guests_of.values():
        for g in gl:
            if g["vid"] and not g["vlan_id"] and g["vid"] not in seen_vid:
                seen_vid.add(g["vid"])
                out.append(dict(level="info", code="guest_unknown_vlan",
                                text=f"VLAN {g['vid']} wird von {g['name']} (Proxmox) genutzt, ist in díktyo aber noch nicht angelegt"))
    for v in st["vlans"]:
        if v["id"] in used and not v["subnets"] and v["vid"] != 1:
            out.append(dict(level="info", code="no_subnet", text=f"{lab(v['id'])} hat noch kein Subnetz (IPAM) – für die Adressprüfung eines anlegen"))
    return out


def pdf_tables(c, pid, lang="de"):
    """-> (Ports je Gerät [(Gerät, [Zeilen])], Umstellungsliste [Zeilen])"""
    st = state(c, pid)
    vl = {v["id"]: v for v in st["vlans"]}
    fmt = lambda m: (str(vl[m["u"]]["vid"]) if m and m["u"] in vl else "–", ", ".join(str(vl[t]["vid"]) for t in (m or {}).get("t", []) if t in vl))  # noqa: E731
    per = []
    for s in st["switches"]:
        rows = [[p["name"], ", ".join(x["name"] for x in p["peers"]), *fmt(p["prod"])] for p in s["ports"] if p["prod"]["u"] or p["prod"]["t"]]
        if rows:
            per.append((s["name"], rows))
    chg = []
    for d in st["diff"]:
        a, b = fmt(d["prod"]), fmt(d["plan"])
        chg.append([d["device"], d["port"], f"U {a[0]}" + (f" · T {a[1]}" if a[1] else ""), f"U {b[0]}" + (f" · T {b[1]}" if b[1] else "")])
    return per, chg
