'use strict';
/* Integrationen (FRITZ!Box, SNMP-Switch), Ping-Überwachung, Diagramme. Nutzt die Hilfen aus app.js, inventory.js, scan.js. */
const DRIVER_HELP = {
  fritzbox: 'díktyo liest nur – an der FRITZ!Box wird nichts geändert.',
  snmp: 'díktyo liest nur: Port-Status, Traffic, gelernte MAC-Adressen und LLDP-Nachbarn.',
};
Object.assign(DRIVER_HELP, {
  asuswrt: 'díktyo liest nur: Clients mit Mesh-Knoten und WLAN-Band sowie die AiMesh-Knoten.',
  proxmox: 'Liest Knoten, VMs und LXCs mit MAC, Bridge, VLAN-Tag und IP (über den QEMU Guest Agent bzw. die LXC-Schnittstellen) und hängt sie virtuell an ihren Host.',
  homeassistant: 'Namen und Bereiche kommen per MAC-Adresse aus HA; Status und Ereignisse gehen per MQTT an HA. Für Benachrichtigungen die Blueprint aus docs/home-assistant importieren.',
});
// Schritt-für-Schritt-Hinweise oben im Dialog
const DRIVER_STEPS = {
  dnsfilter: [
    '<b>Pi-hole (ab v6):</b> unter <b>Einstellungen → Web-Oberfläche/API</b> ein <b>App-Passwort</b> erzeugen und hier als Passwort eintragen (das normale Web-Passwort geht auch). Pi-hole v5 nimmt das API-Token.',
    '<b>AdGuard Home:</b> Benutzer und Passwort der Weboberfläche eintragen.',
    'Adresse und Port wie im Browser (Pi-hole meist Port 80, AdGuard Home oft 80 oder 3000).',
    'díktyo übernimmt Hostnamen (nur wo noch keiner steht) und zeigt Anfragen und Blockierte je Gerät. Gespeichert werden nur Zahlen, keine besuchten Domains einzelner Geräte.',
  ],
  shelly: [
    'Unter <b>Adressen</b> „auto“ lassen: díktyo nimmt alle Geräte, die der Netzscan als Shelly oder Tasmota erkannt hat (und ESP-Module von Espressif). Weitere IPs mit Komma ergänzen.',
    'Shelly: Die lokale HTTP-Schnittstelle ist ab Werk an. Ist am Shelly „Authentifizierung“ eingeschaltet, hier das Passwort eintragen (Gen2+: Benutzer <b>admin</b>).',
    'Tasmota: läuft ohne Einstellung; ist ein Web-Passwort gesetzt, Benutzer <b>admin</b> und das Passwort eintragen.',
    'díktyo liest Leistung, Energie, Ausgänge und Firmware. Schalten und Firmware-Update gibt es im Gerätedialog unter „Aktionen“.',
  ],
  fritzbox: [
    'Adresse der FRITZ!Box eintragen, meist <b>192.168.178.1</b>.',
    'In der FRITZ!Box unter <b>Heimnetz → Netzwerk → Netzwerkeinstellungen</b> „Zugriff für Anwendungen zulassen“ einschalten.',
    'Verlangt die FRITZ!Box für das Backup eine Bestätigung (zweiter Faktor), kann díktyo mit dem <b>Authenticator-Schlüssel</b> auch automatisch sichern. Den Schlüssel zeigt die FRITZ!Box beim Einrichten der App (<b>System → FRITZ!Box-Benutzer → Anmeldung im Heimnetz</b>, „Schlüssel manuell eingeben“). Achtung: Damit kann díktyo den zweiten Faktor allein erfüllen.',
    'Ohne Benutzer liest díktyo nur Geräteliste und WAN-Traffic. Für Mesh-Topologie, WLAN und Konfigurations-Backup unter <b>System → FRITZ!Box-Benutzer</b> einen Benutzer mit dem Recht <b>„FRITZ!Box Einstellungen“</b> anlegen und hier eintragen.',
    '„Verbindung testen“ zeigt Modell, FRITZ!OS und ob die Anmeldung reicht.',
  ],
  snmp: [
    'Am Switch SNMP einschalten, beim Zyxel unter <b>Management → Access Control → SNMP</b>: <b>v3</b> mit Benutzer (Sicherheitsstufe „priv“, SHA/AES, Gruppe „read-only“) oder <b>v2c</b> mit eigener Community.',
    'Unter <b>Service Access</b> muss SNMP erlaubt sein. Sind <b>Trusted Hosts</b> gesetzt, die Absenderadresse von díktyo erlauben – steht díktyo hinter einem Router, ist das dessen <b>WAN-Adresse</b>.',
    'Einstellungen am Switch mit <b>Save</b> dauerhaft speichern, dann hier Adresse, Version und Zugangsdaten eintragen.',
    'Für Konfigurations-Backups SSH einrichten (díktyo liest „show running-config“): mit <b>Benutzer und Passwort</b> oder ohne Passwort mit <b>Schlüssel</b> – „Schlüssel von díktyo“ zeigt einen öffentlichen Schlüssel, den du am Switch hinterlegst (Zyxel: <b>Maintenance → SSH Authorized Keys</b> → Import, dann Save).',
  ],
  asuswrt: [
    'Adresse des Hauptrouters eintragen (bei AiMesh der Knoten mit dem Internetanschluss), z. B. <b>192.168.50.1</b>.',
    'Port und Protokoll wie in der Weboberfläche: meist <b>HTTPS, Port 8443</b> (sonst HTTP, Port 80).',
    'Benutzer und Passwort des <b>Admin-Kontos</b> des Routers eintragen.',
    'ASUS erlaubt nur <b>eine Admin-Sitzung</b>: Meldet dich die Weboberfläche ab, das Abfrageintervall erhöhen (Standard 5 min).',
  ],
  proxmox: [
    'Auf einem Proxmox-Knoten (Shell als root) einen Nur-Lese-Zugang anlegen:<pre>pveum role add DiktyoRead -privs "VM.Audit,VM.GuestAgent.Audit,Sys.Audit,Datastore.Audit,SDN.Audit"\npveum user add diktyo@pve\npveum acl modify / --users diktyo@pve --roles DiktyoRead\npveum user token add diktyo@pve diktyo --privsep 1\npveum acl modify / --tokens \'diktyo@pve!diktyo\' --roles DiktyoRead</pre>',
    'Das <b>Token-Secret</b> wird nur einmal angezeigt – kopieren und hier einfügen. Token-ID: <b>diktyo@pve!diktyo</b>.',
    'Als Adresse die IP eines Knotens eintragen, z. B. <b>192.168.50.12</b> (Port 8006). Im Cluster reicht ein Knoten.',
    'IP-Adressen von VMs kommen über den <b>QEMU Guest Agent</b> (in der VM installieren und in den VM-Optionen aktivieren).',
  ],
  homeassistant: [
    'Adresse von Home Assistant mit IP-Adresse und Port eintragen, z. B. <b>http://192.168.50.9:8123</b>.',
    'Für Namen und Bereiche: in HA unter <b>Profil → Sicherheit → Langlebige Zugriffstoken</b> ein Token erstellen und einfügen.',
    'Als MQTT-Broker die <b>IP-Adresse von Home Assistant</b> eintragen (z. B. 192.168.50.9, Port 1883) – <b>nicht „core-mosquitto“</b>: diesen Namen kennt nur Home Assistant selbst.',
    'MQTT-Benutzer und -Passwort aus dem Mosquitto-Add-on (am besten ein eigener Benutzer für díktyo), dann „Verbindung testen“.',
  ],
};
Object.assign(DRIVER_HELP, {
  omada: 'díktyo liest nur: Gateways, Switches und Access Points mit Uplink-Port sowie die Clients mit AP bzw. Switch-Port.',
  unifi: 'díktyo liest nur: Gateway, Switches und Access Points mit Port-Status, die Clients mit AP bzw. Switch und den WAN-Traffic des Gateways.',
});
Object.assign(DRIVER_STEPS, {
  omada: [
    'Im Omada-Controller unter <b>Einstellungen → Plattform-Integration → Open API</b> auf <b>Neue App hinzufügen</b> klicken, Modus <b>„Client“</b>, Rolle mit Lesezugriff (z. B. Viewer) und die Sites wählen.',
    '<b>Client-ID</b> und <b>Client-Secret</b> der App sowie die <b>Omada-ID</b> (oben auf derselben Seite) hier eintragen. Das Secret wird nur einmal angezeigt.',
    'Als Adresse die IP des Controllers (Software-Controller, OC200/OC300 oder Gateway mit Controller), Port meist <b>8043</b> (OC200/OC300: <b>443</b>).',
    'Optional eine Site eintragen, sonst liest díktyo alle Sites. „Verbindung testen“ zeigt Sites, Geräte und Clients.',
  ],
  unifi: [
    'In UniFi Network unter <b>Einstellungen → Control Plane → Integrationen</b> einen <b>API-Schlüssel</b> erstellen (UniFi Network 9.0 oder neuer). Nicht den Site-Manager-Schlüssel von unifi.ui.com verwenden.',
    'Als Adresse die IP der Konsole (UDM, UCG, Cloud Key) bzw. des selbst gehosteten Controllers eintragen, Port <b>443</b> (selbst gehostet meist <b>8443</b>).',
    'Den Schlüssel einfügen; er wird nur einmal angezeigt und hat vollen Zugriff – díktyo nutzt ihn nur lesend.',
    'Optional eine Site eintragen, sonst liest díktyo alle Sites. Der WAN-Traffic des Gateways erscheint in der Topologie an der Internet-Leitung.',
  ],
});
DRIVER_HELP.opnsense = 'díktyo liest Schnittstellen, ARP, DHCP-Leases, WAN und Firmware; schalten nur über „Aktionen“ mit Bestätigung.';
DRIVER_STEPS.opnsense = [
  'In OPNsense unter <b>System → Zugang → Benutzer</b> einen eigenen Benutzer anlegen (z. B. „diktyo“) und ihm unter <b>Effektive Berechtigungen</b> diese Seiten erlauben: <i>Status: Interfaces</i>, <i>Diagnostics: ARP Table</i>, <i>Services: DHCP: Kea(v4)</i> bzw. <i>Dnsmasq</i>/<i>ISC</i>, <i>System: Firmware</i>, <i>Lobby: Dashboard</i>.',
  'Beim Benutzer unter <b>API-Schlüssel</b> auf „+“ klicken – OPNsense lädt eine Datei mit <b>key</b> und <b>secret</b> herunter; beides hier eintragen.',
  'Optional <b>Internetsperre</b>: unter <b>Firewall → Aliase</b> einen Alias vom Typ „Host(s)“ anlegen (z. B. <span class="mono">diktyo_block</span>), dazu eine LAN-Regel „Block, Quelle = Alias, Ziel = any“ ganz oben. Den Alias-Namen hier eintragen; der Benutzer braucht dann zusätzlich <i>Firewall: Alias: Edit</i>.',
  'Konfigurations-Backup lädt die config.xml – dafür das Recht <i>Diagnostics: Configuration History</i> bzw. <i>Backup &amp; Restore</i>.',
];
DRIVER_HELP.docker = 'Container erscheinen als virtuelle Geräte am Docker-Host; Starten/Stoppen über „Aktionen“.';
DRIVER_STEPS.docker = [
  'Den Docker-Socket <b>nicht</b> direkt freigeben, sondern einen Socket-Proxy auf dem Docker-Host starten, der nur das Nötige erlaubt (docker-compose.yml):<pre>services:\n  socket-proxy:\n    image: tecnativa/docker-socket-proxy\n    restart: unless-stopped\n    environment:\n      CONTAINERS: 1\n      INFO: 1\n      VERSION: 1\n      NETWORKS: 1\n    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock:ro\n    ports:\n      - "2375:2375"</pre>',
  'Für <b>Aktionen</b> (Container starten/stoppen) zusätzlich <span class="mono">POST: 1</span>, <span class="mono">ALLOW_START: 1</span>, <span class="mono">ALLOW_STOP: 1</span>, <span class="mono">ALLOW_RESTARTS: 1</span>.',
  'Port 2375 nur im Heimnetz erreichbar lassen (nicht im Router freigeben). Hier die IP des Docker-Hosts und Port 2375 eintragen.',
  'Viele Container? „nur Container mit eigener IP im Heimnetz“ legt nur die an, die per macvlan/ipvlan oder Host-Netz direkt im Netz hängen.',
];
DRIVER_HELP.mikrotik = 'díktyo liest Ports, Clients (DHCP, ARP, Bridge, WLAN), Nachbarn und WAN; schalten nur über „Aktionen“ mit Bestätigung.';
DRIVER_STEPS.mikrotik = [
  'Zugang <b>RouterOS-API</b> (Standard, RouterOS 6 und 7): unter IP → Services den Dienst <b>api</b> (Port 8728) einschalten und bei „Available From“ die Adresse von díktyo erlauben. Mit TLS: <b>api-ssl</b> (Port 8729, braucht ein Zertifikat).',
  'Eigenen Benutzer anlegen – nur lesen:<pre>/user group add name=diktyo-read policy=read,api,!local,!telnet,!ssh,!ftp,!winbox,!web,!rest-api\n/user add name=diktyo group=diktyo-read password=GEHEIM</pre>Für <b>Aktionen</b> (Port, PoE, WLAN, Neustart, Wake-on-LAN) stattdessen <span class="mono">policy=read,write,reboot,test,api</span>.',
  'Alternativ <b>REST</b> (nur RouterOS 7): Dienst www-ssl (HTTPS, Zertifikat nötig) oder ab 7.9 www (HTTP), Recht rest-api statt api.',
  'Ein Konfigurations-Backup macht díktyo bei MikroTik nicht – dafür hat RouterOS eigene Backups (System → Backup, auch in die MikroTik-Cloud).',
];
const EVENT = { watch_change: 'Wachliste: Änderung', device_offline: 'Gerät offline', device_online: 'Gerät wieder online', new_device: 'Neues Gerät', action_undo_failed: 'Zurückschalten fehlgeschlagen', quarantined: 'Neues Gerät in Quarantäne', schedule_failed: 'Zeitplan fehlgeschlagen', firmware_update: 'Firmware-Update verfügbar' };
const RANGES = [[7200, '2 h'], [86400, '24 h'], [172800, '2 Tage'], [604800, '7 Tage']];
const fmtBps = v => {
  if (v == null || isNaN(v)) return '–';
  const u = [[1e9, 'Gbit/s'], [1e6, 'Mbit/s'], [1e3, 'kbit/s']].find(([f]) => v >= f) || [1, 'bit/s'];
  return (v / u[0]).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: v / u[0] < 10 ? 1 : 0 }) + ' ' + u[1];
};
const fmtUptime = s => { if (!s) return '–'; const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600); return d ? t('{d} Tage {h} h', { d, h: hh }) : t('{h} h', { h: hh }); };

