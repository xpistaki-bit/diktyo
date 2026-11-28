# díktyo – Anleitung

díktyo dokumentiert dein Heimnetz: Geräte mit IP, MAC, Standort und Notizen, IP-Adressverwaltung mit Subnetzen und VLANs,
eine grafische Topologie, Netzscan mit Geräteerkennung, Online-Überwachung und Integrationen für FRITZ!Box, Switches
(SNMP, z. B. Zyxel und Netgear), devolo Powerline, ASUS-Router mit AiMesh, MikroTik, OpenWrt, TP-Link Omada, Ubiquiti UniFi, Proxmox VE und Home Assistant. Diese Anleitung führt durch Installation und Einrichtung.

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
2. **Profil anlegen:** Ein Profil ist ein Netz bzw. Standort (z. B. „Home“). Profile teilst du mit anderen Konten
   (Lesen, Bearbeiten, Besitzer) über *Teilen* oben im Profil oder unter *Mein Konto → Profile und Freigaben*.
3. **Netz scannen:** Reiter *Netzscan* → Netz auswählen → *Jetzt scannen*. Der volle Scan dauert für ein /24-Netz etwa
   1–2 Minuten. Nicht vorhandene Netze werden im IPAM angelegt.
4. **Posteingang:** Gefundene Geräte erscheinen mit einer Vermutung („Amazon Echo (Alexa) · 78 %“) und den Gründen.
   *Übernehmen*, vorher *Bearbeiten* oder *Ignorieren* – auch mehrere auf einmal.
5. **Integrationen** einrichten (Abschnitt 4) – sie liefern Geräte mit MAC-Adressen, Verbindungen und Status.
6. **Topologie** ansehen: Reiter *Topologie*.

**Gut zu wissen:** Ein Scan sieht MAC-Adressen, mDNS und UPnP nur im eigenen Netz. Läuft díktyo hinter einem Router
(z. B. ASUS im Router-Modus hinter der FRITZ!Box), sieht der Scan das FRITZ!Box-Netz nur per Ping/TCP. Die Namen fragt
díktyo dann beim DNS des Subnetzes ab (Gateway bzw. DNS-Angabe im IPAM), die MAC-Adressen liefert die FRITZ!Box-Integration.

### Mein Konto und Einstellungen

- **Mein Konto** öffnet ein Klick auf deine **E-Mail-Adresse** oben rechts (auf dem Handy das Personen-Symbol): Passwort,
  zweiter Faktor, angemeldete Sitzungen, Verknüpfung mit dem OIDC-Anbieter und **Profile und Freigaben** – je Profil
  deine Rolle und, als Besitzer, Mitglieder einladen, Rollen ändern, entfernen (früher Reiter *Freigabe*).
- **Einstellungen** gliedert sich in **Profil-Einstellungen** (oben das Profil wählen: *Benachrichtigungen* und
  *Quarantäne für neue Geräte*, früher im Reiter *Integrationen*) und **System** (nur Administratoren: Updates, Konten,
  E-Mail-Versand, OIDC, Erkennung, KI-Recherche, Sicherung). Jede Kachel hat oben einen Kopf mit ihrem Namen.
- Im Profil führen die Knöpfe *Teilen* (bzw. *Mitglieder*) und *Profil-Einstellungen* direkt dorthin.

### Konto absichern: zweiter Faktor und Sitzungen

díktyo speichert Zugangsdaten für Router, Switches und Server und kann Ports abschalten – deshalb lohnt sich der
**zweite Faktor**: *Mein Konto* (Klick auf die E-Mail-Adresse oben) *→ Zweiter Faktor → Einrichten*, Passwort eingeben, QR-Code mit einer
Authenticator-App scannen (Aegis, 2FAS, Google Authenticator, Bitwarden …) und den Code bestätigen. Danach zeigt díktyo
einmalig **10 Wiederherstellungscodes** – sicher aufbewahren, jeder ersetzt einmal den Code aus der App.

- Anmeldung: erst Passwort, dann der 6-stellige Code (oder ein Wiederherstellungscode). Jeder Code gilt nur einmal,
  nach 5 falschen Codes beginnt die Anmeldung von vorn.
- *Angemeldete Sitzungen* listet alle Browser mit Adresse und letzter Aktivität; einzelne oder alle anderen lassen sich
  abmelden. Ein neues Passwort meldet alle anderen Sitzungen ab.
- **Handy verloren:** Ein Administrator setzt den zweiten Faktor in der Kontenliste zurück (*2FA zurücksetzen*), oder
  auf dem Server: `diktyo reset-2fa deine@adresse.de` (Docker: `docker compose exec diktyo python -m app.cli reset-2fa …`).

### Übersicht

Beim Öffnen eines Profils erscheint die **Übersicht** im HUD-Stil über die ganze Bildschirmbreite:

- **Kennzahlen oben:** Geräte online (Segmentbalken, rot = offline), Internet mit Download/Upload im Verhältnis zur
  Leitung, Verfügbarkeit der Infrastruktur (Ring), Firmware-Updates, Posteingang, Änderungen seit gestern. Kacheln, die
  etwas zu tun bedeuten, sind farbig hinterlegt.
- **WAN-Traffic** als Balkendiagramm: Download nach oben, Upload nach unten (je eigene Skala), links die aktuellen Werte
  und die Leitung; Zeitraum 2 h bis 7 Tage.
- **Internet-Geschwindigkeit:** letzte Messung als zwei Tachos (gelb/rot, wenn deutlich unter der Leitung), Ping und
  Jitter, darunter der Verlauf der Messungen.
- **Braucht Aufmerksamkeit:** offline, Updates, Integrationen mit Fehlern, fehlgeschlagene Aktionen, Posteingang.
- **Aktivste Ports:** Switch einmal oben genannt, je Port das **Gerät dahinter** (aus den Verbindungen der Topologie)
  mit Balken und Werten ↓ zum Gerät / ↑ vom Gerät.
- **Gerade aktiv:** Geräte mit Live-Raten aus den Integrationen; die Quelle steht einmal im Titel.
- **Antwortzeiten Infrastruktur:** je Gerät Mittelwert und Höchstwert der letzten 24 Stunden mit Verlaufslinie
  (gelb ab 15 ms, rot ab 50 ms oder offline).
- **Infrastruktur:** Karten mit Typ, Name, Verfügbarkeit (Ring, 24 h), 7-Tage-Wert und Antwortzeit; ein Klick öffnet
  das Gerät.
- Dazu DNS-Filter (Pi-hole/AdGuard), Top-Verbraucher (ASUS) und die letzten Änderungen.

**Übersicht anpassen** (Rolle *Bearbeiten* oder *Besitzer*): Mit *Anpassen* lassen sich die Felder ziehen oder mit
◀ ▶ verschieben, ihre Breite wählen (S, M, L, XL oder ganze Breite) und Felder aus- und wieder einblenden; *Fertig*
speichert, *Zurücksetzen* stellt den Standard wieder her. Mit **Diagramm anheften** (Stecknadel-Symbol) kommen eigene Diagramme dazu:
WAN einer Integration, ein bestimmter Switch-Port (mit dem Gerät dahinter), ASUS-Schnittstellen (LAN, WLAN-Bänder),
DNS-Anfragen, die Antwortzeit oder Leistung eines bestimmten Geräts – als Balken oder Linie, mit eigenem Titel. Den
Stecknadel-Knopf gibt es auch direkt an den Diagrammen der Integrationskarten (WAN, gewählter Port, DNS) und im Gerätedialog
(Antwortzeit, Leistung). Angeheftete Diagramme zeigen oben rechts den aktuellen Wert und folgen dem Zeitraum des
WAN-Diagramms. Das Layout gilt für das ganze Profil, also für alle, mit denen es geteilt ist.

**Wachliste:** Wichtige Systeme – etwa einen Proxmox-Quorum-Knoten – im Gerätedialog mit **👁 Beobachten** auf die
Wachliste setzen (optional mit Notiz, z. B. „Quorum-Knoten“). Das Feld *Wachliste* in der Übersicht zeigt dann je
System den Zustand: **rot** (pulsierend), solange es offline ist; **gelb**, wenn es seit dem letzten Quittieren
ausgefallen war oder seine IP-Adresse, MAC, seinen Namen oder Anschluss gewechselt hat – mit alt → neu und Zeitpunkt;
**grün**, wenn alles ruhig ist. Der Alarm bleibt stehen, bis jemand *Quittieren* (je System) oder *Alle quittieren*
drückt; ein System, das gerade offline ist, bleibt rot, bis es zurück ist. Eigene Änderungen in díktyo lösen keinen
Alarm aus, nur was Scan, Integrationen und Online-Überwachung feststellen. Mit dem Ereignis *Wachliste* unter
*Benachrichtigungen* kommt jeder Alarm zusätzlich per E-Mail/ntfy (Ausfälle beobachteter Systeme auch dann, wenn
„Gerät offline“ nicht gewählt oder auf Infrastruktur beschränkt ist).

