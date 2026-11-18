"""Lokale Netzwerkschnittstellen, Standard-Gateway und Rechte des Prozesses."""
import ipaddress
import json
import os
import subprocess

SKIP = ("lo", "docker", "veth", "br-", "virbr", "tailscale", "wg", "tun", "tap", "fwbr", "fwpr", "fwln")


def interfaces():
    """-> [{"ifname", "ip", "prefix", "cidr"}] für IPv4, ohne Loopback und virtuelle Brücken."""
    try:
        data = json.loads(subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=5).stdout or "[]")
    except Exception:
        return []
    out = []
    for i in data:
        name = i.get("ifname", "")
        if name.startswith(SKIP):
            continue
        for a in i.get("addr_info", []):
            if a.get("family") != "inet":
                continue
            net = ipaddress.ip_network(f'{a["local"]}/{a["prefixlen"]}', strict=False)
            if net.is_loopback or net.is_link_local:
                continue
            out.append(dict(ifname=name, ip=a["local"], prefix=a["prefixlen"], cidr=str(net)))
    return out


def default_gateway():
    try:
        data = json.loads(subprocess.run(["ip", "-j", "-4", "route", "show", "default"], capture_output=True, text=True, timeout=5).stdout or "[]")
        return data[0].get("gateway", "") if data else ""
    except Exception:
        return ""


def has_raw():
    """CAP_NET_RAW im effektiven Rechte-Set (oder root)."""
    if os.geteuid() == 0:
        return True
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("CapEff:"):
                    return bool(int(line.split()[1], 16) & (1 << 13))
    except OSError:
        pass
    return False
