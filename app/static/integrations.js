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
    'Für Konfigurations-Backups zusätzlich SSH-Benutzer und -Passwort des Switches eintragen (díktyo liest „show running-config“).',
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
DRIVER_HELP.mikrotik = 'díktyo liest Ports, Clients (DHCP, ARP, Bridge, WLAN), Nachbarn und WAN; schalten nur über „Aktionen“ mit Bestätigung.';
DRIVER_STEPS.mikrotik = [
  'RouterOS 7 nötig (System → Packages zeigt die Version). Die REST-API läuft über den Dienst <b>www-ssl</b> (HTTPS) – ab 7.9 alternativ <b>www</b> (HTTP, nur im eigenen Netz).',
  'Für HTTPS braucht www-ssl ein Zertifikat. Im Terminal (WinBox → New Terminal):<pre>/certificate add name=diktyo common-name=diktyo days-valid=3650\n/certificate sign diktyo\n/ip service set www-ssl certificate=diktyo disabled=no</pre>',
  'Eigenen Benutzer anlegen – nur lesen:<pre>/user group add name=diktyo-read policy=read,rest-api,api,ssh,!local,!telnet,!ftp,!winbox,!web\n/user add name=diktyo group=diktyo-read password=GEHEIM</pre>Für <b>Aktionen</b> (Port, PoE, WLAN, Neustart, Wake-on-LAN) stattdessen <span class="mono">policy=read,write,reboot,test,rest-api,api,ssh</span>.',
  'Konfigurations-Backup liest „/export“ per SSH (Dienst ssh, Port 22) mit demselben Benutzer – Passwörter sind im Export nicht enthalten.',
];
const EVENT = { device_offline: 'Gerät offline', device_online: 'Gerät wieder online', new_device: 'Neues Gerät', action_undo_failed: 'Zurückschalten fehlgeschlagen', quarantined: 'Neues Gerät in Quarantäne', schedule_failed: 'Zeitplan fehlgeschlagen' };
const RANGES = [[7200, '2 h'], [86400, '24 h'], [172800, '2 Tage'], [604800, '7 Tage']];
const fmtBps = v => {
  if (v == null || isNaN(v)) return '–';
  const u = [[1e9, 'Gbit/s'], [1e6, 'Mbit/s'], [1e3, 'kbit/s']].find(([f]) => v >= f) || [1, 'bit/s'];
  return (v / u[0]).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: v / u[0] < 10 ? 1 : 0 }) + ' ' + u[1];
};
const fmtUptime = s => { if (!s) return '–'; const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600); return d ? t('{d} Tage {h} h', { d, h: hh }) : t('{h} h', { h: hh }); };

/* Liniendiagramm als SVG. series = [{name, color, points: [[ts, v], ...]}] */
function chartSvg(series, since, { height = 150 } = {}) {
  const W = 720, H = height, L = 86, R = 8, T = 10, B = 22;
  const now = Date.now() / 1000, t0 = now - since;
  const max = Math.max(1, ...series.flatMap(s => s.points.map(p => p[1])));
  const x = ts => L + (ts - t0) / since * (W - L - R), y = v => T + (1 - v / max) * (H - T - B);
  const lines = series.map(s => {
    if (!s.points.length) return '';
    const d = s.points.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
    const area = `${d}L${x(s.points[s.points.length - 1][0]).toFixed(1)},${y(0)}L${x(s.points[0][0]).toFixed(1)},${y(0)}Z`;
    return `<path d="${area}" fill="${s.color}" opacity=".12"/><path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.6"/>`;
  }).join('');
  const grid = [0, .5, 1].map(f => `<line x1="${L}" x2="${W - R}" y1="${y(max * f)}" y2="${y(max * f)}" class="grid"/><text x="${L - 6}" y="${y(max * f) + 4}" text-anchor="end" class="ax">${fmtBps(max * f)}</text>`).join('');
  const tl = ts => new Date(ts * 1000).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', since > 86400 ? { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
  const empty = series.every(s => !s.points.length);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">${grid}${lines}
    <text x="${L}" y="${H - 6}" class="ax">${tl(t0)}</text><text x="${W - R}" y="${H - 6}" class="ax" text-anchor="end">${tl(now)}</text>
    ${empty ? `<text x="${(W + L) / 2}" y="${H / 2}" text-anchor="middle" class="ax">${t('Noch keine Messwerte – sie entstehen mit jeder Abfrage.')}</text>` : ''}</svg>
    <div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${h(s.name)}</span>`).join('')}</div>`;
}