Alle Beschriftungen der Diagramme bleiben unabhängig von der Breite lesbar. Die Seite aktualisiert sich alle 30
Sekunden. Auf *Integrationen* stehen die Karten nebeneinander: Integrationen mit Diagrammen oder Portlisten nehmen zwei
Spalten ein, einfache eine.

## 3. Geräte, IPAM, Standorte

- **Geräte:** Im Gerätedialog Katalogmodell wählen – damit entstehen die Ports (z. B. 24 × RJ45 + 4 × SFP+). Unter
  *Anschluss* legst du fest, woran das Gerät hängt: LAN an einen Port, WLAN bzw. Mesh an einen Access Point, virtuell
  an einen Host. Von Hand gesetzte Verbindungen überschreibt keine Integration.
- **Nur Netzwerkanschlüsse am Gerät:** Der Katalog darf alle Anschlüsse eines Modells enthalten (USB, HDMI,
  Thunderbolt, MagSafe, Kartenleser, Audio …). Am Gerät – und damit im Gerätedialog, in der Topologie, im VLAN-Plan,
  bei der Verkabelung und im PDF – erscheinen nur Netzwerkanschlüsse (RJ45, SFP, Glasfaser, DSL, Koax), fortlaufend
  nummeriert. Bestehende Geräte wurden mit 0.30.1 einmalig umgestellt; Verbindungen und Kabelwege bleiben am
  richtigen Port.
- **Hersteller, Modell, Software:** Hersteller und Modell meinen die **Hardware** (z. B. HP · EliteDesk 800 G4), das Feld
  *Software / Betriebssystem* das, was darauf läuft (z. B. Proxmox VE 9.2). Proxmox füllt es selbst: der Host bekommt
  „Proxmox VE …“, VMs und Container ihr Gast-Betriebssystem (über den Gast-Agent bzw. die Konfiguration), als
  „Hardware“ Proxmox · QEMU-VM bzw. LXC-Container und – wenn leer – den Standort des Hosts. Ihre Verbindung ist
  „virtuell“ zum Host; den physischen Weg (Switch-Port usw.) hat der Host. Eigene Einträge überschreibt díktyo nicht.
- **Typ:** alphabetisch, u. a. Saugroboter, 3D-Drucker, Türklingel, Smart-Home-Hub (Zigbee, Matter, Thread),
  ESP-Gerät, Steckdose/Schalter, Licht, Thermostat, Energie, Wallbox, Haushaltsgerät, Sensor, Telefon/VoIP.
- **Erkannt als …** lässt sich mit *Vermutung verwerfen* ausblenden (z. B. HP-Rechner, der wegen der MAC als Drucker
  vermutet wird). Sie erscheint erst wieder, wenn der Scan etwas anderes erkennt.
- **Nur WLAN:** Hat das Katalogmodell keine Netzwerkbuchse, aber WLAN, steht die Verbindung auf WLAN – auch wenn ein
  Router das Gerät als „kabelgebunden“ meldet.
- **Woher die Namen kommen:** Beim ersten Fund vergibt díktyo einen Namen aus Hostname, mDNS oder Erkennung
  („Espressif .45“). Integrationen können ihn ersetzen: Home Assistant (Einstellung *Namen aus HA übernehmen*), Pi-hole/
  AdGuard (nur Platzhalternamen im Posteingang), neue Geräte aus FRITZ!Box, ASUS, Shelly usw. bekommen den Namen dort.
  **Ein Name, den du selbst änderst, ist geschützt** – keine Integration überschreibt ihn mehr. Die Shelly-Karte zeigt
  zusätzlich den Namen, der im Shelly selbst eingetragen ist („im Gerät: …“), falls er abweicht.
- **IPAM:** Subnetze mit Gateway, DHCP-Bereich und VLAN, Belegung und freie Adressen. Hinweise (z. B. doppelte IP,
  statische IP im DHCP-Bereich) lassen sich als gelesen markieren.
- **Standorte:** Baum aus Haus › Etage › Raum. Home Assistant kann seine Bereiche als Standorte liefern. Ein Klick auf
  einen Standort öffnet seinen **Grundriss** bzw. – bei der Art *Rack* – die **Rack-Ansicht** (siehe unten).
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

### Grundriss und Rack-Ansicht

**Grundriss:** Unter *Standorte* auf einen Standort (z. B. „Erdgeschoss“) klicken, dann *Bearbeiten*.
- *Grundriss-Bild hochladen*: ein Foto, Scan oder Export des Grundrisses als PNG, JPEG, WebP oder GIF (höchstens
  8 MB). Ohne Bild gibt es ein Raster mit wählbarem Seitenverhältnis.
- Rechts stehen Unterstandorte, Geräte und Patchfelder/Dosen, die noch nicht eingezeichnet sind – zuerst die dieses
  Standorts, darunter *Weitere Geräte*. Auf den Plan ziehen oder antippen und dann auf die Stelle tippen (geht auch
  am Handy). Unterstandorte werden als Rechteck eingezeichnet; die Größe ändert der Griff unten rechts. Geräte
  ohne Standort bekommen beim Platzieren diesen Standort.
- Verschieben durch Ziehen, entfernen mit dem roten ×. *Fertig* beendet das Bearbeiten.
- In der Ansicht zeigen die Punkte den Status (grün online, rot offline, grau nicht geprüft); ein Klick öffnet das
  Gerät, ein Rechteck den Unterstandort mit seinem eigenen Grundriss.

**Rack-Ansicht:** Einen Standort mit der Art *Rack / Netzwerkschrank* und der Zahl der Höheneinheiten (HE) anlegen,
z. B. „Rack 1“ unter „Technik“. Gezählt wird wie am Rack von unten (HE 1).
- *Bearbeiten*, dann Geräte oder Patchfelder aus der Liste ins Rack ziehen bzw. antippen und auf eine freie HE
  tippen. Die Höhe kommt aus dem Gerätetyp (Server, NAS, Hypervisor 2 HE, sonst 1 HE; Patchfelder über 24 Ports 2 HE).
- *+ Sonstiges* für USV, Blende, Kabelführung oder Ablage mit Bezeichnung und Höhe.
- Blöcke nach oben oder unten ziehen; ein Klick öffnet Höhe, Position und *Ausbauen*. Belegte HE werden abgelehnt.
- Ein eingebautes Gerät oder Patchfeld bekommt das Rack als Standort und steckt immer nur in einem Rack.
- Die kleinen Kästchen zeigen die Ports: grün verbunden (Geräte), orange belegt (Patchfelder, aus den Kabelwegen).

Im PDF (*Ausgabe*) gibt es dafür den Abschnitt *Grundrisse und Racks*; die Sicherung enthält Bilder, Platzierungen
und Rack-Belegung.

## 4. Integrationen

Reiter *Integrationen* → passenden Knopf wählen. Jeder Dialog zeigt oben die Schritte; *Verbindung testen* prüft die
Angaben, bevor gespeichert wird.

### FRITZ!Box

- In der FRITZ!Box: *Heimnetz → Netzwerk → Netzwerkeinstellungen* → „Zugriff für Anwendungen zulassen“.
- Ohne Benutzer: Geräteliste mit MAC-Adressen und WAN-Traffic.
- Mit Benutzer (*System → FRITZ!Box-Benutzer*, Recht „FRITZ!Box Einstellungen“): zusätzlich Mesh-Topologie (welches
  Gerät an welchem LAN-Port bzw. WLAN hängt), WLAN-Daten und das Konfigurations-Backup.
- **Leitungswerte:** Bei **DSL** liest díktyo über TR-064 Sync-Rate (aktuell und möglich), Störabstand, Dämpfung,
  CRC-/FEC-Fehler und Neusynchronisierungen – bei jeder Abfrage. Bei **Kabel** (DOCSIS) kennt TR-064 die Werte nicht;
  díktyo meldet sich dafür alle **15 Minuten** an der Weboberfläche an (Seite *Kabel-Informationen*), liest alle
  Kanäle (Pegel, MSE/MER, korrigierbare und nicht korrigierbare Fehler) und meldet sich wieder ab. Jede Anmeldung
  steht in der Ereignisliste der FRITZ!Box; wer das nicht möchte, stellt in der Integration „Leitungswerte bei Kabel“
  auf *nein*. Nach einer abgelehnten Anmeldung wartet díktyo eine Stunde, damit die FRITZ!Box nicht sperrt.
  Die Karte zeigt die Werte, auf Wunsch alle Kanäle, den Störabstand der letzten 24 Stunden (anheftbar) und
  **Hinweise nach Richtwerten**: DSL-Störabstand unter 6 dB, viele neue CRC-Fehler, Neusynchronisierung; bei Kabel
  Downstream-Pegel außerhalb von −8 bis 15 dBmV, Upstream außerhalb von 35 bis 51 dBmV, MSE unter 32 dB (256QAM)
  bzw. MER unter 35 dB (DOCSIS 3.1), viele neue nicht korrigierbare Fehler. Die Hinweise stehen auch in der
  Übersicht unter *Braucht Aufmerksamkeit*, und es gibt die Benachrichtigung *Leitung verschlechtert*. Die Grenzen
  deines Netzbetreibers können abweichen – die Richtwerte sind ein Anhaltspunkt, keine Diagnose. Glasfaser-Boxen
  liefern über diese Wege keine Werte.

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
  Den Host-Schlüssel des Switches merkt sich díktyo bei der ersten Verbindung. Ändert er sich später, bricht díktyo
  **vor** der Anmeldung ab – Passwort oder Schlüssel werden dann nicht gesendet. Nach einem gewollten Wechsel
  (neue Firmware, Gerätetausch) die Integration einmal *Speichern* – dann lernt díktyo den Schlüssel neu.
