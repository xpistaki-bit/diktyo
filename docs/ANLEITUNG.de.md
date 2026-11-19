# díktyo – Anleitung

díktyo dokumentiert dein Heimnetz: Geräte mit IP, MAC, Standort und Notizen, IP-Adressverwaltung mit Subnetzen und VLANs,
eine grafische Topologie, Netzscan mit Geräteerkennung, Online-Überwachung und Integrationen für FRITZ!Box, Switches
(SNMP), ASUS-Router mit AiMesh, TP-Link Omada, Ubiquiti UniFi, Proxmox VE und Home Assistant. Diese Anleitung führt durch Installation und Einrichtung.

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
- Für das Konfigurations-Backup zusätzlich SSH-Benutzer und -Passwort eintragen.
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

## 5. Überwachung und Ereignisse

- *Integrationen → Online-Überwachung:* alle bestätigten Geräte werden alle 30 s, 1 min oder 5 min gepingt.
- Statuswechsel und neue Geräte erscheinen unter *Letzte Ereignisse* und gehen – falls eingerichtet – an Home Assistant.
- Messwerte (WAN- und Port-Traffic) werden 2 Tage aufbewahrt, einstellbar bis 14 (*Einstellungen → Erkennung*).

## 6. Topologie

- Gesamtbaum von links nach rechts mit Port-Namen an den Linien; WLAN-Geräte und VMs sind zu aufklappbaren Gruppen
  zusammengefasst.
- Doppelklick auf einen Switch oder Router öffnet die **Frontplatte** mit allen Ports. Klick auf einen Port zeigt das
  angeschlossene Gerät mit IP und MAC (mit SNMP auch Link, Traffic und LLDP).
- *Schnell-Ping* prüft alle Geräte sofort.
- **Internet:** Links steht die Weltkugel, verbunden mit dem Router. Mit FRITZ!Box-Integration zeigt sie, ob die
  Internetverbindung steht (grün animiert bzw. rot), und an der Leitung den aktuellen Traffic ↓/↑ – alle 30 s aktuell.
- **Verschieben:** Geräte und Gruppen lassen sich mit der Maus an eine beliebige Stelle ziehen (in alle Richtungen). díktyo merkt sich die
  Position im Profil (gilt für alle, die das Profil sehen, und für das PDF). *Anordnung zurücksetzen* stellt die
  automatische Anordnung wieder her.
- *Vollbild* vergrößert die Topologie auf den ganzen Bildschirm unter der Kopfzeile; *Normalgröße* oder Esc schaltet zurück.

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

Proxmox-Rechte für VMs schalten (einmal auf einem Knoten):

```bash
pveum role add DiktyoPower -privs VM.PowerMgmt
pveum acl modify / --tokens 'diktyo@pve!diktyo' --roles DiktyoPower
```

## 9. Ausgabe und Sicherung

- *Ausgabe:* PDF (Topologie-Grafik, Geräteliste, IP-Plan, VLANs, Portbelegung, WLAN-Übersicht, Notizen – wählbar) und CSV.
- *Einstellungen → Sicherung:* Ziele Ordner/NAS, WebDAV oder rclone, automatisch alle 12 h, täglich oder wöchentlich.
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
