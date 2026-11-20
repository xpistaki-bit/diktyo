# díktyo – Anleitung

díktyo dokumentiert dein Heimnetz: Geräte mit IP, MAC, Standort und Notizen, IP-Adressverwaltung mit Subnetzen und VLANs,
eine grafische Topologie, Netzscan mit Geräteerkennung, Online-Überwachung und Integrationen für FRITZ!Box, Switches
(SNMP), ASUS-Router mit AiMesh, MikroTik, TP-Link Omada, Ubiquiti UniFi, Proxmox VE und Home Assistant. Diese Anleitung führt durch Installation und Einrichtung.

> **Neu hier?** Die bebilderte Kurzfassung [Erste Schritte](ERSTE-SCHRITTE.de.md) zeigt in 15 Minuten, wo du klickst:
> installieren, scannen, Router verbinden, fertig.

## 1. Installation

### Proxmox (empfohlen)

Auf dem Proxmox-Host als root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/install/install-proxmox.sh)"
```

Das Skript legt einen unprivilegierten Debian-Container an, installiert díktyo und zeigt am Ende die Adresse, z. B.
`http://192.168.50.223:8090`. Mit Variablen lässt sich alles anpassen, etwa feste IP und VLAN-Schnittstellen:

```bash
CTID=130 IP=192.168.50.30/24 GW=192.168.50.1 VLANS="10:192.168.10.5/24,20:dhcp" \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/install/install-proxmox.sh)"
```

**Aktualisieren** (Daten bleiben erhalten, die Zeitzone des Hosts wird übernommen):

```bash
CTID=130 bash -c "$(curl -fsSL https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/install/update-proxmox.sh)"
```

Im Container laufen zwei Dienste: `diktyo` (Weboberfläche) und `diktyo-worker` (Hintergrunddienst für Scans,
Integrationen, Überwachung und Konfigurations-Backups). Prüfen mit `systemctl status diktyo diktyo-worker`.

### Docker

```bash
git clone https://github.com/xpistaki-bit/diktyo.git && cd diktyo && docker compose up -d --build
```

Der Container nutzt das Host-Netzwerk (für den Netzscan), Port und Zeitzone stehen in `docker-compose.yml`.

## 2. Erste Schritte

1. **Konto anlegen:** Das erste Konto wird Administrator. Weitere Konten legst du unter *Einstellungen → Konten* an.
2. **Profil anlegen:** Ein Profil ist ein Netz bzw. Standort (z. B. „Home“). Profile lassen sich unter *Freigabe* mit
   anderen Konten teilen (Lesen, Bearbeiten, Besitzer).
3. **Netz scannen:** Reiter *Netzscan* → Netz auswählen → *Jetzt scannen*. Der volle Scan dauert für ein /24-Netz etwa
   1–2 Minuten. Nicht vorhandene Netze werden im IPAM angelegt.
4. **Posteingang:** Gefundene Geräte erscheinen mit einer Vermutung („Amazon Echo (Alexa) · 78 %“) und den Gründen.
   *Übernehmen*, vorher *Bearbeiten* oder *Ignorieren* – auch mehrere auf einmal.
5. **Integrationen** einrichten (Abschnitt 4) – sie liefern Geräte mit MAC-Adressen, Verbindungen und Status.
6. **Topologie** ansehen: Reiter *Topologie*.

**Gut zu wissen:** Ein Scan sieht MAC-Adressen, mDNS und UPnP nur im eigenen Netz. Läuft díktyo hinter einem Router
(z. B. ASUS im Router-Modus hinter der FRITZ!Box), sieht der Scan das FRITZ!Box-Netz nur per Ping/TCP. Die Namen fragt
díktyo dann beim DNS des Subnetzes ab (Gateway bzw. DNS-Angabe im IPAM), die MAC-Adressen liefert die FRITZ!Box-Integration.

### Übersicht

Beim Öffnen eines Profils erscheint die **Übersicht**: Geräte online/offline, Internet mit aktuellem Traffic,
Verfügbarkeit der Infrastruktur, Firmware-Updates, Posteingang und Änderungen seit gestern. Darunter *Braucht
Aufmerksamkeit* (offline, Updates, Integrationen mit Fehlern, fehlgeschlagene Aktionen), die Diagramme für WAN-Traffic,
Antwortzeiten der Infrastruktur und die aktivsten Ports, eine Infrastruktur-Tabelle und die letzten Änderungen. Die
Seite aktualisiert sich alle 30 Sekunden.

## 3. Geräte, IPAM, Standorte

