"""Bausteine der Erkennung. Alles läuft ohne Root: Ping und TCP-Verbindungen lösen die ARP-Auflösung des Kernels aus,
danach stehen die MAC-Adressen in /proc/net/arp. Nur die Betriebssystem-Erkennung von nmap braucht CAP_NET_RAW."""
import asyncio
import ipaddress
import json
import random
import re
import shutil
import socket
import struct
import subprocess
import time
from xml.etree import ElementTree as ET

import httpx

LIGHT_PORTS = [22, 53, 80, 443, 445, 554, 1400, 1883, 5000, 5001, 8006, 8008, 8009, 8080, 8123, 8443, 9100, 62078]
FULL_PORTS = sorted(set(LIGHT_PORTS + [21, 23, 25, 81, 88, 110, 111, 135, 139, 143, 161, 389, 548, 631, 993, 995, 1080, 1900, 2049,
                                       3000, 3306, 3389, 4070, 5353, 5432, 5900, 6053, 6379, 6466, 7000, 7100, 8000, 8001, 8081, 8088,
                                       8096, 8200, 8888, 9000, 9090, 9443, 10000, 32400, 49152, 55442, 55443]))
TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)


# ------------------------------------------------------------ Lebenszeichen
async def ping(ip, timeout=1.0):
    try:
        p = await asyncio.create_subprocess_exec("ping", "-n", "-q", "-c", "1", "-W", str(max(1, int(timeout))), ip,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return await p.wait() == 0
    except (FileNotFoundError, PermissionError):
        return False


async def tcp(ip, port, timeout=0.8):
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
        w.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


MAX_SOCKETS = 200  # gleichzeitig offene Verbindungen; das Dateilimit im LXC liegt oft bei 1024


async def sweep(ips, ports, concurrency=64, progress=None):
    """Ping + TCP-Proben. -> {ip: {"alive": bool, "ports": [...]}}"""
    sem = asyncio.Semaphore(concurrency)
    socks = asyncio.Semaphore(MAX_SOCKETS)
    out, done = {}, 0

    async def probe(ip, p):
        async with socks:
            return await tcp(ip, p)

    async def one(ip):
        nonlocal done
        async with sem:
            async with socks:
                alive = await ping(ip)
            open_ = [p for p, ok in zip(ports, await asyncio.gather(*(probe(ip, p) for p in ports))) if ok]
            out[ip] = dict(alive=alive or bool(open_), ports=open_)
            done += 1
            if progress:
                progress(done, len(ips))

    await asyncio.gather(*(one(ip) for ip in ips))
    return out


def read_arp():
    """-> {ip: mac} aus der ARP-Tabelle des Kernels (nur vollständige Einträge)."""
    out = {}
    try:
        with open("/proc/net/arp") as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) >= 4 and p[2] != "0x0" and p[3] != "00:00:00:00:00:00":
                    out[p[0]] = p[3].upper()
    except OSError:
        pass
    return out


# ------------------------------------------------------------ Namen
def reverse_dns(ips, timeout=2.0):
    import concurrent.futures as cf
    out = {}

    def one(ip):
        try:
            return ip, socket.gethostbyaddr(ip)[0]
        except (OSError, UnicodeError):
            return ip, ""

    with cf.ThreadPoolExecutor(32) as ex:
        futs = [ex.submit(one, ip) for ip in ips]
        for f in cf.as_completed(futs, timeout=timeout + 5):
            try:
                ip, name = f.result()
                if name and name != ip:
                    out[ip] = name
            except Exception:
                pass
    return out


def dns_ptr(ip, server, timeout=1.5):
    """Rückwärtsauflösung bei einem bestimmten DNS-Server (z. B. der FRITZ!Box für Geräte in ihrem Netz)."""
    try:
        qname = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
        tid = random.randint(0, 65535)
        q = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0) + b"".join(bytes([len(p)]) + p.encode() for p in qname.split(".")) + b"\0" \
            + struct.pack(">HH", 12, 1)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            s.sendto(q, (server, 53))
            data, _ = s.recvfrom(2048)
        finally:
            s.close()
        rid, flags, qd, an = struct.unpack(">HHHH", data[:8])
        if rid != tid or flags & 0x000F or not an:
            return ""
        i = 12
        for _ in range(qd):  # Frage überspringen
            while data[i]:
                i += data[i] + 1
            i += 5
        for _ in range(an):
            i = _skip_name(data, i)
            rtype, _, _, rdlen = struct.unpack(">HHIH", data[i:i + 10])
            i += 10
            if rtype == 12:
                return _read_name(data, i).rstrip(".")
            i += rdlen
    except (OSError, struct.error, IndexError, ValueError):
        pass
    return ""


def _skip_name(data, i):
    while True:
        n = data[i]
        if n & 0xC0 == 0xC0:
            return i + 2
        if n == 0:
            return i + 1
        i += n + 1


