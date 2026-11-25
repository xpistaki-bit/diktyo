# díktyo – Plan, Erweiterungen und Verbesserungen

Stand: Version 0.33.0 (November 2026). Die ausführliche Bedienung steht in [ANLEITUNG.de.md](ANLEITUNG.de.md),
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
| Traffic je Gerät | Live-Raten je Client aus Omada, UniFi, MikroTik, OPNsense und Proxmox in Topologie (auch Gruppen), Gerätedialog und Übersicht („Gerade aktiv“); bebilderte Einstiegsanleitung (DE/EN) | 0.18 |
| Switch | nur echte Frontports (logische Schnittstellen, Bridge-Tabelle, Katalog), Port-Farben nach Geschwindigkeit, SSH-Backup mit Schlüssel und wählbarem Abruf; Online-Überwachung tolerant gegen einzelne verlorene Pings | 0.18.1 |
| Stabilität | Verbindungen: genauere Quelle hat Vorrang; Online-Status: andere Quellen schlagen einen gescheiterten Ping; Scroll-Position bleibt beim Speichern und Neuladen | 0.18.2 |
| Geschwindigkeit | Internet-Speedtest (Cloudflare) von Hand oder nach Zeitplan mit Verlauf und Hinweis bei langsamer Leitung; iperf3 zwischen díktyo und einem Gerät | 0.19 |
| Sicherheit | Anmeldung mit zweitem Faktor (TOTP, QR lokal erzeugt, Wiederherstellungscodes, Einmal-Codes, Versuchsgrenze), Sitzungsverwaltung, Zurücksetzen durch Admin/CLI | 0.20 |
| Benachrichtigungen | E-Mail und ntfy je Profil, Ereignisse wählbar, gebündelt; neue Ereignisse: Internet langsam, Backup fehlgeschlagen, Integration gestört | 0.21 |
| Aktionen und Shelly | UniFi: Gerät neu starten, PoE-Port neu starten; Omada: Gerät neu starten, PoE ein/aus/neu starten; Shelly/Tasmota direkt: Leistung, Energie, Ausgänge schalten, Firmware | 0.22 |
| DNS-Filter | Pi-hole (v6, v5) und AdGuard Home: Hostnamen, Anfragen/Blockierte je Gerät, Statistik und Diagramm in der Übersicht, Werbeblocker schalten | 0.23 |
| Geräte | Typen erweitert (Saugroboter, 3D-Drucker, Türklingel, Hub, ESP …), Software/Betriebssystem-Feld, Proxmox-Gäste übernehmen Software/Standort vom Host, Vermutung verwerfen, WLAN bei Geräten ohne Buchse, KI-Katalog ohne erfundene Ports | 0.24 |
| Katalog und Topologie | Katalog nur mit Netzwerkanschlüssen, Suche im Katalog, Topologie in die Breite | 0.24.1 |
| Übersicht neu | HUD-Stil über die volle Breite: Kennzahl-Kacheln mit Segmentbalken/Ring, WAN als Balkendiagramm, Speedtest als Tachos, Ports mit dem Gerät dahinter, Antwortzeiten mit Verlaufslinie, Infrastruktur als Karten; Integrationen im Raster | 0.25 |
| Übersicht anpassbar | Felder ziehen/verschieben, Breite, aus-/einblenden, eigene Diagramme anheften (WAN, Switch-Port, ASUS-Schnittstelle, DNS, Antwortzeit/Leistung je Gerät) – auch per Pin an Integrationskarten und im Gerätedialog; Layout je Profil | 0.26 |
| Wachliste | Systeme im Gerätedialog beobachten; Feld in der Übersicht meldet Ausfall und Wechsel von IP, MAC, Name oder Anschluss (alt → neu) bis zum Quittieren; eigene Änderungen zählen nicht; Benachrichtigung per E-Mail/ntfy | 0.27 |
| Aussehen | Kacheln mit hellerem Kopfband und größerer Überschrift, Neon-Pin, eigener Anmelde-Hintergrund (Glasfaser vor HUD-Ringen) | 0.27.1 |
| QR-Etiketten | Aufkleber mit QR-Code zum Gerätedialog (Direktlink, auch über die Anmeldung hinweg), Name/IP/MAC/Standort; A4-Bögen (Avery 3474, L7163, 3657) und Etikettendrucker (Brother 62 × 29, Dymo 54 × 25); einzeln aus dem Gerätedialog | 0.28 |
| Verkabelung | Patchfelder und Netzwerkdosen mit Port-Belegung, Kabelwege Switch-Port → Patchfeld → Dose → Gerät mit Kabelnummern, Abgleich mit der erkannten Verbindung (✓/⚠), im Gerätedialog, im PDF und in der Sicherung | 0.29 |
| VLAN-Plan | Ports je Switch grafisch mit VLAN-Farben (untagged/tagged) und als Matrix; produktiver Stand per SNMP vom Switch (Q-BRIDGE-MIB, nur lesend) oder von Hand; Plan-Modus mit geplanten VLANs, Mehrfachauswahl, Umstellungsliste, Prüfungen (Adresse/Subnetz, Uplinks), automatisch abgehakt bei SNMP; im PDF | 0.30 |
| Nur Netzwerkports | USB, HDMI, Thunderbolt, MagSafe, Kartenleser … bleiben im Katalog, werden am Gerät aber keine Ports mehr; einmalige Umnummerierung bestehender Geräte | 0.30.1 |
| VLAN-Plan | Endgeräte eingeklappt unter den Netzwerkgeräten, Subnetze im VLAN-Dialog zuordnen, Hinweis „kein Subnetz – zuordnen“ | 0.30.2 |
| Prometheus/Grafana | Endpunkt je Profil mit Bearer-Token (nur Besitzer, nur Hash gespeichert), fertiger prometheus.yml-Eintrag, Grafana-Dashboard zum Import | 0.31 |
| Anmeldung über OIDC | Authentik, Keycloak, Logto u. a.: Authorization Code mit PKCE, state (an den Browser gebunden), nonce, Signaturprüfung (RS/PS/ES/HS), Verknüpfen über bestätigte E-Mail oder in den eigenen Einstellungen, optional automatisch anlegen, Gruppe nötig, Admin über Gruppe | 0.32 |
| VLAN-Plan und Topologie | VMs/Container (Proxmox) mit ihrem VLAN-Tag beim Host, Prüfung des Host-Ports (tagged); Topologie hängt am Internet-Gateway, auch wenn die Erkennung den Router als Gerät am Switch eingetragen hat; Suchfeld-✕ als Kästchen direkt am Feld | 0.32.1 |
| Update per Knopf, MikroTik per SNMP | Neue Version auf GitHub erkennen (mit Änderungen, Hinweis in der Kopfzeile) und per Knopf installieren: Anfrage-Datei → systemd-Pfad-Einheit → festes Update-Skript als root (Datenbank sichern, laden, setup.sh), Fortschritt und Protokoll in der Oberfläche; Docker mit Anleitung. MikroTik zusätzlich per SNMP v2c/v3 (nur lesen, MIKROTIK-MIB für Board, Version, RouterBOOT, PoE, WLAN, Nachbarn) | 0.34 |
| Code-Scanning (CodeQL) | SSH-Host-Schlüssel wird vor der Anmeldung geprüft (Passwort geht nicht mehr an ein Gerät mit geändertem Schlüssel), Ausdrücke ohne exponentielles Rückverfolgen (E-Mail, Systeminfo), API-SSL ab TLS 1.2, Konfigurations-Backup-Dateien nur innerhalb des Datenordners, unerwartete Fehler nur noch allgemein in der Oberfläche (Details im Protokoll), Kommandozeile zeigt nur selbst erzeugte Passwörter | 0.34.1 |
| Kabel-Etiketten | Kabelnummern aus den Kabelwegen als Aufkleber: Nummer groß, darunter beide Enden (bzw. je Kabelende ein Etikett mit der Gegenstelle), Farbstreifen nach Art (Patch-, Verlege-, Anschlusskabel); A4-Bögen (Avery 3666/L7651, 3657, 3474), Etikettendrucker (Brother 62 × 29, Dymo 54 × 25) und Schriftband 12 mm; in *Ausgabe* und im Reiter *Verkabelung* | 0.35 |
| Grundriss/Raumplan und Rack-Ansicht | Je Standort ein Grundriss (Bild als PNG/JPEG/WebP/GIF oder Raster) mit Geräten, Patchfeldern/Dosen und Unterstandorten als Rechteck, Online-Status, Klick öffnet Gerät bzw. Raum; Standort-Art *Rack* mit Höheneinheiten: Vorderansicht mit Geräten, Patchfeldern und Sonstigem (USV, Blende …), Port-Belegung, Ziehen zum Ein-/Umbauen; PDF-Abschnitt *Grundrisse und Racks*, in der Sicherung enthalten | 0.36 |
| Gruppen in der Topologie | Eigene Gruppen („IoT“, „Kameras“, „Kinderzimmer“) mit Name, Farbe und Mitgliedern erscheinen als Box unter ihrem Access Point/Switch; wahlweise nach Standort, Tag oder VLAN (Port-VLAN, Proxmox-Tag oder Subnetz der IP) gruppieren; Schwellwerte für WLAN, VMs und Gruppen einstellbar (0 = nie); Gruppen-Boxen verschiebbar, im PDF, Netzplan-Export und in der Sicherung | 0.37 |
| Netgear und devolo | SNMP-Hersteller-Profile (automatisch über die Gerätekennung: Netgear, Zyxel, TP-Link, generisch): Modell, Seriennummer, Firmware und Hardware-Revision aus der ENTITY-MIB, bei Netgear Inventar und Temperatur, CPU-Last, Firmware im Firmware-Überblick, Freischalt-/Schreibrechte-Hinweise je Hersteller; devolo Powerline (Geräte-API der Home Network App: mDNS, Protobuf): alle Adapter mit Firmware und Update-Hinweis, Datenraten zwischen den Adaptern, Geräte an den LAN-Buchsen und WLAN-Geräte; neue Verbindungsart „Powerline“ in Topologie, PDF und Netzplan | 0.38 |
| Code-Scanning, zweite Runde | Sicherung meldet nur noch feste, verständliche Fehlertexte (Wortlaut im Protokoll); Kommandozeile fragt Passwörter verdeckt ab und gibt nie eines aus; Systeminfo-Parser ohne polynomielles Regex | 0.38.1 |
| VLANs aus MikroTik, OPNsense, UniFi und Omada | Produktiver VLAN-Stand je Port jetzt auch aus MikroTik (Bridge-VLAN-Tabelle, PVID, VLAN-Schnittstellen), OPNsense (VLAN-Geräte), UniFi (Port-Profile und Port-Einstellungen über die klassische API) und Omada (Netze je Switch); Kennzeichen nennt die Quelle, SNMP hat Vorrang, Umstellungsliste hakt sich auch dort von selbst ab | 0.39 |
| MikroTik und Sprache | MikroTik über die RouterOS-API (Port 8728/8729, RouterOS 6 und 7) als Standard, REST weiter wählbar, kein SSH-Backup mehr (RouterOS hat eigene Backups); alle Server-Meldungen, Aktionen, Diagnosen und gespeicherten Fehler auf Englisch, wenn Englisch gewählt ist (auch in Benachrichtigungen), Test gegen fehlende Übersetzungen; automatisch erzeugte Gerätenamen auf Englisch | 0.33.1 |
| Netzplan-Export | Topologie als SVG, PNG (doppelte Auflösung), draw.io (Geräte mit IP/MAC/Typ/Modell/Standort als Eigenschaften) und Poster-PDF A4–A0 mit Schriftfeld, wahlweise auf A4 gekachelt mit Überlappung und Blattnummern; Gruppen aufklappbar; in Topologie und Ausgabe | 0.33 |