async function drawChart(el, pid, keys, names, since) {
  const r = await api('GET', `/api/profiles/${pid}/metrics?keys=${keys.join(',')}&since=${since}`);
  const colors = ['#00E5FF', '#19F5C8', '#2D7BFF', '#FFB020'];
  el.innerHTML = chartSvg(keys.map((k, i) => ({ name: names[i], color: colors[i % colors.length], points: r.series[k] || [] })), since);
}

function rangeButtons(cur) {
  return `<span class="ranges">${RANGES.map(([s, n]) => `<button type="button" class="sm ${s === cur ? 'on' : ''}" data-range="${s}">${t(n)}</button>`).join('')}</span>`;
}

async function tabIntegrations(ctx) {
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
          <button class="pri" data-add="mikrotik">${t('+ MikroTik')}</button></div>` : ''}</div>
    </div>
    <div id="ints" class="stack" style="margin-top:16px">${r.integrations.map(i => `<div class="panel integ" data-id="${i.id}">
        <div class="row between"><div class="row"><span class="dot ${st(i)}"></span><b>${h(i.name)}</b><span class="muted mono small">${h(i.host)}</span>
          ${i.name !== drv[i.driver]?.name ? `<span class="badge">${h(drv[i.driver]?.name || i.driver)}</span>` : ''}${i.enabled ? '' : `<span class="badge">${t('pausiert')}</span>`}</div>
          <div class="row">${ctx.canEdit ? `<button class="sm" data-poll>${t('Jetzt abfragen')}</button><button class="sm" data-edit>${t('Bearbeiten')}</button><button class="sm danger" data-del>${t('Löschen')}</button>` : ''}</div></div>
        <p class="muted small" style="margin:4px 0 0">${i.last_ok ? t('zuletzt erfolgreich {d}', { d: h(ago(i.last_ok)) }) : t('noch nicht abgefragt')} · ${t('alle {n}', { n: i.interval_s < 60 ? i.interval_s + ' s' : i.interval_s / 60 + ' min' })}
          ${i.summary?.device_id ? ` · <a href="#" data-dev="${i.summary.device_id}">${t('Gerät öffnen')}</a>` : ''}</p>
        ${i.last_error ? `<p class="${i.last_ok ? 'warnc' : 'errtxt'} small">${h(i.last_error)}</p>` : ''}
        ${i.can_backup ? `<p class="small cfgline"><b>${t('Konfiguration')}:</b> ${i.cfg_ok ? t('zuletzt gesichert {d}', { d: h(ago(i.cfg_ok)) }) : t('noch nicht gesichert')}
          ${i.cfg_result?.status === 'error' ? ` · <span class="${i.cfg_result.second_factor ? 'warnc' : 'errtxt'}">${h(t(i.cfg_result.message))}</span>` : i.cfg_result?.status === 'unchanged' ? ` · <span class="muted">${t('unverändert')}</span>` : ''}
          ${ctx.canEdit ? `<button class="sm" data-cfg>${t('Konfiguration sichern')}</button>` : ''}</p>` : ''}
        ${i.driver === 'fritzbox' ? fritzCard(i) : i.driver === 'snmp' ? snmpCard(i) : i.driver === 'asuswrt' ? asusCard(i) : i.driver === 'proxmox' ? pveCard(i) : ['omada', 'unifi'].includes(i.driver) ? ctrlCard(i) : i.driver === 'mikrotik' ? mtCard(i) : haCard(i)}
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
    const dv = $('[data-dev]', card); if (dv) dv.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +dv.dataset.dev); };
    const ch = $('.chartbox', card);
    if (ch) {
      const wanChart = ['fritzbox', 'unifi'].includes(i.driver);
      const keys = () => wanChart ? [`i${i.id}:wan:rx`, `i${i.id}:wan:tx`] : [`i${i.id}:port:${card.dataset.port || ch.dataset.port}:rx`, `i${i.id}:port:${card.dataset.port || ch.dataset.port}:tx`];
      const names = wanChart ? [t('Download'), t('Upload')] : [t('empfangen'), t('gesendet')];
      const draw = () => drawChart(ch, ctx.pid, keys(), names, tabIntegrations.since || 7200).catch(() => { });
      $$('[data-range]', card).forEach(b => b.onclick = () => { tabIntegrations.since = +b.dataset.range; $$('[data-range]', card).forEach(x => x.classList.toggle('on', x === b)); draw(); });
      $$('[data-port]', card).forEach(b => b.onclick = () => { card.dataset.port = b.dataset.port; $$('.pstrip [data-port]', card).forEach(x => x.classList.toggle('sel', x === b)); $('.pname', card).textContent = b.title; draw(); });
      draw();
    }
  }
  // Ansicht aktuell halten, solange der Reiter offen ist
  { const qb = document.createElement('div'); qb.style.marginTop = '16px'; ctx.el.appendChild(qb); quarantinePanel(ctx, qb); }
  { const sb = document.createElement('div'); sb.className = 'panel'; sb.style.marginTop = '16px'; sb.innerHTML = `<h3>${t('Zeitpläne')}</h3><div></div>`; ctx.el.appendChild(sb); scheduleList(ctx, sb.lastElementChild); }
  { const box = document.createElement('div'); box.id = 'recentact'; box.style.marginTop = '16px'; ctx.el.appendChild(box); recentActions(ctx, box); }
  clearTimeout(tabIntegrations.timer);
  tabIntegrations.timer = setTimeout(() => { if (document.body.contains(ctx.el) && location.hash.endsWith('/integrationen') && !$('#dlg').open) ctx.reload(); }, 60000);
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
    ${ports.length ? `<div class="pstrip">${ports.map(p => `<button type="button" class="pp ${p.oper}${p.port_no === first ? ' sel' : ''}" data-port="${p.port_no}"
        title="${t('Port')} ${p.port_no}${p.alias ? ' · ' + h(p.alias) : ''} · ${p.oper === 'up' ? (p.speed >= 1000 ? p.speed / 1000 + ' Gbit/s' : p.speed + ' Mbit/s') : t('kein Link')}${p.macs.length ? ' · ' + t('{n} MAC-Adressen', { n: p.macs.length }) : ''}${p.lldp ? ' · LLDP: ' + h(p.lldp.name) : ''}">${p.port_no}</button>`).join('')}</div>
      <div class="row between" style="margin-top:8px"><b class="small">${t('Traffic')} · <span class="pname">${t('Port')} ${first}</span></b>${rangeButtons(tabIntegrations.since || 7200)}</div>
      <div class="chartbox" data-port="${first}"></div>` : ''}`;
}

function asusCard(i) {
  const r = i.result || {}, info = r.info || {}, s = i.summary || {};
  return `<div class="kv">${info.model ? `<span>${t('Modell')}: <b>${h(info.model)}</b></span>` : ''}${info.firmware ? `<span>Firmware: <b>${h(info.firmware)}</b></span>` : ''}
      ${r.clients != null ? `<span>${t('Clients')}: <b>${r.online} ${t('online')} / ${r.clients}</b> (${t('{n} per WLAN', { n: r.wlan })})</span>` : ''}</div>
    ${r.nodes?.length ? `<div class="kv">${r.nodes.map(n => `<span><span class="dot ${n.online ? 'on' : 'off'}"></span> <b>${h(n.name)}</b> <span class="mono small">${h(n.ip)}</span> <small class="muted">${n.wired_backhaul ? t('LAN-Backhaul') : n.ip === info.ip ? t('Hauptrouter') : t('Mesh')}</small></span>`).join('')}</div>` : ''}
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