/* Liniendiagramm. series = [{name, color, points: [[ts, v], ...]}]. Achsenbeschriftung als HTML (bleibt lesbar). */
function chartSvg(series, since, { height = 150, fmt = fmtBps } = {}) {
  const W = 1000, H = 100, now = Date.now() / 1000, t0 = now - since;
  const max = niceMax(Math.max(1, ...series.flatMap(s => s.points.map(p => p[1]))));
  const x = ts => (ts - t0) / since * W, y = v => H - v / max * (H - 1);
  const lines = series.map(s => {
    if (!s.points.length) return '';
    const d = s.points.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(2)}`).join('');
    const area = `${d}L${x(s.points[s.points.length - 1][0]).toFixed(1)},${H}L${x(s.points[0][0]).toFixed(1)},${H}Z`;
    return `<path d="${area}" fill="${s.color}" opacity=".12"/><path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.8" vector-effect="non-scaling-stroke"/>`;
  }).join('');
  const empty = series.every(s => !s.points.length);
  return `<div class="hbc line" style="--h:${height}px">
      <div class="hb-y">${[[0, max], [50, max / 2], [100, 0]].map(([p, v]) => `<span style="top:${p}%">${h(v ? fmt(v) : '0')}</span>`).join('')}</div>
      <div class="hb-plot"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
        ${[0, 25, 50, 75].map(g => `<line x1="0" x2="${W}" y1="${g}" y2="${g}" class="hb-grid"/>`).join('')}<line x1="0" x2="${W}" y1="${H}" y2="${H}" class="hb-zero"/>${lines}</svg>
        ${empty ? `<div class="hb-empty">${t('Noch keine Messwerte – sie entstehen mit jeder Abfrage.')}</div>` : ''}</div>
      <div></div><div class="hb-x"><span>${h(timeLabel(t0, since))}</span><span>${h(timeLabel(t0 + since / 2, since))}</span><span>${h(timeLabel(now, since))}</span></div>
    </div>
    <div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${h(s.name)}</span>`).join('')}</div>`;
}

async function drawChart(el, pid, keys, names, since, opts = {}) {
  const r = await api('GET', `/api/profiles/${pid}/metrics?keys=${keys.join(',')}&since=${since}`);
  const colors = ['#00E5FF', '#19F5C8', '#2D7BFF', '#FFB020'];
  el.innerHTML = chartSvg(keys.map((k, i) => ({ name: names[i], color: colors[i % colors.length], points: r.series[k] || [] })), since, opts);
}
const fmtBpsShort = v => {
  if (v == null || isNaN(v)) return '–';
  const u = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k']].find(([f]) => v >= f) || [1, ''];
  return (v / u[0]).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: v / u[0] < 10 ? 1 : 0 }) + u[1];
};
/* Geschwindigkeitsklasse eines Ports mit Link (Mbit/s): unter 1 Gbit/s langsam, ab 2,5 Gbit/s schnell */
const speedCls = mbps => !mbps ? '' : mbps < 1000 ? 'sp-slow' : mbps >= 2500 ? 'sp-fast' : '';
const fmtLink = mbps => !mbps ? '' : mbps >= 1000 ? (mbps / 1000).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE') + ' Gbit/s' : mbps + ' Mbit/s';
const fmtW = v => v == null || isNaN(v) ? '–' : Math.abs(v) >= 1000
  ? `${(v / 1000).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: 2 })} kW`
  : `${(+v).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: v < 10 ? 1 : 0 })} W`;
const fmtBytes = v => {
  if (v == null || isNaN(v)) return '–';
  const u = [[1e12, 'TB'], [1e9, 'GB'], [1e6, 'MB'], [1e3, 'kB']].find(([f]) => v >= f) || [1, 'B'];
  return (v / u[0]).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: v / u[0] < 10 ? 1 : 0 }) + ' ' + u[1];
};
const fmtMs = v => v == null || isNaN(v) ? '–' : `${(+v).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: v < 10 ? 1 : 0 })} ms`;
const fmtDur = s => !s ? '–' : s < 60 ? `${s} s` : s < 3600 ? `${Math.round(s / 60)} min` : s < 86400 ? `${(s / 3600).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: 1 })} h` : t('{d} Tage {h} h', { d: Math.floor(s / 86400), h: Math.floor(s % 86400 / 3600) });
const pctCls = p => p == null ? 'muted' : p >= 99.9 ? 'okc' : p >= 98 ? 'warnc' : 'errtxt';
const fmtPct = a => a ? `<span class="${pctCls(a.pct)}">${a.pct.toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: a.pct >= 99.9 ? 2 : 1 })} %</span>` : '<span class="muted">–</span>';
/* Weboberfläche eines Shelly/Tasmota (im lokalen Netz, ohne Cloud) */
const webLink = (ip, label) => ip ? `<a class="btn sm" href="http://${h(ip)}/" target="_blank" rel="noopener noreferrer">${h(label || t('Weboberfläche öffnen'))} ↗</a>` : '';
/* Von díktyo angestoßenes Firmware-Update, das nach 20 Minuten nicht angekommen ist */
const fwStuck = (fw, ip) => fw?.stuck ? `<div class="hint-box small warnc" style="margin:6px 0">${t('Firmware-Update angestoßen {d}, das Gerät meldet aber weiterhin {v}. Meist kommt das Gerät nicht ins Internet oder das Update braucht eine Bestätigung im Gerät.', { d: h(fmtDate(new Date(fw.stuck.since * 1000).toISOString())), v: h(fw.stuck.installed || fw.installed || '?') })}
  ${ip ? ' ' + webLink(ip, t('Im Gerät prüfen')) : ''}</div>` : '';
const fwBadge = fw => !fw ? '' : fw.update ? `<span class="badge fwup" title="${h(t('Update verfügbar'))}">⬆ ${h(fw.latest || t('Update'))}</span>` : '';

function rangeButtons(cur) {
  return `<span class="ranges">${RANGES.map(([s, n]) => `<button type="button" class="sm ${s === cur ? 'on' : ''}" data-range="${s}">${t(n)}</button>`).join('')}</span>`;
}

/* Integrationen mit Diagrammen oder Port-/Gerätelisten bekommen im Raster doppelte Breite */
const BIG_CARDS = ['fritzbox', 'snmp', 'asuswrt', 'proxmox', 'omada', 'unifi', 'mikrotik', 'opnsense'];

async function tabIntegrations(ctx) {
  await meta(ctx.pid);  // Auswahllisten für den Gerätedialog („Gerät öffnen“)
  const P = `/api/profiles/${ctx.pid}`;
  const r = await api('GET', `${P}/integrations`);
  const drv = Object.fromEntries(r.drivers.map(d => [d.key, d]));
  const st = i => i.last_error && !i.last_ok ? 'err' : i.last_error ? 'warn' : i.last_ok ? 'ok' : 'none';
  const since = tabIntegrations.since || 7200;
  ctx.el.innerHTML = `
    <div class="grid-out">
      <form class="panel" id="mon"><h3>${t('Online-Überwachung')}</h3>
        <p class="muted small" style="margin-top:0">${t('Pingt alle bestätigten Geräte mit IP-Adresse im eingestellten Intervall und führt den Online-Verlauf. Geräte, die Ping verwerfen, werden über einen bekannten offenen Port geprüft.')}</p>
        <label class="chk"><input type="checkbox" name="enabled" ${r.monitor.enabled ? 'checked' : ''} ${ctx.canEdit ? '' : 'disabled'}> ${t('eingeschaltet')}</label>
        <label>${t('Intervall')}</label><select name="interval_s" ${ctx.canEdit ? '' : 'disabled'}>${r.intervals.map(v => `<option value="${v}" ${v === r.monitor.interval_s ? 'selected' : ''}>${v < 60 ? v + ' s' : v / 60 + ' min'}</option>`).join('')}</select>
        <p class="muted small">${t('Messwerte werden {n} Tage aufbewahrt (Einstellungen → Erkennung).', { n: r.metrics_days })}</p></form>
      <div class="panel"><h3>${t('Integrationen')}</h3>
        <p class="muted small" style="margin-top:0">${t('Geräte, die díktyo direkt abfragt. Die FRITZ!Box liefert alle angeschlossenen Geräte mit MAC-Adresse (auch aus Netzen hinter einem Router) und den WAN-Traffic; ein Switch per SNMP liefert Port-Status, Traffic und welches Gerät an welchem Port hängt.')}</p>
        ${ctx.canEdit ? `<div class="row"><button class="pri" data-add="fritzbox">${t('+ FRITZ!Box')}</button><button class="pri" data-add="snmp">${t('+ Switch (SNMP)')}</button>
          <button class="pri" data-add="asuswrt">${t('+ ASUS (AiMesh)')}</button><button class="pri" data-add="proxmox">${t('+ Proxmox')}</button><button class="pri" data-add="homeassistant">${t('+ Home Assistant')}</button>
          <button class="pri" data-add="omada">${t('+ Omada')}</button><button class="pri" data-add="unifi">${t('+ UniFi')}</button>
          <button class="pri" data-add="mikrotik">${t('+ MikroTik')}</button><button class="pri" data-add="opnsense">${t('+ OPNsense')}</button>
          <button class="pri" data-add="docker">${t('+ Docker')}</button><button class="pri" data-add="shelly">${t('+ Shelly / Tasmota')}</button><button class="pri" data-add="dnsfilter">${t('+ Pi-hole / AdGuard')}</button></div>` : ''}</div>
    </div>
    <div class="grid-out" style="margin-top:16px"><div id="speedbox"></div><div id="notifybox"></div><div id="prombox"></div></div>
    <div id="ints" class="ints-grid" style="margin-top:16px">${r.integrations.map(i => `<div class="panel integ ${BIG_CARDS.includes(i.driver) ? 'big' : ''}" data-id="${i.id}">
        <div class="row between int-h"><div class="row"><span class="dot ${st(i)}"></span><b>${h(i.name)}</b><span class="muted mono small">${h(i.host)}</span>
          ${i.name !== drv[i.driver]?.name ? `<span class="badge">${h(drv[i.driver]?.name || i.driver)}</span>` : ''}${i.enabled ? '' : `<span class="badge">${t('pausiert')}</span>`}</div>
          <div class="row">${ctx.canEdit ? `<button class="sm" data-poll>${t('Jetzt abfragen')}</button><button class="sm" data-edit>${t('Bearbeiten')}</button><button class="sm danger" data-del>${t('Löschen')}</button>` : ''}</div></div>
        <p class="muted small" style="margin:4px 0 0">${i.last_ok ? t('zuletzt erfolgreich {d}', { d: h(ago(i.last_ok)) }) : t('noch nicht abgefragt')} · ${t('alle {n}', { n: i.interval_s < 60 ? i.interval_s + ' s' : i.interval_s / 60 + ' min' })}
          ${i.summary?.device_id ? ` · <a href="#" data-dev="${i.summary.device_id}">${t('Gerät öffnen')}</a>` : ''}</p>
        ${i.last_error ? `<p class="${i.last_ok ? 'warnc' : 'errtxt'} small">${h(ts(i.last_error))}</p>` : ''}
        ${i.can_backup ? `<p class="small cfgline"><b>${t('Konfiguration')}:</b> ${i.cfg_ok ? t('zuletzt gesichert {d}', { d: h(ago(i.cfg_ok)) }) : t('noch nicht gesichert')}
          ${i.cfg_result?.status === 'error' ? ` · <span class="${i.cfg_result.second_factor ? 'warnc' : 'errtxt'}">${h(t(i.cfg_result.message))}</span>` : i.cfg_result?.status === 'unchanged' ? ` · <span class="muted">${t('unverändert')}</span>` : ''}
          ${ctx.canEdit ? `<button class="sm" data-cfg>${t('Konfiguration sichern')}</button>` : ''}</p>` : ''}
        ${i.driver === 'fritzbox' ? fritzCard(i) : i.driver === 'snmp' ? snmpCard(i) : i.driver === 'asuswrt' ? asusCard(i) : i.driver === 'proxmox' ? pveCard(i) : ['omada', 'unifi'].includes(i.driver) ? ctrlCard(i) : ['mikrotik', 'opnsense'].includes(i.driver) ? mtCard(i) : i.driver === 'docker' ? dockerCard(i) : i.driver === 'shelly' ? shellyCard(i) : i.driver === 'dnsfilter' ? dnsCard(i) : haCard(i)}
      </div>`).join('') || `<div class="panel empty-box">${t('Noch keine Integration. Füge deine FRITZ!Box hinzu – das geht auch ohne Passwort.')}</div>`}</div>
    <h2>${t('Letzte Ereignisse')}</h2><div id="events"></div>`;
  api('GET', `${P}/events?limit=15`).then(({ events }) => {
    const el = $('#events', ctx.el); if (!el) return;
    el.innerHTML = events.length ? `<div class="table-wrap"><table class="compact"><tbody>${events.map(e => `<tr><td class="mono small">${h(fmtDate(e.ts))}</td>
      <td><span class="badge ${e.kind === 'device_offline' ? 'warn' : e.kind === 'new_device' ? 'owner' : 'ok'}">${t(EVENT[e.kind] || e.kind)}</span></td>
      <td>${e.device_id ? `<a href="#" data-ev="${e.device_id}">${h(e.data.name || '')}</a>` : h(e.data.name || '')}</td><td class="mono small">${h(e.data.ip || '')}</td>
      <td class="small muted">${e.delivered ? t('an HA gemeldet') : ''}</td></tr>`).join('')}</tbody></table></div>`
      : `<p class="muted small">${t('Noch keine Ereignisse. Sie entstehen, wenn bestätigte Geräte offline oder wieder online gehen oder neue Geräte auftauchen.')}</p>`;
    $$('[data-ev]', el).forEach(a => a.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +a.dataset.ev); });
  }).catch(() => { });

  const mon = $('#mon', ctx.el);
  mon.onchange = async () => {
    const v = fd(mon);
    try { await api('PUT', `${P}/monitor`, { enabled: !!v.enabled, interval_s: +v.interval_s }); toast(t('gespeichert')); } catch (e) { toast(e.message, true); }
  };
  $$('[data-add]', ctx.el).forEach(b => b.onclick = () => integrationDialog(ctx, null, drv[b.dataset.add]));
  const waits = [];  // Diagramme und Zusatzbereiche: erst fertig, dann zeigen (kein Flackern beim Aktualisieren)
  for (const card of $$('.integ', ctx.el)) {
    const i = r.integrations.find(x => x.id === +card.dataset.id);
    const pb = $('[data-poll]', card);
    if (pb) pb.onclick = async () => { pb.disabled = true; try { await api('POST', `${P}/integrations/${i.id}/poll`); ctx.reload(); } catch (e) { toast(e.message, true); pb.disabled = false; } };
    const eb = $('[data-edit]', card); if (eb) eb.onclick = () => integrationDialog(ctx, i, drv[i.driver]);
    const cb = $('[data-cfg]', card);
    if (cb) cb.onclick = async () => {
      cb.disabled = true;
      try {
        let r = await api('POST', `${P}/integrations/${i.id}/config-backup`);
        if (r.status === 'second_factor') {
          if (!await secondFactor(P, i, r)) { cb.disabled = false; return; }
          r = totpResult || await api('POST', `${P}/integrations/${i.id}/config-backup`);
        }
        toast(r.status === 'new' ? t('Konfiguration gesichert ({n} KB)', { n: Math.max(1, Math.round(r.size / 1024)) }) : t('Konfiguration unverändert seit der letzten Sicherung'));
        ctx.reload();
      } catch (e) { toast(e.message, true); cb.disabled = false; }
    };
    const db_ = $('[data-del]', card);
    if (db_) db_.onclick = async () => {
      if (!await confirmDlg(t('Integration löschen'), t('„{n}“ löschen? Die Geräte bleiben erhalten, die Messwerte werden gelöscht.', { n: h(i.name) }), t('Löschen'))) return;
      await api('DELETE', `${P}/integrations/${i.id}`); ctx.reload();
    };
    $$('[data-dev]', card).forEach(dv => dv.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +dv.dataset.dev); });
    const ch = $('.chartbox', card);
    if (ch) {
      const wanChart = ['fritzbox', 'unifi', 'asuswrt'].includes(i.driver);
      const dnsChart = i.driver === 'dnsfilter';
      const keys = () => dnsChart ? [`i${i.id}:dns:qpm`, `i${i.id}:dns:bpm`] : wanChart ? [`i${i.id}:wan:rx`, `i${i.id}:wan:tx`]
        : [`i${i.id}:port:${card.dataset.port || ch.dataset.port}:rx`, `i${i.id}:port:${card.dataset.port || ch.dataset.port}:tx`];
      const names = dnsChart ? [t('Anfragen/min'), t('blockiert/min')] : wanChart ? [t('Download'), t('Upload')] : [t('empfangen'), t('gesendet')];
      const draw = () => drawChart(ch, ctx.pid, keys(), names, tabIntegrations.since || 7200, dnsChart ? { fmt: v => fmtInt(Math.round(v)) } : {}).catch(() => { });
      if (ctx.canEdit) {
        const pb = document.createElement('button');
        pb.type = 'button'; pb.className = 'sm pinbtn-dyn'; pb.innerHTML = PIN_ICON + ' ' + h(t('An die Übersicht anheften'));
        pb.onclick = () => {
          const port = card.dataset.port || ch.dataset.port;
          pinNow(ctx.pid, dnsChart ? { title: `DNS · ${i.name}`, keys: keys(), names: ['Anfragen/min', 'blockiert/min'], unit: 'count', style: 'bars', mirror: false }
            : wanChart ? { title: `WAN · ${i.name}`, keys: keys(), names: ['Download', 'Upload'], unit: 'bps', style: 'bars', mirror: true }
            : { title: `${i.name} · ${t('Port')} ${port}`, keys: [`i${i.id}:port:${port}:tx`, `i${i.id}:port:${port}:rx`], names: ['gesendet', 'empfangen'], unit: 'bps', style: 'bars', mirror: true });
        };
        ch.after(pb);
      }
      $$('[data-range]', card).forEach(b => b.onclick = () => { tabIntegrations.since = +b.dataset.range; $$('[data-range]', card).forEach(x => x.classList.toggle('on', x === b)); draw(); });
      $$('[data-port]', card).forEach(b => b.onclick = () => { card.dataset.port = b.dataset.port; $$('.pstrip [data-port]', card).forEach(x => x.classList.toggle('sel', x === b)); $('.pname', card).textContent = b.title; draw(); });
      waits.push(draw());
    }
  }
  // Ansicht aktuell halten, solange der Reiter offen ist
  { const hb = document.createElement('div'); hb.style.marginTop = '16px'; ctx.el.appendChild(hb); waits.push(healthPanel(ctx, hb)); }
  { const qb = document.createElement('div'); qb.style.marginTop = '16px'; ctx.el.appendChild(qb); waits.push(quarantinePanel(ctx, qb)); }
  { const sb = document.createElement('div'); sb.className = 'panel'; sb.style.marginTop = '16px'; sb.innerHTML = `<h3>${t('Zeitpläne')}</h3><div></div>`; ctx.el.appendChild(sb); waits.push(scheduleList(ctx, sb.lastElementChild)); }
  { const box = document.createElement('div'); box.id = 'recentact'; box.style.marginTop = '16px'; ctx.el.appendChild(box); waits.push(recentActions(ctx, box)); }
  clearTimeout(tabIntegrations.timer);
  waits.push(speedSettings(ctx, $('#speedbox', ctx.el)), notifySettings(ctx, $('#notifybox', ctx.el)), promPanel(ctx, $('#prombox', ctx.el)));
  await Promise.allSettled(waits);
  // jede Minute aktualisieren: neue Ansicht unsichtbar fertig bauen und dann in einem Schritt tauschen
  tabIntegrations.timer = setTimeout(async () => {
    if (!document.body.contains(ctx.el) || !location.hash.endsWith('/integrationen') || $('#dlg').open) return;
    const fresh = document.createElement('div');
    fresh.id = ctx.el.id;
    try { await tabIntegrations({ ...ctx, el: fresh }); } catch { return; }
    if (document.body.contains(ctx.el) && location.hash.endsWith('/integrationen') && !$('#dlg').open) ctx.el.replaceWith(fresh);
  }, 60000);
  void since;
}

function fritzCard(i) {
  const res = i.result || {}, w = res.wan || {}, info = res.info || {};
  return `<div class="kv">${info.model ? `<span>${t('Modell')}: <b>${h(info.model)}</b></span>` : ''}${info.firmware ? `<span>FRITZ!OS: <b>${h(info.firmware)}</b></span>` : ''}
      ${w.connected != null ? `<span>${t('Internet')}: <b class="${w.connected ? 'okc' : 'offc'}">${w.connected ? t('verbunden') : t('getrennt')}</b></span>` : ''}
      ${w.max_down ? `<span>${t('Leitung')}: <b class="mono">↓ ${fmtBps(w.max_down)} · ↑ ${fmtBps(w.max_up)}</b></span>` : ''}
      ${w.uptime ? `<span>${t('online seit')}: <b>${fmtUptime(w.uptime)}</b></span>` : ''}
      ${res.hosts != null ? `<span>${t('Geräte')}: <b>${res.active} ${t('aktiv')} / ${res.hosts}</b></span>` : ''}
      <span>${t('Mesh-Topologie')}: <b>${res.auth ? t('ja') : t('nein (ohne Anmeldung)')}</b></span></div>
    ${w.rx_bps != null ? `<div class="wan-now"><span>↓ <b class="mono">${fmtBps(w.rx_bps)}</b></span><span>↑ <b class="mono">${fmtBps(w.tx_bps)}</b></span><small class="muted">${t('aktuell')}</small></div>` : ''}
    ${res.wlan?.length ? `<div class="kv">${res.wlan.map(x => `<span>WLAN: <b>${h(x.ssid)}</b> ${x.channel ? `(${t('Kanal')} ${h(x.channel)})` : ''}${x.enabled ? '' : ' – ' + t('aus')}</span>`).join('')}</div>` : ''}
    <div class="row between" style="margin-top:8px"><b class="small">${t('WAN-Traffic')}</b>${rangeButtons(tabIntegrations.since || 7200)}</div>
    <div class="chartbox"></div>
    ${i.summary ? `<p class="muted small">${t('Letzte Abfrage: {n} aktive Geräte, {m} neu im Posteingang, {l} Verbindungen gesetzt.', { n: i.summary.hosts, m: i.summary.new, l: i.summary.links })}</p>` : ''}`;
}

function snmpCard(i) {
  const res = i.result || {}, info = res.info || {}, ports = res.ports || [];
  const first = (ports.find(p => p.oper === 'up') || ports[0] || {}).port_no || 1;
  return `<div class="kv">${info.name ? `<span>${t('Name')}: <b>${h(info.name)}</b></span>` : ''}${info.descr ? `<span>${h(info.descr.slice(0, 80))}</span>` : ''}
      ${info.uptime ? `<span>${t('läuft seit')}: <b>${fmtUptime(info.uptime)}</b></span>` : ''}
      ${ports.length ? `<span>${t('Ports')}: <b>${ports.filter(p => p.oper === 'up').length} ${t('aktiv')} / ${ports.length}</b></span>` : ''}
      ${res.fdb_size != null ? `<span>${t('gelernte MAC-Adressen')}: <b>${res.fdb_size}</b></span>` : ''}</div>
    ${ports.length ? `<div class="pstrip">${ports.map(p => `<button type="button" class="pp ${p.oper} ${p.oper === 'up' ? speedCls(p.speed) : ''}${p.port_no === first ? ' sel' : ''}" data-port="${p.port_no}"
        title="${t('Port')} ${p.port_no}${p.alias ? ' · ' + h(p.alias) : ''} · ${p.oper === 'up' ? (p.speed >= 1000 ? p.speed / 1000 + ' Gbit/s' : p.speed + ' Mbit/s') : t('kein Link')}${p.macs.length ? ' · ' + t('{n} MAC-Adressen', { n: p.macs.length }) : ''}${p.lldp ? ' · LLDP: ' + h(p.lldp.name) : ''}">${p.port_no}</button>`).join('')}</div>
      ${ports.some(p => p.oper === 'up' && speedCls(p.speed)) ? `<div class="legend topo-legend small" style="margin-top:6px"><span><i class="lg up"></i>1 Gbit/s</span>${ports.some(p => p.oper === 'up' && speedCls(p.speed) === 'sp-slow') ? `<span><i class="lg sp-slow"></i>${t('10/100 Mbit/s')}</span>` : ''}${ports.some(p => p.oper === 'up' && speedCls(p.speed) === 'sp-fast') ? `<span><i class="lg sp-fast"></i>${t('ab 2,5 Gbit/s')}</span>` : ''}</div>` : ''}
      <div class="row between" style="margin-top:8px"><b class="small">${t('Traffic')} · <span class="pname">${t('Port')} ${first}</span></b>${rangeButtons(tabIntegrations.since || 7200)}</div>
      <div class="chartbox" data-port="${first}"></div>` : ''}`;
}

function asusCard(i) {
  const r = i.result || {}, info = r.info || {}, s = i.summary || {}, tr = r.traffic || {}, ta = r.analyzer;
  const names = Object.fromEntries((i.devices_by_mac || []).map(x => [x.mac, x.name]));
  const trafficHtml = Object.keys(tr).length ? `<div class="tmon">${Object.entries(tr).filter(([k]) => k !== 'bridge').map(([k, x]) => `<div class="tm"><span class="muted small">${h(t(x.name))}</span>
      <b class="mono">↓ ${fmtBps(k === 'wan' ? x.rx_bps : x.tx_bps)}</b><b class="mono">↑ ${fmtBps(k === 'wan' ? x.tx_bps : x.rx_bps)}</b>
      <small class="muted">${t('gesamt')} ↓ ${fmtBytes(k === 'wan' ? x.rx_total : x.tx_total)} · ↑ ${fmtBytes(k === 'wan' ? x.tx_total : x.rx_total)}</small></div>`).join('')}</div>` : '';
  const topHtml = ta?.clients?.length ? `<div style="margin-top:8px"><b class="small">${t('Letzte 24 Stunden (Traffic Analyzer)')}</b>
      <div class="table-wrap"><table class="compact"><tbody>${ta.clients.slice(0, 8).map(x => `<tr><td>${h(names[x.mac] || x.mac)}</td>
        <td class="mono small">↓ ${fmtBytes(x.rx)}</td><td class="mono small">↑ ${fmtBytes(x.tx)}</td><td class="mono small"><b>${fmtBytes(x.rx + x.tx)}</b></td></tr>`).join('')}</tbody></table></div></div>` : '';
  return `<div class="kv">${info.model ? `<span>${t('Modell')}: <b>${h(info.model)}</b></span>` : ''}${info.firmware ? `<span>Firmware: <b>${h(info.firmware)}</b></span>` : ''}
      ${r.clients != null ? `<span>${t('Clients')}: <b>${r.online} ${t('online')} / ${r.clients}</b> (${t('{n} per WLAN', { n: r.wlan })})</span>` : ''}</div>
    ${r.nodes?.length ? `<div class="kv">${r.nodes.map(n => `<span><span class="dot ${n.online ? 'on' : 'off'}"></span> <b>${h(n.name)}</b> <span class="mono small">${h(n.ip)}</span> <small class="muted">${n.wired_backhaul ? t('LAN-Backhaul') : n.ip === info.ip ? t('Hauptrouter') : t('Mesh')}</small></span>`).join('')}</div>` : ''}
    ${trafficHtml}
    ${tr.wan ? `<div class="row between" style="margin-top:8px"><b class="small">${t('WAN-Traffic')}</b>${rangeButtons(tabIntegrations.since || 7200)}</div><div class="chartbox"></div>` : ''}
    ${topHtml}
    ${s.links != null ? `<p class="muted small">${t('Letzte Abfrage: {n} neu im Posteingang, {l} Verbindungen gesetzt.', { n: s.new, l: s.links })}</p>` : ''}`;
}

/* Zweiter Faktor: Hinweis anzeigen, Status abfragen, bis bestätigt oder abgebrochen. -> true bei Erfolg */
let totpResult = null;
async function secondFactor(P, i, r, { totp = true } = {}) {
  let timer = null;
  totpResult = null;
  const html = `<p>${t('Die FRITZ!Box schützt den Export ihrer Einstellungen mit einem zweiten Faktor. Bitte jetzt bestätigen:')}</p>
    <ol class="steps">${r.button ? `<li>${t('eine <b>beliebige Taste an der FRITZ!Box</b> drücken (z. B. Connect/WPS oder DECT)')}</li>` : ''}
      ${r.dtmf ? `<li>${t('oder an einem angeschlossenen Telefon <b class="mono">{c}</b> wählen', { c: h(r.dtmf) })}</li>` : ''}
      ${totp ? `<li>${t('oder den <b>Code aus der Authenticator-App</b> eingeben (wenn in der FRITZ!Box eingerichtet):')}
        <div class="row" style="margin-top:6px"><input name="totp" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="123456" style="max-width:140px">
        <button type="button" class="sm pri" data-totp>${t('Code senden')}</button></div></li>` : ''}</ol>
    <p class="muted small" id="sfst">${t('Warte auf Bestätigung …')}</p>`;
  const ok = await dialog(t('Bestätigung an der FRITZ!Box'), html, {
    ok: null,
    onOpen: (f, close) => {
      const started = Date.now();
      const send = async () => {
        const code = $('[name=totp]', f).value.replace(/\s/g, '');
        if (!/^\d{6,8}$/.test(code)) { $('.dlg-err', f).textContent = t('Der Code aus der App hat 6 Ziffern'); return; }
        clearInterval(timer); $('[data-totp]', f).disabled = true; $('#sfst', f).textContent = t('Sende Code und exportiere …');
        await api('DELETE', `${P}/integrations/${i.id}/second-factor`).catch(() => { });
        try { totpResult = await api('POST', `${P}/integrations/${i.id}/config-backup`, { totp: code }); close(true); }
        catch (e) { $('.dlg-err', f).textContent = e.message; $('[data-totp]', f).disabled = false; $('#sfst', f).textContent = ''; }
      };
      if ($('[data-totp]', f)) {
        $('[data-totp]', f).onclick = send;
        $('[name=totp]', f).addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); send(); } });
      }
      const err = msg => { clearInterval(timer); const e = $('.dlg-err', f); e.textContent = msg; $('#sfst', f).hidden = true; };
      timer = setInterval(async () => {
        if (!document.body.contains(f) || !$('#dlg').open) return clearInterval(timer);
        try {
          const s = await api('GET', `${P}/integrations/${i.id}/second-factor`);
          if (s.state === 'authenticated') { clearInterval(timer); return close(true); }
          if (s.state !== 'waitingforauth' || Date.now() - started > 180000) {
            err({ blocked: t('Gesperrt – zu viele Versuche. Bis zu 60 Minuten warten.'), anotherauthprocess: t('Eine andere Bestätigung läuft gerade.'),
              disabled: t('Zweiter Faktor ist an der FRITZ!Box ausgeschaltet.'), failure: t('Interner Fehler der FRITZ!Box.') }[s.state] || t('Zeit abgelaufen oder abgebrochen.'));
          }
        } catch (e) { err(e.message); }
      }, 2000);
    },
  });
  clearInterval(timer);
  if (ok !== true) api('DELETE', `${P}/integrations/${i.id}/second-factor`).catch(() => { });
  return ok === true;
}

/* ---------------------------------------------------------------- Schaltaktionen */
const UNDO = [['', 'nicht automatisch'], ['15', 'nach 15 Minuten'], ['60', 'nach 1 Stunde'], ['120', 'nach 2 Stunden'], ['morning', 'morgen um 6:00']];

async function actionsBox(ctx, did, el, port = 0) {
  if (!ctx.isOwner) { el.innerHTML = ''; return; }
  let r;
  try { r = await api('GET', `/api/profiles/${ctx.pid}/devices/${did}/actions${port ? `?port=${port}` : ''}`); } catch { el.innerHTML = ''; return; }
  if (r.ports?.length && !port) {  // Switch: Port wählen, dann seine Aktionen
    el.innerHTML = `<h4>${t('Aktionen')}</h4><div class="row"><label style="margin:0">${t('Switch-Port')}</label>
      <select data-psel style="width:auto"><option value="">${t('– Port wählen –')}</option>${r.ports.map(p => `<option value="${p.port_no}">${p.port_no}${p.name && p.name !== String(p.port_no) ? ' · ' + h(p.name) : ''} – ${p.admin === 'down' ? t('abgeschaltet') : p.oper === 'up' ? t('Link') : t('kein Link')}${p.poe ? ' · PoE' : ''}</option>`).join('')}</select></div><div data-pact></div>`;
    $('[data-psel]', el).onchange = ev => { const sub = $('[data-pact]', el); if (ev.target.value) actionsBox(ctx, did, sub, +ev.target.value); else sub.innerHTML = ''; };
    return;
  }
  if (!r.actions.length) { el.innerHTML = port ? `<p class="muted small">${t('Für diesen Port gibt es keine Aktionen.')}</p>` : ''; return; }
  el.innerHTML = `${port ? '' : `<h4>${t('Aktionen')}</h4>`}<div class="act-list">${r.actions.map((a, n) => `<button type="button" class="sm ${a.danger ? 'warn-btn' : ''}" data-act="${n}"
      ${a.blocked ? `disabled title="${h(t(a.blocked))}"` : `title="${h(t(a.detail))}"`}>${h(t(a.label))}</button>`).join('')}</div>
    ${r.actions.some(a => a.blocked) ? `<p class="muted small">${r.actions.filter(a => a.blocked).map(a => `${h(t(a.label))}: ${h(t(a.blocked))}`).join('<br>')}</p>` : ''}`;
  $$('[data-act]', el).forEach(b => b.onclick = async () => { if (await runAction(ctx, did, r.actions[+b.dataset.act], port)) actionsBox(ctx, did, el, port); });
  if (!port) {
    const box = document.createElement('div'); el.appendChild(box);
    scheduleList(ctx, box, did);
  }
}

const DAY_NAMES = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const daysText = ds => ds.length === 7 ? t('täglich') : ds.join() === '0,1,2,3,4' ? t('Mo–Fr') : ds.join() === '5,6' ? t('Sa, So') : ds.map(i => t(DAY_NAMES[i])).join(', ');

async function scheduleList(ctx, el, did = 0) {
  let r;
  try { r = await api('GET', `/api/profiles/${ctx.pid}/schedules${did ? `?device_id=${did}` : ''}`); } catch { return; }
  if (!r.schedules.length) { el.innerHTML = did ? '' : `<p class="muted small">${t('Noch keine Zeitpläne. Anlegen über die Aktionen eines Geräts → „Zeitplan anlegen“.')}</p>`; return; }
  el.innerHTML = `${did ? `<h4>${t('Zeitpläne')}</h4>` : ''}<div class="table-wrap"><table class="compact"><tbody>
    ${r.schedules.map(s => `<tr class="${s.enabled ? '' : 'off-row'}"><td>${h(t(s.label))}${!did && s.device ? ` · <b>${h(s.device)}</b>` : ''}</td>
      <td class="small mono">${h(daysText(s.days))} ${h(s.start)}${s.end ? '–' + h(s.end) : ''}</td>
      <td class="small muted">${s.enabled && s.next_run ? t('nächster Lauf {d}', { d: h(fmtDate(s.next_run)) }) : !s.enabled ? t('pausiert') : ''}
        ${s.last_result ? `<br><span class="${s.last_result.includes(': done') ? '' : 'errtxt'}">${t('zuletzt')}: ${h(s.last_result)}</span>` : ''}</td>
      <td class="act">${ctx.isOwner ? `<button class="sm" data-st="${s.id}" data-en="${s.enabled ? 0 : 1}">${s.enabled ? t('pausieren') : t('fortsetzen')}</button>
        <button class="sm danger" data-sd="${s.id}">${t('Löschen')}</button>` : ''}</td></tr>`).join('')}</tbody></table></div>`;
  $$('[data-st]', el).forEach(b => b.onclick = async () => { await api('PUT', `/api/profiles/${ctx.pid}/schedules/${b.dataset.st}`, { enabled: !!+b.dataset.en }); scheduleList(ctx, el, did); });
  $$('[data-sd]', el).forEach(b => b.onclick = async () => {
    if (!await confirmDlg(t('Zeitplan löschen'), t('Diesen Zeitplan löschen?'), t('Löschen'))) return;
    await api('DELETE', `/api/profiles/${ctx.pid}/schedules/${b.dataset.sd}`); scheduleList(ctx, el, did);
  });
}

async function healthPanel(ctx, el) {
  let r;
  try { r = await api('GET', `/api/profiles/${ctx.pid}/health`); } catch { return; }
  if (!r.devices.length) { el.innerHTML = ''; return; }
  const ups = r.devices.filter(d => d.firmware?.update);
  const show = r.devices.slice(0, tabIntegrations.healthAll ? 500 : 15);
  el.innerHTML = `<div class="panel"><div class="row between"><h3 style="margin:0">${t('Erreichbarkeit & Firmware')}</h3>
      <span class="muted small">${ups.length ? `<span class="warnc">${ups.length === 1 ? t('1 Firmware-Update verfügbar') : t('{n} Firmware-Updates verfügbar', { n: ups.length })}</span>` : t('Firmware aktuell, soweit bekannt')}</span></div>
    <div class="table-wrap"><table class="compact"><thead><tr><th>${t('Gerät')}</th><th>24 h</th><th>7 ${t('Tage')}</th><th>${t('Ausfälle')}</th><th>${t('Ø Antwortzeit')}</th><th>${t('Firmware')}</th></tr></thead><tbody>
      ${show.map(d => `<tr><td><span class="dot ${d.online === 1 ? 'on' : d.online === 0 ? 'off' : ''}"></span> <a href="#" data-hdev="${d.id}">${h(d.name)}</a></td>
        <td class="mono small">${fmtPct(d.a24)}</td><td class="mono small">${fmtPct(d.a7)}</td>
        <td class="mono small">${d.a24 ? d.a24.outages : '–'}${d.a7 && d.a7.outages ? ` <span class="muted">(${t('7 T')}: ${d.a7.outages})</span>` : ''}</td>
        <td class="mono small">${fmtMs(d.rtt)}</td><td class="small">${d.firmware ? `<span class="mono">${h(d.firmware.installed || '')}</span> ${fwBadge(d.firmware)}` : ''}</td></tr>`).join('')}
    </tbody></table></div>
    ${r.devices.length > 15 ? `<button class="sm link" data-hall>${tabIntegrations.healthAll ? t('weniger anzeigen') : t('alle {n} anzeigen', { n: r.devices.length })}</button>` : ''}
    <p class="muted small">${t('Verfügbarkeit aus der Online-Überwachung (nur der überwachte Zeitraum zählt), Antwortzeit als Mittel der letzten 24 Stunden. Firmware-Angaben liefern FRITZ!Box, ASUS, MikroTik, UniFi, Omada und Proxmox.')}</p></div>`;
  $$('[data-hdev]', el).forEach(a => a.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +a.dataset.hdev); });
  const all = $('[data-hall]', el); if (all) all.onclick = () => { tabIntegrations.healthAll = !tabIntegrations.healthAll; healthPanel(ctx, el); };
}

async function deviceHealth(ctx, did, el) {
  let r;
  try { r = await api('GET', `/api/profiles/${ctx.pid}/devices/${did}/health`); } catch { el.innerHTML = ''; return; }
  const a = r.availability, fw = r.firmware;
  if (!a['24'] && !a['168'] && !fw && r.rtt_24h == null && !r.today && !r.live) { el.innerHTML = ''; return; }
  const cell = (x, label) => `<div class="hcell"><span class="muted small">${t(label)}</span><b class="mono">${fmtPct(x)}</b>${x ? `<span class="small muted">${x.outages === 1 ? t('1 Ausfall') : t('{n} Ausfälle', { n: x.outages })}${x.longest_s ? ' · ' + t('längster {d}', { d: fmtDur(x.longest_s) }) : ''}</span>` : ''}</div>`;
  el.innerHTML = `<h4>${t('Erreichbarkeit')}</h4>
    ${fw?.installed ? `<p class="small">${t('Firmware')}: <b class="mono">${h(fw.installed)}</b> <span class="muted">· ${t('Quelle')}: ${h(fw.source)}</span></p>` : ''}
    ${r.live ? `<p class="small">${t('Gerade')}: <b class="mono">↓ ${fmtBps(r.live.down)} · ↑ ${fmtBps(r.live.up)}</b> <span class="muted">· ${h(r.live.source)}</span></p>` : ''}
    ${r.today ? `<p class="small">${t('Letzte 24 Stunden')}: <b class="mono">↓ ${fmtBytes(r.today.rx)} · ↑ ${fmtBytes(r.today.tx)}</b> <span class="muted">· ${h(r.today.source)}</span></p>` : ''}
    ${a['24'] || a['168'] ? `<div class="hcells">${cell(a['24'], '24 Stunden')}${cell(a['168'], '7 Tage')}${cell(a['720'], '30 Tage')}
      <div class="hcell"><span class="muted small">${t('Ø Antwortzeit (24 h)')}</span><b class="mono">${fmtMs(r.rtt_24h)}</b></div></div>` : ''}
    ${r.rtt_24h != null ? `<div class="row between" style="margin-top:8px"><b class="small">${t('Antwortzeit')}</b><span class="row">${ctx.canEdit ? pinBtn({ title: `${r.name || ''} · ${t('Antwortzeit')}`.replace(/^ · /, ''), keys: [`d${did}:rtt`], names: ['Antwortzeit'], unit: 'ms', style: 'line' }) : ''}${rangeButtons(deviceHealth.since || 86400)}</span></div><div class="chartbox"></div>` : ''}`;
  const ch = $('.chartbox', el);
  if (ch) {
    const draw = () => drawChart(ch, ctx.pid, [`d${did}:rtt`], [t('Antwortzeit')], deviceHealth.since || 86400, { fmt: fmtMs, height: 120 }).catch(() => { });
    $$('[data-range]', el).forEach(b => b.onclick = () => { deviceHealth.since = +b.dataset.range; $$('[data-range]', el).forEach(x => x.classList.toggle('on', x === b)); draw(); });
    draw();
  }
}

async function quarantinePanel(ctx, el) {
  let r;
  try { r = await api('GET', `/api/profiles/${ctx.pid}/quarantine`); } catch { return; }
  const act = r.devices.filter(x => x.status === 'active' || x.status === 'error' || x.status === 'release_failed');
  el.innerHTML = `<div class="panel"><div class="row between"><h3 style="margin:0">${t('Quarantäne für neue Geräte')}</h3>
      ${r.owner ? `<label class="chk" style="margin:0"><input type="checkbox" data-qen ${r.settings.enabled ? 'checked' : ''} ${r.available ? '' : 'disabled'}> ${t('eingeschaltet')}</label>` : ''}</div>
    <p class="muted small">${r.available ? t('Neue Geräte, die nach dem Einschalten auftauchen, bekommen über die FRITZ!Box keinen Internetzugang, bis du sie im Posteingang übernimmst. Das Heimnetz bleibt erreichbar. Ausgenommen sind Infrastruktur, díktyo selbst und das Gastnetz.')
      : t('Dafür wird eine FRITZ!Box-Integration mit Benutzer gebraucht.')}</p>
    ${r.owner && r.available ? `<label class="chk small"><input type="checkbox" data-qrand ${r.settings.random ? 'checked' : ''}> ${t('auch Geräte mit zufälliger (privater) MAC-Adresse')}</label>` : ''}
    ${act.length ? `<div class="table-wrap"><table class="compact"><tbody>${act.map(x => `<tr><td><b>${h(x.device)}</b> <span class="mono small">${h(x.ip)}</span></td>
        <td class="small">${x.status === 'active' ? `<span class="warnc">${t('gesperrt seit {d}', { d: h(fmtDate(x.since)) })}</span>` : `<span class="errtxt">${h(x.message || x.status)}</span>`}</td>
        <td class="act">${x.device_id ? `<button class="sm" data-qopen="${x.device_id}">${t('Gerät öffnen')}</button>` : ''}${r.owner ? `<button class="sm" data-qrel="${x.id}">${t('Freigeben')}</button>` : ''}</td></tr>`).join('')}
      </tbody></table></div>` : r.settings.enabled ? `<p class="muted small">${t('Zurzeit ist kein Gerät in Quarantäne.')}</p>` : ''}</div>`;
  const save = async () => {
    try { await api('PUT', `/api/profiles/${ctx.pid}/quarantine`, { enabled: $('[data-qen]', el).checked, random: $('[data-qrand]', el) ? $('[data-qrand]', el).checked : true }); toast(t('gespeichert')); quarantinePanel(ctx, el); }
    catch (e) { toast(e.message, true); quarantinePanel(ctx, el); }
  };
  const en = $('[data-qen]', el); if (en) en.onchange = save;
  const rd = $('[data-qrand]', el); if (rd) rd.onchange = save;
  $$('[data-qopen]', el).forEach(b => b.onclick = () => deviceDialog(ctx, +b.dataset.qopen));
  $$('[data-qrel]', el).forEach(b => b.onclick = async () => {
    const P = `/api/profiles/${ctx.pid}`;
    try {
      let x = await api('POST', `${P}/quarantine/${b.dataset.qrel}/release`);
      if (x.status === 'second_factor') {
        const q = r.devices.find(y => y.id === +b.dataset.qrel);
        if (!await secondFactor(P, { id: q.integration_id || 0 }, x, { totp: false })) return;
        x = await api('POST', `${P}/quarantine/${b.dataset.qrel}/release`);
      }
      toast(t('Freigegeben')); quarantinePanel(ctx, el);
    } catch (e) { toast(e.message, true); }
  });
}

async function runAction(ctx, did, a, port = 0) {
  const P = `/api/profiles/${ctx.pid}`;
  const v = await dialog(t(a.label), `<p>${h(t(a.detail)) || t('Aktion ausführen?')}</p>
    <div class="row mode-sw"><label class="chk"><input type="radio" name="mode" value="now" checked> ${t('Jetzt ausführen')}</label>
      <label class="chk"><input type="radio" name="mode" value="plan"> ${t('Zeitplan anlegen')}</label></div>
    <div data-now>${a.undo ? `<label>${t('Automatisch zurückschalten')}</label><select name="undo">${UNDO.map(([k, n]) => `<option value="${k}">${t(n)}</option>`).join('')}</select>` : ''}
      <p class="muted small">${t('Vorher sichert díktyo die Konfiguration, falls die letzte Sicherung älter als eine Stunde ist. Die Aktion wird protokolliert.')}</p></div>
    <div data-plan hidden><label>${t('Wochentage')}</label><div class="row days">${DAY_NAMES.map((n, i) => `<label class="chk"><input type="checkbox" name="d${i}" ${i < 5 ? 'checked' : ''}> ${t(n)}</label>`).join('')}</div>
      <div class="grid2"><div><label>${a.undo ? t('Von') : t('Um')}</label><input name="start" type="time" value="${a.kind === 'internet' ? '22:00' : '03:00'}"></div>
        ${a.undo ? `<div><label>${t('Bis (dann zurück)')}</label><input name="end" type="time" value="${a.kind === 'internet' ? '06:30' : '07:00'}"></div>` : ''}</div>
      <p class="muted small">${a.undo ? t('Zu Beginn schaltet díktyo, am Ende zurück – nur an diesen Zeitpunkten; Änderungen von Hand dazwischen bleiben bestehen.') : t('Läuft an den gewählten Tagen einmal zur angegebenen Uhrzeit.')}
        ${a.kind === 'internet' || a.kind === 'wlan' ? ' ' + t('Verlangt die FRITZ!Box für diese Aktion eine Bestätigung, kann der Zeitplan nicht automatisch schalten – díktyo meldet das dann.') : ''}</p></div>`,
    { ok: t('Ausführen'), danger: a.danger, onOk: f => fd(f), onOpen: f => {
      $$('[name=mode]', f).forEach(r => r.onchange = () => {
        const plan = $('[name=mode]:checked', f).value === 'plan';
        $('[data-plan]', f).hidden = !plan; $('[data-now]', f).hidden = plan;
        $('button[type=submit]', f).textContent = plan ? t('Zeitplan speichern') : t('Ausführen');
      });
    } });
  if (!v) return false;
  if (v.mode === 'plan') {
    const days = DAY_NAMES.map((_, i) => v[`d${i}`] ? i : null).filter(x => x !== null);
    try {
      await api('POST', `${P}/devices/${did}/schedules`, { key: a.key, days, start: v.start, end: v.end || null, port });
      toast(t('Zeitplan gespeichert'));
      return true;
    } catch (e) { toast(e.message, true); return false; }
  }
  const body = { key: a.key, undo: v.undo || null, port };
  try {
    let r = await api('POST', `${P}/devices/${did}/actions`, body);
    if (r.status === 'second_factor') {
      if (!await secondFactor(P, { id: a.integration_id }, r, { totp: false })) return false;
      r = await api('POST', `${P}/devices/${did}/actions`, body);
    }
    toast([r.message, r.backup, r.undo_at ? t('Zurück um {d}', { d: fmtDate(r.undo_at) }) : ''].filter(Boolean).join(' · '));
    return true;
  } catch (e) { toast(e.message, true); return false; }
}

async function recentActions(ctx, el) {
  let r;
  try { r = await api('GET', `/api/profiles/${ctx.pid}/actions`); } catch { return; }
  if (!r.actions.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="panel"><h3>${t('Letzte Aktionen')}</h3><div class="table-wrap"><table class="compact"><tbody>
    ${r.actions.map(x => `<tr><td class="mono small">${h(fmtDate(x.created))}</td><td>${h(t(x.label))}${x.device ? ` · <b>${h(x.device)}</b>` : ''}</td>
      <td class="small ${x.status === 'done' ? 'okc' : 'errtxt'}">${h(x.status === 'done' ? (x.message || t('erledigt')) : x.message)}</td>
      <td class="small muted">${h(x.user)}</td>
      <td class="small">${x.undo_at && !x.undone ? `${t('zurück um {d}', { d: h(fmtDate(x.undo_at)) })} ${ctx.isOwner ? `<button class="sm link" data-cu="${x.id}">${t('abbrechen')}</button>` : ''}`
        : x.undone ? `<span class="${(x.undo_result || '').startsWith('done') ? 'muted' : 'errtxt'}">${t('zurückgeschaltet')}${(x.undo_result || '').startsWith('done') ? '' : ': ' + h(x.undo_result)}</span>` : ''}</td></tr>`).join('')}
  </tbody></table></div></div>`;
  $$('[data-cu]', el).forEach(b => b.onclick = async () => { await api('DELETE', `/api/profiles/${ctx.pid}/actions/${b.dataset.cu}/undo`); recentActions(ctx, el); });
}

