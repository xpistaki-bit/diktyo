'use strict';
/* Portfreigaben und UPnP: was der Router aus dem Internet an Geräte im Heimnetz weiterleitet (aus FRITZ!Box, ASUS, OpenWrt,
   MikroTik, OPNsense, UniFi). Neue Freigaben sind markiert, bis sie quittiert werden; Notiz je Eintrag. díktyo ändert nichts am Router. */

/* Dienste, die man nicht offen ins Internet stellen sollte (externer Port) */
const RISKY_PORTS = { 21: 'FTP', 22: 'SSH', 23: 'Telnet', 25: 'SMTP', 135: 'RPC', 139: 'NetBIOS', 445: 'SMB', 1433: 'MSSQL', 1883: 'MQTT', 2375: 'Docker',
  3306: 'MySQL', 3389: 'RDP', 5432: 'PostgreSQL', 5900: 'VNC', 6379: 'Redis', 8006: 'Proxmox', 8123: 'Home Assistant', 9100: 'Drucker', 27017: 'MongoDB' };
function riskyOf(ext) {
  const out = [];
  for (const part of String(ext || '').split(',')) {
    const [a, b] = part.split('-').map(Number);
    if (!a) continue;
    for (const [p, name] of Object.entries(RISKY_PORTS)) if (+p >= a && +p <= (b || a)) out.push(name);
  }
  return [...new Set(out)];
}