## 2. Noch offen aus dem ursprünglichen Plan

| # | Inhalt | Anmerkung |
|---|---|---|
| P2.4 | Weitere Integrationen: Netgear (Smart Switches/Router), devolo (Powerline) | Docker erledigt in 0.16, Netgear (SNMP-Profil) und devolo in 0.38 |
| P2.8 | Passive DHCP-Erkennung (Fingerprinting aus DHCP-Anfragen) | braucht einen Lauscher im Netz bzw. DHCP-Logs vom Router |
| Phase 3 | REST-API mit Tokens | für Skripte, Home Assistant, eigene Auswertungen; Token-Verfahren wie beim Prometheus-Endpunkt |
| ~~Phase 3~~ | ~~Änderungsverlauf zwischen Scans~~ (0.14), ~~Kabel- und Patchpanel-Dokumentation~~ (0.29), ~~Prometheus-Endpunkt~~ (0.31) | erledigt |

## 3. An echter Hardware noch zu testen

| Integration / Funktion | Stand | Wer |
|---|---|---|
| UniFi (inkl. Live-Raten je Client über stat/sta, Aktionen Neustart/PoE) | nach offizieller API gebaut, gegen nachgebildeten Controller getestet | Tester |
| MikroTik (RouterOS-API, SNMP v2c/v3 und REST, inkl. Live-Raten: WLAN-Registrierungen, Kid Control) | API-Protokoll gegen nachgebildeten Server über echten Socket getestet (inkl. Anmeldung vor 6.43); Rückmeldung des Testers: REST-Zugang scheiterte (Port spricht kein HTTPS) – mit 0.33.1 API als Standard | Tester |
| Omada (inkl. Live-Raten je Client, Aktionen PoE/Neustart) | nach Open-API-Doku gebaut, gegen nachgebildeten Controller getestet | offen |
| Shelly / Tasmota | gegen nachgebildete Geräte (Gen1, Gen2/3, Tasmota) getestet | Nutzer |
| Pi-hole / AdGuard Home | gegen nachgebildete APIs (Pi-hole v6/v5, AdGuard) getestet | Nutzer |
| Netgear (SNMP-Profil: Inventar-, Temperatur-OIDs) | gegen simulierten SNMP-Agenten getestet; die Netgear-OIDs stammen aus der FASTPATH-MIB, an echten Switches ungeprüft | Nutzer mit Netgear |
| devolo Powerline | Protokoll nach der devolo-Geräte-API (mDNS, Protobuf, Digest) gegen nachgebildete Antworten getestet, noch nicht an echten Adaptern | Nutzer mit devolo |
| VLANs aus UniFi/Omada/OPNsense/MikroTik | nach API-Beschreibungen gegen nachgebildete Antworten getestet; UniFi-Port-VLANs kommen aus der klassischen API (ob der API-Schlüssel dort reicht, ist ungeprüft), Omada-Endpunkt networks-detail aus der Open-API-Spezifikation | Tester mit UniFi/Omada/MikroTik |
| OPNsense (inkl. Top Talkers), Docker | gegen nachgebildete APIs getestet | Tester |
| Proxmox: Live-Raten je VM, VLAN-Tags der Gäste im VLAN-Plan | gegen nachgebildete API getestet | Nutzer (Proxmox vorhanden) |
| iperf3 zu einem Gerät | gegen nachgebildete iperf3-Ausgabe getestet | Nutzer |
| Switch-Aktionen (SNMP-SET) | gegen Test-Agent getestet; Zyxel mit Schreibrechten offen | Tester |
| Proxmox-Aktionen | gebaut, Token mit `VM.PowerMgmt` offen | Tester |
| Anmeldung über OIDC mit echtem Authentik, Keycloak, Logto | gegen nachgebildeten Anbieter getestet (ES384, RS256, HS256), Browser-Ablauf mit lokalem Test-Anbieter | Nutzer |
| Prometheus abfragen, Grafana-Dashboard importieren | Format geprüft, ohne echtes Prometheus/Grafana | Nutzer |
| draw.io-Datei öffnen (app.diagrams.net / Desktop) | gültiges mxGraph-XML, ohne draw.io geprüft | Nutzer |
| Update per Knopf im Proxmox-LXC | App-Seite und Skriptregeln getestet; Update-Skript und systemd-Einheiten noch nicht in einem echten Container gelaufen | Nutzer |
| QR-Etiketten drucken und scannen | Codes maschinell gelesen (OpenCV), Druck auf echten Bögen offen | Nutzer |

