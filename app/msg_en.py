"""Englische Fassung der Meldungen des Servers (Fehler, Aktionen, Diagnosen, Feldbezeichnungen).

Schlüssel sind die deutschen Texte aus dem Code; Meldungen mit Werten stehen als Muster mit {} (eingesetzte Teile werden
ihrerseits übersetzt). Genutzt bei Fehlerantworten (Sprache des Browsers) und von der Oberfläche für gespeicherte
Meldungen (z. B. letzter Fehler einer Integration), siehe /api/i18n/messages.
"""
import re

ERR_EN = {
    "Bitte anmelden": "Please sign in", "Nur für Administratoren": "Administrators only",
    "Zu viele Versuche. Bitte einige Minuten warten.": "Too many attempts. Please wait a few minutes.",
    "Fehlender Request-Header": "Missing request header",
    "Die Registrierung ist geschlossen. Bitte einen Administrator um ein Konto bitten.": "Registration is closed. Please ask an administrator for an account.",
    "E-Mail-Adresse oder Passwort ist falsch": "E-mail or password is wrong",
    "Bitte eine gültige E-Mail-Adresse angeben": "Please enter a valid e-mail address",
    "Das Passwort muss mindestens 8 Zeichen haben": "The password must be at least 8 characters long",
    "Für diese E-Mail-Adresse gibt es schon ein Konto": "An account with this e-mail address already exists",
    "Der Link ist ungültig oder abgelaufen. Bitte einen neuen anfordern.": "This link is invalid or has expired. Please request a new one.",
    "Das aktuelle Passwort stimmt nicht": "The current password is wrong",
    "Konto nicht gefunden": "Account not found", "Es muss mindestens ein Administrator bleiben": "At least one administrator must remain",
    "Das eigene Konto kann hier nicht gelöscht werden": "You cannot delete your own account here",
    "Profil nicht gefunden": "Profile not found", "Dafür fehlen dir in diesem Profil die Rechte": "You do not have the rights for this in this profile",
    "Name fehlt": "Name missing", "Unbekannte Rolle": "Unknown role", "Kein Konto mit dieser E-Mail-Adresse": "No account with this e-mail address",
    "Ein Profil braucht mindestens einen Besitzer": "A profile needs at least one owner", "Mitglied nicht gefunden": "Member not found",
    "E-Mail-Versand ist nicht eingerichtet": "Sending e-mail is not set up",
    "Gerät nicht gefunden": "Device not found", "Standort nicht gefunden": "Location not found", "VLAN nicht gefunden": "VLAN not found",
    "Subnetz nicht gefunden": "Subnet not found", "Katalogeintrag nicht gefunden": "Catalog entry not found", "Port nicht gefunden": "Port not found",
    "Standort gehört nicht zu diesem Profil": "Location does not belong to this profile",
    "Gegenstelle gehört nicht zu diesem Profil": "Connected device does not belong to this profile",
    "VLAN gehört nicht zu diesem Profil": "VLAN does not belong to this profile",
    "Ein Gerät kann nicht mit sich selbst verbunden werden": "A device cannot be connected to itself",
    "Diese Verbindung würde einen Ring ergeben": "This connection would create a loop",
    "Ein Standort kann nicht in sich selbst liegen": "A location cannot be inside itself",
    "Ungültiges Netz, Beispiel: 192.168.178.0/24": "Invalid network, example: 192.168.178.0/24",
    "Das Gateway liegt nicht im Netz": "The gateway is not inside the network",
    "Für den DHCP-Bereich Anfang und Ende angeben": "Enter start and end of the DHCP range",
    "Der DHCP-Bereich muss im Netz liegen und mit der kleineren Adresse beginnen": "The DHCP range must be inside the network and start with the lower address",
    "Die VLAN-ID muss zwischen 1 und 4094 liegen": "The VLAN ID must be between 1 and 4094",
    "Hersteller und Modell sind erforderlich": "Manufacturer and model are required",
    "Diesen Katalogeintrag gibt es schon": "This catalog entry already exists",
    "Kein Sicherungsziel eingerichtet": "No backup target configured", "Keine gültige Sicherungsdatei": "Not a valid backup file",
    "Wiederherstellen ist nur in einer leeren Installation möglich": "Restoring is only possible in an empty installation",
    "Die Backup-Passphrase ist falsch": "The backup passphrase is wrong",
    "Die Backup-Passphrase muss mindestens 8 Zeichen haben": "The backup passphrase must be at least 8 characters long",
    "Gescannt werden IPv4-Netze": "Only IPv4 networks are scanned", "Für dieses Profil läuft schon ein Scan": "A scan is already running for this profile",
    "Auftrag nicht gefunden": "Job not found", "Unbekannte Aktion": "Unknown action", "Regel nicht gefunden": "Rule not found",
    "Bezeichnung und mindestens eine Bedingung sind erforderlich": "Label and at least one condition are required",
    "Unbekannter Treiber": "Unknown driver", "Adresse fehlt": "Address missing", "Integration nicht gefunden": "Integration not found",
    "Gerät gehört nicht zu diesem Profil": "Device does not belong to this profile", "Ungültige Angabe": "Invalid value",
    "Keine Antwort (Adresse, Community oder SNMP am Gerät prüfen)": "No answer (check address, community or SNMP on the device)",
    "Die FRITZ!Box verlangt eine Anmeldung. Benutzer und Passwort angeben.": "The FRITZ!Box requires a sign-in. Enter user and password.",
    "MQTT-Anmeldung abgelehnt (Benutzer oder Passwort prüfen)": "MQTT sign-in rejected (check user and password)",
    "Token abgelehnt (Long-Lived Access Token prüfen)": "Token rejected (check the long-lived access token)",
    "Token oder MQTT-Broker angeben": "Enter a token or an MQTT broker",
    "Konfigurations-Backup nicht gefunden": "Configuration backup not found",
    "Ungültige Positionen": "Invalid positions",
    "Unbekannte Gruppierung": "Unknown grouping", "Ungültiger Schwellwert": "Invalid threshold", "Ungültige Farbe": "Invalid colour",
    "Ungültige Mitglieder": "Invalid members", "Gruppe nicht gefunden": "Group not found", "Zu viele Gruppen": "Too many groups",
    "Zeitplan nicht gefunden": "Schedule not found",
    "Für die Quarantäne wird eine FRITZ!Box-Integration mit Benutzer gebraucht": "Quarantine needs a FRITZ!Box integration with a user",
    "Eintrag nicht gefunden": "Entry not found",
    "Uhrzeit im Format HH:MM angeben": "Enter the time as HH:MM",
    "Mindestens einen Wochentag wählen": "Choose at least one weekday",
    "Start und Ende dürfen nicht gleich sein": "Start and end must differ",
    "Diese Aktion ist für das Gerät nicht (mehr) verfügbar – Ansicht neu laden": "This action is not (or no longer) available for the device – reload the view",
    "Ungültige Zeit für das Zurückschalten": "Invalid time for switching back",
    "Kein geplantes Zurückschalten": "No scheduled switch-back",
    "Für Schaltaktionen Benutzer und Passwort der FRITZ!Box angeben (Recht „FRITZ!Box Einstellungen“)": "Enter the FRITZ!Box user and password for actions (permission “FRITZ!Box settings”)",
    "Kein Claude-API-Schlüssel hinterlegt (Einstellungen → KI)": "No Claude API key stored (Settings → AI)",
    "Hersteller und Modell werden für die KI-Suche gebraucht": "Manufacturer and model are needed for the AI lookup",
    "Die KI hat die Anfrage abgelehnt": "The AI declined the request",
    "Claude-API-Schlüssel ungültig": "Claude API key invalid",
    "Der API-Schlüssel darf dieses Modell oder die Websuche nicht nutzen (Websuche in der Console freigeben)": "The API key may not use this model or web search (enable web search in the Console)",
    "Claude API: Anfragelimit erreicht – kurz warten": "Claude API: rate limit reached – wait a moment",
    "Claude API: kein Guthaben auf dem Konto": "Claude API: no credit on the account",
    "Claude API nicht erreichbar (Internetzugang des Containers prüfen)": "Claude API not reachable (check the container's internet access)",
    "Die KI hat keinen Katalogeintrag geliefert – später erneut versuchen": "The AI did not return a catalog entry – try again later",
    "Authenticator-Schlüssel ungültig (Base32 aus der FRITZ!Box, z. B. „WI5M JOGQ …“)": "Authenticator key invalid (Base32 from the FRITZ!Box, e.g. “WI5M JOGQ …”)",
    "Bitte Systeminformationen einfügen": "Please paste system information",
    "Hersteller und Modell nicht erkannt – z. B. die Ausgabe von „dmidecode -t system“ einfügen": "Manufacturer and model not recognised – paste e.g. the output of “dmidecode -t system”",
    "Der Code aus der App hat 6 Ziffern": "The code from the app has 6 digits",
    "FRITZ!Box hat den Code nicht angenommen": "The FRITZ!Box did not accept the code",
    "Export abgelehnt – Code falsch oder abgelaufen? Neuen Code aus der App nehmen.": "Export rejected – wrong or expired code? Use a new code from the app.",
    "Anmeldung an der Weboberfläche der FRITZ!Box abgelehnt (Benutzer/Passwort prüfen)": "Sign-in to the FRITZ!Box web interface rejected (check user/password)",
    "Weboberfläche der FRITZ!Box nicht erreichbar": "FRITZ!Box web interface not reachable",
    "Für diese Integration gibt es keine Diagnose": "There is no diagnosis for this integration",
    "Das Gerät hat keine IPv4-Adresse": "The device has no IPv4 address",
    "nmap ist nicht installiert": "nmap is not installed",
    "Zeitlimit erreicht – „Schnell“ wählen oder später erneut versuchen": "Time limit reached – choose “Quick” or try again later",
    "Die FRITZ!Box verlangt für den Export eine Bestätigung (zweiter Faktor). Automatisch geht das nicht – bitte „Konfiguration sichern“ von Hand auslösen und an der FRITZ!Box bestätigen.": "The FRITZ!Box requires a confirmation (second factor) for the export. This cannot be done automatically – please start “Back up configuration” by hand and confirm on the FRITZ!Box.",
    "Bestätigung an der FRITZ!Box gesperrt (zu viele Versuche) – bis zu 60 Minuten warten": "Confirmation on the FRITZ!Box blocked (too many attempts) – wait up to 60 minutes",
    "Die FRITZ!Box wartet gerade auf eine andere Bestätigung – in zwei Minuten erneut versuchen": "The FRITZ!Box is waiting for another confirmation – try again in two minutes",
    "Diese Integration kennt keinen zweiten Faktor": "This integration has no second factor",
    "API-Schlüssel abgelehnt (in UniFi Network unter Integrationen einen lokalen Schlüssel erstellen, nicht den Site-Manager-Schlüssel)": "API key rejected (create a local key under Integrations in UniFi Network, not the Site Manager key)",
    "Integration API nicht gefunden": "Integration API not found",
    "Unerwartete Antwort (ist das eine UniFi-Konsole mit Network 9.0 oder neuer?)": "Unexpected response (is this a UniFi console with Network 9.0 or newer?)",
    "Nur Text-Konfigurationen lassen sich vergleichen": "Only text configurations can be compared",
    "Diese Integration unterstützt kein Konfigurations-Backup": "This integration does not support configuration backups",
    "Für das Konfigurations-Backup Benutzer und Passwort der FRITZ!Box angeben": "Enter the FRITZ!Box user and password for the configuration backup",
    "Benutzer hat nicht das Recht „FRITZ!Box Einstellungen“": "The user lacks the permission “FRITZ!Box settings”",
    "Router hat keine Einstellungsdatei geliefert": "The router did not provide a settings file",
    "Für das Konfigurations-Backup SSH-Benutzer und -Passwort des Switches angeben": "Enter the switch’s SSH user and password for the configuration backup",
    "SSH-Anmeldung abgelehnt (Benutzer oder Passwort prüfen)": "SSH sign-in rejected (check user and password)",
    "Gerät hat keine Konfiguration geliefert (Befehl prüfen)": "The device did not provide a configuration (check the command)",
    "Bild zu groß (höchstens 8 MB)": "Image too large (8 MB at most)",
    "Bitte ein Bild als PNG, JPEG, WebP oder GIF hochladen": "Please upload an image as PNG, JPEG, WebP or GIF",
    "Dieser Standort ist kein Rack": "This location is not a rack", "Ein Rack hat keinen Grundriss": "A rack has no floor plan",
    "Bitte eine Bezeichnung angeben (z. B. USV, Blende, Ablage)": "Please enter a label (e.g. UPS, blank panel, shelf)",
    "Im Rack ist noch etwas eingebaut – erst ausbauen, dann die Art ändern": "Something is still mounted in the rack – remove it first, then change the kind",
    "Nicht gefunden": "Not found", "Patchfeld nicht gefunden": "Patch panel not found", "Keine Datei": "No file",
    "Unbekannte Art": "Unknown kind", "Kein Grundriss-Bild": "No floor plan image",
    "Nur direkte Unterstandorte lassen sich als Raum einzeichnen": "Only direct sub-locations can be drawn as a room",
}
# Meldungen mit Werten: Präfix übersetzen, Rest übernehmen
ERR_EN_PREFIX = {"Ungültige MAC-Adresse: ": "Invalid MAC address: ", "Ungültige IP-Adresse: ": "Invalid IP address: ",
                 "Ungültiges Netz: ": "Invalid network: ", "Ungültige Adresse: ": "Invalid address: ",
                 "Herstellerliste konnte nicht geladen werden: ": "Vendor list could not be loaded: ", "Ungültiger Ausdruck: ": "Invalid expression: ",
                 "FRITZ!Box nicht erreichbar: ": "FRITZ!Box not reachable: ", "Home Assistant nicht erreichbar: ": "Home Assistant not reachable: ",
                 "Proxmox nicht erreichbar: ": "Proxmox not reachable: ",
                 "Versand fehlgeschlagen: ": "Sending failed: "}
