# díktyo – Plan, Erweiterungen und Verbesserungen

Stand: Version 0.22.0 (November 2026). Die ausführliche Bedienung steht in [ANLEITUNG.de.md](ANLEITUNG.de.md),
der technische Aufbau in [architecture.md](architecture.md).

## 1. Erledigt

| Bereich | Inhalt | Version |
|---|---|---|
| Grundlage (M0) | Installer für Proxmox-LXC (inkl. VLAN-Schnittstellen) und Docker, Konten, Profile mit Freigabe, DE/EN, HUD-Design | 0.1 |
| Bestand (M1) | Geräte, IPAM mit Subnetzen/VLANs/DHCP-Bereich, Standorte, Gerätekatalog (93 Modelle) mit CSV, Tabelle, PDF, Backup wie PanelAtlas | 0.2 |
| Netzscan (M2) | Hintergrunddienst, Ping/TCP, ARP, mDNS, SSDP, NetBIOS, DNS, nmap, Erkennung mit Begründung, Posteingang, Zeitplan, OUI, Fingerbank | 0.3 |
| Integrationen (M3) | FRITZ!Box (TR-064, Mesh), Switch per SNMP v2c/v3 (Ports, Traffic, MAC-Tabelle, LLDP) | 0.4 |
| Topologie (M4) | Gesamtbaum, Frontplatte mit klickbaren Ports, aufklappbare WLAN-/VM-Gruppen, Schnell-Ping, PDF | 0.5 |
| Live-Status (M5) | Online-Überwachung, Messwerte (2–14 Tage), ASUS AiMesh, Proxmox, Home Assistant (Namen/Bereiche, MQTT, Blueprint) | 0.6 |
| Konfig-Backups (M6) | FRITZ!Box, ASUS, Switch per SSH; Versionen, Vergleich (Diff), verschlüsselt, im díktyo-Backup | 0.7 |
| Topologie+ | Vollbild, Internet-Knoten mit WAN-Status und Live-Traffic, Geräte frei verschiebbar | 0.7.1 / 0.9 |
| Controller | TP-Link Omada (Open API), Ubiquiti UniFi (Integration API) | 0.8 |
| Werkzeuge | nmap-Dienste-Scan je Gerät, SNMP-Diagnose, FRITZ!Box-2FA (Taste, Telefon, Authenticator-App, Schlüssel für Zeitplan) | 0.9 |
| Katalog | Eintrag aus Systeminfo (dmidecode, lspci …) mit Wikipedia; KI-Recherche über die Claude API (Websuche, Quellen, Kosten) | 0.9.1 / 0.10 |
| Schalten | WLAN, Internetsperre, Wake-on-LAN, Switch-Port, PoE, VMs; Vorschau, Sicherung vorher, automatisches Zurückschalten, Aussperr-Schutz, Protokoll | 0.11 |
| Sicherung | Google Drive geführt verbinden (rclone, nur eigene Dateien) | 0.11.1 |
| MikroTik | RouterOS 7 über REST: Ports, Clients, WLAN, Nachbarn, WAN, `/export`-Backup, Aktionen | 0.12 |
| Automatisierung | Zeitpläne für Aktionen (Zeitfenster, nur an Übergängen), Quarantäne für neue Geräte | 0.13 |
| Verlauf | Änderungsverlauf je Gerät und Profil mit Quelle, Zeitleiste, Kurzfassung „seit gestern“, CSV | 0.14 |
| Erreichbarkeit | Antwortzeit je Gerät, Verfügbarkeit 24 h/7/30 Tage mit Ausfällen; Firmware-Hinweise aus sechs Integrationen | 0.15 |
| Integrationen | OPNsense (REST-API: Schnittstellen, Clients, WAN, Firmware, Backup, Internetsperre per Alias), Docker (Container als virtuelle Geräte, Starten/Stoppen) | 0.16 |
| Übersicht | Übersichtsseite (Kennzahlen, „Braucht Aufmerksamkeit“, WAN-/Antwortzeit-/Port-Diagramme, Infrastruktur, Änderungen); Durchsatz in der Topologie | 0.17 |
| ASUS-Traffic | Traffic Monitor (WAN/LAN/WLAN-Bänder, WAN-Verlauf), Traffic Analyzer je Client (24 h) in Karte, Übersicht, Gerätedialog und Topologie; ASUS-Diagnose | 0.17.1 |
| Traffic je Gerät | Live-Raten je Client aus Omada, UniFi, MikroTik, OPNsense und Proxmox in Topologie (auch Gruppen), Gerätedialog und Übersicht („Gerade aktiv“); bebilderte Einstiegsanleitung (DE/EN); Anzeigefehler Port-Ansicht und Übersicht behoben | 0.18 |
| Switch | nur echte Frontports (logische Schnittstellen, Bridge-Tabelle, Katalog), Port-Farben nach Geschwindigkeit, SSH-Backup mit Schlüssel (díktyo-Schlüssel oder eigener) und wählbarem Abruf; Online-Überwachung tolerant gegen einzelne verlorene Pings | 0.18.1 |
| Stabilität | Verbindungen: genauere Quelle hat Vorrang (kein Wechsel Proxmox ↔ Router mehr); Online-Status: andere Quellen schlagen einen gescheiterten Ping; Scroll-Position bleibt beim Speichern und automatischen Neuladen | 0.18.2 |
| Geschwindigkeit | Internet-Speedtest (Cloudflare) von Hand oder nach Zeitplan mit Verlauf und Hinweis bei langsamer Leitung; iperf3 zwischen díktyo und einem Gerät | 0.19 |
| Sicherheit | Anmeldung mit zweitem Faktor (TOTP, QR lokal erzeugt, Wiederherstellungscodes, Einmal-Codes, Versuchsgrenze), Sitzungsverwaltung, Zurücksetzen durch Admin/CLI | 0.20 |
| Benachrichtigungen | E-Mail und ntfy je Profil, Ereignisse wählbar, gebündelt; neue Ereignisse: Internet langsam, Backup fehlgeschlagen, Integration gestört | 0.21 |
| Aktionen und Shelly | UniFi: Gerät neu starten, PoE-Port neu starten; Omada: Gerät neu starten, PoE ein/aus/neu starten; Shelly/Tasmota direkt: Leistung, Energie, Ausgänge schalten, Firmware | 0.22 |