def _read_name(data, i, depth=0):
    parts = []
    while depth < 10:
        n = data[i]
        if n & 0xC0 == 0xC0:
            return ".".join(parts + [_read_name(data, ((n & 0x3F) << 8) | data[i + 1], depth + 1)])
        if n == 0:
            break
        parts.append(data[i + 1:i + 1 + n].decode("utf-8", "replace"))
        i += n + 1
    return ".".join(parts)


def _nb_name(name):
    name = name.ljust(16, "\x00")[:16]
    return bytes([0x20]) + bytes(c for ch in name for c in ((ord(ch) >> 4) + 0x41, (ord(ch) & 0x0F) + 0x41)) + b"\x00"


def netbios(ips, timeout=1.5):
    """NetBIOS-Namen (Windows, Samba, NAS). -> {ip: name}"""
    out = {}
    pkt = struct.pack(">HHHHHH", 0x1d1d, 0, 1, 0, 0, 0) + _nb_name("*") + struct.pack(">HH", 0x21, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.2)
    try:
        for ip in ips:
            try:
                s.sendto(pkt, (ip, 137))
            except OSError:
                pass
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, (ip, _) = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                n = data[56]
                for i in range(n):
                    e = data[57 + i * 18: 57 + (i + 1) * 18]
                    nm, suffix, flags = e[:15].decode("ascii", "replace").strip(), e[15], struct.unpack(">H", e[16:18])[0]
                    if suffix == 0 and not flags & 0x8000 and nm:
                        out[ip] = nm
                        break
            except (IndexError, struct.error):
                pass
    finally:
        s.close()
    return out


# ------------------------------------------------------------ HTTP
def http_probe(targets, timeout=3.0):
    """targets: [(ip, port)] -> {ip: {"title", "server", "port"}} (erster Treffer je Gerät)."""
    import concurrent.futures as cf
    out = {}

    def one(ip, port):
        scheme = "https" if port in (443, 8006, 8443, 5001, 9443) else "http"
        try:
            with httpx.Client(verify=False, timeout=timeout, follow_redirects=True, headers={"User-Agent": "diktyo"}) as c:
                r = c.get(f"{scheme}://{ip}:{port}/")
            m = TITLE_RE.search(r.content[:20000])
            title = re.sub(r"\s+", " ", m.group(1).decode("utf-8", "replace")).strip()[:120] if m else ""
            return ip, dict(title=title, server=r.headers.get("server", "")[:80], port=port,
                            realm=r.headers.get("www-authenticate", "")[:80])
        except Exception:
            return ip, None

    with cf.ThreadPoolExecutor(24) as ex:
        for f in cf.as_completed([ex.submit(one, ip, p) for ip, p in targets]):
            ip, res = f.result()
            if res and (res["title"] or res["server"]) and ip not in out:
                out[ip] = res
    return out