ERR_EN_RE = [(r"^Port (.+) ist schon mit (.+) belegt$", r"Port \1 is already connected to \2"),
             (r"^Das Subnetz (.+) gibt es schon$", r"The subnet \1 already exists"),
             (r"^MQTT-Broker „(.+)“ unbekannt: .*$", r"MQTT broker “\1” unknown: this name only exists inside Home Assistant. Enter the IP address of Home Assistant (port 1883)."),
             (r"^MQTT-Broker (.+) nicht erreichbar: (.*)$", r"MQTT broker \1 not reachable: \2"),
             (r"^VLAN (\d+) gibt es schon$", r"VLAN \1 already exists"),
             (r"^Netz (.+) ist zu groß zum Scannen \(höchstens /20\)$", r"Network \1 is too large to scan (at most /20)")]



# ------------------------------------------------------------ neu (0.33.1): alle übrigen Meldungen, Aktionen, Felder
ERR_EN.update({
    # Wörter, die in Meldungen eingesetzt werden
    "eingeschaltet": "switched on", "ausgeschaltet": "switched off", "abgeschaltet": "disabled", "einschalten": "switch on",
    "ausschalten": "switch off", "abschalten": "disable", "gesperrt": "blocked", "freigegeben": "allowed", "gestartet": "started",
    "gestoppt": "stopped", "neu gestartet": "restarted", "Gerät": "Device", "Ausgang": "Output", "neu": "new", "Patchfeld": "Patch panel",
    "Dose": "Outlet", "Dieser Switch-Port": "This switch port", "Dieser Patchfeld-Port": "This patch panel port", "Dieser Dosen-Anschluss": "This outlet port",
    "2,4 GHz": "2.4 GHz", "Hintergrunddienst wurde neu gestartet": "background service was restarted", "Port": "Port", "Switch-Port": "Switch port",
    # Schaltaktionen: Bezeichnungen und Hinweise
    "FRITZ!Box neu starten": "Restart FRITZ!Box", "MikroTik neu starten": "Restart MikroTik", "OPNsense neu starten": "Restart OPNsense",
    "Internetzugang sperren": "Block internet access", "Internetzugang freigeben": "Allow internet access",
    "Internetzugang sperren (OPNsense)": "Block internet access (OPNsense)", "Internetzugang freigeben (OPNsense)": "Allow internet access (OPNsense)",
    "Aufwecken (Wake-on-LAN)": "Wake up (Wake-on-LAN)", "Starten": "Start", "Stoppen": "Stop", "Herunterfahren": "Shut down", "Neu starten": "Restart",
    "Internet, WLAN und Telefonie sind 2–3 Minuten weg.": "Internet, Wi-Fi and telephony are gone for 2–3 minutes.",
    "Alle Verbindungen über dieses Gerät sind etwa eine Minute weg.": "All connections through this device are gone for about a minute.",
    "Alle Verbindungen über dieses Gerät sind ein bis zwei Minuten weg.": "All connections through this device are gone for one to two minutes.",
    "Alle Verbindungen über dieses Gerät sind ein bis zwei Minuten weg. díktyo ist währenddessen nicht erreichbar.":
        "All connections through this device are gone for one to two minutes. díktyo is unreachable meanwhile.",
    "Internet und alle Netze über die Firewall sind einige Minuten weg.": "Internet and all networks through the firewall are gone for a few minutes.",
    "Geräte in diesem WLAN verlieren die Verbindung.": "Devices on this Wi-Fi lose their connection.",
    "Strom am Port 5 Sekunden aus und wieder an (startet z. B. Access Point oder Kamera neu).": "Power on the port off for 5 seconds and back on (restarts e.g. an access point or camera).",
    "Strom am Port kurz aus und wieder an (startet z. B. Access Point oder Kamera neu).": "Power on the port briefly off and back on (restarts e.g. an access point or camera).",
    "Das angeschlossene Gerät (Access Point, Kamera …) verliert den Strom.": "The connected device (access point, camera …) loses power.",
    "Alle Geräte bekommen Werbung und Tracker wieder ungefiltert – mit „Zurückschalten nach“ nur für eine Weile.": "All devices get ads and trackers unfiltered again – with “Switch back after” only for a while.",
    "Das Gerät lädt die Firmware selbst und startet neu; Ausgänge können dabei kurz schalten.": "The device downloads the firmware itself and restarts; outputs may switch briefly.",
    "Alles, was an diesem Ausgang hängt, verliert den Strom – Vorsicht bei Server, Router oder Switch.": "Everything on this output loses power – careful with servers, routers or switches.",
    "MikroTik startet neu (dauert etwa eine Minute)": "MikroTik is restarting (takes about a minute)", "FRITZ!Box startet neu (dauert etwa 2–3 Minuten)": "FRITZ!Box is restarting (takes about 2–3 minutes)",
    "OPNsense startet neu (dauert einige Minuten)": "OPNsense is restarting (takes a few minutes)",
    # MikroTik
    "Am Port antwortet kein HTTPS-Dienst – für Port 8728 „RouterOS-API“ wählen, für den Dienst www „REST über HTTP“": "No HTTPS service answers on this port – choose “RouterOS API” for port 8728, “REST over HTTP” for the www service",
    "Anmeldung abgelehnt (Benutzer/Passwort prüfen; Gruppe braucht die Rechte read und rest-api)": "Sign-in rejected (check user/password; the group needs the read and rest-api permissions)",
    "Anmeldung abgelehnt (Benutzer/Passwort prüfen; die Benutzergruppe braucht die Rechte read und api)": "Sign-in rejected (check user/password; the user group needs the read and api permissions)",
    "Keine Berechtigung – die Benutzergruppe braucht für diese Funktion zusätzliche Rechte (z. B. write, reboot, test)": "No permission – the user group needs additional permissions for this function (e.g. write, reboot, test)",
    "TLS-Verbindung fehlgeschlagen – für api-ssl braucht der MikroTik ein Zertifikat (IP → Services → api-ssl → Certificate) oder „RouterOS-API“ ohne TLS wählen": "TLS connection failed – api-ssl needs a certificate on the MikroTik (IP → Services → api-ssl → Certificate), or choose “RouterOS API” without TLS",
    "Unerwartete Antwort – ist das die REST-API von RouterOS 7? Sonst „RouterOS-API“ wählen": "Unexpected response – is this the REST API of RouterOS 7? Otherwise choose “RouterOS API”",
    "Zugang": "Access", "Port (leer = Standard des Zugangs)": "Port (empty = default for the access method)",
    "RouterOS-API (api, Port 8728)": "RouterOS API (api, port 8728)", "RouterOS-API mit TLS (api-ssl, Port 8729)": "RouterOS API with TLS (api-ssl, port 8729)",
    "REST über HTTPS (www-ssl, RouterOS 7)": "REST over HTTPS (www-ssl, RouterOS 7)", "REST über HTTP (www, RouterOS 7.9+)": "REST over HTTP (www, RouterOS 7.9+)",
    # OIDC
    "Anbieter hat kein ID-Token geliefert (Scope „openid“ fehlt?)": "The provider returned no ID token (scope “openid” missing?)",
    "Anbieter hat keinen Code geliefert": "The provider returned no code",
    "Anmeldung abgelaufen oder ungültig – bitte erneut versuchen": "Sign-in expired or invalid – please try again",
    "Anmeldung wurde in einem anderen Browser begonnen – bitte erneut versuchen": "Sign-in was started in another browser – please try again",
    "Anmeldung über OIDC ist nicht eingeschaltet": "Sign-in with OIDC is not enabled",
    "Aussteller (Issuer) bitte mit https:// angeben": "Please enter the issuer with https://", "Aussteller (Issuer) fehlt": "Issuer missing",
    "Das díktyo-Konto mit dieser E-Mail-Adresse ist schon mit einem anderen Anbieter-Konto verknüpft": "The díktyo account with this e-mail address is already linked to another provider account",
    "Der Anbieter liefert keine E-Mail-Adresse (Scope „email“ fehlt?)": "The provider returns no e-mail address (scope “email” missing?)",
    "Der Anbieter meldet die E-Mail-Adresse nicht als bestätigt – das Konto wird nicht automatisch verknüpft. Mit Passwort anmelden und unter Einstellungen → Mein Konto verknüpfen.":
        "The provider does not report the e-mail address as verified – the account is not linked automatically. Sign in with your password and link it under Settings → My account.",
    "Dieses Konto beim Anbieter ist schon mit einem anderen díktyo-Konto verknüpft": "This provider account is already linked to another díktyo account",
    "Für dieses Konto gibt es in díktyo noch keinen Zugang – ein Administrator muss es anlegen oder „Konten automatisch anlegen“ einschalten":
        "There is no díktyo access for this account yet – an administrator has to create it or enable “Create accounts automatically”",
    "ID-Token ist abgelaufen – Uhrzeit von díktyo und Anbieter prüfen": "ID token expired – check the clocks of díktyo and the provider",
    "ID-Token ist mit dem Client-Secret signiert, aber keins eingetragen": "The ID token is signed with the client secret, but none is set",
    "ID-Token ist nicht für díktyo ausgestellt": "The ID token was not issued for díktyo", "ID-Token ist ungültig": "The ID token is invalid",
    "ID-Token liegt in der Zukunft – Uhrzeit von díktyo und Anbieter prüfen": "The ID token lies in the future – check the clocks of díktyo and the provider",
    "ID-Token ohne Benutzerkennung (sub)": "ID token without user identifier (sub)", "ID-Token passt nicht zu dieser Anmeldung (nonce)": "The ID token does not match this sign-in (nonce)",
    "ID-Token stammt von einem anderen Aussteller": "The ID token comes from another issuer",
    "Kein passender Schlüssel des Anbieters für das ID-Token": "No matching provider key for the ID token",
    "Signatur des ID-Tokens stimmt nicht": "The ID token signature does not match", "Verknüpfen nur in der Sitzung, in der es begonnen wurde": "Linking only works in the session where it was started",
    "Zum Einschalten Aussteller (Issuer) und Client-ID angeben": "To enable, enter issuer and client ID", "Zum Verknüpfen zuerst anmelden": "Sign in first to link",
    "Token fehlt oder ist ungültig": "Token missing or invalid",
    # Verkabelung, VLAN-Plan, Übersicht, Wachliste, Etiketten, Netzplan
    "Art lässt sich nur ändern, solange keine Kabelwege daran hängen": "The kind can only be changed while no cable runs use it",
    "Bitte den Switch-Port wählen": "Please choose the switch port", "Kabelweg nicht gefunden": "Cable run not found",
    "Mindestens Switch-Port, Patchfeld, Dose oder Gerät angeben": "Enter at least a switch port, patch panel, outlet or device",
    "Patchfeld/Dose nicht gefunden": "Patch panel/outlet not found", "Ungültige Zahl": "Invalid number",
    "Es gibt noch keinen Plan": "There is no plan yet", "Es gibt schon einen Plan": "A plan already exists",
    "Geplante VLANs gibt es nur im Plan": "Planned VLANs only exist in the plan", "Keine Ports gewählt": "No ports selected",
    "Dieser Switch meldet seine VLANs selbst (SNMP) – der produktive Stand lässt sich hier nicht ändern": "This switch reports its VLANs itself (SNMP) – the productive state cannot be changed here",
    "Dieser Switch meldet seine VLANs selbst – der Port gilt als umgesetzt, sobald der Switch den neuen Stand meldet": "This switch reports its VLANs itself – the port counts as done as soon as the switch reports the new state",
    "Unbekannter Modus": "Unknown mode", "Dieses Diagramm ist schon angeheftet": "This chart is already pinned",
    "Messreihe gibt es in diesem Profil nicht (mehr)": "This data series does not exist in this profile (any more)", "Ungültiges Diagramm": "Invalid chart",
    "Ungültiges Layout": "Invalid layout", "Keine Geräte ausgewählt": "No devices selected", "Keine Kabel ausgewählt": "No cables selected", "Unbekanntes Etikettenformat": "Unknown label format",
    "Adresse der Weboberfläche bitte mit http:// oder https:// angeben": "Please enter the web interface address with http:// or https://",
    "Unbekanntes Papierformat": "Unknown paper size", "Noch keine Geräte in der Topologie.": "No devices in the topology yet.",
    "Unbekanntes Format": "Unknown format", "Token fehlt oder ist ungültig ": "Token missing or invalid",
    # Zweiter Faktor, Konten, Sicherung, E-Mail, ntfy
    "Das Passwort stimmt nicht": "The password is wrong", "Der Code passt nicht – Uhrzeit von Handy und Server prüfen und den aktuellen Code eingeben": "The code does not match – check the clocks of phone and server and enter the current code",
    "Der zweite Faktor ist nicht eingeschaltet": "Two-factor authentication is not enabled", "Der zweite Faktor ist schon eingeschaltet": "Two-factor authentication is already enabled",
    "Anmeldung abgelaufen – bitte noch einmal mit Passwort anmelden": "Sign-in expired – please sign in with your password again",
    "Bitte die Einrichtung neu starten": "Please restart the setup", "Die aktuelle Sitzung bitte über „Abmelden“ beenden": "Please end the current session with “Sign out”",
    "Datei lässt sich nicht entschlüsseln (secret.key geändert?)": "The file cannot be decrypted (secret.key changed?)",
    "Gespeichertes Geheimnis lässt sich nicht entschlüsseln (secret.key geändert?)": "A stored secret cannot be decrypted (secret.key changed?)",
    "Kein gültiges Token – die ganze Zeile {\"access_token\": …} aus „rclone authorize“ einfügen": "No valid token – paste the whole line {\"access_token\": …} from “rclone authorize”",
    "Name nur aus Buchstaben, Ziffern, - und _": "Name only from letters, digits, - and _",
    "rclone ist nicht installiert": "rclone is not installed", "rclone ist nicht installiert (apt install rclone, danach 'rclone config')": "rclone is not installed (apt install rclone, then 'rclone config')",
    "E-Mail-Versand ist nicht eingerichtet (Einstellungen → E-Mail-Versand)": "Sending e-mail is not set up (Settings → E-mail delivery)",
    "Keine Empfänger": "No recipients", "ntfy-Server bitte mit http:// oder https:// angeben": "Please enter the ntfy server with http:// or https://",
    "ntfy-Thema fehlt": "ntfy topic missing", "Passwort fehlt": "Password missing", "Ungültiger Port": "Invalid port",
    # SNMP, SSH
    "Für SNMPv3 einen Benutzer angeben": "Enter a user for SNMPv3", "Antwort ist verschlüsselt, aber kein Privacy-Passwort angegeben": "The answer is encrypted, but no privacy password is set",
    "Gerät hat keine Engine-ID gemeldet": "The device reported no engine ID", "Unterstützt wird die Verschlüsselung AES (AES-128)": "Supported encryption is AES (AES-128)",
    "Verschlüsselung setzt Authentifizierung voraus": "Encryption requires authentication",
    "Keine Antwort (Adresse, Benutzer oder SNMP am Gerät prüfen)": "No answer (check address, user or SNMP on the device)",
    "Bei v2c normal, wenn v3 am Switch aus ist – weiter mit der eigentlichen Abfrage.": "Normal with v2c if v3 is off on the switch – continuing with the actual query.",
    "Herstellerliste unvollständig": "Vendor list incomplete", "Gerät erreichbar": "Device reachable", "Gerät nicht erreichbar": "Device not reachable",
    "SNMP-Dienst antwortet nicht": "SNMP service does not answer", "SNMP-Dienst antwortet": "SNMP service answers", "SNMPv3-Probe ohne Antwort": "SNMPv3 probe without answer",
    "Keine Antwort auf SNMPv2c": "No answer to SNMPv2c", "Netzweg: über einen Router": "Network path: through a router", "Netzweg: direkt im selben Netz": "Network path: directly in the same network",
    "Abfrage mit Zugangsdaten erfolgreich": "Query with credentials succeeded", "Abfrage mit Zugangsdaten fehlgeschlagen": "Query with credentials failed",
    "Weder Ping noch Weboberfläche/SSH antworten – Adresse und Netzweg prüfen.": "Neither ping nor web interface/SSH answer – check address and network path.",
    "Für das Konfigurations-Backup SSH-Benutzer und -Passwort des Switches angeben – oder unter „SSH-Anmeldung“ einen Schlüssel wählen":
        "Enter the switch’s SSH user and password for the configuration backup – or choose a key under “SSH sign-in”",
    "Für das Konfigurations-Backup den SSH-Benutzer des Switches angeben": "Enter the switch’s SSH user for the configuration backup",
    "Das ist ein öffentlicher Schlüssel (.pub) – hier gehört der private Schlüssel hin, der öffentliche kommt auf das Gerät": "This is a public key (.pub) – the private key belongs here, the public one goes onto the device",
    "Der private Schlüssel ist mit einer Passphrase geschützt – Passphrase angeben": "The private key is protected by a passphrase – enter the passphrase",
    "Kein privater Schlüssel angegeben": "No private key given", "paramiko ist nicht installiert": "paramiko is not installed",
    # FRITZ!Box, ASUS, Home Assistant, Proxmox, Controller, OPNsense, Docker, Shelly, DNS
    "Benutzer hat nicht das Recht „FRITZ!Box Einstellungen“ bzw. „Zugang aus dem Internet“": "The user lacks the permission “FRITZ!Box settings” or “Access from the internet”",
    "Die FRITZ!Box verlangt eine Bestätigung (zweiter Faktor)": "The FRITZ!Box requires a confirmation (second factor)",
    "Die FRITZ!Box verlangt für den Export eine Bestätigung (zweiter Faktor). Automatisch geht das nur mit hinterlegtem Authenticator-Schlüssel – sonst „Konfiguration sichern“ von Hand auslösen.":
        "The FRITZ!Box requires a confirmation (second factor) for the export. This only works automatically with a stored authenticator key – otherwise start “Back up configuration” manually.",
    "FRITZ!Box hat keine Konfigurationsdatei geliefert": "The FRITZ!Box did not provide a configuration file", "fritzconnection ist nicht installiert": "fritzconnection is not installed",
    "Router liefert keine Daten (Sitzung abgelaufen oder Firmware ohne appGet)": "The router returns no data (session expired or firmware without appGet)",
    "Unerwartete Antwort beim Anmelden (ist das ein ASUS-Router?)": "Unexpected response when signing in (is this an ASUS router?)",
    "Unerwartete Antwort von Home Assistant": "Unexpected response from Home Assistant", "paho-mqtt ist nicht installiert": "paho-mqtt is not installed",
    "Token abgelehnt (Token-ID oder Secret falsch)": "Token rejected (token ID or secret wrong)", "Token-ID (benutzer@realm!name) und Token-Secret angeben": "Enter token ID (user@realm!name) and token secret",
    "Token darf VMs nicht schalten. Auf dem Proxmox-Knoten: pveum role add DiktyoPower -privs VM.PowerMgmt && pveum acl modify / --tokens 'diktyo@pve!diktyo' --roles DiktyoPower":
        "The token may not control VMs. On the Proxmox node: pveum role add DiktyoPower -privs VM.PowerMgmt && pveum acl modify / --tokens 'diktyo@pve!diktyo' --roles DiktyoPower",
    "Gerät beim Controller nicht gefunden – Integration einmal abfragen": "Device not found at the controller – poll the integration once",
    "API-Schlüssel hat keine Berechtigung für Aktionen (Schlüssel mit Schreibrecht nötig)": "The API key has no permission for actions (a key with write access is needed)",
    "API-Schlüssel oder Secret falsch (System → Zugang → Benutzer → API-Schlüssel)": "API key or secret wrong (System → Access → Users → API keys)",
    "Für die Internetsperre in der Integration einen Firewall-Alias eintragen (siehe Anleitung)": "Enter a firewall alias in the integration for blocking internet access (see guide)",
    "Keine Berechtigung für das Konfigurations-Backup (Recht „Diagnostics: Configuration History“ bzw. „Backup & Restore“)": "No permission for the configuration backup (privilege “Diagnostics: Configuration History” or “Backup & Restore”)",
    "Schnittstellen nicht lesbar (Recht „Status: Interfaces“ nötig, OPNsense 23.7 oder neuer)": "Interfaces not readable (privilege “Status: Interfaces” needed, OPNsense 23.7 or newer)",
    "Unerwartete Antwort – ist das die OPNsense-API?": "Unexpected response – is this the OPNsense API?",
    "Unerwartete Antwort – ist das die Docker-Engine-API?": "Unexpected response – is this the Docker Engine API?",
    "Socket-Proxy erlaubt das nicht – dort POST=1 sowie ALLOW_START/ALLOW_STOP/ALLOW_RESTARTS=1 setzen": "The socket proxy does not allow this – set POST=1 and ALLOW_START/ALLOW_STOP/ALLOW_RESTARTS=1 there",
    "Keine Adressen – IPs eintragen oder „auto“ (dann zuerst einen Netzscan, damit díktyo Shelly/Tasmota kennt)": "No addresses – enter IPs or “auto” (then run a network scan first so díktyo knows Shelly/Tasmota)",
    "Pi-hole: Anmeldung abgelehnt – App-Passwort (Einstellungen → Web-Oberfläche/API) prüfen": "Pi-hole: sign-in rejected – check the app password (Settings → Web interface/API)",
    "Keine Antwort von speed.cloudflare.com": "No answer from speed.cloudflare.com", "iperf3 hat nicht rechtzeitig geantwortet": "iperf3 did not answer in time",
    "iperf3 ist auf dem díktyo-Rechner nicht installiert (apt install iperf3)": "iperf3 is not installed on the díktyo machine (apt install iperf3)",
    # Felder der Integrationen
    "Adresse": "Address", "Adresse des Docker-Hosts bzw. Socket-Proxys": "Address of the Docker host or socket proxy", "Adresse von Home Assistant": "Address of Home Assistant",
    "Anmeldung": "Sign-in", "Auth-Passwort": "Auth password", "Benutzer": "User", "Benutzer (falls Anmeldung eingeschaltet)": "User (if sign-in is enabled)",
    "Benutzer (nur AdGuard Home)": "User (AdGuard Home only)", "Benutzer (optional)": "User (optional)", "Container anlegen": "Create containers",
    "Konfiguration sichern": "Back up configuration", "MQTT-Benutzer": "MQTT user", "MQTT-Broker (IP-Adresse von Home Assistant)": "MQTT broker (IP address of Home Assistant)",
    "MQTT-Passwort": "MQTT password", "Passwort": "Password", "Passwort (Pi-hole: App-Passwort bzw. Web-Passwort)": "Password (Pi-hole: app password or web password)",
    "Passwort (falls Anmeldung eingeschaltet)": "Password (if sign-in is enabled)", "Passwort (optional)": "Password (optional)", "Privacy-Passwort": "Privacy password",
    "SSH-Benutzer": "SSH user", "SSH-Passwort": "SSH password", "API-Schlüssel": "API key", "API-Schlüssel (Key)": "API key (key)",
    "Alias für Internetsperre (optional)": "Alias for internet blocking (optional)", "Authenticator-Schlüssel (optional, für automatische Sicherungen)": "Authenticator key (optional, for automatic backups)",
    "Befehl für die Konfiguration": "Command for the configuration", "Bereiche als Standorte übernehmen": "Use areas as locations",
    "Long-Lived Access Token (für Namen und Bereiche)": "Long-lived access token (for names and areas)", "Namen aus HA übernehmen": "Use names from HA",
    "Passphrase des Schlüssels (falls vergeben)": "Key passphrase (if set)", "Passwort für die Konfigurationsdatei (sonst das Anmeldepasswort)": "Password for the configuration file (otherwise the sign-in password)",
    "Privater Schlüssel (Inhalt der Datei, z. B. id_rsa)": "Private key (file content, e.g. id_rsa)", "SSH-Anmeldung (für Konfigurations-Backup)": "SSH sign-in (for configuration backup)",
    "Verschlüsselung (Privacy)": "Encryption (privacy)", "Zertifikat prüfen": "Verify certificate", "Öffentlicher Schlüssel von díktyo (auf das Gerät laden)": "díktyo’s public key (upload to the device)",
    "HTTP (Socket-Proxy im eigenen Netz)": "HTTP (socket proxy in your own network)", "Shelly Gen2+: admin": "Shelly Gen2+: admin",
    "z. B. diktyo_block": "e.g. diktyo_block", "Versionsangabe auf GitHub nicht gefunden": "Version not found on GitHub",
    "Diese Installation lässt sich nicht aus der Oberfläche aktualisieren": "This installation cannot be updated from the web interface",
    "Es läuft bereits ein Update": "An update is already running", "Update angefordert": "Update requested",
    "Der Update-Dienst hat die Anfrage nicht übernommen (diktyo-update.path aktiv?)": "The update service did not pick up the request (is diktyo-update.path active?)",
    "Sichere die Datenbank": "Backing up the database", "Lade den neuen Stand von GitHub": "Downloading the new version from GitHub",
    "Datenbank-Sicherung fehlgeschlagen": "Database backup failed", "Download von GitHub fehlgeschlagen": "Download from GitHub failed",
    "Archiv unvollständig": "Archive incomplete", "Unerwarteter Fehler – Details im Protokoll des Dienstes": "Unexpected error – details in the service log",
    "Unerwarteter Fehler beim Konfigurations-Backup – Details im Protokoll des Dienstes": "Unexpected error during the configuration backup – details in the service log", "Installation fehlgeschlagen - Protokoll ansehen": "Installation failed – see the log", "SNMP (v2c oder v3, nur lesen)": "SNMP (v2c or v3, read only)", "SNMP-Benutzer": "SNMP user",
    "SNMP-Version": "SNMP version", "v2c (Community)": "v2c (community)", "v3 (Benutzer)": "v3 (user)", "Authentifizierung": "Authentication", "keine": "none",
    "Mit SNMP kann díktyo bei MikroTik nur lesen – für Aktionen den Zugang „RouterOS-API“ wählen": "With SNMP díktyo can only read from the MikroTik – choose the “RouterOS API” access for actions", "z. B. 192.168.50.20": "e.g. 192.168.50.20", "z. B. 192.168.1.53": "e.g. 192.168.1.53",
})