- **Ports:** Manche Switches melden neben den Frontports logische Schnittstellen (Trunk, VLAN, CPU). díktyo
  übernimmt nur echte Ports und höchstens so viele, wie das Katalogmodell hat; die *Diagnose* nennt die
  ausgelassenen. Ports mit Link unter 1 Gbit/s sind **orange**, ab 2,5 Gbit/s **blau**.
- Antwortet der Switch gar nicht („Keine Antwort“), blockiert er die Anfragen – meist fehlt die Freigabe unter Service
  Access oder Trusted Hosts.
- **Hersteller-Profil:** „automatisch“ erkennt Netgear, Zyxel und TP-Link an der Kennung des Geräts. Für alle liest
  díktyo zusätzlich Modell, Seriennummer, Firmware und Hardware-Revision (ENTITY-MIB) und, wo vorhanden, die CPU-Last;
  bei Netgear außerdem Inventar und Temperatur. Die Firmware erscheint unter *Erreichbarkeit und Firmware*, Hersteller
  und Modell am Gerät (nur wenn dort noch leer).
- **Netgear:** SNMP im Web-Menü unter *System → SNMP* (M-Serie: *System → Management → SNMP*) einschalten, Community
  bzw. SNMPv3-Benutzer anlegen und díktyo als erlaubten Client eintragen. Für Aktionen (Port ab-/einschalten, PoE neu
  starten) braucht die Community Zugriff „Read-Write“. Die **Plus-Switches** (GS105E, GS108E, GS305E, GS308E …) haben
  kein SNMP – sie lassen sich nur von Hand dokumentieren.
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
- **Gastnetze:** Die Karte zeigt die eingerichteten Gastnetze je Band mit Status. Im Gerätedialog unter *Aktionen* lassen
  sie sich ein- und ausschalten (mit Zurückschalten und als Zeitplan, z. B. Gastnetz nur Fr–So). Das WLAN des Routers
  startet dafür kurz neu. Bei Firmware mit **Gastnetz Pro** (SDN, z. B. ExpertWiFi-Modelle mit mehreren Netzprofilen)
  verwaltet der Router Gastnetze anders – dort zeigt díktyo nur einen Hinweis und bietet das Schalten (noch) nicht an.
- **Neustart** des Hauptrouters unter *Aktionen* (Internet und WLAN sind etwa zwei Minuten weg).
- **Konfigurations-Backup:** Die Einstellungsdatei (`Settings_<Modell>.CFG`) ist verschlüsselt. díktyo entschlüsselt sie
  zum Vergleichen: *Änderungen* zeigt, welche Einstellungen sich geändert haben (sortiert als `name=wert`), *als Text*
  lädt die lesbare Fassung herunter. Passwörter und Schlüssel (Admin-Passwort, WLAN-Schlüssel, VPN-Schlüssel …) erscheinen
  dabei nur als `••••••` mit einer kurzen Prüfsumme – so sieht man, *dass* sich ein Schlüssel geändert hat, aber nicht
  welcher. Wiederherstellen geht weiter mit der Originaldatei (*Herunterladen*) in der Weboberfläche des Routers. Weil die
  Datei bei jedem Export andere Zufallsbytes enthält, vergleicht díktyo den entschlüsselten Inhalt – eine unveränderte
  Konfiguration wird nicht erneut abgelegt.

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

### MikroTik (RouterOS 6 und 7)

Für hAP, hEX, RB2011, RB5009, CRS-Switches, cAP, Chateau usw. Standard ist die **RouterOS-API** (Dienst *api*,
Port 8728) – sie gibt es bei RouterOS 6 und 7. Im MikroTik-Terminal (WinBox → *New Terminal*):

```
/ip service set api disabled=no address=192.168.88.0/24
/user group add name=diktyo-read policy=read,api,!local,!telnet,!ssh,!ftp,!winbox,!web,!rest-api
/user add name=diktyo group=diktyo-read password=GEHEIM
```

Bei `address=` das Netz bzw. die Adresse von díktyo eintragen (IP → Services → api → *Available From*). Für
**Aktionen** (Port, PoE, WLAN, Neustart, Wake-on-LAN) die Gruppe mit `policy=read,write,reboot,test,api` anlegen.

In díktyo unter *Zugang* wählen:

| Zugang | Dienst am MikroTik | Port | RouterOS |
|---|---|---|---|
| RouterOS-API (Standard) | api | 8728 | 6 und 7 |
| RouterOS-API mit TLS | api-ssl (braucht ein Zertifikat) | 8729 | 6 und 7 |
| REST über HTTPS | www-ssl (braucht ein Zertifikat), Recht *rest-api* | 443 | ab 7.1 |
| REST über HTTP | www, Recht *rest-api* | 80 | ab 7.9 |
| SNMP (v2c oder v3) | snmp, nur lesen | 161 | 6 und 7 |

**SNMP** liefert dieselbe Übersicht (Ports mit Tempo, Traffic und PoE, wer an welchem Port bzw. WLAN hängt, Nachbarn,
WAN über die Standardroute, Modell, RouterOS-Version, RouterBOOT-Update) – nur lesend: keine Schaltaktionen und keine
DHCP-Namen (die Clients kommen aus der ARP-Tabelle, Namen liefert der Netzscan). Am MikroTik:

```
/snmp set enabled=yes
/snmp community add name=diktyo addresses=192.168.88.0/24 read-access=yes write-access=no
```

Für SNMPv3 die Community zusätzlich mit `security=private authentication-protocol=SHA1 authentication-password=…
encryption-protocol=AES encryption-password=…` anlegen; in díktyo ist der Community-Name dann der SNMP-Benutzer.

Das Feld *Port* bleibt leer, wenn der Dienst auf dem Standard-Port läuft. Meldet díktyo „Am Port antwortet kein
HTTPS-Dienst“, ist REST gewählt, am Port läuft aber die API (oder umgekehrt). Integrationen, die vor 0.33.1 mit REST
angelegt wurden, bleiben bei REST; steht dort Port 8728 bzw. 8729, nutzt díktyo automatisch die API.

díktyo liest Modell und Version, Ports (Link, Tempo, Traffic, PoE), Clients aus DHCP und ARP, welches Gerät an welchem
Port bzw. WLAN hängt (Bridge-Hosts, WLAN-Registrierungen mit Signal), Nachbarn per MNDP/LLDP und den WAN-Traffic
(Interface-Liste „WAN“). Ein **Konfigurations-Backup** macht díktyo bei MikroTik nicht – RouterOS hat dafür eigene
Backups (*System → Backup*, auch in die MikroTik-Cloud).

**Hinweis:** gegen nachgebildete Schnittstellen getestet (REST und RouterOS-API über einen echten Socket), noch nicht an
echter Hardware – Rückmeldungen willkommen.

### OpenWrt (ubus/rpcd)

díktyo spricht OpenWrt über dieselbe Schnittstelle wie LuCI (ubus per JSON-RPC unter `/ubus`).

- Voraussetzung: **LuCI** ist installiert (bringt uhttpd mit ubus, rpcd, luci-rpc und iwinfo mit). Ohne LuCI die
  Pakete `uhttpd-mod-ubus rpcd-mod-luci rpcd-mod-iwinfo` installieren (`apk add …` ab 25.x, sonst `opkg install …`).
- *+ OpenWrt*, Adresse des Routers, Benutzer und Passwort. *Verbindung* „automatisch“ versucht HTTPS (selbst
  signiertes Zertifikat ist in Ordnung) und dann HTTP.
- **Benutzer:** am einfachsten `root` mit dem Router-Passwort. Besser ein eigener Benutzer mit nur den nötigen Rechten –
  auf dem Router (per SSH):

  ```sh
  cat > /usr/share/rpcd/acl.d/diktyo.json <<'EOF'
  { "diktyo": { "description": "díktyo",
      "read":  { "ubus": { "system": ["board", "info"], "network.device": ["status"], "network.interface": ["dump"],
                           "network.wireless": ["status"], "luci-rpc": ["getDHCPLeases", "getHostHints"],
                           "iwinfo": ["assoclist"], "uci": ["get"], "luci.upnp": ["get_status"] },
                 "uci": ["network", "wireless", "firewall"], "cgi-io": ["backup"] },
      "write": { "ubus": { "uci": ["set", "commit"], "network": ["reload"], "system": ["reboot"] },
                 "uci": ["wireless"] } } }
  EOF
  uci add rpcd login
  uci set rpcd.@login[-1].username='diktyo'
  uci set rpcd.@login[-1].password="$(uhttpd -m 'ein-langes-passwort')"
  uci add_list rpcd.@login[-1].read='diktyo'
  uci add_list rpcd.@login[-1].write='diktyo'
  uci commit rpcd && service rpcd restart
  ```

  Ohne den Block `write` (und ohne `add_list … write`) liest díktyo nur; die Aktionen melden dann „keine Berechtigung“.