## 2. Noch offen aus dem ursprünglichen Plan

| # | Inhalt | Anmerkung |
|---|---|---|
| P2.4 | Weitere Integrationen: Netgear (Smart Switches/Router), devolo (Powerline) | Docker erledigt in 0.16 |
| P2.8 | Passive DHCP-Erkennung (Fingerprinting aus DHCP-Anfragen) | braucht einen Lauscher im Netz bzw. DHCP-Logs vom Router |
| ~~Phase 3~~ | ~~Änderungsverlauf zwischen Scans~~ | erledigt in 0.14 |
| Phase 3 | Kabel- und Patchpanel-Dokumentation | Patchfelder, Dosen, Kabelnummern zwischen Port und Gerät |
| Phase 3 | Prometheus-Endpunkt | Messwerte für Grafana |
| Phase 3 | REST-API mit Tokens | für Skripte, Home Assistant, eigene Auswertungen |

## 3. An echter Hardware noch zu testen

| Integration / Funktion | Stand | Wer |
|---|---|---|
| UniFi (inkl. Live-Raten je Client über stat/sta) | nach offizieller OpenAPI gebaut, gegen nachgebildeten Controller getestet | Tester |
| MikroTik (inkl. Live-Raten: WLAN-Registrierungen, Kid Control) | nach REST-Doku gebaut, gegen nachgebildete RouterOS-API getestet | Tester |
| Omada (inkl. Live-Raten je Client, Aktionen PoE/Neustart) | nach Open-API-Doku gebaut, gegen nachgebildeten Controller getestet | offen |
| UniFi-Aktionen (Neustart, PoE-Power-Cycle) | nach Integration-API-Doku gebaut, gegen Nachbildung getestet | Tester |
| Shelly / Tasmota | gegen nachgebildete Geräte (Gen1, Gen2/3, Tasmota) getestet | Nutzer |
| OPNsense (inkl. Top Talkers), Docker | gegen nachgebildete APIs getestet | Tester |
| Proxmox: Live-Raten je VM | gegen nachgebildete API getestet | Nutzer (Proxmox vorhanden) |
| iperf3 zu einem Gerät | gegen nachgebildete iperf3-Ausgabe getestet | Nutzer |
| Switch-Aktionen (SNMP-SET) | gegen Test-Agent getestet; Zyxel mit Schreibrechten offen | Tester |
| Proxmox-Aktionen | gebaut, Token mit `VM.PowerMgmt` offen | Tester |