# ------------------------------------------------------------ neu (0.38): SNMP-Profile, devolo Powerline
ERR_EN.update({
    "Hersteller-Profil": "Vendor profile", "automatisch (nach Hersteller)": "automatic (by vendor)", "Generisch": "Generic",
    "Hinweis zum Hersteller": "Vendor hint",
    "am Switch einer Community bzw. einem SNMPv3-Benutzer Schreibrechten (read-write) geben.": "give a community or SNMPv3 user write access (read-write) on the switch.",
    "Netgear: im Web-Menü unter System → SNMP (M-Serie: System → Management → SNMP) eine Community bzw. einen SNMPv3-Benutzer anlegen und díktyos Adresse als erlaubten Client eintragen. Die Plus-Switches (GS105E, GS108E, GS305E, GS308E …) haben kein SNMP – sie lassen sich nur von Hand dokumentieren.":
        "Netgear: in the web menu under System → SNMP (M series: System → Management → SNMP) create a community or SNMPv3 user and add díktyo’s address as an allowed client. The Plus switches (GS105E, GS108E, GS305E, GS308E …) have no SNMP – document them by hand.",
    "Netgear: unter System → SNMP → Community Configuration eine Community mit Zugriff „Read-Write“ anlegen.": "Netgear: create a community with access “Read-Write” under System → SNMP → Community Configuration.",
    "Zyxel: unter Management → Access Control → Service Access SNMP erlauben und díktyos Adresse unter Remote Management/Trusted Hosts eintragen, dann Save.":
        "Zyxel: allow SNMP under Management → Access Control → Service Access and add díktyo’s address under Remote Management/Trusted Hosts, then Save.",
    "Zyxel: unter Management → Access Control → SNMP den Benutzer einer Gruppe mit Schreibrechten (z. B. „admin“) zuordnen bzw. eine Community mit read-write anlegen, dann Save.":
        "Zyxel: under Management → Access Control → SNMP assign the user to a group with write access (e.g. “admin”) or create a read-write community, then Save.",
    "TP-Link: unter Maintenance → SNMP → Global Config SNMP einschalten und eine Community bzw. einen Benutzer anlegen.": "TP-Link: switch on SNMP under Maintenance → SNMP → Global Config and create a community or user.",
    "TP-Link: der Community unter SNMP → Community Config die Zugriffsart „read-write“ geben.": "TP-Link: give the community access type “read-write” under SNMP → Community Config.",
    "Adresse eines devolo-Adapters": "Address of a devolo adapter", "z. B. 192.168.178.40": "e.g. 192.168.178.40",
    "Gerätepasswort (leer lassen, wenn keins gesetzt ist)": "Device password (leave empty if none is set)",
    "Nach Firmware-Updates fragen": "Check for firmware updates", "einmal am Tag": "once a day",
    "Protobuf: Nachricht abgeschnitten": "Protobuf: message truncated", "DNS-Name zu tief verschachtelt": "DNS name nested too deeply",
})