- díktyo liest Modell, OpenWrt-Version und Laufzeit, die **Ports** (lan1 …, wan bzw. eth0 … bei Geräten ohne DSA) mit
  Link, Tempo und Traffic, den **WAN**-Traffic, die **Clients** (aktive DHCP-Leases, WLAN-Geräte mit Band und Signal,
  Namen aus den Host-Hinweisen), die **WLANs** und die **VLANs** der Bridge (DSA, *Netzwerk → Schnittstellen → Geräte →
  br-lan → Bridge-VLAN-Filterung*) für den VLAN-Plan.
- Der Router erscheint als Router (mit WAN), sonst als Access Point (nur WLAN). WLAN-Geräte hängen per WLAN am Router.
  Welcher LAN-Port zu welchem Gerät führt, verrät OpenWrt nicht – das klären ein Switch per SNMP oder du von Hand.
- **Aktionen:** WLAN ein/aus (setzt `disabled` in `/etc/config/wireless`, mit Zurückschalten) und Neustart.
- **Konfigurations-Backup** wie *System → Sichern/Flashen → Sicherung herunterladen* in LuCI (`.tar.gz`, lässt sich
  dort wieder einspielen). Achtung: Die Datei enthält auch Passwörter (WLAN-Schlüssel, `/etc/shadow`); díktyo legt sie
  verschlüsselt ab.

### OPNsense

1. *System → Zugang → Benutzer*: eigenen Benutzer anlegen und unter *Effektive Berechtigungen* erlauben: *Status:
   Interfaces*, *Diagnostics: ARP Table*, *Services: DHCP: Kea(v4)* (bzw. Dnsmasq/ISC), *System: Firmware*.
2. Beim Benutzer unter *API-Schlüssel* „+“ – die heruntergeladene Datei enthält **key** und **secret**.
3. Optional **Internetsperre**: *Firewall → Aliase* → Alias vom Typ „Host(s)“ (z. B. `diktyo_block`) und eine LAN-Regel
   „Block, Quelle = Alias“ ganz oben; den Alias-Namen in der Integration eintragen (Recht *Firewall: Alias: Edit*).
4. Konfigurations-Backup lädt die `config.xml` (Recht *Diagnostics: Configuration History* bzw. *Backup & Restore*).

díktyo liest Schnittstellen (Status, Adressen, Traffic), Clients aus DHCP-Leases und ARP, WAN-Status und -Traffic
(Internet-Leitung in der Topologie) und den Firmware-Stand.

### Pi-hole / AdGuard Home

- *+ Pi-hole / AdGuard*, Art wählen, Adresse und Port wie im Browser.
- **Pi-hole (ab v6):** unter *Einstellungen → Web-Oberfläche/API* ein **App-Passwort** erzeugen und als Passwort
  eintragen. díktyo hält eine Sitzung offen und nutzt sie weiter (Pi-hole begrenzt gleichzeitige Sitzungen). Pi-hole v5
  geht mit dem API-Token, liefert aber nur Zusammenfassung und Top-Clients.
- **AdGuard Home:** Benutzer und Passwort der Weboberfläche. Die Blockierten je Gerät stammen aus den letzten 1000
  blockierten Einträgen des Abfrage-Protokolls (AdGuard führt dazu keine eigene Statistik).
- **Hostnamen:** Geräte ohne Hostnamen bekommen den aus Pi-hole/AdGuard (rDNS, DHCP). Geräte im Posteingang mit
  Platzhalternamen („Espressif .45“) werden umbenannt; selbst vergebene Namen bleiben.
- **Je Gerät:** Anfragen und Blockierte (24 h) im Gerätedialog und auf der Karte; die Übersicht zeigt Anfragen und
  Blockierte je Minute als Diagramm und die meistblockierten Geräte.
- **Aktion** am Pi-hole-Gerät: *Werbeblocker ausschalten* – mit *Zurückschalten nach* z. B. nur für 15 Minuten.
- Gespeichert werden nur Zahlen je Gerät und die meistblockierten Domains insgesamt, keine besuchten Domains einzelner
  Geräte.

### Shelly / Tasmota (direkt, ohne Cloud)

- *+ Shelly / Tasmota*, unter *Adressen* „auto“ lassen: díktyo fragt alle Geräte ab, die der Netzscan als Shelly oder
  Tasmota erkannt hat, und probiert ESP-Module von Espressif (tragen oft Tasmota). Weitere IPs mit Komma ergänzen,
  z. B. `auto, 192.168.50.40`. Was nicht antwortet, wird einige Stunden übersprungen.
- Unterstützt: Shelly Gen1, Gen2/3/4 (z. B. Pro 3EM, 1PM Mini Gen3, Plus-Serie) und Tasmota. Ist am Gerät eine
  Anmeldung eingeschaltet, Passwort eintragen (Shelly Gen2+: Benutzer `admin`).
- Die Karte zeigt jedes Gerät mit Ausgängen (an/aus), Leistung, Energie, WLAN-Signal und Firmware (mit Update-Hinweis);
  im Gerätedialog stehen Leistung, Energie, Spannung und der Leistungsverlauf als Diagramm.
- *Aktionen* im Gerätedialog: Ausgang ein/aus (mit automatischem Zurückschalten) und *Firmware aktualisieren*, wenn
  das Gerät ein Update meldet. Vorsicht bei Steckdosen, an denen Server oder Netzwerktechnik hängen.
- Das Update lädt der Shelly selbst vom Hersteller. díktyo prüft danach, ob die neue Version ankommt; nach 20 Minuten
  ohne neue Version erscheint ein Hinweis (meist kommt das Gerät nicht ins Internet). *Weboberfläche öffnen* (im
  Gerätedialog, in der Topologie und als ↗ auf der Karte) führt direkt zum Gerät.

### devolo Powerline

- Unterstützt sind Adapter, die die **devolo Home Network App** verwaltet (Magic-Serie und neuere dLAN-Modelle).
  Ältere Adapter, die nur das dLAN Cockpit kennen, haben diese Schnittstelle nicht.
- *+ devolo Powerline*, die IP-Adresse **eines** Adapters eintragen – am besten den am Router. Die übrigen Adapter des
  Powerline-Netzes findet díktyo selbst. Ein in der App gesetztes **Gerätepasswort** eintragen, sonst leer lassen.
- díktyo sollte im selben Netz wie die Adapter liegen: sie melden ihre Schnittstelle per mDNS (Port 5353), das leiten
  Router meist nicht weiter.
- Die Karte zeigt alle Adapter mit Modell, IP und Firmware (Update-Hinweis, einmal am Tag geprüft), wie viele Geräte an
  ihrer LAN-Buchse bzw. im WLAN hängen und die **Datenraten zwischen den Adaptern** (beide Richtungen, als Messwerte
  gespeichert).
- Die Adapter werden als Typ *Powerline* angelegt und mit der Verbindungsart **Powerline** verbunden; der Adapter am
  Router ist die Wurzel und hängt am Router. Geräte an den anderen Adaptern hängen an „ihrem“ Adapter, WLAN-Geräte per
  WLAN. Von Hand gesetzte Verbindungen bleiben unangetastet.
- díktyo liest nur; Pairing, LED, WLAN-Einstellungen und Firmware-Update bleiben in der devolo-App.

### Docker

Den Docker-Socket nie direkt freigeben, sondern auf dem Docker-Host einen **Socket-Proxy** starten, der nur das Nötige
erlaubt – die `docker-compose.yml` dafür steht im Einrichtungsdialog (lesen: `CONTAINERS`, `INFO`, `VERSION`,
`NETWORKS`; für Aktionen zusätzlich `POST`, `ALLOW_START`, `ALLOW_STOP`, `ALLOW_RESTARTS`). Port 2375 nur im Heimnetz
erreichbar lassen. Container erscheinen als virtuelle Geräte am Docker-Host (Image als Modell, laufend = online);
Starten, Stoppen und Neustarten über *Aktionen*. díktyo stoppt weder sich selbst noch den Socket-Proxy.

**Hinweis:** OPNsense, OpenWrt, Docker, devolo und die Netgear-Zusatzwerte sind nach der Dokumentation gebaut und gegen
nachgebildete Geräte getestet, noch nicht an echter Hardware.

### Portfreigaben und UPnP

Der Reiter **Portfreigaben** zeigt, was der Router aus dem Internet an Geräte im Heimnetz weiterleitet – Freigaben, die
du eingerichtet hast, und solche, die Geräte per **UPnP** selbst angelegt haben (Spielkonsolen, Torrent-Programme,
Kameras …). díktyo liest nur, am Router ändert sich nichts.