Am echten Gerät bestätigt: FRITZ!Box (inkl. 2FA, Backup, Schaltaktionen), ASUS EBM68 (Traffic Monitor/Analyzer),
Zyxel XGS1935 (SNMP v3, Port-Filter, SSH-Backup mit díktyo-Schlüssel), Proxmox (Gäste), Internet-Speedtest.

Offene Punkte aus den Tests: Bei UniFi ist die Einheit der WAN-Rate (Bit/Byte) nicht dokumentiert; bei MikroTik
heißen WLAN-Felder je Paket (wifi, wifiwave2, wireless) leicht unterschiedlich.

## 4. Mögliche Erweiterungen (Add-ons)

Einschätzung: Nutzen ★–★★★, Aufwand S/M/L.

### Integrationen

| Idee | Nutzen | Aufwand |
|---|---|---|
| ~~OPNsense~~ – erledigt in 0.16 | ★★★ | M |
| pfSense: wartet auf Netgates offizielle REST-API (das Community-Paket „pfrest“ ist im Wartungsmodus und endet nach pfSense 26.10) | ★★ | M |
| OpenWrt (ubus/rpcd): Clients, WLAN, Ports, Aktionen | ★★ | M |
| ~~Docker~~ – erledigt in 0.16 (Portainer optional später) | ★★ | S |
| Pi-hole / AdGuard Home: Hostnamen, Blockstatistik je Gerät | ★★ | S |
| Synology / QNAP / TrueNAS / Unraid: Status, Laufwerke, Dienste | ★★ | M |
| ~~Shelly / Tasmota direkt: Leistung, Schalten, Firmware~~ – erledigt in 0.22 | ★ | S |
| Netgear-Switches (SNMP-Profile), devolo Powerline | ★ | M |
| ~~Aktionen für UniFi (Port-Power-Cycle, Neustart) und Omada (PoE, Neustart)~~ – erledigt in 0.22 (gegen nachgebildete APIs getestet) | ★★ | S |
| ASUS: Aktionen (Gastnetz, Neustart) und lesbarer Konfig-Vergleich (CFG entschlüsseln) | ★★ | M |

### Wünsche aus dem Test (neu)

| Idee | Nutzen | Aufwand |
|---|---|---|
| ~~Datendurchsatz je Gerät in der Topologie~~ – erledigt in 0.17 (kabelgebunden), 0.17.1 (ASUS-Tagesmenge) und 0.18 (Live-Raten aus Omada, UniFi, MikroTik, OPNsense, Proxmox) | ★★★ | M |
| ~~Übersichtsseite (Dashboard)~~ – erledigt in 0.17 | ★★★ | M |
| Übersicht anpassbar: eigene Diagramme anheften (z. B. bestimmter Port, bestimmtes Gerät) | ★★ | S |
| **Gruppen in der Topologie:** eigene Gruppen („IoT“, „Kameras“, „Kinderzimmer“), die als eigene Box unter ihrem Access Point/Switch erscheinen; alternativ nach Standort oder Tag gruppieren; Schwellwerte fürs automatische Zusammenfassen einstellbar | ★★ | M |

### Monitoring

| Idee | Nutzen | Aufwand |
|---|---|---|
| ~~Latenz je Gerät, Ausfallzeiten/Verfügbarkeit~~ – erledigt in 0.15 (Bericht als PDF noch offen) | ★★★ | M |
| ~~Hinweise auf Firmware-Updates~~ – erledigt in 0.15 (Zyxel-Switch per SNMP liefert dazu nichts) | ★★★ | M |
| TLS-Zertifikate: Warnung vor Ablauf (Daten aus dem Dienste-Scan) | ★★ | S |
| ~~Speedtest bzw. iperf zwischen Geräten, Verlauf~~ – erledigt in 0.19 (díktyo ↔ Gerät) | ★★ | M |
| iperf zwischen zwei beliebigen Geräten (per SSH auf einem der beiden), díktyo als iperf3-Gegenstelle für Handy-Apps | ★ | S |
| ~~Benachrichtigungen per E-Mail und ntfy~~ – erledigt in 0.21 (Telegram/Gotify/Webhook offen) | ★★ | S |

### Sicherheit