- **Geräte:** Im Gerätedialog Katalogmodell wählen – damit entstehen die Ports (z. B. 24 × RJ45 + 4 × SFP+). Unter
  *Anschluss* legst du fest, woran das Gerät hängt: LAN an einen Port, WLAN bzw. Mesh an einen Access Point, virtuell
  an einen Host. Von Hand gesetzte Verbindungen überschreibt keine Integration.
- **IPAM:** Subnetze mit Gateway, DHCP-Bereich und VLAN, Belegung und freie Adressen. Hinweise (z. B. doppelte IP,
  statische IP im DHCP-Bereich) lassen sich als gelesen markieren.
- **Standorte:** Baum aus Haus › Etage › Raum. Home Assistant kann seine Bereiche als Standorte liefern.
- **Katalog:** ca. 80 gängige Geräte, eigene Einträge und CSV-Import; dort auch die *Erkennungsregeln* des Netzscans.
  **Aus Systeminfo:** Ausgabe von `dmidecode -t system` (gern zusammen mit `lspci` für die Netzwerkkarten), `hostnamectl`
  oder Windows `Get-CimInstance Win32_ComputerSystem | fl` einfügen – díktyo erkennt Hersteller, Modell, Typ und Ports,
  schlägt auf Wunsch eine Beschreibung bei Wikipedia nach (nur Hersteller und Modell werden gesendet) und öffnet den
  vorausgefüllten Eintrag zum Prüfen. Seriennummer und UUID werden nicht übernommen.
- **KI-Recherche (optional):** Mit einem Claude-API-Schlüssel (*Einstellungen → KI-Recherche*, Schlüssel aus
  platform.claude.com) recherchiert díktyo per Websuche Datenblätter und füllt Typ, Ports, WLAN und Eckdaten aus –
  im Katalogdialog über *Mit KI ergänzen* oder direkt bei *Aus Systeminfo*. Angezeigt werden Quellen, eine Einschätzung
  der Sicherheit und die ungefähren Kosten (meist 5–20 Cent mit Claude Opus 5.5; günstigere Modelle wählbar).
  Gesendet werden nur Hersteller, Modell und erkannte Eckdaten. Vor dem Speichern immer prüfen.

### Dienste prüfen (nmap)

Im Gerätedialog unter *Dienste (nmap)*: Tiefe wählen (Schnell 100 Ports, Standard 1000 Ports, alle 65535 Ports) und
*Dienste prüfen*. Der Hintergrunddienst zeigt den Fortschritt und listet danach offene Ports mit Dienst, Produkt und
Version, Titel von Webseiten (mit Link) und TLS-Zertifikate mit Ablaufdatum.

## 4. Integrationen

Reiter *Integrationen* → passenden Knopf wählen. Jeder Dialog zeigt oben die Schritte; *Verbindung testen* prüft die
Angaben, bevor gespeichert wird.

### FRITZ!Box

- In der FRITZ!Box: *Heimnetz → Netzwerk → Netzwerkeinstellungen* → „Zugriff für Anwendungen zulassen“.
- Ohne Benutzer: Geräteliste mit MAC-Adressen und WAN-Traffic.
- Mit Benutzer (*System → FRITZ!Box-Benutzer*, Recht „FRITZ!Box Einstellungen“): zusätzlich Mesh-Topologie (welches
  Gerät an welchem LAN-Port bzw. WLAN hängt), WLAN-Daten und das Konfigurations-Backup.

### Switch (SNMP), z. B. Zyxel XGS1935

- Am Switch: *Management → Access Control → SNMP*. Empfohlen **v3** mit Benutzer, Sicherheitsstufe „priv“, SHA/AES,
  Gruppe „read-only“; alternativ v2c mit eigener Community.
- Unter *Service Access* SNMP erlauben; sind *Trusted Hosts* gesetzt, die Absenderadresse von díktyo eintragen. Steht
  díktyo hinter einem Router, ist das dessen WAN-Adresse.
- Mit *Save* dauerhaft speichern.
- **Konfigurations-Backup per SSH:** unter *SSH-Anmeldung* wählen:

  | Anmeldung | So geht's |
  |---|---|
  | Benutzer und Passwort | SSH-Benutzer und -Passwort des Switches eintragen |
  | Schlüssel von díktyo | díktyo zeigt seinen öffentlichen Schlüssel (RSA 4096) mit *Kopieren* bzw. *Als Datei*. Am Zyxel unter *Maintenance → SSH Authorized Keys* importieren (Firmware ab 4.90), danach *Save*. Benutzer meist `admin`. Der private Schlüssel bleibt verschlüsselt in díktyo. |
  | eigener privater Schlüssel | Inhalt der privaten Schlüsseldatei einfügen (RSA, ECDSA oder Ed25519; Zyxel kann kein Ed25519), ggf. Passphrase |

  *Abruf* „automatisch“ versucht zuerst den Einzelbefehl und wechselt sonst in eine interaktive Sitzung, die bei
  „-- More --“ weiterblättert. Ältere Switches, die RSA-Schlüssel nur mit `ssh-rsa` annehmen, bedient díktyo mit
  einem zweiten Versuch.
