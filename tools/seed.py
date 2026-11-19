#!/usr/bin/env python3
"""Erzeugt app/catalog_seed.json (Startkatalog). Aufruf: python3 tools/seed.py

Port-Angaben stammen aus den Produktbeschreibungen der Hersteller, sind aber nicht einzeln gegen Datenblätter
geprüft (verified=False). Wer ein Gerät geprüft hat, kann es im Katalog als geprüft markieren.
Format der Ports: "Anzahl:Art:Geschwindigkeit:Bezeichnung:poe", Gruppen durch Komma getrennt.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app.catalog import parse_ports  # noqa: E402

AVM = dict(vendor=["AVM"], driver="fritzbox_tr064")
ZYXEL = dict(vendor=["Zyxel"])
ASUS = dict(vendor=["ASUSTek"])
TPL = dict(vendor=["TP-Link"])
NETGEAR = dict(vendor=["Netgear"])
DEVOLO = dict(vendor=["devolo"])
UBNT = dict(vendor=["Ubiquiti"])
MIKROTIK = dict(vendor=["Routerboard", "MikroTik"])

# (Typ, Hersteller, Modell, Ports, WLAN, verwaltet, Treiber, Hinweis, Erkennung)
E = [
    # AVM FRITZ!
    ("router", "AVM", "FRITZ!Box 6591 Cable", "4:rj45:1G:LAN, 1:coax::Kabel", "Wi-Fi 5 (2,4/5 GHz)", True, "fritzbox_tr064", "DOCSIS 3.1, DECT, 2× USB", AVM),
    ("router", "AVM", "FRITZ!Box 6660 Cable", "1:rj45:2.5G:LAN, 4:rj45:1G:LAN, 1:coax::Kabel", "Wi-Fi 6 (2,4/5 GHz)", True, "fritzbox_tr064", "", AVM),
    ("router", "AVM", "FRITZ!Box 6690 Cable", "1:rj45:2.5G:WAN/LAN, 4:rj45:1G:LAN, 1:coax::Kabel", "Wi-Fi 6 (2,4/5 GHz)", True, "fritzbox_tr064", "", AVM),
    ("router", "AVM", "FRITZ!Box 7590", "4:rj45:1G:LAN, 1:rj45:1G:WAN, 1:dsl::DSL", "Wi-Fi 5 (2,4/5 GHz)", True, "fritzbox_tr064", "", AVM),
    ("router", "AVM", "FRITZ!Box 7590 AX", "4:rj45:1G:LAN, 1:rj45:1G:WAN, 1:dsl::DSL", "Wi-Fi 6 (2,4/5 GHz)", True, "fritzbox_tr064", "", AVM),
    ("router", "AVM", "FRITZ!Box 7530 AX", "4:rj45:1G:LAN, 1:dsl::DSL", "Wi-Fi 6 (2,4/5 GHz)", True, "fritzbox_tr064", "", AVM),
    ("router", "AVM", "FRITZ!Box 5590 Fiber", "1:rj45:2.5G:WAN/LAN, 4:rj45:1G:LAN, 1:sfp::Glasfaser", "Wi-Fi 6 (2,4/5 GHz)", True, "fritzbox_tr064", "", AVM),
    ("router", "AVM", "FRITZ!Box 4060", "1:rj45:2.5G:WAN, 3:rj45:1G:LAN", "Wi-Fi 6 Tri-Band", True, "fritzbox_tr064", "", AVM),
    ("repeater", "AVM", "FRITZ!Repeater 1200 AX", "1:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "fritzbox_tr064", "", AVM),
    ("repeater", "AVM", "FRITZ!Repeater 3000 AX", "2:rj45:1G:LAN", "Wi-Fi 6 Tri-Band", True, "fritzbox_tr064", "", AVM),
    ("repeater", "AVM", "FRITZ!Repeater 600", "", "Wi-Fi 4 (2,4 GHz)", True, "fritzbox_tr064", "", AVM),
    ("powerline", "AVM", "FRITZ!Powerline 1260E", "1:rj45:1G:LAN", "Wi-Fi 5 (2,4/5 GHz)", True, "fritzbox_tr064", "", AVM),
    # Zyxel
    ("switch", "Zyxel", "XGS1935-28", "24:rj45:1G, 4:sfp+:10G", "", True, "snmp", "Lite-L3 Smart Managed", ZYXEL),
    ("switch", "Zyxel", "XGS1935-28HP", "24:rj45:1G::poe, 4:sfp+:10G", "", True, "snmp", "Lite-L3 Smart Managed, PoE+", ZYXEL),
    ("switch", "Zyxel", "XGS1930-28", "24:rj45:1G, 4:sfp+:10G", "", True, "snmp", "Smart Managed", ZYXEL),
    ("switch", "Zyxel", "GS1900-8", "8:rj45:1G", "", True, "snmp", "Smart Managed", ZYXEL),
    ("switch", "Zyxel", "GS1900-8HP", "8:rj45:1G::poe", "", True, "snmp", "Smart Managed, PoE", ZYXEL),
    ("switch", "Zyxel", "GS1900-10HP", "8:rj45:1G::poe, 2:sfp:1G", "", True, "snmp", "Smart Managed, PoE", ZYXEL),
    ("switch", "Zyxel", "GS1900-24", "24:rj45:1G, 2:sfp:1G", "", True, "snmp", "Smart Managed", ZYXEL),
    ("switch", "Zyxel", "GS1900-24E", "24:rj45:1G", "", True, "snmp", "Smart Managed", ZYXEL),
    ("switch", "Zyxel", "XMG1915-10E", "8:rj45:2.5G, 2:sfp+:10G", "", True, "snmp", "Smart Managed", ZYXEL),
    ("switch", "Zyxel", "GS1200-8", "8:rj45:1G", "", True, "", "Web Managed, kein SNMP", ZYXEL),
    ("switch", "Zyxel", "GS1200-5", "5:rj45:1G", "", True, "", "Web Managed, kein SNMP", ZYXEL),
    ("switch", "Zyxel", "GS-108B", "8:rj45:1G", "", False, "", "unmanaged", ZYXEL),
    # ASUS
    ("mesh", "ASUS", "ExpertWiFi EBM68", "1:rj45:2.5G:WAN, 3:rj45:1G:LAN", "Wi-Fi 6E Tri-Band (2,4/5/6 GHz)", True, "asuswrt", "AiMesh", ASUS),
    ("mesh", "ASUS", "ZenWiFi XT8", "1:rj45:2.5G:WAN, 3:rj45:1G:LAN", "Wi-Fi 6 Tri-Band", True, "asuswrt", "AiMesh", ASUS),
    ("mesh", "ASUS", "ZenWiFi XD5", "1:rj45:1G:WAN, 1:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "asuswrt", "AiMesh", ASUS),
    ("router", "ASUS", "RT-AX88U", "1:rj45:1G:WAN, 8:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "asuswrt", "AiMesh", ASUS),
    ("router", "ASUS", "RT-AX86U", "1:rj45:1G:WAN, 1:rj45:2.5G:WAN/LAN, 4:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "asuswrt", "AiMesh", ASUS),
    ("router", "ASUS", "RT-AX58U", "1:rj45:1G:WAN, 4:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "asuswrt", "AiMesh", ASUS),
    # TP-Link Omada
    ("router", "TP-Link", "Omada ER605", "1:rj45:1G:WAN, 3:rj45:1G:WAN/LAN, 1:rj45:1G:LAN", "", True, "omada", "VPN-Router", TPL),
    ("router", "TP-Link", "Omada ER7206", "1:sfp:1G:WAN, 1:rj45:1G:WAN, 2:rj45:1G:WAN/LAN, 1:sfp:1G:WAN/LAN, 1:rj45:1G:LAN", "", True, "omada", "", TPL),
    ("switch", "TP-Link", "Omada TL-SG2008", "8:rj45:1G", "", True, "omada", "Smart Switch", TPL),
    ("switch", "TP-Link", "Omada TL-SG2008P", "8:rj45:1G::poe", "", True, "omada", "Smart Switch, 4 Ports PoE+", TPL),
    ("switch", "TP-Link", "Omada TL-SG2210P", "8:rj45:1G::poe, 2:sfp:1G", "", True, "omada", "Smart Switch, PoE+", TPL),
    ("switch", "TP-Link", "Omada TL-SG2428P", "24:rj45:1G::poe, 4:sfp:1G", "", True, "omada", "Smart Switch, 24 Ports PoE+", TPL),
    ("switch", "TP-Link", "Omada TL-SG3428", "24:rj45:1G, 4:sfp:1G", "", True, "omada", "L2+ Managed", TPL),
    ("switch", "TP-Link", "Omada SX3008F", "8:sfp+:10G", "", True, "omada", "L2+ Managed", TPL),
    ("ap", "TP-Link", "Omada EAP610", "1:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "omada", "Deckenmontage, PoE", TPL),
    ("ap", "TP-Link", "Omada EAP650", "1:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "omada", "Deckenmontage, PoE", TPL),
    ("ap", "TP-Link", "Omada EAP670", "1:rj45:2.5G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "omada", "Deckenmontage, PoE+", TPL),
    ("ap", "TP-Link", "Omada EAP615-Wall", "1:rj45:1G:Uplink, 3:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "omada", "Wandmontage", TPL),
    ("server", "TP-Link", "Omada OC200", "2:rj45:100M", "", True, "omada", "Hardware-Controller", TPL),
    ("mesh", "TP-Link", "Deco X50", "3:rj45:1G", "Wi-Fi 6 (2,4/5 GHz)", True, "", "Deco-Mesh", TPL),
    ("switch", "TP-Link", "TL-SG108", "8:rj45:1G", "", False, "", "unmanaged", TPL),
    ("switch", "TP-Link", "TL-SG105", "5:rj45:1G", "", False, "", "unmanaged", TPL),
    # Netgear
    ("switch", "Netgear", "GS105", "5:rj45:1G", "", False, "", "unmanaged", NETGEAR),
    ("switch", "Netgear", "GS108", "8:rj45:1G", "", False, "", "unmanaged", NETGEAR),
    ("switch", "Netgear", "GS308E", "8:rj45:1G", "", True, "", "Plus Switch, kein SNMP", NETGEAR),
    ("switch", "Netgear", "GS108Tv3", "8:rj45:1G", "", True, "snmp", "Smart Managed Pro", NETGEAR),
    ("switch", "Netgear", "GS110TP", "8:rj45:1G::poe, 2:sfp:1G", "", True, "snmp", "Smart Managed Pro, PoE", NETGEAR),
    ("switch", "Netgear", "MS510TXPP", "4:rj45:1G::poe, 2:rj45:2.5G::poe, 2:rj45:5G::poe, 1:rj45:10G, 1:sfp+:10G", "", True, "snmp", "Multi-Gigabit, PoE+", NETGEAR),
    ("mesh", "Netgear", "Orbi RBR750", "1:rj45:1G:WAN, 3:rj45:1G:LAN", "Wi-Fi 6 Tri-Band", True, "", "Orbi-Router", NETGEAR),
    ("mesh", "Netgear", "Orbi RBS750", "2:rj45:1G:LAN", "Wi-Fi 6 Tri-Band", True, "", "Orbi-Satellit", NETGEAR),
    # devolo
    ("powerline", "devolo", "Magic 2 LAN triple", "3:rj45:1G:LAN", "", True, "", "G.hn", DEVOLO),
    ("powerline", "devolo", "Magic 2 LAN 1-1", "1:rj45:1G:LAN", "", True, "", "G.hn", DEVOLO),
    ("powerline", "devolo", "Magic 2 WiFi 6", "2:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "", "G.hn, Mesh", DEVOLO),
    ("powerline", "devolo", "Magic 2 WiFi next", "2:rj45:1G:LAN", "Wi-Fi 5 (2,4/5 GHz)", True, "", "G.hn, Mesh", DEVOLO),
    ("powerline", "devolo", "Magic 1 WiFi", "2:rj45:100M:LAN", "Wi-Fi 4 (2,4 GHz)", True, "", "HomePlug AV2", DEVOLO),
    # MikroTik (RouterOS)
    ("router", "MikroTik", "hAP ax³", "1:rj45:2.5G:WAN/PoE-in, 4:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "mikrotik", "RouterOS 7, USB", MIKROTIK),
    ("router", "MikroTik", "hAP ax²", "5:rj45:1G", "Wi-Fi 6 (2,4/5 GHz)", True, "mikrotik", "RouterOS 7", MIKROTIK),
    ("router", "MikroTik", "hAP ac²", "5:rj45:1G", "Wi-Fi 5 (2,4/5 GHz)", True, "mikrotik", "RouterOS", MIKROTIK),
    ("router", "MikroTik", "hEX S (RB760iGS)", "5:rj45:1G, 1:sfp:1G", "", True, "mikrotik", "RouterOS, PoE-out an ether5", MIKROTIK),
    ("router", "MikroTik", "hEX (RB750Gr3)", "5:rj45:1G", "", True, "mikrotik", "RouterOS", MIKROTIK),
    ("router", "MikroTik", "RB5009UG+S+IN", "1:rj45:2.5G, 7:rj45:1G, 1:sfp+:10G", "", True, "mikrotik", "RouterOS 7", MIKROTIK),
    ("switch", "MikroTik", "CRS326-24G-2S+RM", "24:rj45:1G, 2:sfp+:10G", "", True, "mikrotik", "RouterOS / SwOS", MIKROTIK),
    ("switch", "MikroTik", "CRS310-8G+2S+IN", "8:rj45:2.5G, 2:sfp+:10G", "", True, "mikrotik", "RouterOS 7", MIKROTIK),
    ("switch", "MikroTik", "CRS305-1G-4S+IN", "1:rj45:1G, 4:sfp+:10G", "", True, "mikrotik", "RouterOS / SwOS", MIKROTIK),
    ("ap", "MikroTik", "cAP ax", "2:rj45:1G", "Wi-Fi 6 (2,4/5 GHz)", True, "mikrotik", "Deckenmontage, PoE-in", MIKROTIK),
    # Ubiquiti UniFi
    ("router", "Ubiquiti", "UniFi Dream Machine Pro", "1:rj45:1G:WAN, 8:rj45:1G:LAN, 1:sfp+:10G:WAN, 1:sfp+:10G:LAN", "", True, "unifi", "UniFi OS Konsole", UBNT),
    ("router", "Ubiquiti", "UniFi Cloud Gateway Ultra", "1:rj45:2.5G:WAN, 4:rj45:1G:LAN", "", True, "unifi", "UniFi OS Konsole", UBNT),
    ("router", "Ubiquiti", "UniFi Dream Router", "1:rj45:1G:WAN, 4:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "unifi", "UniFi OS Konsole, 2 Ports PoE", UBNT),
    ("switch", "Ubiquiti", "UniFi Switch Flex Mini", "5:rj45:1G", "", True, "unifi", "PoE-versorgt", UBNT),
    ("switch", "Ubiquiti", "UniFi Switch Lite 8 PoE", "4:rj45:1G::poe, 4:rj45:1G", "", True, "unifi", "", UBNT),
    ("switch", "Ubiquiti", "UniFi Switch Lite 16 PoE", "8:rj45:1G::poe, 8:rj45:1G", "", True, "unifi", "", UBNT),
    ("switch", "Ubiquiti", "UniFi Switch 24", "24:rj45:1G, 2:sfp:1G", "", True, "unifi", "", UBNT),
    ("switch", "Ubiquiti", "UniFi Switch Pro 24", "24:rj45:1G, 2:sfp+:10G", "", True, "unifi", "Layer 3", UBNT),
    ("ap", "Ubiquiti", "UniFi U6 Lite", "1:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "unifi", "Deckenmontage, PoE", UBNT),
    ("ap", "Ubiquiti", "UniFi U6+", "1:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "unifi", "Deckenmontage, PoE", UBNT),
    ("ap", "Ubiquiti", "UniFi U6 Pro", "1:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "unifi", "Deckenmontage, PoE+", UBNT),
    ("ap", "Ubiquiti", "UniFi U7 Pro", "1:rj45:2.5G:LAN", "Wi-Fi 7 (2,4/5/6 GHz)", True, "unifi", "Deckenmontage, PoE+", UBNT),
    ("ap", "Ubiquiti", "UniFi U6 In-Wall", "1:rj45:1G:Uplink, 4:rj45:1G:LAN", "Wi-Fi 6 (2,4/5 GHz)", True, "unifi", "Wandmontage", UBNT),
    # Generische Einträge zum Konfigurieren
    ("switch", "Generisch", "Switch 5 Ports", "5:rj45:1G", "", False, "", "unmanaged", {}),
    ("switch", "Generisch", "Switch 8 Ports", "8:rj45:1G", "", False, "", "unmanaged", {}),
    ("switch", "Generisch", "Switch 16 Ports", "16:rj45:1G", "", False, "", "unmanaged", {}),
    ("switch", "Generisch", "Switch 24 Ports", "24:rj45:1G", "", False, "", "unmanaged", {}),
    ("switch", "Generisch", "Switch 48 Ports + 4 SFP+", "48:rj45:1G, 4:sfp+:10G", "", True, "snmp", "", {}),
    ("router", "Generisch", "Router 4 Ports", "1:rj45:1G:WAN, 4:rj45:1G:LAN", "", True, "", "", {}),
    ("ap", "Generisch", "Access Point", "1:rj45:1G:LAN", "Wi-Fi", True, "", "", {}),
    ("hypervisor", "Generisch", "Proxmox-Host", "2:rj45:1G:NIC", "", True, "proxmox", "", {}),
    ("nas", "Synology", "DS224+", "2:rj45:1G:LAN", "", True, "snmp", "", dict(vendor=["Synology"])),
    ("nas", "Synology", "DS923+", "4:rj45:1G:LAN", "", True, "snmp", "", dict(vendor=["Synology"])),
    ("computer", "Raspberry Pi", "Raspberry Pi 5", "1:rj45:1G:LAN", "Wi-Fi 5", False, "", "", dict(vendor=["Raspberry Pi"])),
]


def main():
    out = []
    for typ, man, model, ports, wifi, managed, driver, note, match in E:
        data = dict(ports=parse_ports(ports), wifi=wifi, managed=managed, driver=driver, note=note, verified=False,
                    source="Herstellerangaben, nicht einzeln geprüft")
        vend = {k: v for k, v in match.items() if k != "driver"}
        if vend:
            data["match"] = vend
        out.append(dict(type=typ, manufacturer=man, model=model, data=data))
    keys = [(e["manufacturer"], e["model"]) for e in out]
    assert len(keys) == len(set(keys)), "doppelte Einträge"
    path = pathlib.Path(__file__).resolve().parent.parent / "app" / "catalog_seed.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out)} Einträge -> {path}")


if __name__ == "__main__":
    main()