# Meldungen mit Werten: {} steht für einen eingesetzten Teil (der seinerseits übersetzt wird)
PATTERNS = [
    ("Adapter {} lehnt die Anmeldung ab – Gerätepasswort prüfen (in der devolo Home Network App gesetzt)", "Adapter {} rejects the sign-in – check the device password (set in the devolo Home Network app)"),
    ("Adapter {} meldet HTTP {} für {}", "Adapter {} returns HTTP {} for {}"), ("Adapter {} meldet kein Powerline-Netz", "Adapter {} reports no powerline network"),
    ("Adapter {} nicht erreichbar: {}", "Adapter {} not reachable: {}"), ("mDNS-Anfrage an {} nicht möglich: {}", "mDNS query to {} not possible: {}"),
    ("Protobuf: Feldtyp {} nicht unterstützt", "Protobuf: field type {} not supported"),
    ("Unter {} antwortet kein devolo-Adapter mit Geräte-API (mDNS-Dienst _dvl-plcnetapi). Ältere dLAN-Adapter, die nur das dLAN Cockpit kennen, lassen sich nicht abfragen.",
     "No devolo adapter with device API answers at {} (mDNS service _dvl-plcnetapi). Older dLAN adapters that only know dLAN Cockpit cannot be queried."),

    ("Anbieter lehnt den Code ab (HTTP {}): {}", "The provider rejects the code (HTTP {}): {}"), ("Anbieter meldet HTTP {} für {}", "The provider returns HTTP {} for {}"),
    ("Anbieter nicht erreichbar: {}", "Provider not reachable: {}"), ("Anbieter: {}", "Provider: {}"), ("Discovery-Dokument ohne „{}“", "Discovery document without “{}”"),
    ("Keine gültige Antwort von {}", "No valid response from {}"), ("Signaturverfahren {} wird nicht unterstützt", "Signature algorithm {} is not supported"),
    ("Für díktyo ist die Gruppe „{}“ beim Anbieter nötig", "díktyo requires the group “{}” at the provider"),
    ("Anmeldung abgelehnt: {} (Client-ID, Client-Secret und Omada-ID prüfen)", "Sign-in rejected: {} (check client ID, client secret and Omada ID)"),
    ("Anmeldung an der FRITZ!Box für {} s gesperrt – kurz warten", "Sign-in to the FRITZ!Box blocked for {} s – wait a moment"),
    ("Claude API lehnt die Anfrage ab: {}", "Claude API rejects the request: {}"), ("Claude API meldet Fehler {}: {}", "Claude API reports error {}: {}"),
    ("Claude API meldet Fehler {}", "Claude API reports error {}"), ("Container „{}“ war schon {}", "Container “{}” was already {}"), ("Container „{}“ {}", "Container “{}” {}"),
    ("Diese FRITZ!Box kennt die Funktion nicht ({})", "This FRITZ!Box does not know the function ({})"), ("Diese RouterOS-Version kennt „{}“ nicht", "This RouterOS version does not know “{}”"),
    ("Docker meldet Fehler {} bei {}", "Docker reports error {} for {}"), ("Docker meldet Fehler {}: {}", "Docker reports error {}: {}"),
    ("Docker-API nicht erreichbar ({}) – Socket-Proxy gestartet und Port freigegeben?", "Docker API not reachable ({}) – socket proxy started and port open?"),
    ("Docker-API nicht erreichbar: {}", "Docker API not reachable: {}"),
    ("Ein Switch antwortet bei v2c auf eine falsche Community gar nicht – Community prüfen. Sonst wie bei v3: SNMP unter Service Access erlauben und {} als Trusted Host eintragen.",
     "With v2c a switch does not answer a wrong community at all – check the community. Otherwise as with v3: allow SNMP under Service Access and add {} as trusted host."),
    ("FRITZ!Box meldet Fehler {}{}", "FRITZ!Box reports error {}{}"), ("Gerät hat keine Konfiguration geliefert (Befehl prüfen): {}", "The device did not provide a configuration (check the command): {}"),
    ("Host-Schlüssel des Geräts hat sich geändert ({}); Backup aus Sicherheitsgründen abgebrochen. Wurde das Gerät ausgetauscht, die Integration einmal neu speichern.",
     "The device’s host key has changed ({}); backup aborted for security reasons. If the device was replaced, save the integration once again."),
    ("Höchstens {} Geräte auf der Wachliste", "At most {} devices on the watchlist"), ("Höchstens {} angeheftete Diagramme", "At most {} pinned charts"),
    ("Integration API nicht gefunden (HTTP {}) – UniFi Network 9.0 oder neuer nötig", "Integration API not found (HTTP {}) – UniFi Network 9.0 or newer required"),
    ("Internet für {} {} (Alias {})", "Internet for {} {} (alias {})"), ("Internet für {} {}", "Internet for {} {}"), ("Kein Gerät hat geantwortet: {}", "No device answered: {}"),
    ("Keine Antwort auf die SNMPv3-Anfrage. Der Switch verwirft die Pakete: SNMP unter Service Access nicht erlaubt, oder Trusted Hosts/Secured Client enthält {} nicht. Danach am Switch mit Save speichern.",
     "No answer to the SNMPv3 request. The switch drops the packets: SNMP not allowed under Service Access, or Trusted Hosts/Secured Client does not contain {}. Then save on the switch with Save."),
    ("Keine Berechtigung für {} – dem Benutzer die passenden Rechte geben (siehe Anleitung)", "No permission for {} – give the user the matching privileges (see guide)"),
    ("MQTT-Verbindung abgelehnt (Code {})", "MQTT connection rejected (code {})"), ("Messung fehlgeschlagen: {}", "Measurement failed: {}"),
    ("MikroTik meldet Fehler {}: {}", "MikroTik reports error {}: {}"), ("MikroTik meldet Fehler: {}", "MikroTik reports an error: {}"),
    ("MikroTik nicht erreichbar ({}) – ist der Dienst www-ssl bzw. www unter IP → Services eingeschaltet?", "MikroTik not reachable ({}) – is the www-ssl or www service enabled under IP → Services?"),
    ("MikroTik nicht erreichbar auf Port {} ({}) – ist der Dienst api bzw. api-ssl unter IP → Services eingeschaltet und für díktyo freigegeben (Available From)?",
     "MikroTik not reachable on port {} ({}) – is the api or api-ssl service enabled under IP → Services and allowed for díktyo (Available From)?"),
    ("MikroTik nicht erreichbar: {}", "MikroTik not reachable: {}"), ("Verbindung zum MikroTik abgebrochen ({})", "Connection to the MikroTik lost ({})"),
    ("OPNsense hat keine Konfiguration geliefert (HTTP {})", "OPNsense did not provide a configuration (HTTP {})"), ("OPNsense meldet Fehler {} bei {}", "OPNsense reports error {} for {}"),
    ("OPNsense nicht erreichbar: {}", "OPNsense not reachable: {}"),
    ("OPNsense trägt {} in den Alias „{}“ ein; die Block-Regel dafür legst du einmal selbst an.", "OPNsense adds {} to the alias “{}”; you create the block rule for it once yourself."),
    ("OPNsense: Alias „{}“ nicht geändert ({}) – gibt es den Alias vom Typ „Host(s)“?", "OPNsense: alias “{}” not changed ({}) – does the alias of type “Host(s)” exist?"),
    ("Die FRITZ!Box sperrt den Internetzugang für {}; das Heimnetz bleibt erreichbar.", "The FRITZ!Box blocks internet access for {}; the home network stays reachable."),
    ("PoE an Port {} aus- und wieder eingeschaltet", "PoE on port {} switched off and on again"), ("PoE an Port {} ausschalten", "Switch off PoE on port {}"),
    ("PoE an Port {} einschalten", "Switch on PoE on port {}"), ("PoE an Port {} neu starten", "Restart PoE on port {}"), ("PoE an Port {} {}", "PoE on port {} {}"),
    ("PoE an {} für 5 Sekunden unterbrochen", "PoE on {} interrupted for 5 seconds"),
    ("Port {} gibt es an diesem Gerät nicht", "Port {} does not exist on this device"), ("Port {} ist noch belegt – erst den Kabelweg ändern", "Port {} is still in use – change the cable run first"),
    ("Ports: 1 bis {}", "Ports: 1 to {}"), ("Höheneinheiten: 1 bis {}", "Rack units: 1 to {}"), ("Höhe: 1 bis {} HE", "Height: 1 to {} U"),
    ("Passt nicht ins Rack (HE 1 bis {})", "Does not fit into the rack (U 1 to {})"), ("Höheneinheit {} ist noch belegt", "Rack unit {} is still in use"),
    ("HE {} ist schon belegt", "U {} is already in use"), ("Privater Schlüssel nicht lesbar ({})", "Private key not readable ({})"), ("Proxmox meldet Fehler {}: {}", "Proxmox reports error {}: {}"),
    ("SSH-Anmeldung abgelehnt ({})", "SSH sign-in rejected ({})"), ("SSH-Verbindung fehlgeschlagen: {}", "SSH connection failed: {}"),
    ("Schnittstelle antwortet, aber ohne Daten{}", "The interface answers, but without data{}"), ("Site „{}“ nicht gefunden", "Site “{}” not found"),
    ("Socket-Proxy verweigert {} – dort den Bereich freigeben (z. B. CONTAINERS=1)", "The socket proxy denies {} – allow the section there (e.g. CONTAINERS=1)"),
    ("Unerwartete Antwort des Controllers (HTTP {}) – ist das ein Omada-Controller mit Open API?", "Unexpected response from the controller (HTTP {}) – is this an Omada controller with Open API?"),
    ("Unerwartete Antwort des Controllers (HTTP {})", "Unexpected response from the controller (HTTP {})"), ("VLAN {} gibt es schon", "VLAN {} already exists"),
    ("VLAN {} wird von {} (Proxmox) genutzt, ist in díktyo aber noch nicht angelegt", "VLAN {} is used by {} (Proxmox) but does not exist in díktyo yet"),
    ("Verbindung angelegt, aber Google Drive antwortet nicht: {}", "Connection created, but Google Drive does not answer: {}"),
    ("Weckruf an {} gesendet", "Wake-up sent to {}"), ("Weckruf an {} über den MikroTik", "Wake-up to {} through the MikroTik"), ("Weckruf an {} über die FRITZ!Box", "Wake-up to {} through the FRITZ!Box"),
    ("Zurückschalten: {}", "Switch back: {}"), ("Automatisch zurück: {}", "Automatically back: {}"), ("Zähler für: {}", "Counters for: {}"),
    ("díktyo erreicht {} über {} ({}). Der Switch sieht als Absender {}.", "díktyo reaches {} via {} ({}). The switch sees {} as the sender."),
    ("keine Antwort{}", "no answer{}"), ("keine Zähler – Felder: {}", "no counters – fields: {}"), ("nmap meldet einen Fehler: {}", "nmap reports an error: {}"),
    ("ntfy nicht erreichbar: {}", "ntfy not reachable: {}"), ("ntfy meldet HTTP {}: {}", "ntfy returns HTTP {}: {}"), ("{} Clients über {}; WAN-Stundenwerte: {}", "{} clients via {}; WAN hourly values: {}"),
    ("{} Clients; Felder: {}", "{} clients; fields: {}"), ("{} Ports übernommen (ifIndex {}–{}), {} andere Schnittstellen{}", "{} ports used (ifIndex {}–{}), {} other interfaces{}"),
    ("{} hat noch kein Subnetz (IPAM) – für die Adressprüfung eines anlegen", "{} has no subnet yet (IPAM) – add one for the address check"),
    ("{} ist schon in einem anderen Kabelweg eingetragen", "{} is already used in another cable run"),
    ("{} liegt nicht in einem Netz von díktyo (eigene Adresse {}), der Weg führt über {}. Macht der Router NAT, sieht der Switch als Absender nicht {}, sondern {}. Genau diese Adresse muss am Switch erlaubt sein.",
     "{} is not in a network of díktyo (own address {}), the path goes via {}. If the router does NAT, the switch does not see {} as sender, but {}. Exactly this address must be allowed on the switch."),
    ("{} neu starten (über {})", "Restart {} (through {})"), ("{} nicht erreichbar ({})", "{} not reachable ({})"), ("{} startet neu", "{} is restarting"),
    ("{} {} abschalten", "Disable {} {}"), ("{} {} einschalten", "Switch on {} {}"), ("{} – das angeschlossene Gerät verliert die Verbindung.", "{} – the connected device loses its connection."),
    ("{} · Port {} → {}: Adresse {} liegt nicht im Netz von {} ({}) – statische Adresse anpassen", "{} · port {} → {}: address {} is not in the network of {} ({}) – change the static address"),
    ("{} · Port {} → {}: Adresse {} liegt nicht im Netz von {} ({}) – bekommt per DHCP eine neue Adresse", "{} · port {} → {}: address {} is not in the network of {} ({}) – gets a new address via DHCP"),
    ("{} · Port {} → {}: führt {} nicht weiter, obwohl es auf {} genutzt wird (als tagged eintragen)", "{} · port {} → {}: does not carry {} although it is used on {} (add as tagged)"),
    ("{} · Port {} → {}: führt {} nicht, das VMs/Container nutzen ({}) – als tagged eintragen", "{} · port {} → {}: does not carry {}, which VMs/containers use ({}) – add as tagged"),
    ("{} „{}“: Port 1 bis {} wählen", "{} “{}”: choose port 1 to {}"), ("„{}“ ist kein {}", "“{}” is not a {}"),
    ("{}: Anmeldung abgelehnt – Passwort prüfen", "{}: sign-in rejected – check the password"),
    ("{}: Anmeldung verlangt – Benutzer/Passwort in der Integration eintragen", "{}: sign-in required – enter user/password in the integration"),
    ("{}: Anmeldung verlangt – Passwort (Benutzer admin) in der Integration eintragen", "{}: sign-in required – enter the password (user admin) in the integration"),
    ("{}: Auftrag vom Gerät angenommen – es lädt die Firmware selbst vom Hersteller und startet danach neu. díktyo prüft bei den nächsten Abfragen, ob die neue Version ankommt.",
     "{}: request accepted by the device – it downloads the firmware from the manufacturer itself and then restarts. díktyo checks during the next polls whether the new version arrives."),
    ("{}: keine JSON-Antwort (Adresse/Port richtig?)", "{}: no JSON response (address/port correct?)"), ("{}: keine JSON-Antwort", "{}: no JSON response"),
    ("{}: weder Shelly noch Tasmota", "{}: neither Shelly nor Tasmota"),
    ("WLAN „{}“ ({}) {}", "{2} Wi-Fi “{0}” ({1})"), ("WLAN „{}“ {}", "Wi-Fi “{}” {}"), ("Port {} {}", "Port {} {}"),
    ("AdGuard-Schutz {}", "AdGuard protection {}"), ("Pi-hole-Werbeblocker {}", "Pi-hole ad blocker {}"),
    ("{} ausschalten", "Switch off {}"), ("{} einschalten", "Switch on {}"), ("„{}“ starten", "Start “{}”"), ("„{}“ stoppen", "Stop “{}”"), ("„{}“ herunterfahren", "Shut down “{}”"),
    ("für {}", "for {}"), ("{} auf {}", "{} on {}"), ("{} sauber beenden", "Shut {} down cleanly"), ("Firmware aktualisieren ({} → {})", "Update firmware ({} → {})"),
    ("Abgebrochen: {}", "Cancelled: {}"), ("GitHub nicht erreichbar: {}", "GitHub not reachable: {}"),
    ("Installiere Version {}", "Installing version {}"), ("Version {} installiert", "Version {} installed"), ("Versand fehlgeschlagen: {}", "Sending failed: {}"),
    ("{}: {}", "{}: {}"),  # zuletzt: „Name: Meldung“ – beide Teile einzeln übersetzen
]