- **Ports:** Manche Switches melden neben den Frontports logische Schnittstellen (Trunk, VLAN, CPU). díktyo
  übernimmt nur echte Ports und höchstens so viele, wie das Katalogmodell hat; die *Diagnose* nennt die
  ausgelassenen. Ports mit Link unter 1 Gbit/s sind **orange**, ab 2,5 Gbit/s **blau**.
- Antwortet der Switch gar nicht („Keine Antwort“), blockiert er die Anfragen – meist fehlt die Freigabe unter Service
  Access oder Trusted Hosts.
- **Diagnose** im Dialog prüft Schritt für Schritt: Netzweg, Erreichbarkeit, ob der SNMP-Dienst überhaupt antwortet
  (ohne Zugangsdaten) und dann die Anmeldung. So ist klar, ob der Switch díktyo blockiert oder Benutzer/Passwort falsch sind.
- **díktyo in einem anderen Netz als der Switch** (z. B. díktyo hinter dem ASUS-Router, Switch im FRITZ!Box-Netz): Der
  Router dazwischen macht NAT, der Switch sieht als Absender also die **WAN-Adresse dieses Routers**, nicht díktyo. Genau
  diese Adresse muss am Switch als Trusted Host erlaubt sein. Die Diagnose nennt sie, wenn der Router in díktyo bekannt
  ist. Alternative: dem díktyo-Container eine zweite Netzwerkkarte im Netz des Switches geben (Proxmox: Netzwerkgerät
  an der Bridge dieses Netzes hinzufügen) – dann ist der Weg direkt.

### ASUS-Router mit AiMesh (z. B. ExpertWiFi EBM68)

- Adresse des Hauptrouters, meist HTTPS-Port 8443, Admin-Konto des Routers.
- ASUS erlaubt nur **eine Admin-Sitzung**. díktyo hält seine Sitzung offen; wirft dich die Weboberfläche trotzdem
  hinaus, das Abfrageintervall erhöhen.
- **Traffic Monitor:** Die Karte zeigt WAN, LAN und jedes WLAN-Band (aktuell und gesamt) und zeichnet den WAN-Verlauf
  auf. Er erscheint auch in der Übersicht und am Internet-Knoten der Topologie.
- **Traffic Analyzer:** Ist er am Router eingeschaltet (*Traffic Analyzer → Statistik*), holt díktyo höchstens alle
  15 Minuten die Datenmenge je Client der letzten 24 Stunden. Sie steht auf der Karte, als „Top-Verbraucher“ in der
  Übersicht, im Gerätedialog und mit „Durchsatz“ als „Σ …“ an den WLAN-Linien der Topologie. Eine **Live-Rate je
  WLAN-Client** gibt der Router nicht heraus; die Werte in der Client-Liste (z. B. 866 Mbit/s) sind die Verbindungsrate
  (Link-Speed), nicht der Datenverkehr.
- **Diagnose** (Knopf an der Karte) prüft Schritt für Schritt Anmeldung, Client-Liste, Traffic Monitor, Traffic Analyzer
  und Firmware-Status und zeigt, was die Firmware tatsächlich liefert.

### Proxmox VE

Auf einem Knoten (Shell als root) einen Nur-Lese-Token anlegen:

```bash
pveum role add DiktyoRead -privs "VM.Audit,VM.GuestAgent.Audit,Sys.Audit,Datastore.Audit,SDN.Audit"
pveum user add diktyo@pve
pveum acl modify / --users diktyo@pve --roles DiktyoRead
pveum user token add diktyo@pve diktyo --privsep 1
pveum acl modify / --tokens 'diktyo@pve!diktyo' --roles DiktyoRead
```

Das Token-Secret wird nur einmal angezeigt. Token-ID `diktyo@pve!diktyo`, Adresse eines Knotens (Port 8006) – im
Cluster reicht einer. IP-Adressen von VMs kommen über den QEMU Guest Agent.

### Home Assistant

