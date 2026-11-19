'use strict';
/* Profil-Reiter: Geräte, IPAM, Standorte, Ausgabe. Nutzt die Hilfen aus app.js (t, h, api, dialog, toast, …). */
const MEDIUM = { lan: 'LAN', wlan: 'WLAN', mesh: 'Mesh-Backhaul', virtual: 'Virtuell (läuft auf)' };
const MEDIUM_SHORT = { lan: 'LAN', wlan: 'WLAN', mesh: 'Mesh', virtual: 'virtuell' };
const PORT_KINDS = ['rj45', 'sfp', 'sfp+', 'sfp28', 'coax', 'dsl', 'fiber', 'usb'];
const IP_KIND = { static: 'statisch', dhcp: 'DHCP', reserved: 'reserviert' };
const SECTIONS = [['topology', 'Topologie-Grafik'], ['devices', 'Geräteliste'], ['ipplan', 'IP-Plan pro Subnetz'], ['vlans', 'VLAN-Übersicht'], ['ports', 'Portbelegung pro Switch'],
  ['wlan', 'WLAN-Übersicht'], ['notes', 'Notizen']];
let META = null, META_LANG = null;
async function meta(pid) {
  if (!META || META_LANG !== LANG) { META = await api('GET', `/api/profiles/${pid}/meta`); META_LANG = LANG; }
  return META;
}
const typeName = k => (META?.types.find(x => x.key === k) || {}).name || k;
const ipNum = a => { const p = String(a || '').split('.'); return p.length === 4 ? p.reduce((n, x) => n * 256 + (+x || 0), 0) : 1e12 + String(a).length; };
const cmp = (a, b) => typeof a === 'number' && typeof b === 'number' ? a - b : String(a ?? '').localeCompare(String(b ?? ''), LANG, { numeric: true, sensitivity: 'base' });
const uplinkText = u => !u ? '' : `${u.device_name}${u.port_name ? ' · ' + t('Port') + ' ' + u.port_name : ''}`;