Am echten Gerät bestätigt: FRITZ!Box (inkl. 2FA, Backup, Schaltaktionen), ASUS EBM68 (Traffic Monitor/Analyzer),
Zyxel XGS1935 (SNMP v3, Port-Filter, SSH-Backup mit díktyo-Schlüssel, **VLANs per Q-BRIDGE-MIB im VLAN-Plan**),
Proxmox (Gäste), Internet-Speedtest, Verkabelung mit Patchfeld und Dosen.

Rückmeldung aus dem Test (MikroTik): Nutzer verwenden meist SNMP oder die RouterOS-API, selten HTTP/REST; Backups macht RouterOS selbst. Offene Punkte aus den Tests: Bei UniFi ist die Einheit der WAN-Rate (Bit/Byte) nicht dokumentiert; bei MikroTik
heißen WLAN-Felder je Paket (wifi, wifiwave2, wireless) leicht unterschiedlich.

## 4. Mögliche Erweiterungen (Add-ons)

Einschätzung: Nutzen ★–★★★, Aufwand S/M/L.

### Integrationen

| Idee | Nutzen | Aufwand |
|---|---|---|
| pfSense: wartet auf Netgates offizielle REST-API (das Community-Paket „pfrest“ ist im Wartungsmodus und endet nach pfSense 26.10) | ★★ | M |
| OpenWrt (ubus/rpcd): Clients, WLAN, Ports, Aktionen | ★★ | M |
| Synology / QNAP / TrueNAS / Unraid: Status, Laufwerke, Dienste | ★★ | M |
| ASUS: Aktionen (Gastnetz, Neustart) und lesbarer Konfig-Vergleich (CFG entschlüsseln) | ★★ | M |
| Erledigt: ~~OPNsense~~ (0.16), ~~Docker~~ (0.16), ~~Shelly/Tasmota~~ (0.22), ~~Aktionen UniFi/Omada~~ (0.22), ~~Pi-hole/AdGuard~~ (0.23), ~~Netgear (SNMP-Profile), devolo Powerline~~ (0.38), ~~VLANs aus MikroTik/OPNsense/UniFi/Omada~~ (0.39) | | |