async function tabPortfw(ctx) {
  await meta(ctx.pid);  // Gerätetypen für den Gerätedialog
  const P = `/api/profiles/${ctx.pid}`;
  const ui = tabPortfw.ui[ctx.pid] || (tabPortfw.ui[ctx.pid] = { q: '', kind: '', onlyNew: false });
  let st = await api('GET', `${P}/portforwards`);
  const kindTxt = k => k === 'upnp' ? t('UPnP (vom Gerät)') : k === 'static' ? t('eingerichtet') : t('Freigabe');
  const leaseTxt = s => !s ? '' : s < 3600 ? t('läuft ab in {n} min', { n: Math.max(1, Math.round(s / 60)) }) : t('läuft ab in {n} h', { n: Math.round(s / 3600) });

  function rows() {
    const q = ui.q.trim().toLowerCase();
    return st.items.filter(x => (!ui.onlyNew || x.new) && (!ui.kind || (ui.kind === 'upnp' ? x.kind === 'upnp' : x.kind !== 'upnp'))
      && (!q || [x.ip, x.ext, x.port, x.desc, x.note, x.proto, x.source, x.device?.name].join(' ').toLowerCase().includes(q)));
  }

  function bodyHtml() {
    const tr = rows().map(x => {
      const risky = riskyOf(x.ext);
      return `<tr class="${x.enabled ? '' : 'muted'}${x.new ? ' pf-new' : ''}">
        <td>${x.new ? `<span class="badge warn">${t('neu')}</span>` : ''}</td>
        <td class="small">${kindTxt(x.kind)}${x.lease ? `<div class="muted">${h(leaseTxt(x.lease))}</div>` : ''}</td>
        <td class="mono">${h(x.proto)}</td>
        <td class="mono"><b>${h(x.ext || t('alle'))}</b>${risky.map(r => ` <span class="badge risk" title="${h(t('Dienst, der selten offen im Internet stehen sollte'))}">⚠ ${h(t(r))}</span>`).join('')}</td>
        <td>${x.device ? `<a href="#" data-dev="${x.device.id}">${h(x.device.name)}</a><div class="mono small muted">${h(x.ip)}</div>` : `<span class="mono">${h(x.ip)}</span><div class="small muted">${t('kein bekanntes Gerät')}</div>`}</td>
        <td class="mono">${h(x.port || t('wie extern'))}</td>
        <td class="small">${h(x.desc)}${x.remote ? `<div class="muted">${t('nur von {n}', { n: h(x.remote) })}</div>` : ''}${x.enabled ? '' : ` <span class="badge">${t('aus')}</span>`}</td>
        <td class="small">${h(x.source)}</td>
        <td class="small">${h(x.note)}${ctx.canEdit ? ` <button type="button" class="sm" data-note="${h(x.key)}" title="${h(t('Notiz bearbeiten'))}">✎</button>` : ''}</td>
        <td>${ctx.canEdit && x.new ? `<button type="button" class="sm" data-ack="${h(x.key)}">${t('bekannt')}</button>` : ''}</td></tr>`;
    }).join('');
    return tr || `<tr><td colspan="10" class="muted">${t('Keine Treffer.')}</td></tr>`;
  }

  function drawBody() {
    const tb = $('#pfbody', ctx.el);
    if (!tb) return;
    tb.innerHTML = bodyHtml();
    bindRows();
  }

  function draw() {
    const src = st.sources.map(s => `${h(s.name)} (${s.count})`).join(', ');
    ctx.el.innerHTML = `<div class="panel">
      <div class="hud-h"><h3>${t('Portfreigaben und UPnP')}</h3>${st.new ? `<span class="hint">${t('{n} neu', { n: st.new })}</span>` : ''}</div>
      <p class="muted small">${t('Was der Router aus dem Internet an Geräte im Heimnetz weiterleitet – eingerichtete Freigaben und solche, die Geräte per UPnP selbst angelegt haben. Neue Einträge bleiben markiert, bis du sie als bekannt bestätigst. díktyo ändert nichts am Router.')}</p>
      ${(st.problems || []).map(x => `<div class="hint-box small warnc"><b>${h(x.name)}:</b> ${h(ts(x.error))}${x.driver === 'fritzbox' && /Recht/.test(x.error) ? ` – ${t('in der FRITZ!Box unter System → FRITZ!Box-Benutzer → Benutzer bearbeiten.')}` : ''}</div>`).join('')}
      ${!st.sources.length && (st.problems || []).length ? '' : !st.sources.length ? `<div class="hint-box small">${t('Noch keine Quelle. Portfreigaben liefern: FRITZ!Box (mit Benutzer), ASUS, OpenWrt, MikroTik (API/REST), OPNsense (ab 25.7) und UniFi – jeweils als Integration.')}</div>` : `
      <div class="kv small"><span>${t('Freigaben')}: <b>${st.total}</b></span><span>UPnP: <b>${st.upnp}</b></span><span>${t('Quellen')}: ${src}</span></div>
      <div class="row pf-filters" style="margin:10px 0;flex-wrap:wrap;gap:8px">
        <input type="search" id="pfq" placeholder="${h(t('Suchen (IP, Port, Gerät, Beschreibung) …'))}" value="${h(ui.q)}" style="max-width:320px">
        <select id="pfkind"><option value="">${t('alle Arten')}</option><option value="static" ${ui.kind === 'static' ? 'selected' : ''}>${t('eingerichtet')}</option><option value="upnp" ${ui.kind === 'upnp' ? 'selected' : ''}>UPnP</option></select>
        <label class="row small" style="gap:6px"><input type="checkbox" id="pfnew" ${ui.onlyNew ? 'checked' : ''}> ${t('nur neue')}</label>
        <span style="flex:1"></span>
        ${ctx.canEdit && st.new ? `<button type="button" id="pfackall">${t('Alle als bekannt bestätigen')}</button>` : ''}
        <a class="btn" href="${P}/portforwards.csv?lang=${LANG}">${t('CSV speichern')}</a></div>
      ${st.total ? `<div class="table-wrap"><table class="compact pf-table"><thead><tr><th></th><th>${t('Art')}</th><th>${t('Protokoll')}</th><th>${t('Port extern')}</th><th>${t('Ziel')}</th>
        <th>${t('Port intern')}</th><th>${t('Beschreibung')}</th><th>${t('Quelle')}</th><th>${t('Notiz')}</th><th></th></tr></thead>
        <tbody id="pfbody">${bodyHtml()}</tbody></table></div>`
        : `<div class="allok"><b>✓</b>${t('Keine Portfreigaben – der Router leitet nichts aus dem Internet weiter.')}</div>`}
      ${st.sources.some(s => s.driver === 'fritzbox') ? `<p class="muted small">${t('FRITZ!Box: TR-064 sagt nicht, ob eine Freigabe in der Oberfläche eingerichtet oder von einem Gerät angelegt wurde; Einträge mit Laufzeit gelten als UPnP. IPv6-Freigaben und MyFRITZ!-Freigaben fehlen in der Liste. Abfrage alle 5 Minuten.')}</p>` : ''}`}
    </div>`;
    const q = $('#pfq', ctx.el);
    if (q) q.oninput = () => { ui.q = q.value; drawBody(); };
    const k = $('#pfkind', ctx.el);
    if (k) k.onchange = () => { ui.kind = k.value; drawBody(); };
    const nw = $('#pfnew', ctx.el);
    if (nw) nw.onchange = () => { ui.onlyNew = nw.checked; drawBody(); };
    const all = $('#pfackall', ctx.el);
    if (all) all.onclick = async () => { try { st = await api('POST', `${P}/portforwards/ack`, {}); toast(t('Als bekannt bestätigt')); draw(); } catch (e) { toast(e.message, true); } };
    bindRows();
  }

  function bindRows() {
    $$('[data-ack]', ctx.el).forEach(b => b.onclick = async () => {
      try { st = await api('POST', `${P}/portforwards/ack`, { keys: [b.dataset.ack] }); draw(); } catch (e) { toast(e.message, true); }
    });
    $$('[data-dev]', ctx.el).forEach(a => a.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +a.dataset.dev); });
    $$('[data-note]', ctx.el).forEach(b => b.onclick = async () => {
      const x = st.items.find(i => i.key === b.dataset.note);
      if (!x) return;
      const ok = await dialog(t('Notiz zur Freigabe'), `<p class="muted small mono">${h(x.proto)} ${h(x.ext || t('alle'))} → ${h(x.ip)}${x.port ? ':' + h(x.port) : ''}${x.desc ? ' · ' + h(x.desc) : ''}</p>
        <label>${t('Notiz')}</label><input name="note" maxlength="200" value="${h(x.note)}" placeholder="${h(t('z. B. „Nextcloud – bewusst offen“'))}">`, {
        onOk: f => api('PUT', `${P}/portforwards/note`, { key: x.key, note: fd(f).note }),
      });
      if (ok) { st = ok; draw(); }
    });
  }
  draw();
}
tabPortfw.ui = {};
window.INV.portfreigaben = tabPortfw;
/* Link „Portfreigaben“ im Gerätedialog: Dialog schließen, dann zum Reiter */
document.addEventListener('click', ev => { if (ev.target.closest('[data-pfgo]')) { const d = document.getElementById('dlg'); if (d?.open) d.close(); } });