def _compile(de):
    parts = de.split("{}")
    return re.compile("^" + "(.+?)".join(re.escape(p) for p in parts[:-1]) + ("(.+?)" if len(parts) > 1 else "") + re.escape(parts[-1]) + "$", re.S)


def _rank(de):
    lit = [x for x in de.split("{}") if x.strip()]
    return (-len(lit), -sum(len(x) for x in lit))  # genauere Muster (mehr feste Teile) zuerst


_PATTERNS = sorted(((de, _compile(de), en_) for de, en_ in PATTERNS), key=lambda x: _rank(x[0]))


def en(text, _depth=0):
    """Deutsche Meldung -> englisch (sonst unverändert). Eingesetzte Teile werden ihrerseits übersetzt."""
    if not isinstance(text, str) or not text or _depth > 4:
        return text
    if text in ERR_EN:
        return ERR_EN[text]
    s = text.strip()
    if s != text and s in ERR_EN:
        return ERR_EN[s]
    for pat, rep in ERR_EN_RE:
        if re.match(pat, text):
            return re.sub(pat, rep, text)
    for de_p, en_p in ERR_EN_PREFIX.items():
        if text.startswith(de_p):
            return en_p + en(text[len(de_p):], _depth + 1)
    for de, rx, tpl in _PATTERNS:
        m = rx.match(text)
        if m:
            out = tpl.format(*[en(g, _depth + 1) for g in m.groups()])
            return out[:1].upper() + out[1:] if tpl.startswith("{") and out[:1].islower() and _depth == 0 else out
    return text