1. Adresse mit IP: `http://192.168.50.9:8123`.
2. Token: *Profil → Sicherheit → Langlebige Zugriffstoken* – für Namen und Bereiche.
3. MQTT-Broker: die **IP-Adresse von Home Assistant** (Port 1883), **nicht „core-mosquitto“** – diesen Namen kennt nur
   Home Assistant selbst. díktyo ersetzt ihn automatisch, schöner ist aber die IP.
4. MQTT-Benutzer aus dem Mosquitto-Add-on (am besten ein eigener für díktyo).

In HA erscheint danach unter *Einstellungen → Geräte & Dienste → MQTT* das Gerät „díktyo <Profil>“ mit Online-Sensoren,
Zählern, WAN-Traffic und der Ereignis-Entität. Für Handy-Benachrichtigungen die Blueprint importieren:
`https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/docs/home-assistant/diktyo-benachrichtigung.yaml`.

### TP-Link Omada

1. Im Omada-Controller: *Einstellungen → Plattform-Integration → Open API → Neue App hinzufügen*, Modus **„Client“**,
   eine Rolle mit Lesezugriff (z. B. Viewer) und die gewünschten Sites.
2. In díktyo **Client-ID**, **Client-Secret** (wird nur einmal angezeigt) und **Omada-ID** (oben auf der Open-API-Seite)
   eintragen.
3. Adresse des Controllers – Software-Controller, OC200/OC300 oder Gateway mit eingebautem Controller –, Port meist
   8043 (OC200/OC300: 443). Site leer lassen, um alle Sites zu lesen.

díktyo übernimmt Gateways, Switches und Access Points mit Uplink-Port sowie die Clients mit Access Point bzw.
Switch-Port und baut daraus die Topologie.

### Ubiquiti UniFi

1. In UniFi Network (9.0 oder neuer): *Einstellungen → Control Plane → Integrationen* → **API-Schlüssel erstellen**.
   Nicht den Site-Manager-Schlüssel von unifi.ui.com verwenden – der gilt nur für die Cloud.
2. Adresse der Konsole (UDM, UCG, Cloud Key) bzw. des selbst gehosteten Controllers, Port 443 (selbst gehostet meist
   8443). díktyo erkennt den richtigen Pfad selbst.
3. Schlüssel einfügen. Er hat vollen Zugriff; díktyo liest damit nur.

díktyo übernimmt Gateway, Switches und Access Points mit Port-Status (Frontplatte in der Topologie), die verbundenen
Clients und den WAN-Traffic des Gateways (Internet-Leitung in der Topologie, Diagramm in der Integration).

**Hinweis:** Beide Integrationen sind nach der Dokumentation der Hersteller gebaut und gegen nachgebildete Controller
getestet, aber noch nicht an echter Hardware. Klappt etwas nicht, die Meldung der Integration als Issue melden.

### MikroTik (RouterOS 7)

Für hAP, hEX, RB5009, CRS-Switches, cAP, Chateau usw. mit RouterOS 7 (REST-API). Im MikroTik-Terminal (WinBox →
*New Terminal*):

```
/certificate add name=diktyo common-name=diktyo days-valid=3650
/certificate sign diktyo
/ip service set www-ssl certificate=diktyo disabled=no
/user group add name=diktyo-read policy=read,rest-api,api,ssh,!local,!telnet,!ftp,!winbox,!web
/user add name=diktyo group=diktyo-read password=GEHEIM
```

Für **Aktionen** (Port, PoE, WLAN, Neustart, Wake-on-LAN) die Gruppe mit `policy=read,write,reboot,test,rest-api,api,ssh`
anlegen. Ab RouterOS 7.9 geht statt HTTPS auch HTTP (Dienst *www*, nur im eigenen Netz).

díktyo liest Modell und Version, Ports (Link, Tempo, Traffic, PoE), Clients aus DHCP und ARP, welches Gerät an welchem
Port bzw. WLAN hängt (Bridge-Hosts, WLAN-Registrierungen mit Signal), Nachbarn per MNDP/LLDP und den WAN-Traffic
(Interface-Liste „WAN“). Das Konfigurations-Backup holt `/export` per SSH (ohne Passwörter); „Änderungen“ zeigt, was
sich zwischen zwei Ständen geändert hat.

**Hinweis:** gegen eine nachgebildete RouterOS-API getestet, noch nicht an echter Hardware – Rückmeldungen willkommen.

### OPNsense

1. *System → Zugang → Benutzer*: eigenen Benutzer anlegen und unter *Effektive Berechtigungen* erlauben: *Status:
   Interfaces*, *Diagnostics: ARP Table*, *Services: DHCP: Kea(v4)* (bzw. Dnsmasq/ISC), *System: Firmware*.