| Quelle | Was | Hinweis |
|---|---|---|
| FRITZ!Box | IPv4-Portfreigaben über TR-064 | nur mit Benutzer; alle 5 Minuten (je Eintrag eine Abfrage). TR-064 sagt nicht, ob eine Freigabe eingerichtet oder per UPnP angelegt wurde – Einträge mit Laufzeit gelten als UPnP. IPv6- und MyFRITZ!-Freigaben fehlen. |
| ASUS | Portweiterleitungen (*WAN → Virtueller Server*) und die UPnP-Liste | UPnP-Liste alle 5 Minuten, nur wenn UPnP eingeschaltet ist |
| OpenWrt | Portweiterleitungen (*Firewall → Port Forwards*, DNAT) und UPnP (luci-app-upnp) | die ACL braucht Lesezugriff auf `firewall` und `luci.upnp` (Beispiel oben) |
| MikroTik | `/ip firewall nat`-Regeln mit `action=dst-nat`; von UPnP angelegte sind dynamisch | RouterOS-API oder REST, nicht über SNMP |
| OPNsense | Destination NAT | erst ab OPNsense 25.7 (vorher gibt es dafür keine API) |
| UniFi | Portweiterleitungen der Network-App (klassische API) | antwortet die Konsole nicht, versucht díktyo es am nächsten Tag wieder |

- Die Tabelle nennt Protokoll, externen Port, das **Gerät hinter der Ziel-IP** (Klick öffnet es), internen Port,
  Beschreibung, Quelle und erlaubte Absender, falls eingeschränkt. Abgeschaltete Freigaben sind grau, bei UPnP steht
  die Restlaufzeit dabei.
- **Riskante Dienste** auf dem externen Port (SSH, Telnet, RDP, SMB, VNC, Datenbanken, Proxmox, Home Assistant …)
  sind rot markiert – nicht zwingend falsch, aber eine Prüfung wert.
- **Neue Freigaben** – auch wenn eine bestehende plötzlich auf ein anderes Gerät oder einen anderen Port zeigt –
  stehen oben, sind markiert und erscheinen unter *Braucht Aufmerksamkeit*, bis du sie mit *bekannt* bestätigst.
  Dazu gibt es die Benachrichtigung *Neue Portfreigabe*. Beim ersten Abruf gilt alles Vorhandene als bekannt.
- Je Freigabe eine **Notiz** („Nextcloud – bewusst offen“); *CSV speichern* exportiert die Liste mit Notizen.
- Im **Gerätedialog** steht oben „Aus dem Internet erreichbar“, wenn Freigaben auf das Gerät zeigen.

## 5. Überwachung und Ereignisse

- *Integrationen → Online-Überwachung:* alle bestätigten Geräte werden alle 30 s, 1 min oder 5 min gepingt. Antwortet
  ein Gerät nicht, prüft díktyo einen bekannten offenen Port (sonst 80) und pingt noch einmal mit mehr Geduld. Ein
  Gerät, das online war, gilt erst nach **zwei Runden ohne Antwort** als offline – WLAN-Geräte im Stromsparmodus
  (z. B. Shellys) verschlucken gern einen einzelnen Ping. Hat eine andere Quelle (FRITZ!Box, Router, SNMP, Scan) das
  Gerät kürzlich gesehen (mindestens 10 Minuten, bei längerem Abfrageintervall 2,5 Intervalle), bleibt es online, auch
  wenn der Ping nicht durchkommt (z. B. Switch hinter NAT oder mit ICMP-Filter). Der *Schnell-Ping* prüft Geräte, die
  online waren und in der Lastspitze nicht antworten, danach einzeln mit mehr Geduld nach.
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

### Anmeldung über OIDC (Authentik, Keycloak, Logto …)

Unter *Einstellungen → Anmeldung über OIDC (SSO)* (nur Administratoren) lässt sich ein eigener Identity Provider
anbinden. Auf der Anmeldeseite erscheint dann **Anmelden mit …**; die Anmeldung mit Passwort bleibt daneben möglich.

1. Beim Anbieter eine Anwendung/einen Client anlegen und die angezeigte **Redirect-URI** eintragen
   (`…/api/auth/oidc/callback`). Läuft díktyo hinter einem Reverse-Proxy oder mit HTTPS, zuerst unter
   *E-Mail-Versand* die **Adresse der Weboberfläche** eintragen – daraus entsteht die Redirect-URI.
   - **Authentik:** Anwendung mit Provider „OAuth2/OpenID“ (vertraulich). Issuer:
     `https://<host>/application/o/<slug>/`. Gruppen kommen im Claim `groups`.
   - **Keycloak:** Client „OpenID Connect“, *Client authentication* an, *Standard flow*. Issuer:
     `https://<host>/realms/<realm>`. Für Gruppen einen Mapper „Group Membership“ (Claim `groups`, ohne vollen Pfad).
   - **Logto:** Anwendung „Traditional Web“. Issuer: `https://<host>/oidc`. Für Rollen den Scope `roles` ergänzen und
     als Gruppen-Claim `roles` eintragen.
2. In díktyo **Aussteller (Issuer-URL)**, **Client-ID** und **Client-Secret** eintragen, *Verbindung testen*,
   *Eingeschaltet* ankreuzen und speichern. Am besten in einem privaten Fenster *Anmelden mit …* ausprobieren.
3. **Konten:** Beim ersten Anmelden wird ein bestehendes díktyo-Konto mit gleicher E-Mail-Adresse verknüpft – nur wenn
   der Anbieter die Adresse als bestätigt meldet (sonst ließe sich mit einer fremden, unbestätigten Adresse ein Konto
   übernehmen). Weicht die Adresse ab, verknüpft man unter *Mein Konto* mit **Mit … verknüpfen**.
   *Konten automatisch anlegen* gibt jedem, der sich beim Anbieter anmelden darf, ein díktyo-Konto (ohne Profile, bis
   jemand sie teilt). Optional: nur Mitglieder einer Gruppe zulassen, und Mitglieder einer Admin-Gruppe werden
   Administratoren (díktyo entzieht die Rolle nie automatisch).

Den zweiten Faktor übernimmt bei dieser Anmeldung der Anbieter – der Code aus der Authenticator-App von díktyo wird
dann nicht abgefragt. *Abmelden* meldet nur bei díktyo ab, nicht beim Anbieter. Geprüft werden PKCE, state, nonce
und die Signatur des ID-Tokens (RS…, PS…, ES… – Logto nutzt ES384 – und HS… mit dem Client-Secret).

### Prometheus und Grafana

*Integrationen → Prometheus / Grafana* stellt die Messwerte des Profils für **Prometheus** bereit; **Grafana** zeigt
sie mit einem fertigen Dashboard an.

1. **Token erzeugen** (nur Besitzer des Profils). Es wird nur einmal angezeigt und gilt nur für dieses Profil und nur
   zum Lesen der Messwerte; díktyo speichert lediglich einen Hash. *Neues Token* macht das alte ungültig,
   *Ausschalten* löscht es.
2. Den angezeigten **Eintrag für prometheus.yml** kopieren (Adresse, Pfad und Token sind schon eingesetzt) und in die
   `scrape_configs` deiner Prometheus-Konfiguration übernehmen, Prometheus neu laden. Prometheus muss díktyo unter der
   angezeigten Adresse erreichen können (bei Docker/LXC die Adresse im Heimnetz, nicht `localhost`).
3. **Grafana-Dashboard herunterladen** und in Grafana unter *Dashboards → Neu → Importieren* hochladen, dabei die
   Prometheus-Datenquelle wählen.

Im Kasten steht, wann Prometheus zuletzt abgefragt hat. Bereitgestellt werden (Präfix `diktyo_`): Geräte gesamt/online/
offline und je Gerät erreichbar (`device_up`), Antwortzeit, Verfügbarkeit 24 h (Infrastruktur), Leistung, Firmware-
Updates, WAN-Traffic, Traffic je Switch-Port (mit angeschlossenem Gerät) und Schnittstelle, DNS-Anfragen/Blockierte,
letzter Speedtest, Zustand der Integrationen, Wachliste, offene VLAN-Umstellungen, Posteingang. díktyo liefert jeweils
den aktuellen Stand – den Verlauf speichert Prometheus.

### Benachrichtigungen (E-Mail, ntfy)

*Einstellungen → Profil-Einstellungen → Benachrichtigungen* meldet Ereignisse des Profils per **E-Mail** (über den E-Mail-Versand unter
*Einstellungen*) und/oder **ntfy** (Push aufs Handy) – unabhängig von Home Assistant.

1. ntfy: die App installieren (Android/iOS) und ein **Thema** abonnieren, z. B. `diktyo-k7x2q9` – bei ntfy.sh kann jeder
   ein Thema lesen, der den Namen kennt, also einen schwer erratbaren Namen wählen oder einen eigenen ntfy-Server
   nutzen (dann Server-Adresse und ggf. Zugangstoken eintragen).
2. In díktyo ntfy und/oder E-Mail einschalten (Empfänger leer = Besitzer des Profils), die gewünschten Ereignisse
   ankreuzen, *Testnachricht senden*, *Speichern*.