/* Sortierbare Tabelle: cols = [{k, label, val(row), html(row), cls}] */
function sortTable(el, cols, rows, { onRow, empty, key = 'tbl', initial } = {}) {
  let st = sortTable.state[key] || initial || { k: cols[0].k, dir: 1 };
  const draw = () => {
    const c = cols.find(x => x.k === st.k) || cols[0];
    const list = [...rows].sort((a, b) => cmp(c.val ? c.val(a) : a[c.k], c.val ? c.val(b) : b[c.k]) * st.dir);
    el.innerHTML = `<div class="table-wrap"><table class="sortable"><thead><tr>${cols.map(x => `<th data-k="${x.k}" class="${x.cls || ''}${x.k === st.k ? ' on' : ''}">${h(x.label)}${x.k === st.k ? (st.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead>
      <tbody>${list.length ? list.map((r, i) => `<tr data-i="${rows.indexOf(r)}" class="${onRow ? 'click' : ''}">${cols.map(x => `<td class="${x.cls || ''}">${x.html ? x.html(r) : h(r[x.k])}</td>`).join('')}</tr>`).join('')
        : `<tr><td colspan="${cols.length}" class="empty">${empty || t('Keine Einträge.')}</td></tr>`}</tbody></table></div>`;
    $$('th[data-k]', el).forEach(th => th.onclick = () => { st = { k: th.dataset.k, dir: st.k === th.dataset.k ? -st.dir : 1 }; sortTable.state[key] = st; draw(); });
    if (onRow) $$('tbody tr[data-i]', el).forEach(tr => tr.onclick = ev => { if (!ev.target.closest('button,a,input,select')) onRow(rows[+tr.dataset.i]); });
  };
  draw();
}
sortTable.state = {};

/* ---------------------------------------------------------------- Port-Gruppen */
function portEditorHtml(groups, disabled) {
  const row = g => `<tr class="pg"><td><input type="number" min="1" max="128" data-f="count" value="${h(g.count || '')}" ${disabled}></td>
    <td><select data-f="kind" ${disabled}>${PORT_KINDS.map(k => `<option value="${k}" ${k === (g.kind || 'rj45') ? 'selected' : ''}>${k.toUpperCase()}</option>`).join('')}</select></td>
    <td><input data-f="speed" value="${h(g.speed || '')}" placeholder="1G" ${disabled}></td>
    <td><input data-f="label" value="${h(g.label || '')}" placeholder="${t('z. B. LAN')}" ${disabled}></td>
    <td class="c"><input type="checkbox" data-f="poe" ${g.poe ? 'checked' : ''} ${disabled}></td>
    <td>${disabled ? '' : `<button type="button" class="sm" data-rmpg title="${t('Entfernen')}">×</button>`}</td></tr>`;
  return `<table class="pgt"><thead><tr><th>${t('Anzahl')}</th><th>${t('Art')}</th><th>${t('Tempo')}</th><th>${t('Bezeichnung')}</th><th>PoE</th><th></th></tr></thead>
    <tbody>${(groups || []).map(row).join('')}</tbody></table>
    ${disabled ? '' : `<button type="button" class="sm" data-addpg>${t('+ Port-Gruppe')}</button>`}
    <template data-pgtpl>${row({ count: 1, kind: 'rj45', speed: '1G' })}</template>`;
}
function bindPortEditor(root, onChange) {
  const tb = $('.pgt tbody', root);
  const bind = () => $$('[data-rmpg]', root).forEach(b => b.onclick = () => { b.closest('tr').remove(); onChange && onChange(); });
  const add = $('[data-addpg]', root);
  if (add) add.onclick = () => { tb.insertAdjacentHTML('beforeend', $('[data-pgtpl]', root).innerHTML); bind(); onChange && onChange(); };
  root.addEventListener('input', ev => { if (ev.target.closest('.pgt')) onChange && onChange(); });
  bind();
}
const readPorts = root => $$('.pgt tbody tr', root).map(tr => ({
  count: +$('[data-f=count]', tr).value || 0, kind: $('[data-f=kind]', tr).value, speed: $('[data-f=speed]', tr).value.trim(),
  label: $('[data-f=label]', tr).value.trim(), poe: $('[data-f=poe]', tr).checked,
})).filter(g => g.count > 0);
const portCount = groups => (groups || []).reduce((n, g) => n + (+g.count || 0), 0);

/* ---------------------------------------------------------------- Geräte */
async function tabDevices(ctx) {
  await meta(ctx.pid);
  const [{ devices: all }, { locations }] = await Promise.all([api('GET', `/api/profiles/${ctx.pid}/devices`), api('GET', `/api/profiles/${ctx.pid}/locations`)]);
  const devices = all.filter(d => d.status === 'confirmed');
  const inboxN = all.filter(d => d.status === 'discovered').length;
  const f = tabDevices.filter[ctx.pid] || (tabDevices.filter[ctx.pid] = { q: '', type: '', loc: '' });
  ctx.el.innerHTML = `<div class="toolbar">
      <input type="search" id="q" placeholder="${t('Suchen: Name, IP, MAC, Notiz …')}" value="${h(f.q)}">
      <select id="ft"><option value="">${t('Alle Typen')}</option>${META.types.filter(x => devices.some(d => d.type === x.key)).map(x => `<option value="${x.key}" ${f.type === x.key ? 'selected' : ''}>${h(x.name)}</option>`).join('')}</select>
      <select id="fl"><option value="">${t('Alle Standorte')}</option>${locations.map(l => `<option value="${l.id}" ${String(f.loc) === String(l.id) ? 'selected' : ''}>${h(l.path)}</option>`).join('')}</select>
      <span class="grow"></span><span class="muted" id="cnt"></span>
      ${ctx.canEdit ? `<button class="pri" id="add">${t('+ Gerät')}</button>` : ''}</div><div id="list"></div>`;
  const cols = [
    { k: 'online', label: '', cls: 'dotcol', val: d => d.online == null ? 2 : d.online ? 0 : 1, html: onlineDot },
    { k: 'name', label: t('Name'), html: d => `<b>${h(d.name)}</b>${d.hostname && d.hostname.toLowerCase() !== d.name.toLowerCase() ? `<small class="muted block mono">${h(d.hostname)}</small>` : ''}` },
    { k: 'type', label: t('Typ'), val: d => typeName(d.type), html: d => h(typeName(d.type)) },
    { k: 'model', label: t('Hersteller / Modell'), val: d => `${d.manufacturer} ${d.model}`, html: d => h(`${d.manufacturer} ${d.model}`.trim()) },
    { k: 'ip', label: t('IP'), cls: 'mono', val: d => d.ips.length ? ipNum(d.ips[0].address) : 1e13, html: d => d.ips.map(i => h(i.address)).join('<br>') },
    { k: 'mac', label: t('MAC'), cls: 'mono' },
    { k: 'location', label: t('Standort') },
    { k: 'uplink', label: t('Anschluss'), val: d => uplinkText(d.uplink), html: d => d.uplink ? `${h(uplinkText(d.uplink))} <span class="badge">${t(MEDIUM_SHORT[d.uplink.medium])}</span>` : '' },
    { k: 'ports', label: t('Ports'), cls: 'mono', val: d => d.ports_total ? d.ports_used / d.ports_total : -1, html: d => d.ports_total ? `${d.ports_used}/${d.ports_total}` : (d.children ? `<span title="${t('verbundene Geräte')}">↳ ${d.children}</span>` : '') },
  ];
  const draw = () => {
    const q = f.q.trim().toLowerCase();
    const rows = devices.filter(d => (!f.type || d.type === f.type) && (!f.loc || String(d.location_id) === String(f.loc))
      && (!q || [d.name, d.hostname, d.mac, d.manufacturer, d.model, d.notes, d.location, ...d.tags, ...d.ips.map(i => i.address), uplinkText(d.uplink)].join(' ').toLowerCase().includes(q)));
    $('#cnt').textContent = rows.length === devices.length ? t('{n} Geräte', { n: devices.length }) : t('{n} von {m} Geräten', { n: rows.length, m: devices.length });
    sortTable($('#list'), cols, rows, {
      key: 'dev', initial: { k: 'name', dir: 1 }, onRow: d => deviceDialog(ctx, d.id),
      empty: devices.length ? t('Kein Gerät passt zum Filter.') : inboxN
        ? t('Noch keine bestätigten Geräte. Im Posteingang warten {n} gefundene Geräte.', { n: inboxN }) + ` <a href="#/p/${ctx.pid}/posteingang">${t('Zum Posteingang')}</a>`
        : t('Noch keine Geräte. Lass das Netz scannen oder lege das erste Gerät von Hand an.') + ` <a href="#/p/${ctx.pid}/netzscan">${t('Netz scannen')}</a>`,
    });
  };
  $('#q').oninput = e => { f.q = e.target.value; draw(); };
  $('#ft').onchange = e => { f.type = e.target.value; draw(); };
  $('#fl').onchange = e => { f.loc = e.target.value; draw(); };
  const add = $('#add');
  if (add) add.onclick = () => deviceDialog(ctx, null);
  draw();
}
tabDevices.filter = {};

async function deviceDialog(ctx, did) {
  const P = `/api/profiles/${ctx.pid}`;
  const [{ devices }, { locations }, { models }, d] = await Promise.all([
    api('GET', `${P}/devices`), api('GET', `${P}/locations`), api('GET', '/api/catalog'), did ? api('GET', `${P}/devices/${did}`) : Promise.resolve(null)]);
  const dis = ctx.canEdit ? '' : 'disabled';
  const v = d || { name: '', type: 'other', ips: [{ address: '', kind: 'static' }], uplink: null, port_groups: [], tags: [] };
  const up = v.uplink || {};
  const others = devices.filter(x => x.id !== did && x.status === 'confirmed').sort((a, b) => cmp(a.name, b.name));
  const byMan = {};
  models.forEach(m => (byMan[m.manufacturer] = byMan[m.manufacturer] || []).push(m));
  const ipRow = ip => `<div class="iprow"><input data-ip value="${h(ip.address)}" placeholder="192.168.178.10" ${dis}>
      <select data-ipk ${dis}>${Object.keys(IP_KIND).map(k => `<option value="${k}" ${k === (ip.kind || 'static') ? 'selected' : ''}>${t(IP_KIND[k])}</option>`).join('')}</select>
      ${dis ? '' : `<button type="button" class="sm" data-rmip title="${t('Entfernen')}">×</button>`}</div>`;
  const html = `
    ${did && ctx.canEdit ? `<div class="dlg-actions"><button type="button" class="sm danger" data-del>${t('Gerät löschen')}</button></div>` : ''}
    ${d && (d.ident_full || d.seen) ? identBox(d) : ''}
    <div class="grid2">
      <div><label>${t('Name')}</label><input name="name" required maxlength="120" value="${h(v.name)}" ${dis}></div>
      <div><label>${t('Typ')}</label><select name="type" ${dis}>${META.types.map(x => `<option value="${x.key}" ${x.key === v.type ? 'selected' : ''}>${h(x.name)}</option>`).join('')}</select></div>
      <div class="span2"><label>${t('Katalogmodell')}</label><select name="model_id" ${dis}><option value="">${t('– kein Katalogmodell –')}</option>
        ${Object.keys(byMan).sort(cmp).map(man => `<optgroup label="${h(man)}">${byMan[man].map(m => `<option value="${m.id}" ${m.id === v.model_id ? 'selected' : ''}>${h(m.model)}${m.port_summary ? ' · ' + h(m.port_summary) : ''}</option>`).join('')}</optgroup>`).join('')}</select></div>
      <div><label>${t('Hersteller')}</label><input name="manufacturer" maxlength="80" value="${h(v.manufacturer || '')}" ${dis}></div>
      <div><label>${t('Modell')}</label><input name="model" maxlength="120" value="${h(v.model || '')}" ${dis}></div>
      <div><label>${t('Standort')}</label><select name="location_id" ${dis}><option value="">–</option>${locations.map(l => `<option value="${l.id}" ${l.id === v.location_id ? 'selected' : ''}>${h(l.path)}</option>`).join('')}</select></div>
      <div><label>${t('Hostname')}</label><input name="hostname" maxlength="120" value="${h(v.hostname || '')}" ${dis}></div>
    </div>
    <h4>${t('Netzwerk')}</h4>
    <div class="grid2">
      <div><label>${t('MAC-Adresse')}</label><input name="mac" class="mono" value="${h(v.mac || '')}" placeholder="AA:BB:CC:DD:EE:FF" ${dis}></div>
      <div><label>${t('IP-Adressen')}</label><div id="ips">${(v.ips.length ? v.ips : [{ address: '', kind: 'static' }]).map(ipRow).join('')}</div>
        ${dis ? '' : `<button type="button" class="sm" id="addip">${t('+ IP-Adresse')}</button>`}</div>
    </div>
    <h4>${t('Anschluss')}</h4>
    <div class="grid2">
      <div><label>${t('Verbindung')}</label><select name="medium" ${dis}><option value="">${t('– nicht verbunden –')}</option>${Object.keys(MEDIUM).map(k => `<option value="${k}" ${k === up.medium ? 'selected' : ''}>${t(MEDIUM[k])}</option>`).join('')}</select></div>
      <div><label id="uplbl">${t('Verbunden mit')}</label><select name="up_device" ${dis}><option value="">–</option>${others.map(o => `<option value="${o.id}" ${o.id === up.device_id ? 'selected' : ''}>${h(o.name)} (${h(typeName(o.type))})</option>`).join('')}</select></div>
      <div class="lanonly"><label>${t('Port an der Gegenstelle')}</label><select name="up_port" ${dis}><option value="">${t('– kein bestimmter Port –')}</option></select></div>
      <div class="lanonly"><label>${t('Eigener Port (bei Switches/Routern)')}</label><select name="local_port" ${dis}><option value="">${t('– Netzwerkschnittstelle des Geräts –')}</option>
        ${(v.ports || []).map(p => `<option value="${p.id}" ${p.id === up.local_port_id ? 'selected' : ''} ${p.peer && p.peer.direction === 'down' ? 'disabled' : ''}>${h(p.name)}${p.peer && p.peer.direction === 'down' ? ' – ' + t('belegt: {n}', { n: h(p.peer.device_name) }) : ''}</option>`).join('')}</select>
        ${!did ? `<small class="muted">${t('Eigene Ports lassen sich nach dem ersten Speichern wählen.')}</small>` : ''}</div>
    </div>
    <h4>${t('Ports')} <small class="muted" id="pcount"></small></h4>
    <div id="pe">${portEditorHtml(v.port_groups, dis)}</div>
    <p class="muted small">${t('Die Ports kommen aus dem Katalogmodell und lassen sich hier für dieses Gerät anpassen. Werden es weniger, entfallen die Verbindungen an den wegfallenden Ports.')}</p>
    <h4>${t('Notizen')}</h4>
    <textarea name="notes" rows="3" maxlength="5000" ${dis}>${h(v.notes || '')}</textarea>
    <label>${t('Tags (durch Komma getrennt)')}</label><input name="tags" value="${h((v.tags || []).join(', '))}" ${dis}>
    ${d && d.ports.length ? portTable(d) : ''}
    ${d && d.connected.length ? `<h4>${t('Verbundene Geräte')} (${d.connected.length})</h4><div class="table-wrap"><table class="compact"><thead><tr><th>${t('Name')}</th><th>${t('Verbindung')}</th><th>${t('IP')}</th><th>${t('MAC')}</th></tr></thead><tbody>
      ${d.connected.map(k => `<tr><td>${h(k.name)}</td><td>${t(MEDIUM_SHORT[k.medium])}${k.port_name ? ' · ' + t('Port') + ' ' + h(k.port_name) : ''}</td><td class="mono">${h(k.ip)}</td><td class="mono">${h(k.mac)}</td></tr>`).join('')}
      </tbody></table></div>` : ''}`;

  const discovered = d && d.status === 'discovered';
  const res = await dialog(did ? v.name : t('Neues Gerät'), html, {
    wide: true, ok: ctx.canEdit ? (discovered ? t('Übernehmen') : t('Speichern')) : null,
    onOpen: (f, close) => {
      const sel = n => $(`[name=${n}]`, f);
      const pc = () => { const n = portCount(readPorts($('#pe', f))); $('#pcount', f).textContent = n ? `(${n})` : ''; };
      bindPortEditor($('#pe', f), pc); pc();
      const bindIps = () => $$('[data-rmip]', f).forEach(b => b.onclick = () => b.closest('.iprow').remove());
      bindIps();
      const addip = $('#addip', f);
      if (addip) addip.onclick = () => { $('#ips', f).insertAdjacentHTML('beforeend', ipRow({ address: '', kind: 'static' })); bindIps(); $('#ips .iprow:last-child input', f).focus(); };
      sel('model_id').onchange = () => {
        const m = models.find(x => String(x.id) === sel('model_id').value);
        if (!m) return;
        sel('manufacturer').value = m.manufacturer; sel('model').value = m.model; sel('type').value = m.type;
        $('#pe', f).innerHTML = portEditorHtml(m.ports, dis); bindPortEditor($('#pe', f), pc); pc();
        if (!sel('name').value.trim()) sel('name').value = m.model;
      };
      const loadPorts = async () => {
        const target = sel('up_device').value, ps = sel('up_port');
        ps.innerHTML = `<option value="">${t('– kein bestimmter Port –')}</option>`;
        if (!target) return;
        const { ports } = await api('GET', `${P}/devices/${target}/ports`);
        ps.innerHTML += ports.map(p => {
          const mine = p.peer && p.peer.device_id === did, busy = p.peer && !mine;
          return `<option value="${p.id}" ${p.id === up.port_id ? 'selected' : ''} ${busy ? 'disabled' : ''}>${h(p.name)} (${h(p.kind.toUpperCase())} ${h(p.speed)})${busy ? ' – ' + t('belegt: {n}', { n: h(p.peer.device_name) }) : ''}</option>`;
        }).join('');
      };
      const medium = () => {
        const m = sel('medium').value;
        $$('.lanonly', f).forEach(x => x.style.display = m === 'lan' ? '' : 'none');
        sel('up_device').disabled = !!dis || !m;
        $('#uplbl', f).textContent = m === 'virtual' ? t('Läuft auf (Host)') : m === 'wlan' || m === 'mesh' ? t('Verbunden mit (Access Point / Mesh-Knoten)') : t('Verbunden mit');
      };
      sel('medium').onchange = medium; sel('up_device').onchange = loadPorts;
      medium(); loadPorts();
      const del = $('[data-del]', f);
      if (del) del.onclick = async () => {
        close(null);
        if (!await confirmDlg(t('Gerät löschen'), t('„{n}“ mit allen Ports und Verbindungen löschen?', { n: h(v.name) }), t('Löschen'))) return;
        try { await api('DELETE', `${P}/devices/${did}`); toast(t('Gerät gelöscht')); ctx.reload(); } catch (e) { toast(e.message, true); }
      };
    },
    onOk: f => {
      const x = fd(f);
      const body = {
        name: x.name, type: x.type, model_id: x.model_id ? +x.model_id : null, manufacturer: x.manufacturer, model: x.model,
        location_id: x.location_id ? +x.location_id : null, hostname: x.hostname, mac: x.mac, notes: x.notes, tags: x.tags,
        ips: $$('.iprow', f).map(r => ({ address: $('[data-ip]', r).value.trim(), kind: $('[data-ipk]', r).value })).filter(i => i.address),
        ports: readPorts($('#pe', f)),
        uplink: x.medium && x.up_device ? { medium: x.medium, device_id: +x.up_device, port_id: x.medium === 'lan' && x.up_port ? +x.up_port : null,
          local_port_id: x.medium === 'lan' && x.local_port ? +x.local_port : null } : null,
      };
      if (discovered) body.status = 'confirmed';
      return did ? api('PUT', `${P}/devices/${did}`, body) : api('POST', `${P}/devices`, body);
    },
  });
  if (res) { toast(t('gespeichert')); ctx.reload(); }
}

function portTable(d) {
  const live = d.ports.some(p => p.live);
  return `<h4>${t('Portbelegung')}${live ? ` <small class="muted">· ${t('Status per SNMP')}</small>` : ''}</h4><div class="table-wrap"><table class="compact"><thead><tr>${live ? '<th></th>' : ''}<th>${t('Port')}</th><th>${t('Art')}</th><th>${t('Verbunden mit')}</th><th>${t('IP')}</th><th>${t('MAC')}</th>
    ${live ? `<th>${t('Link')}</th><th>↓ / ↑</th><th>${t('gelernt')}</th>` : ''}</tr></thead><tbody>
    ${d.ports.map(p => `<tr>${live ? `<td>${p.live ? `<span class="dot ${p.live.oper === 'up' ? 'on' : 'off'}"></span>` : ''}</td>` : ''}<td>${h(p.name)}</td><td class="mono">${h(p.kind.toUpperCase())} ${h(p.speed)}${p.poe ? ' PoE' : ''}</td>
      <td>${p.peer ? `${h(p.peer.device_name)}${p.peer.direction === 'up' ? ` <span class="badge">${t('Uplink')}</span>` : ''}` : p.live?.lldp ? `<span class="muted">LLDP: ${h(p.live.lldp.name)}</span>` : '<span class="muted">–</span>'}</td>
      <td class="mono">${h(p.peer?.ip || '')}</td><td class="mono">${h(p.peer?.mac || '')}</td>
      ${live ? `<td class="mono small">${p.live && p.live.oper === 'up' ? (p.live.speed >= 1000 ? p.live.speed / 1000 + 'G' : p.live.speed + 'M') : ''}</td>
        <td class="mono small">${p.live && p.live.in_bps != null ? fmtBps(p.live.in_bps) + ' / ' + fmtBps(p.live.out_bps) : ''}</td>
        <td class="mono small" title="${t('MAC-Adressen, die der Switch an diesem Port gelernt hat')}">${p.live?.macs || ''}</td>` : ''}</tr>`).join('')}
  </tbody></table></div>`;
}

function identBox(d) {
  const i = d.ident_full, s = d.seen || {};
  const rows = [
    [t('Hersteller (MAC)'), s.vendor], [t('DNS-Name'), s.hostname], [t('NetBIOS'), s.netbios], [t('mDNS'), (s.mdns_names || []).join(', ')],
    [t('mDNS-Dienste'), (s.mdns_services || []).join(', ')], [t('UPnP'), [s.ssdp_name, s.ssdp_model].filter(Boolean).join(' · ')],
    [t('Weboberfläche'), [s.http_title, s.http_server].filter(Boolean).join(' · ')], [t('Offene Ports'), (s.ports || []).join(', ')],
    [t('Dienste'), Object.entries(s.services || {}).map(([p, v]) => `${p}: ${v}`).join(' · ')], [t('Betriebssystem'), s.os],
  ].filter(r => r[1]);
  return `<div class="identbox">
    ${i && identLabel(i) ? `<div class="row"><b>${t('Erkannt als')}: ${h(identLabel(i))}</b> ${confBar(i.confidence || 0)}</div><div class="reasons">${reasonsHtml(i)}</div>` : ''}
    <div class="row small muted" style="margin-top:6px">${onlineDot(d)} ${d.online ? t('online') : d.online === 0 ? t('offline') : t('noch nicht geprüft')}${d.last_seen ? ' · ' + t('zuletzt gesehen') + ' ' + h(fmtDate(d.last_seen)) : ''}
      ${d.events && d.events.length > 1 ? ' · ' + t('Wechsel') + ': ' + d.events.slice(0, 5).map(e => `<span class="${e.online ? 'okc' : 'offc'}">${e.online ? '▲' : '▼'} ${h(fmtDate(e.ts))}</span>`).join(' ') : ''}</div>
    ${rows.length ? `<details><summary>${t('Beobachtet beim letzten Scan')}</summary><table class="compact kvt">${rows.map(([k, v]) => `<tr><th>${h(k)}</th><td>${h(v)}</td></tr>`).join('')}</table></details>` : ''}
  </div>`;
}

/* ---------------------------------------------------------------- IPAM */
function conflictText(c) {
  const devs = c.devices ? c.devices.map(h).join(', ') : '';
  switch (c.code) {
    case 'dup_ip': return t('IP {ip} ist mehrfach vergeben: {d}', { ip: h(c.ip), d: devs });
    case 'dup_mac': return t('MAC {mac} ist mehrfach eingetragen: {d}', { mac: h(c.mac), d: devs });
    case 'in_dhcp': return t('{d}: statische IP {ip} liegt im DHCP-Bereich von {s}', { d: h(c.device), ip: h(c.ip), s: h(c.subnet) });
    case 'outside': return t('{d}: IP {ip} liegt in keinem eingetragenen Subnetz', { d: h(c.device), ip: h(c.ip) });
    case 'overlap': return t('Subnetze überschneiden sich: {a} und {b}', { a: h(c.a), b: h(c.b) });
    default: return h(c.code);
  }
}

async function tabIpam(ctx) {
  const P = `/api/profiles/${ctx.pid}`;
  const [{ subnets, conflicts }, { vlans }] = await Promise.all([api('GET', `${P}/subnets`), api('GET', `${P}/vlans`)]);
  const open = conflicts.filter(c => !c.acked), acked = conflicts.filter(c => c.acked);
  const showAcked = tabIpam.showAcked;
  const item = c => `<li class="${c.level}${c.acked ? ' acked' : ''}" data-key="${h(c.key)}"><span>${conflictText(c)}</span>${ctx.canEdit ? `<button type="button" class="link sm" data-ack="${c.acked ? 0 : 1}" title="${c.acked ? t('wieder einblenden') : t('als gelesen markieren')}">${c.acked ? t('einblenden') : '✓ ' + t('gelesen')}</button>` : ''}</li>`;
  ctx.el.innerHTML = `
    ${open.length || acked.length ? `<div class="panel conflicts ${open.length ? '' : 'quiet'}"><div class="row between"><b>${t('Hinweise')} (${open.length})</b>
        <span class="row">${ctx.canEdit && open.length > 1 ? `<button type="button" class="sm" data-ackall>${t('alle als gelesen markieren')}</button>` : ''}
        ${acked.length ? `<button type="button" class="link sm" data-showacked>${showAcked ? t('gelesene ausblenden') : t('{n} gelesene anzeigen', { n: acked.length })}</button>` : ''}</span></div>
      ${open.length ? `<ul>${open.map(item).join('')}</ul>` : `<p class="muted small" style="margin:6px 0 0">${t('Keine offenen Hinweise.')}</p>`}
      ${showAcked && acked.length ? `<ul class="ackedlist">${acked.map(item).join('')}</ul>` : ''}</div>` : ''}
    <div class="row between"><h2>${t('Subnetze')}</h2>${ctx.canEdit ? `<button class="pri sm" id="addsn">${t('+ Subnetz')}</button>` : ''}</div><div id="sn"></div>
    <div class="row between"><h2>${t('VLANs')}</h2>${ctx.canEdit ? `<button class="pri sm" id="addvl">${t('+ VLAN')}</button>` : ''}</div><div id="vl"></div>`;
  sortTable($('#sn'), [
    { k: 'cidr', label: t('Netz'), cls: 'mono', val: s => ipNum(s.cidr.split('/')[0]) },
    { k: 'name', label: t('Name') },
    { k: 'vid', label: t('VLAN'), val: s => s.vid || 0, html: s => s.vid ? `${s.vid}${s.vlan_name ? ' · ' + h(s.vlan_name) : ''}` : '' },
    { k: 'gateway', label: t('Gateway'), cls: 'mono' },
    { k: 'dhcp', label: t('DHCP-Bereich'), cls: 'mono', val: s => ipNum(s.dhcp_start), html: s => s.dhcp_start ? `${h(s.dhcp_start)} – ${h(s.dhcp_end.split('.').pop())}` : '' },
    { k: 'used', label: t('Belegung'), val: s => s.used / s.size, html: s => `<div class="usage"><div class="meter"><i style="width:${Math.min(100, s.used / s.size * 100).toFixed(1)}%"></i></div><span class="mono">${s.used}/${s.size}</span></div>` },
  ], subnets, { key: 'sn', onRow: s => subnetDialog(ctx, s.id), empty: t('Noch kein Subnetz. Für dein Heimnetz zum Beispiel 192.168.178.0/24 mit Gateway 192.168.178.1.') });
  sortTable($('#vl'), [
    { k: 'vid', label: t('VLAN-ID'), cls: 'mono' }, { k: 'name', label: t('Name') },
    { k: 'subnets', label: t('Subnetze'), cls: 'mono', val: v => v.subnets.join(' '), html: v => v.subnets.map(h).join(', ') },
    { k: 'description', label: t('Beschreibung') },
  ], vlans, { key: 'vl', onRow: ctx.canEdit ? v => vlanDialog(ctx, v, vlans) : null, empty: t('Noch keine VLANs.') });
  const ack = async (keys, on) => { try { await api('POST', `${P}/hints/ack`, { keys, ack: on }); ctx.reload(); } catch (e) { toast(e.message, true); } };
  $$('[data-ack]', ctx.el).forEach(b => b.onclick = () => ack([b.closest('li').dataset.key], b.dataset.ack === '1'));
  const aa = $('[data-ackall]', ctx.el); if (aa) aa.onclick = () => ack(open.map(c => c.key), true);
  const sa = $('[data-showacked]', ctx.el); if (sa) sa.onclick = () => { tabIpam.showAcked = !tabIpam.showAcked; ctx.reload(); };
  const as = $('#addsn'); if (as) as.onclick = () => subnetForm(ctx, null, vlans);
  const av = $('#addvl'); if (av) av.onclick = () => vlanDialog(ctx, null, vlans);
}

async function subnetForm(ctx, s, vlans) {
  s = s || {};
  const r = await dialog(s.id ? t('Subnetz bearbeiten') : t('Neues Subnetz'), `<div class="grid2">
      <div><label>${t('Netz (CIDR)')}</label><input name="cidr" class="mono" required value="${h(s.cidr || '')}" placeholder="192.168.178.0/24"></div>
      <div><label>${t('Name')}</label><input name="name" value="${h(s.name || '')}" placeholder="${t('z. B. Heimnetz')}"></div>
      <div><label>${t('Gateway')}</label><input name="gateway" class="mono" value="${h(s.gateway || '')}" placeholder="192.168.178.1"></div>
      <div><label>${t('DNS (optional)')}</label><input name="dns" class="mono" value="${h(s.dns || '')}"></div>
      <div><label>${t('DHCP von')}</label><input name="dhcp_start" class="mono" value="${h(s.dhcp_start || '')}" placeholder="192.168.178.20"></div>
      <div><label>${t('DHCP bis')}</label><input name="dhcp_end" class="mono" value="${h(s.dhcp_end || '')}" placeholder="192.168.178.200"></div>
      <div><label>${t('VLAN')}</label><select name="vlan_id"><option value="">–</option>${vlans.map(v => `<option value="${v.id}" ${v.id === s.vlan_id ? 'selected' : ''}>${v.vid} ${h(v.name)}</option>`).join('')}</select></div>
    </div><label>${t('Beschreibung')}</label><textarea name="description" rows="2">${h(s.description || '')}</textarea>`,
    { onOk: f => { const v = fd(f); v.vlan_id = v.vlan_id ? +v.vlan_id : null; return s.id ? api('PUT', `/api/profiles/${ctx.pid}/subnets/${s.id}`, v) : api('POST', `/api/profiles/${ctx.pid}/subnets`, v); } });
  if (r) { toast(t('gespeichert')); ctx.reload(); }
}

async function subnetDialog(ctx, sid) {
  const P = `/api/profiles/${ctx.pid}`;
  const [det, { vlans }] = await Promise.all([api('GET', `${P}/subnets/${sid}`), api('GET', `${P}/vlans`)]);
  const s = det.subnet;
  const free = det.free;
  const html = `
    ${ctx.canEdit ? `<div class="dlg-actions"><button type="button" class="sm" data-edit>${t('Bearbeiten')}</button><button type="button" class="sm danger" data-del>${t('Löschen')}</button></div>` : ''}
    <div class="kv"><span>${t('Gateway')}: <b class="mono">${h(s.gateway || '–')}</b></span><span>${t('DHCP-Bereich')}: <b class="mono">${s.dhcp_start ? h(s.dhcp_start + ' – ' + s.dhcp_end) : '–'}</b></span>
      <span>${t('VLAN')}: <b>${s.vid ? s.vid + ' ' + h(s.vlan_name) : '–'}</b></span><span>${t('Belegt')}: <b class="mono">${s.used} / ${s.size}</b></span>${s.dns ? `<span>DNS: <b class="mono">${h(s.dns)}</b></span>` : ''}</div>
    ${s.description ? `<p class="muted">${h(s.description)}</p>` : ''}
    <h4>${t('Vergebene Adressen')}</h4>
    <div class="table-wrap"><table class="compact"><thead><tr><th>${t('IP')}</th><th>${t('Gerät')}</th><th>${t('MAC')}</th><th>${t('Art')}</th></tr></thead><tbody>
      ${det.addresses.length ? det.addresses.map(a => `<tr><td class="mono">${h(a.address)}</td><td>${h(a.device_name)}${a.gateway ? ` <span class="badge owner">${t('Gateway')}</span>` : ''}</td><td class="mono">${h(a.mac)}</td>
        <td>${t(IP_KIND[a.kind] || a.kind)}${a.in_dhcp && a.kind === 'static' ? ` <span class="badge warn">${t('im DHCP-Bereich')}</span>` : ''}</td></tr>`).join('') : `<tr><td colspan="4" class="empty">${t('Keine Einträge.')}</td></tr>`}
    </tbody></table></div>
    ${free ? `<h4>${t('Freie Adressen')}</h4><div class="free">${free.map(r => `<span class="${r.dhcp ? 'dhcp' : ''}" title="${r.dhcp ? t('im DHCP-Bereich') : t('frei für statische Adressen')}">${h(r.start)}${r.count > 1 ? ' – ' + h(r.end) : ''} <small>(${r.count})</small></span>`).join('')}</div>
      <p class="muted small"><span class="legend-free"></span> ${t('frei für statische Adressen')} &nbsp; <span class="legend-free dhcp"></span> ${t('frei im DHCP-Bereich')}</p>` : ''}`;
  await dialog(`${s.cidr}${s.name ? ' · ' + s.name : ''}`, html, {
    ok: null, wide: true,
    onOpen: (f, close) => {
      const e = $('[data-edit]', f); if (e) e.onclick = () => { close(null); subnetForm(ctx, s, vlans); };
      const d = $('[data-del]', f); if (d) d.onclick = async () => {
        close(null);
        if (!await confirmDlg(t('Subnetz löschen'), t('Subnetz {n} löschen? Die IP-Adressen der Geräte bleiben erhalten.', { n: h(s.cidr) }), t('Löschen'))) return;
        await api('DELETE', `${P}/subnets/${sid}`); ctx.reload();
      };
    },
  });
}

async function vlanDialog(ctx, v, vlans) {
  v = v || {};
  const r = await dialog(v.id ? t('VLAN bearbeiten') : t('Neues VLAN'), `
    ${v.id ? `<div class="dlg-actions"><button type="button" class="sm danger" data-del>${t('Löschen')}</button></div>` : ''}
    <div class="grid2"><div><label>${t('VLAN-ID')}</label><input name="vid" type="number" min="1" max="4094" required value="${h(v.vid || '')}"></div>
    <div><label>${t('Name')}</label><input name="name" value="${h(v.name || '')}" placeholder="${t('z. B. IoT')}"></div></div>
    <label>${t('Beschreibung')}</label><textarea name="description" rows="2">${h(v.description || '')}</textarea>`, {
    onOpen: (f, close) => {
      const d = $('[data-del]', f); if (d) d.onclick = async () => {
        close(null);
        if (!await confirmDlg(t('VLAN löschen'), t('VLAN {n} löschen? Zugeordnete Subnetze bleiben ohne VLAN erhalten.', { n: v.vid }), t('Löschen'))) return;
        await api('DELETE', `/api/profiles/${ctx.pid}/vlans/${v.id}`); ctx.reload();
      };
    },
    onOk: f => v.id ? api('PUT', `/api/profiles/${ctx.pid}/vlans/${v.id}`, fd(f)) : api('POST', `/api/profiles/${ctx.pid}/vlans`, fd(f)),
  });
  if (r) { toast(t('gespeichert')); ctx.reload(); }
}

/* ---------------------------------------------------------------- Standorte */
async function tabLocations(ctx) {
  const P = `/api/profiles/${ctx.pid}`;
  const { locations } = await api('GET', `${P}/locations`);
  const depth = l => (l.path.match(/ › /g) || []).length;
  ctx.el.innerHTML = `<div class="row between"><p class="muted" style="margin:0">${t('Standorte bilden einen Baum, zum Beispiel Haus › Erdgeschoss › Büro.')}</p>
      ${ctx.canEdit ? `<button class="pri sm" id="addloc">${t('+ Standort')}</button>` : ''}</div>
    <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>${t('Standort')}</th><th>${t('Geräte')}</th><th></th></tr></thead><tbody>
    ${locations.length ? locations.map(l => `<tr data-id="${l.id}"><td><span style="padding-left:${depth(l) * 22}px">${depth(l) ? '<span class="muted">└ </span>' : ''}${h(l.name)}</span></td><td class="mono">${l.devices}</td>
      <td class="act">${ctx.canEdit ? `<button class="sm" data-sub>${t('+ Unterstandort')}</button><button class="sm" data-edit>${t('Bearbeiten')}</button><button class="sm danger" data-del>${t('Löschen')}</button>` : ''}</td></tr>`).join('')
      : `<tr><td colspan="3" class="empty">${t('Noch keine Standorte.')}</td></tr>`}</tbody></table></div>`;
  const form = async (l, parent) => {
    const r = await dialog(l ? t('Standort bearbeiten') : t('Neuer Standort'), `<label>${t('Name')}</label><input name="name" required maxlength="80" value="${h(l?.name || '')}" placeholder="${t('z. B. Keller')}">
      <label>${t('Liegt in')}</label><select name="parent_id"><option value="">${t('– oberste Ebene –')}</option>${locations.filter(x => !l || (x.id !== l.id && !x.path.startsWith(l.path + ' › '))).map(x => `<option value="${x.id}" ${x.id === (l ? l.parent_id : parent) ? 'selected' : ''}>${h(x.path)}</option>`).join('')}</select>`,
      { onOk: f => { const v = fd(f); v.parent_id = v.parent_id ? +v.parent_id : null; return l ? api('PUT', `${P}/locations/${l.id}`, v) : api('POST', `${P}/locations`, v); } });
    if (r) ctx.reload();
  };
  const byId = id => locations.find(x => x.id === +id);
  const al = $('#addloc'); if (al) al.onclick = () => form(null, null);
  $$('[data-sub]', ctx.el).forEach(b => b.onclick = () => form(null, +b.closest('tr').dataset.id));
  $$('[data-edit]', ctx.el).forEach(b => b.onclick = () => form(byId(b.closest('tr').dataset.id)));
  $$('[data-del]', ctx.el).forEach(b => b.onclick = async () => {
    const l = byId(b.closest('tr').dataset.id);
    if (!await confirmDlg(t('Standort löschen'), t('„{n}“ löschen? Geräte und Unterstandorte rücken eine Ebene nach oben.', { n: h(l.name) }), t('Löschen'))) return;
    await api('DELETE', `${P}/locations/${l.id}`); ctx.reload();
  });
}

/* ---------------------------------------------------------------- Ausgabe */
function tabOutput(ctx) {
  const P = `/api/profiles/${ctx.pid}`;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem('dk_pdf_sections') || 'null'); } catch { }
  const on = k => !saved || saved.includes(k);
  ctx.el.innerHTML = `<div class="grid-out">
    <div class="panel"><h3>${t('Drucken / PDF')}</h3><p class="muted">${t('Wähle aus, was ins PDF soll. Das PDF ist hell gesetzt und für A4 gedacht.')}</p>
      ${SECTIONS.map(([k, n]) => `<label class="chk"><input type="checkbox" data-sec="${k}" ${on(k) ? 'checked' : ''}> ${t(n)}</label>`).join('')}
      <div class="row" style="margin-top:14px"><button class="pri" id="pdf">${t('PDF erstellen')}</button></div></div>
    <div class="panel"><h3>${t('Tabellen (CSV)')}</h3><p class="muted">${t('Für Excel, LibreOffice oder Numbers. Trennzeichen ist das Semikolon.')}</p>
      <div class="row"><a class="btn" href="${P}/export/devices.csv?lang=${LANG}">${t('Geräteliste')}</a><a class="btn" href="${P}/export/ips.csv?lang=${LANG}">${t('IP-Adressen')}</a></div></div></div>`;
  $('#pdf').onclick = () => {
    const secs = $$('[data-sec]', ctx.el).filter(x => x.checked).map(x => x.dataset.sec);
    if (!secs.length) return toast(t('Bitte mindestens einen Abschnitt wählen'), true);
    try { localStorage.setItem('dk_pdf_sections', JSON.stringify(secs)); } catch { }
    window.open(`${P}/export/report.pdf?sections=${secs.join(',')}&lang=${LANG}`, '_blank');
  };
}

window.INV = { geraete: tabDevices, ipam: tabIpam, standorte: tabLocations, ausgabe: tabOutput };
