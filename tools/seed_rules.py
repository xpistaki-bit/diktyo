#!/usr/bin/env python3
"""Erzeugt app/ident_rules.json (Erkennungsregeln). Aufruf: python3 tools/seed_rules.py

Eine Regel trifft zu, wenn ALLE ihre Bedingungen zutreffen. Bedingungen (reguläre Ausdrücke, Groß-/Kleinschreibung egal):
  vendor    Hersteller laut MAC-Adresse (IEEE)
  hostname  Hostname aus DNS, mDNS oder NetBIOS
  mdns      mDNS-Dienste, -Namen und -Merkmale (z. B. _googlecast._tcp)
  ssdp      UPnP-Server, -Hersteller und -Modell
  http      Titel, Server-Kopfzeile und Anmeldebereich der Weboberfläche
  ports     alle diese TCP-Ports offen (Liste)
  any_ports mindestens einer dieser Ports offen (Liste)
  random    True: zufällige (lokal verwaltete) MAC-Adresse
Gewicht 0–100 = Sicherheit der Vermutung. Die höchste zutreffende Regel gewinnt.
"""
import json
import pathlib

# (Schlüssel, Bezeichnung DE, Bezeichnung EN, Typ, Gewicht, Bedingungen)
R = [
    # Amazon
    ("amazon", "Amazon-Gerät (Echo, Fire TV oder Kindle)", "Amazon device (Echo, Fire TV or Kindle)", "speaker", 40, dict(vendor="amazon")),
    ("amazon-echo", "Amazon Echo (Alexa)", "Amazon Echo (Alexa)", "speaker", 80, dict(vendor="amazon", hostname=r"echo|alexa|amazon-")),
    ("amazon-echo-host", "Amazon Echo (Alexa)", "Amazon Echo (Alexa)", "speaker", 70, dict(hostname=r"\becho[-_ ]|alexa")),
    ("amazon-firetv", "Amazon Fire TV", "Amazon Fire TV", "tv", 84, dict(mdns=r"_amzn-wplay|fire ?tv|aftm|afts")),
    ("amazon-firetv-host", "Amazon Fire TV", "Amazon Fire TV", "tv", 70, dict(hostname=r"fire-?tv|aftm|afts")),
    # Google
    ("google", "Google-Gerät (Nest, Chromecast)", "Google device (Nest, Chromecast)", "speaker", 40, dict(vendor="google")),
    ("googlecast", "Chromecast / Google Cast", "Chromecast / Google Cast", "tv", 65, dict(mdns="_googlecast")),
    ("google-nest", "Google Nest Lautsprecher/Display", "Google Nest speaker/display", "speaker", 80, dict(mdns=r"_googlecast", hostname=r"nest|google-home")),
    ("google-nest-txt", "Google Nest Lautsprecher/Display", "Google Nest speaker/display", "speaker", 80, dict(mdns=r"google (home|nest)|nest (mini|audio|hub)")),
    ("chromecast", "Google Chromecast", "Google Chromecast", "tv", 80, dict(mdns=r"chromecast")),
    # Apple
    ("apple", "Apple-Gerät", "Apple device", "phone", 35, dict(vendor="apple")),
    ("apple-tv", "Apple TV", "Apple TV", "tv", 80, dict(mdns=r"appletv|apple ?tv")),
    ("airplay", "AirPlay-Gerät", "AirPlay device", "tv", 55, dict(mdns="_airplay|_raop")),
    ("homepod", "Apple HomePod", "Apple HomePod", "speaker", 85, dict(mdns=r"homepod|audioaccessory")),
    ("iphone", "iPhone", "iPhone", "phone", 80, dict(hostname="iphone")),
    ("ipad", "iPad", "iPad", "tablet", 80, dict(hostname="ipad")),
    ("mac", "Mac", "Mac", "laptop", 75, dict(hostname=r"macbook|imac|mac-?mini|mac-?studio")),
    ("iphone-port", "iPhone / iPad", "iPhone / iPad", "phone", 60, dict(vendor="apple", ports=[62078])),
    # Smartphones allgemein
    ("random-mac", "Smartphone, Tablet oder Laptop mit zufälliger MAC-Adresse (Privatsphäre-Funktion)",
     "Smartphone, tablet or laptop with a random MAC address (privacy feature)", "phone", 35, dict(random=True)),
    ("android", "Android-Smartphone", "Android smartphone", "phone", 70, dict(hostname=r"android|galaxy|pixel|redmi|oneplus|huawei")),
    ("samsung-phone", "Samsung-Smartphone/-Tablet", "Samsung smartphone/tablet", "phone", 55, dict(vendor="samsung", hostname=r"galaxy|sm-")),
    # AVM
    ("avm", "AVM FRITZ!-Gerät", "AVM FRITZ! device", "router", 55, dict(vendor=r"\bavm\b")),
    ("fritzbox", "AVM FRITZ!Box", "AVM FRITZ!Box", "router", 85, dict(http="fritz!box")),
    ("fritzbox-ssdp", "AVM FRITZ!Box", "AVM FRITZ!Box", "router", 85, dict(ssdp="fritz!box")),
    ("fritzrepeater", "AVM FRITZ!Repeater", "AVM FRITZ!Repeater", "repeater", 88, dict(ssdp="fritz!repeater")),
    ("fritzrepeater-http", "AVM FRITZ!Repeater", "AVM FRITZ!Repeater", "repeater", 88, dict(http="fritz!repeater")),
    ("fritzpowerline", "AVM FRITZ!Powerline", "AVM FRITZ!Powerline", "powerline", 88, dict(ssdp="fritz!powerline")),
    ("fritzdect", "AVM FRITZ!DECT / FRITZ!Smart", "AVM FRITZ!DECT / FRITZ!Smart", "iot", 80, dict(hostname=r"fritz-?dect|fritz-?smart")),
    # Netzwerk
    ("asus", "ASUS Router / Mesh-Knoten", "ASUS router / mesh node", "mesh", 50, dict(vendor="asustek")),
    ("asus-http", "ASUS Router / Mesh-Knoten", "ASUS router / mesh node", "mesh", 80, dict(http=r"asus|expertwifi|zenwifi|rt-ax|rt-be")),
    ("zyxel", "Zyxel-Gerät", "Zyxel device", "switch", 50, dict(vendor="zyxel")),
    ("zyxel-switch", "Zyxel Switch", "Zyxel switch", "switch", 85, dict(http=r"xgs1|gs19|gs12|xmg|zyxel")),
    ("tplink", "TP-Link-Gerät (Router, Access Point oder Smart Plug)", "TP-Link device (router, access point or smart plug)", "iot", 30, dict(vendor="tp-?link")),
    ("omada", "TP-Link Omada", "TP-Link Omada", "ap", 75, dict(http=r"omada|eap\d")),
    ("tapo", "TP-Link Tapo / Kasa", "TP-Link Tapo / Kasa", "iot", 75, dict(hostname=r"tapo|kasa|hs1\d\d|p1\d\d")),
    ("deco", "TP-Link Deco Mesh", "TP-Link Deco mesh", "mesh", 80, dict(hostname=r"deco")),
    ("ubiquiti", "Ubiquiti UniFi", "Ubiquiti UniFi", "ap", 55, dict(vendor="ubiquiti")),
    ("unifi-http", "UniFi-Konsole", "UniFi console", "router", 80, dict(http=r"unifi")),
    ("netgear", "Netgear-Gerät", "Netgear device", "switch", 45, dict(vendor="netgear")),
    ("devolo", "devolo Powerline", "devolo powerline", "powerline", 80, dict(vendor="devolo")),
    ("mikrotik", "MikroTik", "MikroTik", "router", 70, dict(vendor="routerboard|mikrotik")),
    # Server, NAS, Smart Home
    ("proxmox", "Proxmox VE", "Proxmox VE", "hypervisor", 92, dict(ports=[8006])),
    ("proxmox-http", "Proxmox VE", "Proxmox VE", "hypervisor", 95, dict(http="proxmox")),
    ("homeassistant", "Home Assistant", "Home Assistant", "server", 90, dict(ports=[8123])),
    ("homeassistant-mdns", "Home Assistant", "Home Assistant", "server", 92, dict(mdns="_home-assistant")),
    ("synology", "Synology NAS", "Synology NAS", "nas", 85, dict(vendor="synology")),
    ("synology-http", "Synology NAS", "Synology NAS", "nas", 88, dict(http=r"synology|diskstation")),
    ("qnap", "QNAP NAS", "QNAP NAS", "nas", 85, dict(vendor="qnap")),
    ("nas-ports", "NAS (Synology/QNAP-Weboberfläche)", "NAS (Synology/QNAP web interface)", "nas", 45, dict(ports=[5000, 5001])),
    ("plex", "Medienserver (Plex)", "Media server (Plex)", "server", 60, dict(ports=[32400])),
    ("raspberrypi", "Raspberry Pi", "Raspberry Pi", "computer", 70, dict(vendor="raspberry")),
    ("proxmox-vm", "VM / Container auf Proxmox", "VM / container on Proxmox", "vm", 75, dict(vendor="proxmox")),
    ("vmware-vm", "VM (VMware)", "VM (VMware)", "vm", 70, dict(vendor="vmware")),
    ("qemu-vm", "VM (QEMU/KVM)", "VM (QEMU/KVM)", "vm", 60, dict(vendor=r"qemu|red hat")),
    ("ssh-only", "Linux-Server", "Linux server", "server", 30, dict(ports=[22])),
    # IoT
    ("espressif", "IoT-Gerät mit ESP-Chip (z. B. Shelly, Tasmota, ESPHome)", "IoT device with ESP chip (e.g. Shelly, Tasmota, ESPHome)", "iot", 60, dict(vendor="espressif")),
    ("esphome", "ESPHome-Gerät", "ESPHome device", "iot", 88, dict(mdns="_esphomelib")),
    ("shelly", "Shelly", "Shelly", "iot", 88, dict(hostname="shelly")),
    ("shelly-mdns", "Shelly", "Shelly", "iot", 88, dict(mdns="shelly")),
    ("tasmota", "Tasmota-Gerät", "Tasmota device", "iot", 88, dict(http="tasmota")),
    ("hue", "Philips Hue Bridge", "Philips Hue Bridge", "iot", 88, dict(vendor=r"signify|philips lighting")),
    ("hue-mdns", "Philips Hue Bridge", "Philips Hue Bridge", "iot", 88, dict(mdns="_hue|philips hue")),
    ("ikea", "IKEA Gateway (TRÅDFRI/DIRIGERA)", "IKEA gateway (TRÅDFRI/DIRIGERA)", "iot", 75, dict(vendor="ikea")),
    ("homekit", "HomeKit-Gerät", "HomeKit device", "iot", 50, dict(mdns="_hap")),
    ("tuya", "Smart-Home-Gerät (Tuya)", "Smart home device (Tuya)", "iot", 70, dict(vendor="tuya")),
    ("vacuum", "Saugroboter", "Robot vacuum", "iot", 86, dict(hostname=r"vacuum|dreame|roborock|roomba|deebot")),
    ("xiaomi", "Xiaomi / Roborock (z. B. Saugroboter)", "Xiaomi / Roborock (e.g. robot vacuum)", "iot", 55, dict(vendor=r"xiaomi|roborock|dreame")),
    ("bsh", "Hausgerät (Home Connect: Bosch, Siemens, Neff)", "Home appliance (Home Connect: Bosch, Siemens, Neff)", "iot", 80, dict(vendor=r"bsh hausger")),
    ("miele", "Miele-Hausgerät", "Miele appliance", "iot", 80, dict(vendor="miele")),
    ("tado", "tado° Thermostat-Bridge", "tado° thermostat bridge", "iot", 80, dict(vendor="tado")),
    ("netatmo", "Netatmo", "Netatmo", "iot", 80, dict(vendor="netatmo")),
    ("nuki", "Nuki Smart Lock / Bridge", "Nuki smart lock / bridge", "iot", 80, dict(vendor="nuki")),
    ("sonos", "Sonos-Lautsprecher", "Sonos speaker", "speaker", 85, dict(vendor="sonos")),
    ("sonos-port", "Sonos-Lautsprecher", "Sonos speaker", "speaker", 75, dict(ports=[1400], ssdp="sonos")),
    ("mqtt", "MQTT-Broker", "MQTT broker", "server", 50, dict(ports=[1883])),
    # Medien
    ("samsung-tv", "Samsung Smart TV", "Samsung smart TV", "tv", 80, dict(ssdp=r"samsung.*(tv|tizen)|tizen")),
    ("lg-tv", "LG Smart TV (webOS)", "LG smart TV (webOS)", "tv", 80, dict(ssdp=r"webos|lg.*tv")),
    ("sony-tv", "Sony Bravia TV", "Sony Bravia TV", "tv", 80, dict(ssdp=r"bravia")),
    ("dlna", "Medienwiedergabe (DLNA/UPnP)", "Media player (DLNA/UPnP)", "tv", 45, dict(ssdp=r"mediarenderer|dlna")),
    ("spotify", "Lautsprecher mit Spotify Connect", "Speaker with Spotify Connect", "speaker", 50, dict(mdns="_spotify-connect")),
    ("playstation", "Sony PlayStation", "Sony PlayStation", "console", 85, dict(vendor="sony interactive")),
    ("nintendo", "Nintendo-Konsole", "Nintendo console", "console", 85, dict(vendor="nintendo")),
    ("xbox", "Microsoft Xbox", "Microsoft Xbox", "console", 75, dict(hostname="xbox")),
    # Drucker, Kameras, PCs
    ("printer-mdns", "Netzwerkdrucker", "Network printer", "printer", 80, dict(mdns=r"_ipp|_printer|_pdl-datastream")),
    ("printer-port", "Netzwerkdrucker", "Network printer", "printer", 65, dict(ports=[9100])),
    ("ipp-port", "Drucker oder Computer mit Druckdienst (IPP)", "Printer or computer with print service (IPP)", "printer", 32, dict(ports=[631])),
    ("printer-vendor", "Drucker", "Printer", "printer", 45, dict(vendor=r"brother|seiko epson|canon|hewlett|hp inc|kyocera|lexmark")),
    ("camera-rtsp", "Kamera (RTSP-Stream)", "Camera (RTSP stream)", "camera", 55, dict(ports=[554])),
    ("camera-vendor", "IP-Kamera", "IP camera", "camera", 85, dict(vendor=r"hikvision|dahua|reolink|axis comm|amcrest|wyze|ezviz|foscam")),
    ("windows", "Windows-PC", "Windows PC", "computer", 60, dict(hostname=r"^desktop-|^laptop-|^win-")),
    ("pc-host", "Computer", "Computer", "computer", 55, dict(hostname=r"(^|[-_])(pc|desktop|notebook|laptop|workstation)($|[-_])")),
    ("smb", "Computer oder NAS mit Dateifreigabe", "Computer or NAS with file sharing", "computer", 35, dict(ports=[445])),
    ("intel-nic", "Computer (Intel-Netzwerkkarte)", "Computer (Intel network card)", "computer", 30, dict(vendor=r"^intel")),
    ("wifi-module", "Laptop oder Mobilgerät (WLAN-Modul)", "Laptop or mobile device (Wi-Fi module)", "laptop", 25, dict(vendor=r"azurewave|liteon|murata|universal global|hon hai|chongqing fugui")),
    # Aus einem echten Heimnetz (EBM68, Shelly, Echo, Reolink, SMLIGHT …)
    ("amazon-echo-ports", "Amazon Echo (Alexa)", "Amazon Echo (Alexa)", "speaker", 78, dict(vendor="amazon", any_ports=[55442, 55443, 4070])),
    ("asus-ebm68", "ASUS ExpertWiFi EBM68", "ASUS ExpertWiFi EBM68", "mesh", 92, dict(ssdp=r"ebm68")),
    ("asus-expertwifi-mdns", "ASUS ExpertWiFi", "ASUS ExpertWiFi", "mesh", 88, dict(mdns=r"_expertwifi")),
    ("shelly-http", "Shelly", "Shelly", "iot", 90, dict(http=r"shelly")),
    ("reolink-http", "Reolink-Kamera", "Reolink camera", "camera", 90, dict(http="reolink")),
    ("slzb", "Zigbee-Koordinator (SMLIGHT SLZB)", "Zigbee coordinator (SMLIGHT SLZB)", "iot", 90, dict(mdns=r"slzb")),
    ("ai-on-the-edge", "Zählerauslesung (AI on the edge, ESP32-CAM)", "Meter reader (AI on the edge, ESP32-CAM)", "iot", 90, dict(http=r"ai on the edge")),
    ("matter", "Matter-Gerät", "Matter device", "iot", 45, dict(mdns=r"_matter")),
    ("windows-dosvc", "Windows-PC", "Windows PC", "computer", 65, dict(mdns=r"_dosvc")),
    ("proxmox-server", "Proxmox VE", "Proxmox VE", "hypervisor", 95, dict(http="pve-api-daemon")),
    ("homeassistant-http", "Home Assistant", "Home Assistant", "server", 93, dict(http="home assistant")),
    ("esphome-builder", "Home Assistant (ESPHome Builder)", "Home Assistant (ESPHome Builder)", "server", 91, dict(mdns="_esphomebuilder")),
    ("trilium", "Trilium Notes (Server)", "Trilium Notes (server)", "server", 85, dict(http="trilium")),
    ("panelatlas", "PanelAtlas (Server)", "PanelAtlas (server)", "server", 85, dict(http="panelatlas")),
    ("diktyo", "díktyo (Server)", "díktyo (server)", "server", 85, dict(http=r"díktyo|diktyo")),
    ("netbox", "NetBox (Server)", "NetBox (server)", "server", 85, dict(http=r"netbox")),
    ("ring", "Ring (Türklingel oder Kamera)", "Ring (doorbell or camera)", "camera", 82, dict(vendor=r"\bring\b")),
    ("ring-host", "Ring (Türklingel oder Kamera)", "Ring (doorbell or camera)", "camera", 82, dict(hostname=r"^ring-")),
    ("switchbot", "SwitchBot Hub", "SwitchBot hub", "iot", 86, dict(hostname=r"switchbot")),
    ("smart-plug", "Smarte Steckdose", "Smart plug", "iot", 72, dict(hostname=r"steckdose|plug|socket|outlet")),
    ("esphome-host", "ESPHome-Gerät", "ESPHome device", "iot", 84, dict(hostname=r"esphome|bluetooth-proxy|esp32-|esp8266-")),
    ("asus-8443", "ASUS Router / Mesh-Knoten", "ASUS router / mesh node", "mesh", 75, dict(vendor="asustek", ports=[8443])),
    ("iot-module", "Wahrscheinlich ein IoT-Gerät (WLAN-Modul eines Zulieferers)", "Probably an IoT device (Wi-Fi module from a supplier)", "iot", 25,
     dict(vendor=r"fn-link|hui zhou|gsd viet|ampak|shenzhen|hangzhou|lwip|beken|bouffalo|realtek|mediatek|silicon labs|texas instruments|ti\b|cyx|china dragon|qingdao")),
    ("android-tv", "Android TV / Google TV", "Android TV / Google TV", "tv", 70, dict(ssdp=r"android", any_ports=[8009])),
]


def main():
    out = []
    for key, de, en, typ, w, cond in R:
        out.append(dict(key=key, label=de, label_en=en, type=typ, weight=w, cond=cond))
    keys = [e["key"] for e in out]
    assert len(keys) == len(set(keys)), "doppelte Schlüssel"
    path = pathlib.Path(__file__).resolve().parent.parent / "app" / "ident_rules.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out)} Regeln -> {path}")


if __name__ == "__main__":
    main()