2. Beim Benutzer unter *API-Schlüssel* „+“ – die heruntergeladene Datei enthält **key** und **secret**.
3. Optional **Internetsperre**: *Firewall → Aliase* → Alias vom Typ „Host(s)“ (z. B. `diktyo_block`) und eine LAN-Regel
   „Block, Quelle = Alias“ ganz oben; den Alias-Namen in der Integration eintragen (Recht *Firewall: Alias: Edit*).
4. Konfigurations-Backup lädt die `config.xml` (Recht *Diagnostics: Configuration History* bzw. *Backup & Restore*).

díktyo liest Schnittstellen (Status, Adressen, Traffic), Clients aus DHCP-Leases und ARP, WAN-Status und -Traffic
(Internet-Leitung in der Topologie) und den Firmware-Stand.

### Docker

Den Docker-Socket nie direkt freigeben, sondern auf dem Docker-Host einen **Socket-Proxy** starten, der nur das Nötige
erlaubt – die `docker-compose.yml` dafür steht im Einrichtungsdialog (lesen: `CONTAINERS`, `INFO`, `VERSION`,
`NETWORKS`; für Aktionen zusätzlich `POST`, `ALLOW_START`, `ALLOW_STOP`, `ALLOW_RESTARTS`). Port 2375 nur im Heimnetz
erreichbar lassen. Container erscheinen als virtuelle Geräte am Docker-Host (Image als Modell, laufend = online);
Starten, Stoppen und Neustarten über *Aktionen*. díktyo stoppt weder sich selbst noch den Socket-Proxy.

**Hinweis:** OPNsense und Docker sind nach der Dokumentation gebaut und gegen nachgebildete APIs getestet, noch nicht
an echter Hardware.

## 5. Überwachung und Ereignisse

- *Integrationen → Online-Überwachung:* alle bestätigten Geräte werden alle 30 s, 1 min oder 5 min gepingt. Antwortet
  ein Gerät nicht, prüft díktyo einen bekannten offenen Port (sonst 80) und pingt noch einmal mit mehr Geduld. Ein
  Gerät, das online war, gilt erst nach **zwei Runden ohne Antwort** als offline – WLAN-Geräte im Stromsparmodus
  (z. B. Shellys) verschlucken gern einen einzelnen Ping. Hat eine andere Quelle (FRITZ!Box, Router, SNMP, Scan) das
  Gerät in den letzten 10 Minuten gesehen, bleibt es online, auch wenn der Ping nicht durchkommt (z. B. Switch hinter
  NAT oder mit ICMP-Filter).
- **Verbindungen aus mehreren Integrationen:** Die genauere Angabe gewinnt – „läuft auf Host“ (Proxmox, Docker) oder ein
  bestimmter Switch-Port vor „WLAN am Access Point“ vor „irgendwo im LAN des Routers“. Erst wenn die genauere Quelle
  eine Verbindung 30 Minuten lang nicht mehr bestätigt, darf eine ungenauere sie ändern. Von Hand gesetzte Verbindungen
  haben immer Vorrang.
- Statuswechsel und neue Geräte erscheinen unter *Letzte Ereignisse* und gehen – falls eingerichtet – an Home Assistant.
- Messwerte (WAN- und Port-Traffic) werden 2 Tage aufbewahrt, einstellbar bis 14 (*Einstellungen → Erkennung*).

### Erreichbarkeit und Firmware

- Die Online-Überwachung misst bei jedem Ping auch die **Antwortzeit**. Im Gerätedialog unter *Erreichbarkeit &
  Firmware*: Verfügbarkeit über 24 Stunden, 7 und 30 Tage mit Zahl der Ausfälle und dem längsten Ausfall, mittlere
  Antwortzeit und ein Diagramm (2 h bis 7 Tage). Gezählt wird nur der Zeitraum, in dem díktyo das Gerät überwacht.
- **Firmware-Hinweise** liefern die Integrationen: FRITZ!Box (die Box prüft selbst, díktyo liest das Ergebnis), ASUS,
  MikroTik (RouterOS und RouterBOOT, Prüfung höchstens alle 12 Stunden), UniFi und Omada je Gerät, Proxmox als Zahl der
  ausstehenden Paket-Updates. Geräte mit Update sind in der Topologie mit ⬆ markiert; neue Updates können per Home
  Assistant gemeldet werden; ein Versionswechsel steht im Verlauf.
- *Integrationen → Erreichbarkeit & Firmware* zeigt alles auf einen Blick – Geräte mit Problemen zuerst.