def table():
    """Für die Oberfläche: exakte Texte und Muster."""
    return dict(exact=ERR_EN, prefix=ERR_EN_PREFIX, patterns=[[de, en_] for de, en_ in PATTERNS],
                regex=[[p, r.replace("\\1", "$1").replace("\\2", "$2")] for p, r in ERR_EN_RE])


# ------------------------------------------------------------ 0.38.1: feste Fehlertexte der Sicherung
ERR_EN.update({
    "Keine Schreibrechte – Rechte des díktyo-Dienstes am Ziel prüfen": "No write permission – check the díktyo service’s rights on the target",
    "Ordner nicht vorhanden oder kein Ordner": "Folder does not exist or is not a folder", "Kein Speicherplatz mehr am Ziel": "No space left on the target",
    "Ziel ist schreibgeschützt (nur lesbar eingebunden)": "Target is read-only (mounted read-only)",
    "WebDAV-Server antwortet nicht (Zeitüberschreitung)": "WebDAV server does not respond (timeout)",
    "WebDAV-Server nicht erreichbar – Adresse prüfen": "WebDAV server not reachable – check the address",
    "rclone hat nach 10 Minuten nicht geantwortet": "rclone did not respond within 10 minutes",
    "Gespeichertes Passwort lässt sich nicht entschlüsseln – Passwort neu eintragen": "Stored password cannot be decrypted – enter the password again",
    "Fehler beim Sichern – Details im Protokoll des Dienstes": "Backup failed – details in the service log",
    "Anmeldung abgelehnt – Benutzer und Passwort prüfen": "Sign-in rejected – check user and password",
    "unbekannter Zieltyp": "unknown target type",
    "rclone ist nicht installiert (apt install rclone, danach 'rclone config')": "rclone is not installed (apt install rclone, then 'rclone config')",
})
ERR_EN_RE.append((r"^WebDAV-Server meldet HTTP (\d+)$", r"WebDAV server returns HTTP \1"))


