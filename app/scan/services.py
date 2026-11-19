"""Dienste-Scan eines Geräts mit nmap auf Knopfdruck (Auftrag „services“ im Hintergrunddienst).

Ermittelt offene TCP-Ports mit Dienst, Produkt und Version (-sV), dazu Titel von Webseiten und das TLS-Zertifikat
(Inhaber, Ablaufdatum). Mit CAP_NET_RAW zusätzlich eine Vermutung zum Betriebssystem.
"""
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

from ..db import db, now
from . import netinfo

DEPTHS = {"quick": ["--top-ports", "100"], "standard": ["--top-ports", "1000"], "full": ["-p-"]}
TIMEOUT = {"quick": 300, "standard": 900, "full": 3600}
WEB = {"http", "https", "http-proxy", "http-alt", "https-alt", "ssl/http", "upnp"}


def available():
    return bool(shutil.which("nmap"))


def command(ips, depth="standard", privileged=False):
    cmd = ["nmap", "-n", "-Pn", "-sV", "-T4", "--stats-every", "3s", "--script", "http-title,ssl-cert", "-oX", "-"]
    cmd += DEPTHS.get(depth, DEPTHS["standard"])
    cmd += ["--privileged", "-sS", "-O", "--osscan-limit"] if privileged else ["-sT", "--unprivileged"]
    return cmd + list(ips)


def parse(xml_text):
    """nmap-XML -> {ip: dict(ports=[...], os)}"""
    root = ET.fromstring(xml_text)
    out = {}
    for h in root.iter("host"):
        ip = next((a.get("addr") for a in h.iter("address") if a.get("addrtype") == "ipv4"), None)
        if not ip:
            continue
        ports = []
        for p in h.iter("port"):
            st = p.find("state")
            if st is None or st.get("state") != "open":
                continue
            sv = p.find("service")
            sv = sv.attrib if sv is not None else {}
            e = dict(port=int(p.get("portid")), proto=p.get("protocol", "tcp"), name=sv.get("name", ""), product=sv.get("product", ""),
                     version=sv.get("version", ""), extra=sv.get("extrainfo", ""), tls=sv.get("tunnel") == "ssl", title="", cert=None)
            for s in p.iter("script"):
                if s.get("id") == "http-title":
                    e["title"] = (s.get("output") or "").strip()[:120]
                elif s.get("id") == "ssl-cert":
                    cert = {}
                    for tbl in s.iter("table"):
                        if tbl.get("key") == "subject":
                            cert["subject"] = next((x.text for x in tbl.iter("elem") if x.get("key") == "commonName"), "")
                        elif tbl.get("key") == "issuer":
                            cert["issuer"] = next((x.text for x in tbl.iter("elem") if x.get("key") in ("organizationName", "commonName")), "")
                        elif tbl.get("key") == "validity":
                            cert["not_after"] = next((x.text for x in tbl.iter("elem") if x.get("key") == "notAfter"), "")
                    e["cert"] = cert or None
            name = e["name"]
            e["web"] = ("https" if e["tls"] or "https" in name or name == "ssl/http" else "http") if (name in WEB or name.startswith("http")) else ""
            ports.append(e)
        om = next(iter(h.iter("osmatch")), None)
        os_ = om.get("name", "")[:100] if om is not None and int(om.get("accuracy", "0")) >= 85 else ""
        out[ip] = dict(ports=sorted(ports, key=lambda x: x["port"]), os=os_)
    return out


def run(job_id, log=print):
    """Auftrag ausführen: params = {device_id, ips, depth}. Ergebnis landet am Gerät (data.services_scan)."""
    import json
    with db() as c:
        j = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    p = json.loads(j["params"] or "{}")
    if not available():
        raise RuntimeError("nmap ist nicht installiert")
    depth = p.get("depth", "standard")
    cmd = command(p["ips"], depth, privileged=netinfo.has_raw())
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines, last = [], 0
    try:
        for line in proc.stdout:
            lines.append(line)
            m = re.search(r'<taskprogress task="([^"]+)"[^>]*percent="([\d.]+)"', line)
            if m and time.time() - last > 2:
                last = time.time()
                task = {"Service scan": "Dienste erkennen", "SYN Stealth Scan": "Ports prüfen", "Connect Scan": "Ports prüfen",
                        "NSE": "Zusatzinfos lesen"}.get(m.group(1), m.group(1))
                with db() as c:
                    c.execute("UPDATE jobs SET progress=?, message=? WHERE id=?", (min(99, int(float(m.group(2)))), task, job_id))
            if time.time() - t0 > TIMEOUT.get(depth, 900):
                proc.kill()
                raise RuntimeError("Zeitlimit erreicht – „Schnell“ wählen oder später erneut versuchen")
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    xml_text = "".join(lines)
    if proc.returncode not in (0, None) and "<nmaprun" not in xml_text:
        raise RuntimeError(f"nmap meldet einen Fehler: {proc.stderr.read()[:200]}")
    hosts = parse(xml_text)
    res = dict(ts=now(), depth=depth, duration=round(time.time() - t0, 1), hosts=hosts,
               ports=sorted({x["port"] for h in hosts.values() for x in h["ports"]}))
    with db() as c:
        d = c.execute("SELECT data FROM devices WHERE id=?", (p["device_id"],)).fetchone()
        if d:
            data = json.loads(d["data"] or "{}")
            before = (data.get("services_scan") or {}).get("ports")
            data["services_scan"] = res
            if before is not None and sorted(before) != res["ports"]:  # offene Ports haben sich geändert
                from .. import changes
                pid = c.execute("SELECT profile_id FROM devices WHERE id=?", (p["device_id"],)).fetchone()[0]
                opened, closed = sorted(set(res["ports"]) - set(before)), sorted(set(before) - set(res["ports"]))
                changes.record(c, pid, p["device_id"], "changed", "ports", ", ".join(map(str, sorted(before))) or "–",
                               ", ".join(map(str, res["ports"])) or "–", "nmap", None, dict(opened=opened, closed=closed))
            c.execute("UPDATE devices SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), p["device_id"]))
    log(f"Dienste-Scan Gerät {p['device_id']}: {len(res['ports'])} offene Ports in {res['duration']} s")
    return dict(device_id=p["device_id"], open=len(res["ports"]), duration=res["duration"])