| Ereignis | Wann |
|---|---|
| Gerät offline / wieder online | nach der Online-Überwachung (zwei Runden ohne Antwort); wahlweise nur Infrastruktur |
| Neues Gerät, Quarantäne | wenn der Scan oder eine Integration ein unbekanntes Gerät findet |
| Firmware-Update | wenn eine Integration ein Update meldet |
| Zurückschalten / Zeitplan fehlgeschlagen | bei Schaltaktionen |
| Internet langsam | Speedtest unter der Hälfte der Leitung (laut FRITZ!Box) |
| Konfigurations-Backup fehlgeschlagen | beim automatischen Backup |
| Integration gestört | wenn eine Integration seit 15 Minuten nicht mehr antwortet (einmal, bis sie wieder klappt) |
| Leitung verschlechtert | ein neuer Hinweis zu den DSL-/Kabelwerten der FRITZ!Box (einmal je Hinweisart, bis er verschwunden ist) |
| Neue Portfreigabe | ein Router meldet eine neue Portfreigabe oder UPnP-Weiterleitung (siehe *Portfreigaben und UPnP*) |
| Wachliste | ein beobachtetes System fällt aus oder wechselt IP, MAC, Name oder Anschluss (siehe *Übersicht*) |

Mehrere Ereignisse werden höchstens einmal pro Minute zu einer Nachricht gebündelt. Beim Einschalten zählen nur neue
Ereignisse, nicht die bisherigen.

### Geschwindigkeit messen

- **Internet:** *Jetzt messen* in der Übersicht (oder *Integrationen → Speedtest*) misst Ping, Jitter, Download und
  Upload des díktyo-Rechners gegen `speed.cloudflare.com`: mehrere parallele Verbindungen für einige Sekunden je
  Richtung, höchstens 600 MB herunter und 150 MB hoch je Messung. Unter *Automatisch messen* lässt sich alle 3, 6, 12
  oder 24 Stunden messen (voreingestellt: aus). Der Verlauf bleibt zwei Jahre, die Übersicht zeigt ihn als Diagramm
  und meldet unter *Braucht Aufmerksamkeit*, wenn der Download unter die Hälfte der Leitung fällt, die die FRITZ!Box
  meldet. Gemessen wird díktyos Weg ins Internet – steht díktyo hinter einem weiteren Router (z. B. ASUS hinter der
  FRITZ!Box), zählt dessen Anbindung mit.
- **iperf3 zu einem Gerät:** im Gerätedialog *Durchsatz messen (iperf3)*. Auf dem Gerät muss ein iperf3-Server laufen
  (`iperf3 -s`, Port 5201; z. B. NAS, Proxmox-Host, Linux-Rechner). díktyo misst in beide Richtungen und führt den
  Verlauf je Gerät. Der Installer bringt den iperf3-Client mit (ab 0.19; er läuft nicht als Server).

## 6. Topologie

- Gesamtbaum von links nach rechts mit Port-Namen an den Linien; WLAN-Geräte und VMs sind zu aufklappbaren Gruppen
  zusammengefasst.
- **Gruppieren** (Auswahl in der Werkzeugleiste) legt fest, welche Boxen unter einem Access Point oder Switch entstehen:
  - *Verbindungsart* – wie bisher WLAN-Geräte und VMs/Container;
  - *Eigene Gruppen* – z. B. „IoT“, „Kameras“, „Kinderzimmer“. Anlegen unter *Gruppen …* → *+ Gruppe*: Name, Farbe und
    Geräte ankreuzen (mit Suche). Ein Gerät gehört zu höchstens einer Gruppe; wählt man es in einer anderen Gruppe an,
    wechselt es beim Speichern dorthin;
  - *Standort*, *Tag* (der erste Tag des Geräts) oder *VLAN* – das VLAN kommt vom Switch-Port, an dem das Gerät hängt,
    bei VMs aus dem Proxmox-Tag, sonst aus dem Subnetz seiner IP-Adresse (IPAM). Die Box hat die Farbe des VLANs.

  Geräte ohne passende Angabe landen wie bisher in den WLAN- bzw. VM-Boxen. Unter *Gruppen …* stehen auch die
  Schwellwerte: ab wie vielen WLAN-Geräten, VMs oder Gruppenmitgliedern zusammengefasst wird (0 = nie). Die Einstellung
  gilt für das ganze Profil, auch für PDF und Netzplan-Export. Ein Klick auf eine Box klappt sie auf, das − am Gerät
  wieder zu.
- Doppelklick auf einen Switch oder Router öffnet die **Frontplatte** mit allen Ports. Klick auf einen Port zeigt das
  angeschlossene Gerät mit IP und MAC (mit SNMP auch Link, Traffic und LLDP).
- *Schnell-Ping* prüft alle Geräte sofort.
- Hängen an einem Gerät mehr als 8 Endgeräte (aufgeklappt), stehen sie in mehreren Spalten nebeneinander – die
  Topologie wird breiter statt sehr hoch. An der Internet-Leitung steht der Eingang des Routers (z. B. „Kabel“, „DSL“).
- **Durchsatz** (Knopf in der Werkzeugleiste) zeigt an jeder Verbindung den aktuellen Traffic ↓/↑ aus Sicht des
  angeschlossenen Geräts; die Linie wird mit der Last dicker, der Wert steht kurz vor dem Gerät. Die Einstellung merkt
  sich der Browser. Woher die Werte kommen:

  | Verbindung | Quelle |
  |---|---|
  | Kabel | Ports von Switch (SNMP), MikroTik, OPNsense, OpenWrt, UniFi-/Omada-Switches |
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
  Konfigurationsstände, Port-Änderungen); darunter Zeitraum, Art und Suche.
- **Verlauf speichern** lädt die gerade gefilterten Einträge (Zeitraum, Art, Suche) als CSV-Datei herunter (Excel,
  LibreOffice).
- **Verlauf löschen** (nur Besitzer): wählen, was (Änderungen, Online/Offline, Aktionen, Quarantäne) und welche Einträge
  (alle oder älter als 30/90 Tage/ein Jahr). Erhalten bleiben der letzte Online/Offline-Stand je Gerät, Aktionen mit noch
  offenem Zurückschalten, Geräte in aktiver Quarantäne und die Konfigurationsstände (die löschst du im Gerätedialog).
  Achtung: Online/Offline-Einträge sind die Grundlage der Verfügbarkeit – vorher am besten speichern. Das Löschen steht
  im Protokoll.
- Im **Gerätedialog** steht der Verlauf der letzten 30 Tage.
- Wechselt ein Handy nur zwischen WLAN- bzw. Mesh-Zugangspunkten (Roaming), wird das nicht eingetragen.
- Der Verlauf wird ein Jahr aufbewahrt und ist Teil der díktyo-Sicherung.

## 7. Konfigurations-Backups der Geräte

- FRITZ!Box (mit Benutzer), ASUS-Router, OPNsense, OpenWrt und Switches per SSH sichern ihre Konfiguration wöchentlich oder täglich
  (Einstellung in der Integration) oder per *Konfiguration sichern*.
- Unveränderte Konfigurationen werden nicht doppelt abgelegt; pro Gerät bleiben die letzten 30 Stände.
- Die Dateien liegen verschlüsselt in díktyo. Im Gerätedialog unter *Konfigurations-Backups*: herunterladen und bei
  Text-Konfigurationen (FRITZ!Box, Switch, OPNsense) und der entschlüsselten ASUS-Einstellungsdatei die **Änderungen** zum
  vorherigen Stand ansehen (ASUS zusätzlich *als Text*, Passwörter maskiert).
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
| MikroTik | Port ab-/einschalten, PoE neu starten, WLAN ein/aus, Wake-on-LAN, Neustart | Benutzergruppe mit write, reboot, test (und api bzw. rest-api) |
| OPNsense | Internetzugang je Gerät (über den Alias), Neustart | Alias + Block-Regel, Recht *Firewall: Alias: Edit* |
| OpenWrt | WLAN ein/aus (mit Zurückschalten), Neustart | Benutzer root oder rpcd-Benutzer mit dem `write`-Teil der ACL (siehe Kapitel 4) |
| ASUS | Gastnetz ein/aus (mit Zurückschalten, nicht bei „Gastnetz Pro“/SDN), Neustart | Admin-Konto des Routers (wie für das Lesen) |
| Docker | Container starten, stoppen, neu starten | Socket-Proxy mit POST und ALLOW_* |
| UniFi | verwaltetes Gerät (Gateway, Switch, AP) neu starten; PoE an einem Switch-Port neu starten | API-Schlüssel mit Schreibrecht |
| Omada | verwaltetes Gerät neu starten; PoE an einem Switch-Port ein/aus (mit Zurückschalten) und neu starten | Open-API-App mit Schreibrecht (Rolle Administrator) |
| Shelly / Tasmota | Ausgang ein/aus (mit Zurückschalten), Firmware aktualisieren | ggf. Passwort der Geräte in der Integration |
| Pi-hole / AdGuard Home | Werbeblocker bzw. Schutz aus/ein (mit Zurückschalten) | App-Passwort bzw. Admin-Zugang |