const fmtInt = v => v == null ? '–' : (+v).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE');

function dnsCard(i) {
  const r = i.result || {}, s = r.summary || {}, inf = r.info || {}, cl = r.clients || [];
  const byMac = Object.fromEntries((i.devices_by_mac || []).map(x => [x.ip || x.mac, x]));
  return `<div class="kv"><span>${h(inf.kind === 'adguard' ? 'AdGuard Home' : 'Pi-hole')} <b>${h(inf.version || '')}</b></span>
      <span>${inf.kind === 'adguard' ? t('Schutz') : t('Werbeblocker')}: <b class="${inf.blocking ? 'okc' : 'offc'}">${inf.blocking ? t('an') : t('aus')}</b></span>
      <span>${t('Anfragen')}: <b class="mono">${fmtInt(s.queries)}</b></span><span>${t('blockiert')}: <b class="mono">${fmtInt(s.blocked)} (${(s.pct ?? 0).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE')} %)</b></span>
      ${s.listed ? `<span>${t('Sperrliste')}: <b class="mono">${fmtInt(s.listed)}</b> ${t('Domains')}</span>` : ''}</div>
    <div class="row between" style="margin-top:8px"><b class="small">${t('Anfragen je Minute')}</b>${rangeButtons(tabIntegrations.since || 7200)}</div><div class="chartbox"></div>
    ${cl.length ? `<div class="table-wrap"><table class="compact"><thead><tr><th>${t('Gerät')}</th><th>${t('Anfragen')}</th><th>${t('blockiert')}</th><th>%</th></tr></thead><tbody>
      ${cl.slice(0, 15).map(x => { const dv = byMac[x.ip]; return `<tr><td>${dv ? `<a href="#" data-dev="${dv.id}">${h(dv.name)}</a>` : h(x.name || x.ip)} <span class="mono muted small">${h(x.ip)}</span></td>
        <td class="mono small">${fmtInt(x.queries)}</td><td class="mono small">${fmtInt(x.blocked)}</td><td class="mono small">${x.pct != null ? x.pct.toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE') : '–'}</td></tr>`; }).join('')}</tbody></table></div>
      <p class="muted small">${t('Zeitraum: {w}', { w: h(t(inf.window || '24 h')) })}${r.top_domains?.length ? ` · ${t('Meistblockiert')}: ${r.top_domains.slice(0, 5).map(d => h(d.domain)).join(', ')}` : ''}</p>` : ''}`;
}

