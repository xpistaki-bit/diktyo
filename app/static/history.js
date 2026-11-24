'use strict';
/* Änderungsverlauf: Kurzfassung, Filter, Zeitleiste nach Tagen; kompakter Verlauf im Gerätedialog. */
const HIST_FIELD = { name: 'Name', type: 'Typ', status: 'Status', model: 'Modell', location: 'Standort', ips: 'IP-Adresse', mac: 'MAC', uplink: 'Anschluss', ports: 'Offene Ports', firmware: 'Firmware' };
const HIST_SOURCE = { user: 'von Hand', scan: 'Netzscan', fritzbox: 'FRITZ!Box', snmp: 'Switch (SNMP)', asuswrt: 'ASUS', proxmox: 'Proxmox',
  homeassistant: 'Home Assistant', omada: 'Omada', unifi: 'UniFi', mikrotik: 'MikroTik', nmap: 'Dienste-Scan', monitor: 'Überwachung', '': 'Abgleich' };
const HIST_KINDS = [['change', 'Änderungen'], ['status', 'Online/Offline'], ['action', 'Aktionen'], ['config', 'Konfiguration'], ['quarantine', 'Quarantäne']];
const STATUS_NAME = { confirmed: 'bestätigt', discovered: 'Posteingang', ignored: 'ignoriert' };

function histText(x) {
  const src = x.source != null && x.cat !== 'action' ? `<span class="muted"> · ${h(t(HIST_SOURCE[x.source] ?? x.source))}${x.user ? ' (' + h(x.user) + ')' : ''}</span>` : '';
  if (x.cat === 'change') {
    if (x.kind === 'created') return `<b>${t('Neu')}</b>${x.detail?.ip ? ` <span class="mono">${h(x.detail.ip)}</span>` : ''}${x.detail?.status === 'discovered' ? ` <span class="badge">${t('Posteingang')}</span>` : ''}${src}`;
    if (x.kind === 'deleted') return `<b class="offc">${t('Gelöscht')}</b>${x.detail?.ip ? ` <span class="mono">${h(x.detail.ip)}</span>` : ''}${src}`;
    if (x.field === 'ports' && x.detail) {
      const o = x.detail.opened || [], c = x.detail.closed || [];
      return `${t('Offene Ports')}: ${o.length ? `<span class="warnc">+ ${h(o.join(', '))}</span> ` : ''}${c.length ? `<span class="muted">− ${h(c.join(', '))}</span>` : ''}${src}`;
    }
    const v = s => x.field === 'status' ? t(STATUS_NAME[s] || s) : x.field === 'type' ? typeName(s) : s;
    return `${t(HIST_FIELD[x.field] || x.field)}: <span class="muted">${h(v(x.old))}</span> → <b>${h(v(x.new))}</b>${src}`;
  }
  if (x.cat === 'status') return x.kind === 'online' ? `<span class="okc">● ${t('wieder online')}</span>${src}` : `<span class="offc">● ${t('offline')}</span>${src}`;
  if (x.cat === 'action') return `${t('Aktion')}: <b>${h(t(x.new))}</b> <span class="${x.kind === 'done' ? 'muted' : 'errtxt'}">${h(ts(x.old || ''))}</span> <span class="muted">· ${h(x.user)}</span>`;
  if (x.cat === 'config') return `${t('Neuer Konfigurationsstand')} <span class="mono small">${h(x.new)}</span>`;
  if (x.cat === 'quarantine') return `${t('Quarantäne')}: ${x.kind === 'active' ? `<span class="warnc">${t('Internet gesperrt')}</span>` : x.kind === 'released' ? t('freigegeben') : `<span class="errtxt">${h(x.old || x.kind)}</span>`}`;
  return h(x.kind);
}

const HIST_ICON = { change: '✎', status: '●', action: '⚡', config: '⎘', quarantine: '⛔' };