## 6. Topologie

- Gesamtbaum von links nach rechts mit Port-Namen an den Linien; WLAN-Geräte und VMs sind zu aufklappbaren Gruppen
  zusammengefasst.
- Doppelklick auf einen Switch oder Router öffnet die **Frontplatte** mit allen Ports. Klick auf einen Port zeigt das
  angeschlossene Gerät mit IP und MAC (mit SNMP auch Link, Traffic und LLDP).
- *Schnell-Ping* prüft alle Geräte sofort.
- **Durchsatz** (Knopf in der Werkzeugleiste) zeigt an jeder Verbindung den aktuellen Traffic ↓/↑ aus Sicht des
  angeschlossenen Geräts; die Linie wird mit der Last dicker, der Wert steht kurz vor dem Gerät. Die Einstellung merkt
  sich der Browser. Woher die Werte kommen:

  | Verbindung | Quelle |
  |---|---|
  | Kabel | Ports von Switch (SNMP), MikroTik, OPNsense, UniFi-/Omada-Switches |
  | je Gerät (auch WLAN) | Live-Rate aus Omada, UniFi, MikroTik (WLAN-Registrierungen, Kid Control), OPNsense (Top Talkers) |
  | VMs und Container | Proxmox (Netzwerkzähler je Gast) |
  | WLAN mit ASUS | Datenmenge der letzten 24 Stunden (Σ) aus dem Traffic Analyzer – ASUS liefert keine Live-Rate je Gerät |

  Zusammengefasste Gruppen zeigen die Summe ihrer Mitglieder, die Maus über dem Wert nennt die Quelle. FRITZ!Box und
  Docker geben keinen Traffic je Gerät heraus. Den aktuellen Wert zeigt auch der Gerätedialog, die Übersicht listet
  unter **Gerade aktiv**, wer gerade Daten schiebt.
- **Internet:** Links steht die Weltkugel, verbunden mit dem Router. Mit FRITZ!Box-Integration zeigt sie, ob die
  Internetverbindung steht (grün animiert bzw. rot), und an der Leitung den aktuellen Traffic ↓/↑ – alle 30 s aktuell.
- **Verschieben:** Geräte und Gruppen lassen sich mit der Maus an eine beliebige Stelle ziehen (in alle Richtungen). díktyo merkt sich die
  Position im Profil (gilt für alle, die das Profil sehen, und für das PDF). *Anordnung zurücksetzen* stellt die
  automatische Anordnung wieder her.
- *Vollbild* vergrößert die Topologie auf den ganzen Bildschirm unter der Kopfzeile; *Normalgröße* oder Esc schaltet zurück.

### Verlauf

Der Reiter **Verlauf** zeigt, was sich wann geändert hat – und wodurch:

- **Geräte:** neu, gelöscht, Name, Typ, Status (Posteingang/bestätigt/ignoriert), Modell, Standort, IP-Adresse, MAC und
  Anschluss (z. B. „XGS1935 · Port 3 → Port 5“). Bei jeder Zeile steht die Quelle: von Hand (mit Konto), Netzscan,
  FRITZ!Box, Switch, MikroTik, Dienste-Scan …
- **Dazu:** online/offline, Schaltaktionen, neue Konfigurationsstände, Quarantäne und neu geöffnete oder geschlossene
  Ports aus dem Dienste-Scan.
- Oben die **Kurzfassung seit gestern** (neu, gelöscht, geändert, IP-Wechsel, Anschlusswechsel, Ausfälle,
  Konfigurationsstände, Port-Änderungen); darunter Zeitraum, Art und Suche; **CSV** zum Weiterverarbeiten.
- Im **Gerätedialog** steht der Verlauf der letzten 30 Tage.
- Wechselt ein Handy nur zwischen WLAN- bzw. Mesh-Zugangspunkten (Roaming), wird das nicht eingetragen.
- Der Verlauf wird ein Jahr aufbewahrt und ist Teil der díktyo-Sicherung.

## 7. Konfigurations-Backups der Geräte

- FRITZ!Box (mit Benutzer), ASUS-Router und Switches per SSH sichern ihre Konfiguration wöchentlich oder täglich
  (Einstellung in der Integration) oder per *Konfiguration sichern*.
- Unveränderte Konfigurationen werden nicht doppelt abgelegt; pro Gerät bleiben die letzten 30 Stände.
- Die Dateien liegen verschlüsselt in díktyo. Im Gerätedialog unter *Konfigurations-Backups*: herunterladen und bei
  Text-Konfigurationen (FRITZ!Box, Switch) die **Änderungen** zum vorherigen Stand ansehen.
