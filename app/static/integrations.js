'use strict';
/* Integrationen (FRITZ!Box, SNMP-Switch), Ping-Überwachung, Diagramme. Nutzt die Hilfen aus app.js, inventory.js, scan.js. */
const DRIVER_HELP = {
  fritzbox: 'Ohne Anmeldung liest díktyo die Geräteliste und den WAN-Traffic. Mit einem FRITZ!Box-Benutzer (System → FRITZ!Box-Benutzer, Recht „FRITZ!Box Einstellungen“) kommen die Mesh-Topologie (welches Gerät an welchem LAN-Port bzw. WLAN hängt) und die WLAN-Daten dazu. In der FRITZ!Box muss unter Heimnetz → Netzwerk → Netzwerkeinstellungen „Zugriff für Anwendungen zulassen“ eingeschaltet sein.',
  snmp: 'Am Switch SNMP v2c einschalten und eine Community vergeben (Zyxel: Management → Access Control → SNMP; dort ggf. die Adresse von díktyo als erlaubten Manager eintragen). díktyo liest nur: Port-Status, Traffic, gelernte MAC-Adressen und LLDP-Nachbarn.',
};
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
        ${ctx.canEdit ? `<div class="row"><button class="pri" data-add="fritzbox">${t('+ FRITZ!Box')}</button><button class="pri" data-add="snmp">${t('+ Switch (SNMP)')}</button></div>` : ''}</div>
    </div>
    <div id="ints" class="stack" style="margin-top:16px">${r.integrations.map(i => `<div class="panel integ" data-id="${i.id}">
        <div class="row between"><div class="row"><span class="dot ${st(i)}"></span><b>${h(i.name)}</b><span class="muted mono small">${h(i.host)}</span>
          ${i.name !== drv[i.driver]?.name ? `<span class="badge">${h(drv[i.driver]?.name || i.driver)}</span>` : ''}${i.enabled ? '' : `<span class="badge">${t('pausiert')}</span>`}</div>
          <div class="row">${ctx.canEdit ? `<button class="sm" data-poll>${t('Jetzt abfragen')}</button><button class="sm" data-edit>${t('Bearbeiten')}</button><button class="sm danger" data-del>${t('Löschen')}</button>` : ''}</div></div>
        <p class="muted small" style="margin:4px 0 0">${i.last_ok ? t('zuletzt erfolgreich {d}', { d: h(ago(i.last_ok)) }) : t('noch nicht abgefragt')} · ${t('alle {n}', { n: i.interval_s < 60 ? i.interval_s + ' s' : i.interval_s / 60 + ' min' })}
          ${i.summary?.device_id ? ` · <a href="#" data-dev="${i.summary.device_id}">${t('Gerät öffnen')}</a>` : ''}</p>
        ${i.last_error ? `<p class="${i.last_ok ? 'warnc' : 'errtxt'} small">${h(i.last_error)}</p>` : ''}
        ${i.driver === 'fritzbox' ? fritzCard(i) : snmpCard(i)}
      </div>`).join('') || `<div class="panel empty-box">${t('Noch keine Integration. Füge deine FRITZ!Box hinzu – das geht auch ohne Passwort.')}</div>`}</div>`;

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
    const db_ = $('[data-del]', card);
    if (db_) db_.onclick = async () => {
      if (!await confirmDlg(t('Integration löschen'), t('„{n}“ löschen? Die Geräte bleiben erhalten, die Messwerte werden gelöscht.', { n: h(i.name) }), t('Löschen'))) return;
      await api('DELETE', `${P}/integrations/${i.id}`); ctx.reload();
    };
    const dv = $('[data-dev]', card); if (dv) dv.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +dv.dataset.dev); };
    const ch = $('.chartbox', card);
    if (ch) {
      const keys = () => i.driver === 'fritzbox' ? [`i${i.id}:wan:rx`, `i${i.id}:wan:tx`] : [`i${i.id}:port:${card.dataset.port || ch.dataset.port}:rx`, `i${i.id}:port:${card.dataset.port || ch.dataset.port}:tx`];
      const names = i.driver === 'fritzbox' ? [t('Download'), t('Upload')] : [t('empfangen'), t('gesendet')];
      const draw = () => drawChart(ch, ctx.pid, keys(), names, tabIntegrations.since || 7200).catch(() => { });
      $$('[data-range]', card).forEach(b => b.onclick = () => { tabIntegrations.since = +b.dataset.range; $$('[data-range]', card).forEach(x => x.classList.toggle('on', x === b)); draw(); });
      $$('[data-port]', card).forEach(b => b.onclick = () => { card.dataset.port = b.dataset.port; $$('.pstrip [data-port]', card).forEach(x => x.classList.toggle('sel', x === b)); $('.pname', card).textContent = b.title; draw(); });
      draw();
    }
  }
  // Ansicht aktuell halten, solange der Reiter offen ist
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

async function integrationDialog(ctx, i, drv) {
  const P = `/api/profiles/${ctx.pid}`;
  const { devices } = await api('GET', `${P}/devices`);
  i = i || { driver: drv.key, interval_s: drv.interval, enabled: true, port: drv.fields.find(f => f.key === 'port')?.default };
  const val = f => i[f.key] ?? (i.id ? '' : f.default ?? '');
  const fields = drv.fields.map(f => `<div><label>${t(f.label)}</label><input name="${f.key}" type="${f.type === 'password' ? 'password' : f.type === 'number' ? 'number' : 'text'}" autocomplete="off" value="${h(val(f))}" ${f.required ? 'required' : ''}></div>`).join('');
  const res = await dialog(i.id ? i.name : t(drv.name), `
    <p class="muted small" style="margin-top:0">${t(DRIVER_HELP[drv.key])}</p>
    <div class="grid2"><div><label>${t('Name')}</label><input name="name" value="${h(i.name || t(drv.name))}"></div>${fields}
      <div><label>${t('Abfrage alle')}</label><select name="interval_s">${[30, 60, 300, 900].map(v => `<option value="${v}" ${v === i.interval_s ? 'selected' : ''}>${v < 60 ? v + ' s' : v / 60 + ' min'}</option>`).join('')}</select></div>
      <div><label>${t('Gerät in díktyo')}</label><select name="device_id"><option value="">${t('– automatisch zuordnen –')}</option>${devices.filter(d => d.status !== 'ignored').sort((a, b) => cmp(a.name, b.name)).map(d => `<option value="${d.id}" ${d.id === i.device_id ? 'selected' : ''}>${h(d.name)}</option>`).join('')}</select></div>
      <div><label>&nbsp;</label><label class="chk"><input type="checkbox" name="enabled" ${i.enabled ? 'checked' : ''}> ${t('aktiv')}</label></div></div>
    <div class="row" style="margin-top:12px"><button type="button" class="sm" data-test>${t('Verbindung testen')}</button><span class="small" id="testres"></span></div>`, {
    wide: true,
    onOpen: f => {
      $('[data-test]', f).onclick = async ev => {
        ev.target.disabled = true; $('#testres', f).textContent = t('prüfe …'); $('#testres', f).className = 'small muted';
        try {
          const r = await api('POST', `${P}/integrations/test`, { ...fd(f), driver: drv.key, id: i.id });
          const x = r.result;
          $('#testres', f).textContent = '✓ ' + (drv.key === 'fritzbox' ? `${x.model} · FRITZ!OS ${x.firmware} · ${t('{n} Geräte', { n: x.hosts })} · ${x.auth ? t('Anmeldung ok, Mesh-Topologie verfügbar') : t('ohne Anmeldung (Mesh-Topologie nicht verfügbar)')}` : `${x.name} · ${x.descr}`);
          $('#testres', f).className = 'small okc';
        } catch (e) { $('#testres', f).textContent = '✗ ' + e.message; $('#testres', f).className = 'small errtxt'; }
        ev.target.disabled = false;
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
