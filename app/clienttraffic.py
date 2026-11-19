"""Datenverkehr je Gerät aus den Integrationen – für Topologie, Gerätedialog und Übersicht.

live:  aktuelle Rate je MAC (bit/s, aus Sicht des Geräts) – Omada, UniFi, MikroTik (WLAN-Registrierungen, Kid Control),
       OPNsense (Top Talkers), Proxmox (Gäste). Kabelgebundene Ports (Switch per SNMP usw.) liefert integrations.live_ports.
today: Datenmenge der letzten 24 Stunden je MAC – ASUS Traffic Analyzer.
Ältere Werte als MAX_AGE werden nicht als „live“ angezeigt.
"""
import json
import time

MAX_AGE = 900


def collect(c, pid):
    live, today = {}, {}
    now = time.time()
    for r in c.execute("SELECT name, driver, state FROM integrations WHERE profile_id=? AND enabled=1 ORDER BY id", (pid,)):
        st = json.loads(r["state"] or "{}")
        res = st.get("result") or {}
        if now - float(st.get("ts") or 0) <= MAX_AGE:
            for m, (down, up) in (res.get("rates") or {}).items():
                if m not in live:
                    live[m] = dict(down=down, up=up, source=r["name"])
        for x in (res.get("analyzer") or {}).get("clients") or []:
            today.setdefault(x["mac"], dict(rx=x["rx"], tx=x["tx"], source="ASUS Traffic Analyzer"))
    return live, today


def macs_of(c, did):
    return {r["mac"].upper() for r in c.execute("SELECT mac FROM interfaces WHERE device_id=? AND mac<>''", (did,))}


def device(live, today, macs):
    """Summen für ein Gerät (mehrere MACs, z. B. LAN und WLAN): (live|None, today|None)."""
    lv = [live[m] for m in macs if m in live]
    td = [today[m] for m in macs if m in today]
    out_l = dict(down=sum(x["down"] for x in lv), up=sum(x["up"] for x in lv), source=lv[0]["source"]) if lv else None
    out_t = dict(rx=sum(x["rx"] for x in td), tx=sum(x["tx"] for x in td), source=td[0]["source"]) if td else None
    return out_l, out_t