function shellyCard(i) {
  const r = i.result || {}, devs = r.devices || [];
  const total = devs.reduce((a, d) => a + (d.power_w || 0), 0);
  const byIp = Object.fromEntries((i.devices_by_mac || []).map(x => [x.ip, x]));
  return `<div class="kv"><span>${t('Geräte')}: <b>${devs.length}</b></span><span>${t('Leistung zusammen')}: <b class="mono">${fmtW(total)}</b></span></div>
    ${devs.length ? `<div class="table-wrap"><table class="compact"><thead><tr><th>${t('Gerät')}</th><th>${t('Modell')}</th><th>${t('Ausgänge')}</th><th>${t('Leistung')}</th><th>${t('Energie')}</th><th>${t('WLAN')}</th><th>${t('Firmware')}</th><th></th></tr></thead><tbody>
      ${devs.map(d => { const dv = byIp[d.ip]; return `<tr><td>${dv ? `<a href="#" data-dev="${dv.id}">${h(dv.name)}</a>` : h(d.name || d.ip)} <span class="mono muted small">${h(d.ip)}</span>
        ${dv && d.name && d.name !== dv.name ? `<div class="muted small">${t('im Gerät')}: ${h(d.name)}</div>` : ''}</td>
        <td class="small">${h(d.kind === 'tasmota' ? 'Tasmota' : `Shelly Gen${d.gen || 1}`)} · ${h(d.model || '')}</td>
        <td>${(d.channels || []).map(c => `<span class="badge ${c.on ? 'ok' : ''}" title="${h(c.name)}">${c.on ? t('an') : t('aus')}</span>`).join(' ') || '<span class="muted">–</span>'}</td>
        <td class="mono small">${fmtW(d.power_w)}</td><td class="mono small">${d.energy_kwh != null ? `${d.energy_kwh.toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: 1 })} kWh` : '–'}</td>
        <td class="mono small">${d.rssi != null ? (d.kind === 'tasmota' ? `${d.rssi} %` : `${d.rssi} dBm`) : '–'}</td>
        <td class="small"><span class="mono">${h(d.firmware?.installed || '')}</span> ${fwBadge(d.firmware)}</td>
        <td><a href="http://${h(d.ip)}/" target="_blank" rel="noopener noreferrer" title="${h(t('Weboberfläche öffnen'))}">↗</a></td></tr>`; }).join('')}</tbody></table></div>`
    : `<p class="muted small">${t('Noch kein Gerät gefunden. Mit „auto“ zuerst einen Netzscan laufen lassen oder IPs eintragen.')}</p>`}`;
}