- Die FRITZ!Box-Datei ist mit dem „Passwort für die Konfigurationsdatei“ (sonst dem Anmeldepasswort) geschützt – du
  brauchst es zum Wiederherstellen in der FRITZ!Box.
- **Bestätigung (zweiter Faktor):** Neuere FRITZ!OS-Versionen verlangen für den Export eine Bestätigung. díktyo zeigt
  dann einen Dialog: eine Taste an der FRITZ!Box drücken, am Telefon den angezeigten Code (z. B. `*11234`) wählen
  oder – wenn in der FRITZ!Box eingerichtet – den **Code aus der Authenticator-App** eingeben; danach läuft die
  Sicherung von selbst weiter. (Der App-Code geht nur über die Weboberfläche der FRITZ!Box; díktyo meldet sich dafür
  kurz mit demselben Benutzer an und wieder ab.)
- **Automatisch trotz Bestätigung:** Trägst du in der FRITZ!Box-Integration den **Authenticator-Schlüssel** ein (den
  Base32-Text, den die FRITZ!Box beim Einrichten der App unter „Schlüssel manuell eingeben“ zeigt), erzeugt díktyo den
  Code selbst und sichert auch nach Zeitplan. Abwägung: díktyo kann den zweiten Faktor dann allein erfüllen; der
  Schlüssel liegt verschlüsselt in díktyo und kommt nur mit Backup-Passphrase in die Sicherung. Beim automatischen Zeitplan geht das nicht – dann erscheint ein Hinweis
  und die Sicherung wird per *Konfiguration sichern* von Hand ausgelöst. (Die Bestätigung lässt sich in der FRITZ!Box
  unter *System → FRITZ!Box-Benutzer → Anmeldung im Heimnetz* abschalten; das schwächt aber den Schutz.)

## 8. Schalten (Aktionen)

Besitzer eines Profils können über die Integrationen schalten – im Gerätedialog unter *Aktionen*, in der
Topologie-Seitenleiste und in der Frontplatte beim angeklickten Port:

| Wo | Aktion | Voraussetzung |
|---|---|---|
| FRITZ!Box | WLAN (auch Gastnetz) ein/aus, Neustart | Benutzer mit Recht „FRITZ!Box Einstellungen“ |
| Gerät im FRITZ!Box-Netz | Internetzugang sperren/freigeben, Aufwecken (Wake-on-LAN) | wie oben |
| Gerät an einem Switch-Port | Port ab-/einschalten, PoE neu starten | SNMP mit **Schreibrechten** (Zyxel: Benutzer in einer Gruppe mit Schreibrechten, z. B. „admin“, bzw. Community mit read-write) |
| VM / LXC | starten, herunterfahren, neu starten | Proxmox-Token mit `VM.PowerMgmt` (siehe unten) |
| MikroTik | Port ab-/einschalten, PoE neu starten, WLAN ein/aus, Wake-on-LAN, Neustart | Benutzergruppe mit write, reboot, test |
| OPNsense | Internetzugang je Gerät (über den Alias), Neustart | Alias + Block-Regel, Recht *Firewall: Alias: Edit* |
| Docker | Container starten, stoppen, neu starten | Socket-Proxy mit POST und ALLOW_* |

- Vor jeder Aktion kommt eine **Vorschau mit Bestätigung**. Bei WLAN, Internetsperre und Switch-Port lässt sich
  **automatisch zurückschalten** (nach 15 min, 1 h, 2 h oder morgen um 6:00) – praktisch etwa für eine Internetpause.
- Vor Änderungen sichert díktyo die **Konfiguration**, wenn die letzte Sicherung älter als eine Stunde ist.
- **Schutz vor dem Aussperren:** Den Switch-Port, über den díktyo bzw. der Router den Switch erreicht, schaltet díktyo
  nicht ab; Router, Switches und Access Points werden nicht vom Internet gesperrt; die VM, in der díktyo läuft, wird
  nicht heruntergefahren.
- Verlangt die FRITZ!Box eine **Bestätigung** (zweiter Faktor), erscheint der bekannte Dialog (Taste oder Telefon-Code).
  Gelingt das automatische Zurückschalten deshalb nicht, meldet díktyo das unter *Letzte Aktionen* und – falls
  eingerichtet – per Home Assistant.
- Alle Aktionen stehen unter *Integrationen → Letzte Aktionen*; geplantes Zurückschalten lässt sich dort abbrechen.
- Am **Switch** selbst: im Gerätedialog unter *Aktionen* den Port wählen (oder in der Frontplatte auf den Port klicken).
- Am **Proxmox-Host**: Liste seiner VMs und Container zum Starten bzw. Herunterfahren.