# ------------------------------------------------------------ 0.39: VLANs aus MikroTik, OPNsense, UniFi, Omada
ERR_EN.update({
    "Dieses Gerät meldet seine VLANs selbst (Integration) – der produktive Stand lässt sich hier nicht ändern":
        "This device reports its VLANs itself (integration) – the production state cannot be changed here",
})


# ------------------------------------------------------------ 0.40: OpenWrt
ERR_EN.update({
    "OpenWrt neu starten": "Restart OpenWrt", "OpenWrt startet neu (dauert etwa eine Minute)": "OpenWrt is restarting (takes about a minute)",
    "Keine Berechtigung für die Sicherung (ACL „cgi-io: backup“ bzw. Benutzer root nötig)": "No permission for the backup (ACL “cgi-io: backup” or user root required)",
    "Sicherung nicht verfügbar – auf dem Router fehlt cgi-io (Teil von LuCI)": "Backup not available – cgi-io is missing on the router (part of LuCI)",
    "WLAN beim Router nicht gefunden – Integration einmal abfragen": "Wi-Fi not found on the router – poll the integration once",
    "Anmeldung abgelehnt – Benutzer und Passwort prüfen (rpcd-Benutzer, z. B. root)": "Sign-in rejected – check user and password (rpcd user, e.g. root)",
    "Anmeldung ohne Sitzung – rpcd antwortet unerwartet": "Sign-in without session – rpcd answers unexpectedly",
    "Zugriff verweigert – Sitzung abgelaufen oder fehlende Rechte": "Access denied – session expired or missing permissions",
    "Keine ubus-Schnittstelle unter /ubus – auf dem Router das Paket uhttpd-mod-ubus installieren (bei LuCI vorhanden)":
        "No ubus interface at /ubus – install the package uhttpd-mod-ubus on the router (included with LuCI)",
    "Verbindung": "Connection", "automatisch (HTTPS, sonst HTTP)": "automatic (HTTPS, otherwise HTTP)", "Port (leer = 443 bzw. 80)": "Port (empty = 443 or 80)",
    "ungültiger Befehl": "invalid command", "ungültiges Argument": "invalid argument", "Methode nicht gefunden": "method not found",
    "nicht gefunden": "not found", "keine Daten": "no data", "keine Berechtigung": "permission denied", "Zeitüberschreitung": "timeout",
    "nicht unterstützt": "not supported", "unbekannter Fehler": "unknown error", "Verbindung fehlgeschlagen": "connection failed",
})
PATTERNS += [
    ("OpenWrt hat keine Sicherung geliefert (HTTP {})", "OpenWrt did not deliver a backup (HTTP {})"),
    ("Unerwartete Antwort (HTTP {}) – ist das ein OpenWrt-Router mit LuCI?", "Unexpected response (HTTP {}) – is this an OpenWrt router with LuCI?"),
    ("OpenWrt nicht erreichbar: {}", "OpenWrt not reachable: {}"), ("OpenWrt unter {} nicht erreichbar ({})", "OpenWrt at {} not reachable ({})"),
]
_PATTERNS = sorted(((de, _compile(de), en_) for de, en_ in PATTERNS), key=lambda x: _rank(x[0]))