# ------------------------------------------------------------ SSDP / UPnP
def ssdp(timeout=3.0):
    """-> {ip: {"server", "location", "friendlyName", "manufacturer", "modelName", "modelNumber", "modelDescription"}}"""
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n").encode()
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(0.3)
    try:
        for _ in range(2):
            s.sendto(msg, ("239.255.255.250", 1900))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, (ip, _) = s.recvfrom(4096)
            except socket.timeout:
                continue
            hdr = {}
            for line in data.decode("utf-8", "replace").split("\r\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    hdr[k.strip().lower()] = v.strip()
            e = found.setdefault(ip, dict(server=hdr.get("server", ""), locations=set()))
            if hdr.get("location"):
                e["locations"].add(hdr["location"])
    except OSError:
        pass
    finally:
        s.close()
    out = {}
    for ip, e in found.items():
        info = dict(server=e["server"][:120])
        for loc in sorted(e["locations"])[:4]:
            try:
                r = httpx.get(loc, timeout=2.5, headers={"User-Agent": "diktyo"})
                root = ET.fromstring(r.content)
                dev = next((el for el in root.iter() if el.tag.endswith("device")), None)
                if dev is None:
                    continue
                for el in dev:
                    tag = el.tag.split("}")[-1]
                    if tag in ("friendlyName", "manufacturer", "modelName", "modelNumber", "modelDescription") and el.text and not info.get(tag):
                        info[tag] = el.text.strip()[:120]
                if info.get("modelName"):
                    break
            except Exception:
                continue
        out[ip] = info
    return out


# ------------------------------------------------------------ mDNS / Bonjour
def mdns(timeout=4.0):
    """-> {ip: {"names": [...], "services": [...], "txt": {...}}}"""
    try:
        from zeroconf import IPVersion, ServiceBrowser, Zeroconf, ZeroconfServiceTypes
    except ImportError:
        return {}
    out = {}
    try:
        zc = Zeroconf(ip_version=IPVersion.V4Only)
    except OSError:
        return {}
    try:
        types = set(ZeroconfServiceTypes.find(zc=zc, timeout=min(3.0, timeout)))
        types |= {"_googlecast._tcp.local.", "_airplay._tcp.local.", "_amzn-wplay._tcp.local.", "_hap._tcp.local.", "_ipp._tcp.local.",
                  "_printer._tcp.local.", "_smb._tcp.local.", "_http._tcp.local.", "_esphomelib._tcp.local.", "_hue._tcp.local.",
                  "_sonos._tcp.local.", "_spotify-connect._tcp.local.", "_companion-link._tcp.local.", "_raop._tcp.local.",
                  "_home-assistant._tcp.local.", "_workstation._tcp.local.", "_device-info._tcp.local.", "_shelly._tcp.local.",
                  "_matter._tcp.local.", "_esphomebuilder._tcp.local.", "_slzb-06._tcp.local.", "_dosvc._tcp.local."}
        names = {}

        class L:
            def add_service(self, zc_, t, n):
                names.setdefault(t, set()).add(n)

            def update_service(self, zc_, t, n):
                names.setdefault(t, set()).add(n)

            def remove_service(self, zc_, t, n):
                pass

        browsers = []
        for t in sorted(types):
            # Manche Geräte melden kaputte Diensttypen (z. B. „.“); die werden übersprungen.
            if not (t.endswith("._tcp.local.") or t.endswith("._udp.local.")):
                continue
            try:
                browsers.append(ServiceBrowser(zc, t, L()))
            except Exception:
                pass
        time.sleep(timeout)
        for b in browsers:
            b.cancel()
        for t, ns in names.items():
            for n in list(ns)[:200]:
                try:
                    info = zc.get_service_info(t, n, timeout=800)
                except Exception:
                    info = None
                if not info:
                    continue
                for ip in info.parsed_addresses():
                    e = out.setdefault(ip, dict(names=set(), services=set(), txt={}))
                    e["services"].add(t.replace(".local.", ""))
                    inst = n.replace("." + t, "").strip()
                    if inst:
                        e["names"].add(inst[:80])
                    if info.server:
                        e["names"].add(info.server.rstrip(".").replace(".local", "")[:80])
                    for k, v in (info.properties or {}).items():
                        try:
                            k2, v2 = k.decode("utf-8", "replace"), (v or b"").decode("utf-8", "replace")
                        except AttributeError:
                            continue
                        if k2 in ("md", "model", "fn", "ty", "manufacturer", "am", "product", "app", "gen", "usb_MFG", "usb_MDL") and v2:
                            e["txt"][k2] = v2[:80]
    finally:
        zc.close()
    return {ip: dict(names=sorted(e["names"]), services=sorted(e["services"]), txt=e["txt"]) for ip, e in out.items()}


# ------------------------------------------------------------ nmap
def nmap_available():
    return bool(shutil.which("nmap"))


def nmap(ips, privileged=False, timeout=900):
    """Dienst- (und mit CAP_NET_RAW Betriebssystem-)Erkennung. -> {ip: {"ports": [...], "services": {port: text}, "os": str}}"""
    if not ips or not nmap_available():
        return {}
    cmd = ["nmap", "-n", "-Pn", "--top-ports", "100", "-sV", "--version-light", "-T4", "--host-timeout", "90s", "-oX", "-"]
    cmd += ["--privileged", "-sS", "-O", "--osscan-limit"] if privileged else ["-sT", "--unprivileged"]
    try:
        r = subprocess.run(cmd + list(ips), capture_output=True, timeout=timeout)
        root = ET.fromstring(r.stdout)
    except Exception:
        return {}
    return parse_nmap(root)


def parse_nmap(root):
    out = {}
    for h in root.iter("host"):
        ip = next((a.get("addr") for a in h.iter("address") if a.get("addrtype") == "ipv4"), None)
        if not ip:
            continue
        e = dict(ports=[], services={}, os="")
        for p in h.iter("port"):
            st = p.find("state")
            if st is None or st.get("state") != "open":
                continue
            no = int(p.get("portid"))
            e["ports"].append(no)
            sv = p.find("service")
            if sv is not None:
                txt = " ".join(x for x in (sv.get("product"), sv.get("version"), sv.get("extrainfo")) if x) or sv.get("name", "")
                if txt:
                    e["services"][str(no)] = txt[:100]
        om = next(iter(h.iter("osmatch")), None)
        if om is not None and int(om.get("accuracy", "0")) >= 85:
            e["os"] = om.get("name", "")[:100]
        out[ip] = e
    return out


def hosts_of(cidr, exclude=()):
    net = ipaddress.ip_network(cidr, strict=False)
    ex = [ipaddress.ip_network(x, strict=False) for x in exclude]
    hosts = net.hosts() if net.num_addresses > 2 else iter(net)
    return [str(h) for h in hosts if not any(h in e for e in ex)]


def dumps(x):
    return json.dumps(x, ensure_ascii=False, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