**Zeitpläne:** Im Aktionsdialog „Zeitplan anlegen“ wählen – Wochentage und Uhrzeit. Bei Internetsperre, WLAN und
Switch-Port gilt ein Zeitfenster (z. B. Mo–Fr 22:00–06:30 Internet gesperrt): zu Beginn schaltet díktyo, am Ende
zurück. Geschaltet wird nur an diesen Zeitpunkten – gibst du zwischendurch von Hand frei, bleibt das bis zum nächsten
Übergang so. Andere Aktionen (Neustart, PoE, Wake-on-LAN, VM) laufen einmal zur gewählten Uhrzeit. Vor jedem Lauf
prüft díktyo den Aussperr-Schutz erneut; die Internetsperre nutzt immer die aktuelle IP des Geräts. Übersicht,
Pausieren und Löschen unter *Integrationen → Zeitpläne* und im Gerätedialog.

**Quarantäne für neue Geräte:** *Integrationen → Quarantäne für neue Geräte* einschalten (braucht die
FRITZ!Box-Integration mit Benutzer). Jedes Gerät, das danach neu im Posteingang landet, bekommt über die FRITZ!Box keinen
Internetzugang; das Heimnetz bleibt erreichbar. **Übernehmen** im Posteingang gibt es automatisch frei, *Freigeben*
geht auch ohne Übernehmen. Ausgenommen: Infrastruktur, díktyo selbst, Geräte außerhalb des FRITZ!Box-Netzes (Gastnetz);
optional auch Geräte mit zufälliger MAC-Adresse. Wechselt ein Gerät in Quarantäne die IP, zieht díktyo die Sperre nach.
Home Assistant kann bei jeder neuen Quarantäne benachrichtigen (Blueprint, Ereignis „Neues Gerät in Quarantäne“).

Proxmox-Rechte für VMs schalten (einmal auf einem Knoten):

```bash
pveum role add DiktyoPower -privs VM.PowerMgmt
pveum acl modify / --tokens 'diktyo@pve!diktyo' --roles DiktyoPower
```

## 9. Ausgabe und Sicherung

- *Ausgabe:* PDF (Topologie-Grafik, Geräteliste, IP-Plan, VLANs, Portbelegung, WLAN-Übersicht, Notizen – wählbar) und CSV.
- *Einstellungen → Sicherung:* Ziele Ordner/NAS, WebDAV oder rclone, automatisch alle 12 h, täglich oder wöchentlich.
- **Google Drive (rclone):** Ziel „rclone“ hinzufügen → *Google Drive verbinden*. Auf deinem PC mit Browser
  `rclone authorize "drive"` ausführen (rclone von rclone.org; unter Windows reicht die rclone.exe), mit dem
  gewünschten Google-Konto anmelden, die ausgegebene Zeile `{"access_token": …}` in den Dialog kopieren. díktyo legt
  die Verbindung an (Zugriff nur auf selbst angelegte Dateien) und trägt als Ziel z. B. `gdrive:diktyo` ein –
  `gdrive` ist der Name der Verbindung, `diktyo` der Ordner in Google Drive. Danach speichern und *Jetzt sichern*.
  Mit einer **Backup-Passphrase** kommen Zugangsdaten und die neuesten Gerätekonfigurationen verschlüsselt mit in die
  Sicherung – Passphrase gut aufheben.
- **Wiederherstellen:** In einer neuen, leeren Installation bietet die Ersteinrichtung „Aus einer Sicherung
  wiederherstellen“ an.

## 10. Wenn etwas nicht klappt

| Problem | Lösung |
|---|---|
| „Der Hintergrunddienst meldet sich nicht“ | Im Container: `systemctl status diktyo-worker`, Protokoll: `journalctl -u diktyo-worker -n 50` |
| Netzscan findet im Netz hinter dem Router keine MAC-Adressen | Normal; FRITZ!Box-Integration einrichten |
| Switch: „Keine Antwort“ | SNMP unter Service Access erlauben, Trusted Hosts prüfen, mit *Save* speichern |
| MQTT: „Name or service not known“ | IP-Adresse von Home Assistant statt „core-mosquitto“ eintragen |
| ASUS meldet dich ständig ab | Abfrageintervall der ASUS-Integration erhöhen |
| Uhrzeit falsch | Update ausführen (übernimmt die Zeitzone des Proxmox-Hosts) |
| Passwort vergessen | Im Container: `diktyo reset-password deine@adresse.de` |