# ------------------------------------------------------------ 0.41: Verlauf löschen
ERR_EN.update({"Nichts zum Löschen gewählt": "Nothing selected to delete", "Ungültiger Zeitraum": "Invalid period"})


# ------------------------------------------------------------ 0.42: ASUS-Aktionen und lesbare Konfiguration
ERR_EN.update({
    "Diese Konfigurationen lassen sich nicht vergleichen": "These configurations cannot be compared",
    "Diese Datei lässt sich nicht lesbar machen": "This file cannot be made readable",
    "ASUS-Router neu starten": "Restart ASUS router",
    "Internet und WLAN sind etwa zwei Minuten weg; AiMesh-Knoten verbinden sich danach neu.": "Internet and Wi-Fi are gone for about two minutes; AiMesh nodes reconnect afterwards.",
    "Router nimmt die Einstellung nicht an (Sitzung abgelaufen)": "Router does not accept the setting (session expired)",
    "Gastnetz nicht gefunden – Integration einmal abfragen": "Guest network not found – poll the integration once",
    "Geräte im Gastnetz verlieren die Verbindung.": "Devices in the guest network lose their connection.",
    "Das WLAN des Routers startet dafür kurz neu.": "The router's Wi-Fi restarts briefly for this.",
    "ASUS-Router startet neu (dauert etwa zwei Minuten)": "ASUS router is restarting (takes about two minutes)",
})
PATTERNS += [
    ("Gastnetz „{}“ ({}) einschalten", "Switch on guest network “{}” ({})"), ("Gastnetz „{}“ ({}) ausschalten", "Switch off guest network “{}” ({})"),
    ("Gastnetz „{}“ eingeschaltet", "Guest network “{}” switched on"), ("Gastnetz „{}“ ausgeschaltet", "Guest network “{}” switched off"),
]
_PATTERNS = sorted(((de, _compile(de), en_) for de, en_ in PATTERNS), key=lambda x: _rank(x[0]))


# ------------------------------------------------------------ 0.43: geplante VLAN-Wechsel von VMs/Containern
ERR_EN.update({
    "Keine VM bzw. kein Container aus Proxmox gewählt": "No VM or container from Proxmox selected",
    "Dieses VLAN gibt es nicht – zuerst anlegen (auch als geplantes VLAN möglich)": "This VLAN does not exist – create it first (a planned VLAN works too)",
})


# ------------------------------------------------------------ 0.45: Portfreigaben und UPnP
ERR_EN.update({
    "Diese Freigabe gibt es nicht (mehr)": "This port forward does not exist (any more)",
})