### Wünsche aus dem Test

| Idee | Nutzen | Aufwand |
|---|---|---|
| VLAN-Plan: geplante VLAN-Wechsel von VMs/Containern im Plan-Modus mitführen (bisher nur der Ist-Stand aus Proxmox) | ★ | S |
| Erledigt: ~~Gruppen in der Topologie~~ (0.37), ~~Durchsatz je Gerät in der Topologie~~ (0.17/0.18), ~~Übersichtsseite~~ (0.17), ~~Übersicht anpassbar~~ (0.26), ~~Wachliste / Alarm~~ (0.27) | | |

### Monitoring

| Idee | Nutzen | Aufwand |
|---|---|---|
| **Verfügbarkeitsbericht als PDF** (je Monat: Verfügbarkeit, Ausfälle, Antwortzeiten der Infrastruktur, Speedtests) | ★★★ | S |
| TLS-Zertifikate: Warnung vor Ablauf (Daten aus dem Dienste-Scan) | ★★ | S |
| iperf zwischen zwei beliebigen Geräten (per SSH auf einem der beiden), díktyo als iperf3-Gegenstelle für Handy-Apps | ★ | S |
| Weitere Benachrichtigungswege: Telegram, Gotify, Webhook | ★★ | S |
| Erledigt: ~~Latenz/Verfügbarkeit~~ (0.15), ~~Firmware-Hinweise~~ (0.15), ~~Speedtest/iperf~~ (0.19), ~~E-Mail/ntfy~~ (0.21) | | |