- Vor jeder Aktion kommt eine **Vorschau mit Bestätigung**. Bei WLAN, Internetsperre und Switch-Port lässt sich
  **automatisch zurückschalten** (nach 15 min, 1 h, 2 h oder morgen um 6:00) – praktisch etwa für eine Internetpause.
- Vor Änderungen sichert díktyo die **Konfiguration**, wenn die letzte Sicherung älter als eine Stunde ist.
- **Schutz vor dem Aussperren:** Den Switch-Port, über den díktyo bzw. der Router den Switch erreicht, schaltet díktyo
  nicht ab; Router, Switches und Access Points werden nicht vom Internet gesperrt; die VM, in der díktyo läuft, wird
  nicht heruntergefahren.
- Verlangt die FRITZ!Box eine **Bestätigung** (zweiter Faktor), erscheint der bekannte Dialog (Taste oder Telefon-Code).
  Gelingt das automatische Zurückschalten deshalb nicht, meldet díktyo das unter *Letzte Aktionen* und – falls
  eingerichtet – per Home Assistant.
- Alle Aktionen stehen im Reiter **Aktionen** unter *Letzte Aktionen*; geplantes Zurückschalten lässt sich dort abbrechen.
- Am **Switch** selbst: im Gerätedialog unter *Aktionen* den Port wählen (oder in der Frontplatte auf den Port klicken).
- Am **Proxmox-Host**: Liste seiner VMs und Container zum Starten bzw. Herunterfahren.

**Zeitpläne:** Im Aktionsdialog „Zeitplan anlegen“ wählen – Wochentage und Uhrzeit. Bei Internetsperre, WLAN und
Switch-Port gilt ein Zeitfenster (z. B. Mo–Fr 22:00–06:30 Internet gesperrt): zu Beginn schaltet díktyo, am Ende
zurück. Geschaltet wird nur an diesen Zeitpunkten – gibst du zwischendurch von Hand frei, bleibt das bis zum nächsten
Übergang so. Andere Aktionen (Neustart, PoE, Wake-on-LAN, VM) laufen einmal zur gewählten Uhrzeit. Vor jedem Lauf
prüft díktyo den Aussperr-Schutz erneut; die Internetsperre nutzt immer die aktuelle IP des Geräts. Übersicht,
Pausieren und Löschen im Reiter **Aktionen** unter *Zeitpläne* und im Gerätedialog.