function histList(items, withDevice = true) {
  if (!items.length) return `<p class="muted">${t('Im gewählten Zeitraum keine Einträge.')}</p>`;
  const days = new Map();
  for (const x of items) {
    const d = new Date(x.ts), key = d.toLocaleDateString(LANG === 'en' ? 'en-GB' : 'de-DE', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' });
    if (!days.has(key)) days.set(key, []);
    days.get(key).push(x);
  }
  return [...days].map(([day, xs]) => `<div class="hist-day"><h4>${h(day)}</h4><ul class="hist">${xs.map(x => `<li class="hc-${x.cat} hk-${x.kind}">
      <span class="ht mono small">${new Date(x.ts).toLocaleTimeString(LANG === 'en' ? 'en-GB' : 'de-DE', { hour: '2-digit', minute: '2-digit' })}</span>
      <span class="hi" title="${h(t(HIST_KINDS.find(k => k[0] === x.cat)?.[1] || ''))}">${HIST_ICON[x.cat] || '·'}</span>
      <span class="hb">${withDevice ? (x.device_id ? `<a href="#" data-hdev="${x.device_id}"><b>${h(x.device || '')}</b></a> · ` : x.device ? `<b>${h(x.device)}</b> · ` : '') : ''}${histText(x)}</span></li>`).join('')}</ul></div>`).join('');
}

async function tabHistory(ctx) {
  await meta(ctx.pid);  // Auswahllisten für den Gerätedialog
  const P = `/api/profiles/${ctx.pid}`, f = tabHistory.f;
  ctx.el.innerHTML = `<div id="hsum"></div>
    <div class="toolbar"><select id="hdays" style="width:auto">${[[1, 'letzte 24 Stunden'], [7, 'letzte 7 Tage'], [30, 'letzte 30 Tage'], [90, 'letzte 90 Tage'], [365, 'letztes Jahr']].map(([v, n]) => `<option value="${v}" ${v === f.days ? 'selected' : ''}>${t(n)}</option>`).join('')}</select>
      <span class="chips">${HIST_KINDS.map(([k, n]) => `<label class="chk"><input type="checkbox" data-hk="${k}" ${f.kinds.includes(k) ? 'checked' : ''}> ${t(n)}</label>`).join('')}</span>
      <input type="search" id="hq" placeholder="${t('Gerät, IP, Wert …')}" value="${h(f.q)}" style="max-width:220px">
      <span class="grow"></span><a class="btn sm" id="hcsv" href="${P}/history.csv?days=${f.days}">${t('CSV')}</a></div>
    <div id="hlist" class="panel"><p class="muted">${t('lade …')}</p></div>`;
  const load = async () => {
    const r = await api('GET', `${P}/history?days=${f.days}&kinds=${f.kinds.join(',')}&q=${encodeURIComponent(f.q)}`);
    const s = r.summary;
    if (s) {
      const card = (n, label, cls = '') => `<div class="hs ${n ? cls : 'zero'}"><b>${n}</b><span>${t(label)}</span></div>`;
      $('#hsum', ctx.el).innerHTML = `<div class="hsum"><span class="muted small">${t('Seit gestern')}:</span>${card(s.created, 'neu', 'info')}${card(s.deleted, 'gelöscht')}
        ${card(s.changed, 'Geräte geändert')}${card(s.ip, 'IP-Wechsel')}${card(s.moved, 'Anschluss gewechselt')}${card(s.offline, 'mal offline', 'warn')}
        ${card(s.configs, 'Konfig-Stände')}${card(s.ports, 'Port-Änderungen', 'warn')}</div>`;
    }
    $('#hlist', ctx.el).innerHTML = histList(r.items);
    $$('[data-hdev]', ctx.el).forEach(a => a.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +a.dataset.hdev); });
    $('#hcsv', ctx.el).href = `${P}/history.csv?days=${Math.max(f.days, 30)}`;
  };
  $('#hdays', ctx.el).onchange = e => { f.days = +e.target.value; load(); };
  $$('[data-hk]', ctx.el).forEach(cb => cb.onchange = () => { f.kinds = $$('[data-hk]', ctx.el).filter(x => x.checked).map(x => x.dataset.hk); load(); });
  let tmr; $('#hq', ctx.el).oninput = e => { clearTimeout(tmr); tmr = setTimeout(() => { f.q = e.target.value.trim(); load(); }, 300); };
  await load();
}
tabHistory.f = { days: 7, kinds: ['change', 'status', 'action', 'config', 'quarantine'], q: '' };
window.INV.verlauf = tabHistory;

/* Gerätedialog: letzte 30 Tage */
async function deviceHistory(ctx, did, el) {
  try {
    const r = await api('GET', `/api/profiles/${ctx.pid}/history?device_id=${did}&days=30`);
    if (!r.items.length) { el.innerHTML = ''; return; }
    el.innerHTML = `<h4>${t('Verlauf (30 Tage)')}</h4><div class="hist-dev">${histList(r.items.slice(0, 40), false)}</div>
      <p class="small"><a href="#/p/${ctx.pid}/verlauf">${t('Gesamter Verlauf')} →</a></p>`;
  } catch { el.innerHTML = ''; }
}