### Sicherheit

| Idee | Nutzen | Aufwand |
|---|---|---|
| Passkeys (WebAuthn) und „2FA für alle Pflicht“ | ★★ | M |
| Abmelden auch beim OIDC-Anbieter (RP-initiated logout) | ★ | S |
| Audit-Log-Ansicht in der Oberfläche | ★ | S |
| Erledigt: ~~Quarantäne für neue Geräte~~ (0.13), ~~Vergleich offener Ports~~ (0.14), ~~2FA und Sitzungen~~ (0.20), ~~OIDC~~ (0.32) | | |

### Dokumentation

| Idee | Nutzen | Aufwand |
|---|---|---|
| Erledigt: ~~Änderungsverlauf~~ (0.14), ~~QR-Etiketten~~ (0.28), ~~Kabel und Patchpanels~~ (0.29), ~~Kabel-Etiketten~~ (0.35), ~~Grundriss/Raumplan und Rack-Ansicht~~ (0.36), ~~VLAN-Plan~~ (0.30), ~~Export nach draw.io / SVG / PNG, Netzplan als Poster-PDF~~ (0.33) | | |

### Automatisierung

| Idee | Nutzen | Aufwand |
|---|---|---|
| Regeln („Kamera offline → PoE neu starten“, „AP antwortet nicht → Port neu starten“) | ★★ | M |
| Aktionen als Schalter/Taster in Home Assistant (MQTT) | ★★ | S |
| Erledigt: ~~Zeitpläne für Aktionen~~ (0.13) | | |

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
| Handy-Ansicht / installierbare Web-App (PWA) | ★★ | M |
| Import aus NetBox | ★ | M |
| Erledigt: ~~Prometheus/Grafana~~ (0.31), ~~Anmeldung über OIDC~~ (0.32) | | |