**Quarantäne für neue Geräte:** *Einstellungen → Profil-Einstellungen → Quarantäne für neue Geräte* einschalten (braucht die
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

### Update aus der Oberfläche

Unter *Einstellungen → Updates* (nur Administratoren) zeigt díktyo die installierte und die neueste Version auf
GitHub samt Änderungen; ist eine neue da, erscheint oben in der Kopfzeile **↑ Update**. Der Hintergrunddienst prüft
höchstens alle 12 Stunden (*Nach Updates suchen* prüft sofort).

**Jetzt aktualisieren** (Installation per Proxmox-Skript bzw. `setup.sh`): díktyo legt nur eine Anfrage ab; ein
eigener systemd-Dienst (`diktyo-update.path` → `diktyo-update.service`) sichert dann als root die Datenbank (die letzten
drei Sicherungen bleiben als `/var/lib/diktyo/before-update-*.db`), lädt den Stand von GitHub und führt `setup.sh`
aus – wie `update-proxmox.sh`. Die Oberfläche zeigt Fortschritt und Protokoll (`/var/log/diktyo-update.log`) und lädt
sich neu, sobald die neue Version läuft. Die Web-App selbst führt dabei nichts als root aus; die Quelle (Repository,
Zweig) steht in `/opt/diktyo/update.conf` und lässt sich nur auf dem Container ändern.

Bestehende Installationen bekommen den Update-Dienst mit dem **nächsten Update wie bisher** (`update-proxmox.sh` auf
dem Proxmox-Host) – danach geht es per Knopf. Bei **Docker** zeigt díktyo die Befehle zum Neubauen
(`git pull` und `docker compose up -d --build`); VLAN-Schnittstellen am Container ändert weiterhin `update-proxmox.sh`.

## 9. Ausgabe und Sicherung

### VLAN-Plan (welcher Port in welchem VLAN)

Der Reiter **VLAN-Plan** zeigt je Switch/Router (auch Access Points, Server, Hypervisor, NAS) die Ports als Kacheln: die große Zahl ist das **untagged** VLAN
(Zugangs-VLAN, Farbe des VLANs), farbige Streifen unten sind **tagged** VLANs (Trunk), darunter steht das
angeschlossene Gerät. Die Ansicht **Matrix** zeigt dasselbe als Tabelle Port × VLAN (U/T). Endgeräte mit eigenem Netzwerkport (PC, Laptop …)
stehen eingeklappt darunter – ist ein Gerät eigentlich ein Server oder Hypervisor, im Gerätedialog den Typ ändern.
Ein Klick auf ein VLAN öffnet den VLAN-Dialog; dort ordnest du ihm die **Subnetze** aus IPAM zu (z. B. VLAN 1 = dein
bisheriges Heimnetz). Erst dann prüft der Plan, ob die Adressen der Geräte zum neuen VLAN passen.

**VMs und Container (Proxmox):** Das VLAN einer VM bzw. eines Containers stellst du in Proxmox an der Netzwerkkarte ein
(*Hardware → Netzwerkgerät → VLAN-Tag*, bei LXC *Netzwerk → VLAN-Tag*). díktyo liest den Tag über die Proxmox-Integration
und zeigt die Gäste im VLAN-Plan unter ihrem Host – mit VLAN-Nummer und -Farbe, „ohne Tag“ heißt: im VLAN des Host-Ports.
Der Plan prüft, ob der Switch-Port zum Host alle VLANs seiner Gäste **tagged** führt, und meldet VLANs, die Gäste nutzen,
die es in díktyo aber noch nicht gibt. Damit das klappt, muss die Linux-Bridge in Proxmox *VLAN aware* sein.

**VLAN-Wechsel von VMs und Containern planen:** Im Modus *Plan* auf einen Gast klicken und das künftige VLAN wählen
(auch ein nur geplantes VLAN oder „ohne Tag“). Der Gast zeigt dann den Wechsel (z. B. „ohne → 30“) und ist markiert;
die **Umstellungsliste** führt ihn unter *VMs und Container – in Proxmox umstellen*. Der Plan prüft mit den geplanten
Tags, ob der Switch-Port zum Host die VLANs tagged führt. díktyo ändert nichts in Proxmox: Du stellst das Tag dort um,
und sobald die Proxmox-Integration das neue Tag meldet, verschwindet der Eintrag von selbst. *Aus dem Plan nehmen* setzt
den Gast auf den Ist-Stand zurück. Beim *Plan abschließen* fallen noch nicht umgestellte Gäste aus dem Plan heraus (der
Hinweis nennt ihre Zahl); die PDF-Ausgabe enthält sie in der Umstellungsliste.

**Produktiv** ist der Ist-Stand. Bei Geräten mit passender Integration liest díktyo ihn bei jeder Abfrage (nur
lesend) – dort lässt er sich nicht von Hand ändern. Das Kennzeichen am Gerät nennt die Quelle:

| Quelle | Kennzeichen | Was gelesen wird |
|---|---|---|
| Switch (SNMP) | *vom Switch (SNMP)* | Q-BRIDGE-MIB: untagged/tagged je Port, VLAN-Namen |
| MikroTik (RouterOS-API/REST) | *aus MikroTik* | Bridge-VLAN-Tabelle (nur Bridges mit *vlan-filtering*), PVID der Bridge-Ports, VLAN-Schnittstellen direkt auf einem Port; Namen der VLAN-Schnittstellen. Mit SNMP-Zugang keine VLANs |
| OPNsense | *aus OPNsense* | VLAN-Geräte (*Schnittstellen → Geräte → VLAN*): auf der Eltern-Schnittstelle tagged, die zugewiesene VLAN-Schnittstelle untagged; Recht „Interfaces: VLAN settings“ nötig |
| OpenWrt | *aus OpenWrt* | Bridge-VLAN-Filterung (DSA): `bridge-vlan`-Einträge der Netzwerkkonfiguration, Kennzeichen `t` = tagged, sonst untagged (`*` = PVID); Name aus der Schnittstelle auf `br-lan.<VLAN>` |
| UniFi | *aus UniFi* | je Switch-Port Native-Netz und getaggte Netze aus Port-Profil und Port-Einstellung („Alle erlauben“, „Alle blockieren“, eigene Auswahl); dafür nutzt díktyo die klassische Network-API mit demselben API-Schlüssel – lässt die Konsole das nicht zu, fehlen nur die VLANs |
| Omada | *aus Omada* | Netze je Switch mit Native-, Tagged- und Untagged-Ports (Open API, *networks-detail*) |

Meldet ein Switch seine VLANs selbst per SNMP, hat das Vorrang vor einem Controller. Bei anderen Geräten trägst du den
Ist-Stand selbst ein. VLANs, die ein Gerät meldet, legt díktyo automatisch an (Beschreibung „vom Switch gelesen“ bzw.
„aus … gelesen“); einem vorhandenen VLAN ohne Namen gibt díktyo den Namen vom Gerät.

**Plan** ist für die Umstellung:
1. *Plan* → **Plan starten** (optional mit Stichwort, z. B. „IoT und Gäste trennen“). Der Plan beginnt als Kopie des
   produktiven Stands; der gelb gestreifte Balken zeigt, dass du im Plan arbeitest – am Netz ändert sich nichts.
2. Neue VLANs mit **+ VLAN (geplant)** anlegen (ID, Name, Farbe). Subnetz und Gateway dazu unter *IPAM*, dann prüft
   der Plan auch die Adressen.
3. Ports **anklicken** (mit Umschalt-Klick einen Bereich, *alle wählen* für ein ganzes Gerät), unten in der Leiste das
   **Untagged**-VLAN wählen und **Tagged**-VLANs antippen (+ hinzufügen, − entfernen), *Zuweisen*.
4. Geänderte Ports tragen ein **Δ**. Die **Umstellungsliste** nennt Port für Port, was am Switch umzustellen ist
   (produktiv → Plan). **Hinweise** warnen z. B., wenn die statische Adresse eines Geräts nicht ins Subnetz seines
   neuen VLANs passt oder ein Uplink zu einem anderen Switch ein dort genutztes VLAN nicht weiterführt.
5. Umstellen am Switch. Bei SNMP-Switches verschwindet ein Port von selbst aus der Liste, sobald der Switch den neuen
   Stand meldet; bei von Hand gepflegten Geräten **✓ umgesetzt** klicken.
6. **Plan abschließen** übernimmt den Rest bei von Hand gepflegten Geräten und macht geplante VLANs zu normalen.
   **Plan verwerfen** löscht den Plan und die nur geplanten VLANs; der produktive Stand bleibt.

díktyo schreibt nichts auf die Switches. Tipp: zuerst die Uplinks (Trunks) mit den neuen VLANs tagged versehen, dann
die Zugangs-Ports umstellen – und den Port, über den du den Switch verwaltest, zuletzt. Im PDF (*Ausgabe*, Abschnitt
*VLANs*) stehen die VLANs je Port und die geplante Umstellung.

### Verkabelung (Kabel und Patchpanels)

Der Reiter **Verkabelung** hält fest, welcher Switch-Port über welches Patchfeld und welche Netzwerkdose zu welchem
Gerät führt – mit den Nummern auf den Kabeln.

1. **+ Patchfeld** bzw. **+ Dose** anlegen: Name (z. B. „PP1 Keller“, „Dose Wohnzimmer 2“), Anzahl Ports, Standort.
   Patchfelder und Dosen sind keine Geräte – sie erscheinen nicht in der Geräteliste, Topologie oder Überwachung.
2. **Kabelweg** eintragen – über **+ Kabelweg** oder einen Klick auf einen freien Port im Patchfeld bzw. in der Dose:
   Switch-Port → *Patchkabel-Nr.* → Patchfeld-Port → *Verlegekabel-Nr.* → Dose → *Anschlusskabel-Nr.* → Gerät. Jeder
   Teil ist optional (z. B. Switch direkt auf eine Dose oder Patchfeld direkt auf ein Gerät im Rack). Bei der
   Port-Auswahl steht, was laut Netz am Port hängt; hängt dort genau ein Gerät, wird es vorgeschlagen. Jeder Port kann
   nur in einem Kabelweg vorkommen.
3. **Abgleich:** Sind Switch-Port und Gerät eingetragen, vergleicht díktyo mit der erkannten Verbindung (Integrationen,
   Scan oder von Hand): **✓** passt, **⚠** laut Netz hängt dort etwas anderes (das Gerät wird genannt), **–** nicht
   prüfbar. Belegte Ports im Patchfeld sind grün (passt), gelb (Abweichung) oder cyan (nicht prüfbar).

Im **Gerätedialog** stehen die Kabelwege des Geräts (beim Switch alle seine Ports). Im PDF (*Ausgabe*) gibt es den
Abschnitt *Verkabelung* mit allen Kabelwegen und Patchfeldern. Die Sicherung enthält alles.

**Kabel-Etiketten:** Sobald Kabelnummern eingetragen sind, erscheint oben der Knopf *Kabel-Etiketten* (dasselbe gibt es
unter *Ausgabe*). Jedes Kabel mit Nummer wird ein Aufkleber: die Nummer groß, darunter die beiden Enden – z. B.
„Switch · Port 5“ und „PP1 Keller · 12“. Ein Kabel reicht dabei bis zur nächsten eingetragenen Station; fehlt das
Patchfeld, geht das Patchkabel also vom Switch direkt zur Dose. Mit *je Kabelende ein Etikett* entstehen zwei
Aufkleber je Kabel: Oben steht das Ende, an das der Aufkleber kommt, mit dem Pfeil die Gegenstelle. Der Farbstreifen
links zeigt die Art: Patchkabel türkis, Verlegekabel orange, Anschlusskabel grau. Formate: A4-Bögen 38 × 21,2 mm
(65 Stück, z. B. Avery Zweckform 3666 / L7651), 48,5 × 25,4 mm (40) und 70 × 37 mm (24), Etikettendrucker 62 × 29 mm
und 54 × 25 mm sowie Schriftband 12 mm (Brother P-touch, 60 mm je Etikett). Lange Nummern werden kleiner gesetzt,
nie gekürzt. *Erstes freies Etikett* und *Schnittlinien* wie bei den QR-Etiketten.

- *Ausgabe:* PDF (Topologie-Grafik, Geräteliste, IP-Plan, VLANs, Portbelegung, WLAN-Übersicht, Notizen – wählbar) und CSV.
- **Netzplan** (*Ausgabe → Netzplan* oder *Topologie → Exportieren*): die Topologie – so angeordnet wie in der
  Oberfläche, auch mit von Hand verschobenen Geräten – als **Poster-PDF**, **SVG**, **PNG** oder **draw.io**-Datei.
  Das Poster-PDF gibt es in A4 bis A0 mit Schriftfeld (Profil, Stand, Anzahl Geräte) und Legende; Hoch- oder
  Querformat wählt díktyo nach der Form des Netzplans. *Auf A4-Blätter kacheln* verteilt das Poster zum Drucken zu
  Hause auf A4-Seiten mit 1 cm Überlappung, Klebemarken und Blattnummer (Zeile/Spalte). *Gruppen aufklappen* zeigt
  jedes WLAN-Gerät und jede VM einzeln. In draw.io (app.diagrams.net oder Desktop) stehen IP, MAC, Typ, Modell und
  Standort als Eigenschaften an jedem Gerät (*Rechtsklick → Daten bearbeiten*); die Linien sind nach Art gestrichelt
  bzw. gepunktet. Beim PDF in Originalgröße drucken (100 %).
- **QR-Etiketten** (*Ausgabe → QR-Etiketten*): Aufkleber für die Geräte. Der QR-Code öffnet mit dem Handy direkt den
  Gerätedialog in díktyo – ist man nicht angemeldet, geht es nach der Anmeldung dorthin. Neben dem Code stehen Name und
  wahlweise IP-Adresse, MAC sowie Standort und Typ. Formate: A4-Bögen 70 × 37 mm (24 Stück, z. B. Avery Zweckform
  3474), 99,1 × 38,1 mm (14, Avery L7163), 48,5 × 25,4 mm (40, Avery Zweckform 3657) sowie Etikettendrucker 62 × 29 mm
  (Brother DK-11209) und 54 × 25 mm (Dymo 11352) mit einer Seite je Etikett. Geräte per Suche oder mit *Alle* /
  *Infrastruktur* / *Keine* wählen; bei angebrochenen Bögen das *erste freie Etikett* angeben, die Plätze davor bleiben
  leer. *Schnittlinien* helfen beim Drucken auf normales Papier. Wichtig ist die **Adresse der Weboberfläche im
  QR-Code**: Sie muss vom Handy aus erreichbar sein (Heimnetz oder VPN); fest einstellen lässt sie sich unter
  *Einstellungen → E-Mail-Versand*. Für ein einzelnes Gerät gibt es im Gerätedialog den Knopf *QR-Etikett* (mit dem
  zuletzt gewählten Format). Drucken in Originalgröße (100 %, nicht „an Seite anpassen“).
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
| Passwort vergessen | Im Container: `diktyo reset-password deine@adresse.de` – fragt das neue Passwort verdeckt ab (Docker: `docker compose exec diktyo python -m app.cli reset-password …`) |
| Schnell-Ping meldet „Ping ist für die Weboberfläche nicht erlaubt“ bzw. Geräte gehen dabei kurz offline | díktyo mit dem Update-Skript aktualisieren (ab 0.21.2 darf die Weboberfläche pingen) |
| Authenticator-App weg, keine Wiederherstellungscodes | Admin: *Einstellungen → Konten → 2FA zurücksetzen*; oder im Container `diktyo reset-2fa deine@adresse.de` |