| Idee | Nutzen | Aufwand |
|---|---|---|
| ~~Neue unbekannte Geräte automatisch in „Quarantäne“~~ – erledigt in 0.13 | ★★★ | S |
| ~~Vergleich offener Ports über die Zeit~~ – im Verlauf seit 0.14 | ★★ | S |
| ~~Anmeldung an díktyo mit 2FA (TOTP), Sitzungsverwaltung~~ – erledigt in 0.20; Passkeys (WebAuthn) und „2FA für alle Pflicht“ offen | ★★★ | M |
| Audit-Log-Ansicht in der Oberfläche | ★ | S |

### Dokumentation

| Idee | Nutzen | Aufwand |
|---|---|---|
| ~~Änderungsverlauf je Gerät~~ – erledigt in 0.14 | ★★★ | M |
| Grundriss/Raumplan mit Geräten, Rack-Ansicht | ★★ | L |
| Kabel und Patchpanels | ★★ | M |
| Export nach draw.io / SVG / PNG, Netzplan als Poster-PDF | ★★ | S |
| QR-Etiketten für Geräte (Aufkleber mit Link zum Gerät in díktyo) | ★★ | S |
| VLAN-Plan grafisch (welcher Port in welchem VLAN) | ★★ | M |

### Automatisierung

| Idee | Nutzen | Aufwand |
|---|---|---|
| ~~Zeitpläne für Aktionen~~ – erledigt in 0.13 | ★★★ | S |
| Regeln („Kamera offline → PoE neu starten“, „AP antwortet nicht → Port neu starten“) | ★★ | M |
| Aktionen als Schalter/Taster in Home Assistant (MQTT) | ★★ | S |

### KI

| Idee | Nutzen | Aufwand |
|---|---|---|
| Fragen ans eigene Netz („Welche Geräte waren gestern Nacht offline?“) | ★★ | M |
| Vorschläge für Namen und Zuordnung im Posteingang | ★★ | S |
| Konfig-Änderungen in Klartext erklären („WLAN-Kanal von 36 auf 44, neue Portfreigabe für das NAS“) | ★★ | S |

### Plattform

| Idee | Nutzen | Aufwand |
|---|---|---|
| REST-API mit Tokens, Webhooks | ★★ | M |
| Prometheus/Grafana | ★ | S |
| Handy-Ansicht / installierbare Web-App (PWA) | ★★ | M |
| Anmeldung über OIDC (Authentik, Keycloak …) | ★ | M |
| Import aus NetBox | ★ | M |

## 5. Verbesserungen an Bestehendem

- **Topologie:** Filter (nur Infrastruktur, nur offline, nach Standort oder VLAN), Suche, weniger Linienkreuzungen,
  Minikarte für große Netze, Export als Bild.
- **Netzscan:** IPv6, Erkennung über VLAN-Grenzen hinweg mit Hilfe der Integrationen, schnellere Läufe für große Netze.
- **Sicherung:** Aufbewahrung am Ziel (alte Sicherungen in Google Drive automatisch löschen), einzelne Profile
  wiederherstellen, komplette ZIP-Verschlüsselung.
- **Abfragen:** Integrationen parallel abfragen; Rückmeldung, wenn eine Integration länger hängt.
- **Qualität:** automatische Tests der Oberfläche (Playwright) und eine CI auf GitHub, fertiges Docker-Image
  (GHCR), Änderungsprotokoll je Version; doppelte Übersetzungsschlüssel in `i18n.js` aufräumen.
- **Härtung:** Content-Security-Policy, Ratenbegrenzung auch außerhalb der Anmeldung, Sitzungen beenden können.

## 6. Vorschlag für die nächsten Schritte

1. ~~Anmeldung mit zweitem Faktor (TOTP) und Sitzungsverwaltung~~ – erledigt in 0.20.
2. ~~Benachrichtigungen per E-Mail und ntfy~~ – erledigt in 0.21.
3. **Übersicht anpassbar** (Diagramme anheften) und **Verfügbarkeitsbericht als PDF**.
4. **Quarantäne und Internetsperre auch über OPNsense/MikroTik** (bisher Quarantäne nur über die FRITZ!Box).
5. Rückmeldungen der Tester (UniFi, MikroTik, OPNsense, Docker) einarbeiten; weitere Integrationen nach Bedarf
   (Pi-hole/AdGuard, NAS-Systeme, OpenWrt).