## 5. Verbesserungen an Bestehendem

- **Topologie:** Filter (nur Infrastruktur, nur offline, nach Standort oder VLAN), Suche, weniger Linienkreuzungen,
  Minikarte für große Netze. (Export als Bild/PDF/draw.io erledigt in 0.33.)
- **Netzscan:** IPv6, Erkennung über VLAN-Grenzen hinweg mit Hilfe der Integrationen, schnellere Läufe für große Netze.
- **Sicherung:** Aufbewahrung am Ziel (alte Sicherungen in Google Drive automatisch löschen), einzelne Profile
  wiederherstellen, komplette ZIP-Verschlüsselung.
- **Abfragen:** Integrationen parallel abfragen; Rückmeldung, wenn eine Integration länger hängt.
- **Qualität:** CI auf GitHub mit den Tests, fertiges Docker-Image (GHCR), Änderungsprotokoll je Version; doppelte
  Übersetzungsschlüssel in `i18n.js` aufräumen; die Oberflächentests (Playwright) ins Repository übernehmen.
- **Härtung:** Content-Security-Policy, Ratenbegrenzung auch außerhalb der Anmeldung.

## 6. Vorschlag für die nächsten Schritte

1. **Verfügbarkeitsbericht als PDF** – liegt seit 0.15 als Rest offen, die Daten sind vorhanden.
2. **Quarantäne und Internetsperre auch über OPNsense/MikroTik** (bisher Quarantäne nur über die FRITZ!Box).
3. ~~**Topologie: Gruppen**~~ (0.37) – offen bleibt ein reiner Filter (nur ein VLAN/Standort einblenden).
4. **REST-API mit Tokens und Webhooks** – letzter offener Punkt aus Phase 3.
5. Rückmeldungen der Tester (UniFi, MikroTik, OPNsense, Docker) und echte Tests von OIDC, Prometheus/Grafana und
   draw.io einarbeiten; weitere Integrationen nach Bedarf (NAS-Systeme, OpenWrt).