/* Gerätedialog: Leistung eines Shelly/Tasmota mit Verlauf */
function smartBox(ctx, d, el) {
  const s = d.smart;
  if (!s) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="row between" style="margin-top:22px"><h4 style="margin:0;border:0;padding:0">${t('Leistung')} <small class="muted">· ${h(s.kind === 'tasmota' ? 'Tasmota' : `Shelly Gen${s.gen || 1}`)}${s.device_name ? ' · ' + t('im Gerät') + ': ' + h(s.device_name) : ''}</small></h4>
      ${webLink(s.ip)}</div>${fwStuck(d.firmware_info || null, s.ip)}
    <div class="speed-now"><span>${t('Jetzt')} <b class="mono">${fmtW(s.power_w)}</b></span>
      ${s.energy_kwh != null ? `<span>${t('Energie gesamt')} <b class="mono">${s.energy_kwh.toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: 2 })} kWh</b></span>` : ''}
      ${s.voltage ? `<span>${t('Spannung')} <b class="mono">${(+s.voltage).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: 1 })} V</b></span>` : ''}
      ${(s.channels || []).map(c => `<span>${h(t(c.name))} <b class="${c.on ? 'okc' : 'offc'}">${c.on ? t('an') : t('aus')}</b></span>`).join('')}</div>
    <div class="row between" style="margin-top:6px"><span class="muted small">${t('Stand {d}', { d: h(fmtDate(s.ts)) })}</span><span class="row">${ctx.canEdit ? pinBtn({ title: `${d.name} · ${t('Leistung')}`, keys: [`d${d.id}:power`], names: ['Leistung'], unit: 'W', style: 'line' }) : ''}${rangeButtons(smartBox.since || 86400)}</span></div>
    <div class="chartbox" data-power></div>`;
  const draw = () => drawChart($('[data-power]', el), ctx.pid, [`d${d.id}:power`], [t('Leistung')], smartBox.since || 86400, { fmt: fmtW, height: 110 }).catch(() => { });
  $$('[data-range]', el).forEach(b => b.onclick = () => { smartBox.since = +b.dataset.range; $$('[data-range]', el).forEach(x => x.classList.toggle('on', x === b)); draw(); });
  draw();
}

function dockerCard(i) {
  const r = i.result || {}, info = r.info || {}, cts = r.containers || [];
  return `<div class="kv">${info.version ? `<span>Docker: <b>${h(info.version)}</b></span>` : ''}${info.os ? `<span>${h(info.os)}</span>` : ''}
      <span>${t('Container')}: <b>${cts.filter(x => x.state === 'running').length} ${t('laufen')} / ${cts.length}</b></span></div>
    ${cts.length ? `<div class="kv">${cts.slice(0, 40).map(x => `<span title="${h(x.image)} · ${h(x.status)}${x.ports.length ? ' · ' + h(x.ports.join(', ')) : ''}"><span class="dot ${x.state === 'running' ? 'on' : 'off'}"></span> ${h(x.name)}</span>`).join('')}</div>` : ''}`;
}

function mtCard(i) {
  const r = i.result || {}, info = r.info || {}, w = r.wan || {};
  return `<div class="kv">${info.model ? `<span>${t('Modell')}: <b>${h(info.model)}</b></span>` : ''}${info.version ? `<span>${i.driver === 'opnsense' ? 'Version' : 'RouterOS'}: <b>${h(info.version)}</b></span>` : ''}
      ${info.uptime ? `<span>${t('läuft seit')}: <b>${h(info.uptime)}</b></span>` : ''}${info.cpu != null ? `<span>CPU: <b>${h(info.cpu)} %</b></span>` : ''}
      ${r.clients != null ? `<span>${t('Clients')}: <b>${r.online} ${t('online')} / ${r.clients}</b>${r.wifi?.length ? ` (${t('{n} per WLAN', { n: r.wlan })})` : ''}</span>` : ''}</div>
    ${r.wifi?.length ? `<div class="kv">${r.wifi.map(x => `<span><span class="dot ${x.enabled ? 'on' : 'off'}"></span> WLAN <b>${h(x.ssid || x.iface)}</b> ${x.band ? `<small class="muted">${h(x.band)}</small>` : ''}</span>`).join('')}</div>` : ''}
    ${w.rx_bps != null ? `<div class="wan-now"><span>↓ <b class="mono">${fmtBps(w.rx_bps)}</b></span><span>↑ <b class="mono">${fmtBps(w.tx_bps)}</b></span><small class="muted">WAN (${h(w.iface)})</small></div>` : ''}
    ${snmpCard({ ...i, result: { ...r, info: {} } })}`;
}

function ctrlCard(i) {
  const r = i.result || {}, s = i.summary || {}, w = r.wan || {};
  const label = { router: t('Gateway'), switch: t('Switch'), ap: t('Access Point') };
  return `<div class="kv">${r.info?.sites?.length ? `<span>${t('Sites')}: <b>${h(r.info.sites.join(', '))}</b></span>` : ''}
      ${r.clients != null ? `<span>${t('Clients')}: <b>${r.clients}</b> (${t('{n} per WLAN', { n: r.wlan })})</span>` : ''}</div>
    ${r.devices?.length ? `<div class="kv">${r.devices.map(d => `<span><span class="dot ${d.online ? 'on' : 'off'}"></span> <b>${h(d.name)}</b> <span class="mono small">${h(d.ip)}</span>
      <small class="muted">${h(label[d.type] || d.model)}${d.clients ? ' · ' + t('{n} Clients', { n: d.clients }) : ''}</small></span>`).join('')}</div>` : ''}
    ${w.rx_bps != null ? `<div class="wan-now"><span>↓ <b class="mono">${fmtBps(w.rx_bps)}</b></span><span>↑ <b class="mono">${fmtBps(w.tx_bps)}</b></span><small class="muted">${t('WAN aktuell')}</small></div>
      <div class="row between" style="margin-top:8px"><b class="small">${t('WAN-Traffic')}</b>${rangeButtons(tabIntegrations.since || 7200)}</div><div class="chartbox"></div>` : ''}
    ${s.links != null ? `<p class="muted small">${t('Letzte Abfrage: {n} neu im Posteingang, {l} Verbindungen gesetzt.', { n: s.new, l: s.links })}</p>` : ''}`;
}

function pveCard(i) {
  const r = i.result || {}, s = i.summary || {};
  return `<div class="kv">${r.info?.version ? `<span>Proxmox VE: <b>${h(r.info.version)}</b></span>` : ''}
      ${r.guests != null ? `<span>${t('VMs und Container')}: <b>${r.running} ${t('laufen')} / ${r.guests}</b></span>` : ''}
      ${(r.nodes || []).map(n => `<span><span class="dot ${n.online ? 'on' : 'off'}"></span> <b>${h(n.name)}</b> <span class="mono small">${h(n.ip)}</span></span>`).join('')}</div>
    ${s.links != null ? `<p class="muted small">${t('Letzte Abfrage: {n} neu im Posteingang, {l} Verbindungen gesetzt.', { n: s.new, l: s.links })}</p>` : ''}`;
}

function haCard(i) {
  const s = i.summary || {}, r = i.result || {};
  return `<div class="kv">${r.info?.devices != null ? `<span>${t('HA-Geräte mit MAC')}: <b>${r.info.devices}</b></span>` : ''}
      ${s.matched != null ? `<span>${t('zugeordnet')}: <b>${s.matched}</b></span><span>${t('Namen übernommen')}: <b>${s.renamed}</b></span><span>${t('Standorte gesetzt')}: <b>${s.located}</b></span>` : ''}
      ${s.messages != null ? `<span>MQTT: <b>${t('{n} Geräte gemeldet', { n: s.published })}, ${t('{n} Ereignisse', { n: s.events })}</b></span>` : ''}</div>`;
}

async function integrationDialog(ctx, i, drv) {
  const P = `/api/profiles/${ctx.pid}`;
  const { devices } = await api('GET', `${P}/devices`);
  i = i || { driver: drv.key, interval_s: drv.interval, enabled: true, port: drv.fields.find(f => f.key === 'port')?.default };
  const val = f => f.secret ? (i.secrets?.[f.key] || (i.id ? '' : f.default ?? '')) : (i[f.key] ?? i.options?.[f.key] ?? (i.id && f.type !== 'select' ? '' : f.default ?? ''));
  const show = f => f.show ? Object.entries(f.show).map(([k, v]) => `data-show-k="${k}" data-show-v="${h(v)}"`).join(' ') : '';
  const steps = DRIVER_STEPS[drv.key];
  const fields = drv.fields.map(f => `<div ${show(f)} ${f.wide ? 'style="grid-column:1/-1"' : ''}><label>${t(f.label)}</label>${f.type === 'select'
    ? `<select name="${f.key}">${f.options.map(([k, n]) => `<option value="${h(k)}" ${k === val(f) ? 'selected' : ''}>${h(t(n))}</option>`).join('')}</select>`
    : f.type === 'textarea' ? `<textarea name="${f.key}" rows="5" class="mono small" autocomplete="off" spellcheck="false" ${f.placeholder ? `placeholder="${h(f.placeholder)}"` : ''}>${h(val(f))}</textarea>`
    : f.type === 'sshpub' ? `<div class="sshpub" data-sshpub><p class="muted small">${t('wird erzeugt …')}</p></div>`
    : `<input name="${f.key}" type="${f.type === 'password' ? 'password' : f.type === 'number' ? 'number' : 'text'}" autocomplete="off" value="${h(val(f))}" ${f.placeholder ? `placeholder="${h(f.placeholder)}"` : ''} ${f.required ? 'required' : ''}>`}</div>`).join('');
  const res = await dialog(i.id ? i.name : t(drv.name), `
    ${steps ? `<ol class="steps">${steps.map(x => `<li>${t(x)}</li>`).join('')}</ol>` : ''}
    <p class="muted small" style="margin-top:0">${t(DRIVER_HELP[drv.key])}</p>
    <div class="grid2"><div><label>${t('Name')}</label><input name="name" value="${h(i.name || t(drv.name))}"></div>${fields}
      <div><label>${t('Abfrage alle')}</label><select name="interval_s">${[30, 60, 300, 900].map(v => `<option value="${v}" ${v === i.interval_s ? 'selected' : ''}>${v < 60 ? v + ' s' : v / 60 + ' min'}</option>`).join('')}</select></div>
      <div><label>${t('Gerät in díktyo')}</label><select name="device_id"><option value="">${t('– automatisch zuordnen –')}</option>${devices.filter(d => d.status !== 'ignored').sort((a, b) => cmp(a.name, b.name)).map(d => `<option value="${d.id}" ${d.id === i.device_id ? 'selected' : ''}>${h(d.name)}</option>`).join('')}</select></div>
      <div><label>&nbsp;</label><label class="chk"><input type="checkbox" name="enabled" ${i.enabled ? 'checked' : ''}> ${t('aktiv')}</label></div></div>
    <div class="row" style="margin-top:12px"><button type="button" class="sm" data-test>${t('Verbindung testen')}</button>
      ${drv.diagnose ? `<button type="button" class="sm" data-diag title="${h(t('Prüft Schritt für Schritt, was das Gerät liefert'))}">${t('Diagnose')}</button>` : ''}<span class="small" id="testres"></span></div>
    <div id="diagres"></div>`, {
    wide: true,
    onOpen: f => {
      const vis = () => $$('[data-show-k]', f).forEach(el => { const sel = $(`[name=${el.dataset.showK}]`, f); el.style.display = !sel || sel.value === el.dataset.showV ? '' : 'none'; });
      $$('select', f).forEach(sel => sel.addEventListener('change', vis));
      vis();
      // díktyos öffentlicher SSH-Schlüssel zum Hochladen auf das Gerät
      const pubBox = $('[data-sshpub]', f);
      const loadPub = async () => {
        if (!pubBox || pubBox.dataset.done) return;
        pubBox.dataset.done = '1';
        try {
          const k = await api('GET', '/api/ssh-key');
          pubBox.innerHTML = `<textarea readonly rows="3" class="mono small" spellcheck="false">${h(k.public)}</textarea>
            <div class="row" style="margin-top:6px"><button type="button" class="sm" data-copy>${t('Kopieren')}</button>
              <a class="btn sm" download="diktyo.pub" href="data:text/plain;charset=utf-8,${encodeURIComponent(k.public + '\n')}">${t('Als Datei (diktyo.pub)')}</a></div>
            <p class="muted small">${t('Am Gerät als „authorized key“ hinterlegen (Zyxel: Maintenance → SSH Authorized Keys → Import, danach Save). Benutzer wie oben, meist admin. Der private Schlüssel bleibt verschlüsselt in díktyo.')}</p>`;
          $('[data-copy]', pubBox).onclick = () => { navigator.clipboard?.writeText(k.public).then(() => toast(t('kopiert')), () => { $('textarea', pubBox).select(); }); };
        } catch (e) { pubBox.innerHTML = `<p class="errtxt small">${h(e.message)}</p>`; delete pubBox.dataset.done; }
      };
      const authSel = $('[name=ssh_auth]', f);
      if (authSel) { authSel.addEventListener('change', () => authSel.value === 'key_diktyo' && loadPub()); if (authSel.value === 'key_diktyo') loadPub(); }
      // MQTT-Broker aus der HA-Adresse vorschlagen
      const hostIn = $('[name=host]', f), mq = $('[name=mqtt_host]', f);
      if (hostIn && mq) hostIn.addEventListener('change', () => {
        try { const u = new URL(hostIn.value.includes('://') ? hostIn.value : 'http://' + hostIn.value); if (!mq.value || mq.value === 'core-mosquitto') mq.value = u.hostname; } catch { }
      });
      $('[data-test]', f).onclick = async ev => {
        ev.target.disabled = true; $('#testres', f).textContent = t('prüfe …'); $('#testres', f).className = 'small muted';
        try {
          const r = await api('POST', `${P}/integrations/test`, { ...fd(f), driver: drv.key, id: i.id });
          const x = r.result;
          $('#testres', f).textContent = '✓ ' + (drv.key === 'fritzbox' ? `${x.model} · FRITZ!OS ${x.firmware} · ${t('{n} Geräte', { n: x.hosts })} · ${x.auth ? t('Anmeldung ok, Mesh-Topologie verfügbar') : t('ohne Anmeldung (Mesh-Topologie nicht verfügbar)')}`
            : drv.key === 'snmp' ? `${x.name} · ${x.descr}` : drv.key === 'asuswrt' ? `${x.model} · Firmware ${x.firmware} · ${t('{n} Clients', { n: x.clients })} · ${t('{n} Mesh-Knoten', { n: x.nodes })}`
            : drv.key === 'proxmox' ? `Proxmox VE ${x.version} · ${t('{n} VMs und Container', { n: x.guests })}`
            : drv.key === 'opnsense' ? `${x.name || 'OPNsense'} · OPNsense ${x.version} · ${t('{n} Schnittstellen', { n: x.ports })} · ${t('{n} Clients', { n: x.clients })}`
            : drv.key === 'dnsfilter' ? `${x.kind === 'adguard' ? 'AdGuard Home' : 'Pi-hole'} ${h(x.version || '')} · ${t('{q} Anfragen, {b} blockiert', { q: fmtInt(x.queries), b: fmtInt(x.blocked) })} · ${t('{n} Geräte, {m} mit Namen', { n: x.clients, m: x.names })}`
            : drv.key === 'shelly' ? t('{n} Geräte ({s} Shelly, {t} Tasmota) · zusammen {w}', { n: x.devices, s: x.shelly, t: x.tasmota, w: fmtW(x.power_w) })
            : drv.key === 'docker' ? `Docker ${x.version} · ${h(x.os)} · ${t('{n} von {m} Containern laufen', { n: x.running, m: x.containers })}`
            : drv.key === 'mikrotik' ? `${x.model} · RouterOS ${x.version} · ${t('{n} Ports', { n: x.ports })} · ${t('{n} Clients', { n: x.clients })}${x.wifi ? ' · ' + t('{n} WLAN', { n: x.wifi }) : ''}`
            : ['omada', 'unifi'].includes(drv.key) ? [x.version ? `UniFi Network ${x.version}` : '', `${t('Sites')}: ${x.sites}`, t('{n} Geräte', { n: x.devices }), t('{n} Clients', { n: x.clients })].filter(Boolean).join(' · ')
            : [x.devices != null ? t('{n} HA-Geräte mit MAC, {m} Bereiche', { n: x.devices, m: x.areas }) : '', x.mqtt ? t('MQTT-Anmeldung ok') : ''].filter(Boolean).join(' · '));
          $('#testres', f).className = 'small okc';
        } catch (e) { $('#testres', f).textContent = '✗ ' + e.message; $('#testres', f).className = 'small errtxt'; }
        ev.target.disabled = false;
      };
      const db = $('[data-diag]', f);
      if (db) db.onclick = async () => {
        db.disabled = true; const out = $('#diagres', f); out.innerHTML = `<p class="muted small">${t('Diagnose läuft (bis zu 15 s) …')}</p>`;
        try {
          const r = await api('POST', `${P}/integrations/diagnose`, { ...fd(f), driver: drv.key, id: i.id });
          out.innerHTML = `<ul class="diag">${r.steps.map(s => `<li class="${s.ok === true ? 'ok' : s.ok === false ? 'bad' : 'info'}"><b>${h(t(s.title))}</b><div class="small">${h(ts(s.detail))}</div></li>`).join('')}</ul>
            <p class="diag-sum"><b>${t('Ergebnis')}:</b> ${h(ts(r.summary))}</p>`;
        } catch (e) { out.innerHTML = `<p class="errtxt small">${h(e.message)}</p>`; }
        db.disabled = false;
      };
    },
    onOk: f => {
      const v = fd(f);
      const body = { ...v, driver: drv.key, enabled: !!v.enabled, interval_s: +v.interval_s, device_id: v.device_id ? +v.device_id : null };
      return i.id ? api('PUT', `${P}/integrations/${i.id}`, body) : api('POST', `${P}/integrations`, body);
    },
  });
  if (res) {
    toast(t('gespeichert'));
    try { await api('POST', `${P}/integrations/${res.id}/poll`); } catch { }
    ctx.reload();
  }
}

window.INV.integrationen = tabIntegrations;