function mtCard(i) {
  const r = i.result || {}, info = r.info || {}, w = r.wan || {};
  return `<div class="kv">${info.model ? `<span>${t('Modell')}: <b>${h(info.model)}</b></span>` : ''}${info.version ? `<span>RouterOS: <b>${h(info.version)}</b></span>` : ''}
      ${info.uptime ? `<span>${t('läuft seit')}: <b>${h(info.uptime)}</b></span>` : ''}${info.cpu != null ? `<span>CPU: <b>${h(info.cpu)} %</b></span>` : ''}
      ${r.clients != null ? `<span>${t('Clients')}: <b>${r.online} ${t('online')} / ${r.clients}</b> (${t('{n} per WLAN', { n: r.wlan })})</span>` : ''}</div>
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
  const fields = drv.fields.map(f => `<div ${show(f)}><label>${t(f.label)}</label>${f.type === 'select'
    ? `<select name="${f.key}">${f.options.map(([k, n]) => `<option value="${h(k)}" ${k === val(f) ? 'selected' : ''}>${h(t(n))}</option>`).join('')}</select>`
    : `<input name="${f.key}" type="${f.type === 'password' ? 'password' : f.type === 'number' ? 'number' : 'text'}" autocomplete="off" value="${h(val(f))}" ${f.placeholder ? `placeholder="${h(f.placeholder)}"` : ''} ${f.required ? 'required' : ''}>`}</div>`).join('');
  const res = await dialog(i.id ? i.name : t(drv.name), `
    ${steps ? `<ol class="steps">${steps.map(x => `<li>${t(x)}</li>`).join('')}</ol>` : ''}
    <p class="muted small" style="margin-top:0">${t(DRIVER_HELP[drv.key])}</p>
    <div class="grid2"><div><label>${t('Name')}</label><input name="name" value="${h(i.name || t(drv.name))}"></div>${fields}
      <div><label>${t('Abfrage alle')}</label><select name="interval_s">${[30, 60, 300, 900].map(v => `<option value="${v}" ${v === i.interval_s ? 'selected' : ''}>${v < 60 ? v + ' s' : v / 60 + ' min'}</option>`).join('')}</select></div>
      <div><label>${t('Gerät in díktyo')}</label><select name="device_id"><option value="">${t('– automatisch zuordnen –')}</option>${devices.filter(d => d.status !== 'ignored').sort((a, b) => cmp(a.name, b.name)).map(d => `<option value="${d.id}" ${d.id === i.device_id ? 'selected' : ''}>${h(d.name)}</option>`).join('')}</select></div>
      <div><label>&nbsp;</label><label class="chk"><input type="checkbox" name="enabled" ${i.enabled ? 'checked' : ''}> ${t('aktiv')}</label></div></div>
    <div class="row" style="margin-top:12px"><button type="button" class="sm" data-test>${t('Verbindung testen')}</button>
      ${drv.key === 'snmp' ? `<button type="button" class="sm" data-diag>${t('Diagnose')}</button>` : ''}<span class="small" id="testres"></span></div>
    <div id="diagres"></div>`, {
    wide: true,
    onOpen: f => {
      const vis = () => $$('[data-show-k]', f).forEach(el => { const sel = $(`[name=${el.dataset.showK}]`, f); el.style.display = !sel || sel.value === el.dataset.showV ? '' : 'none'; });
      $$('select', f).forEach(sel => sel.addEventListener('change', vis));
      vis();
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
          out.innerHTML = `<ul class="diag">${r.steps.map(s => `<li class="${s.ok === true ? 'ok' : s.ok === false ? 'bad' : 'info'}"><b>${h(t(s.title))}</b><div class="small">${h(s.detail)}</div></li>`).join('')}</ul>
            <p class="diag-sum"><b>${t('Ergebnis')}:</b> ${h(r.summary)}</p>`;
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
