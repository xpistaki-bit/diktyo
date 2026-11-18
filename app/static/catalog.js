'use strict';
/* Gerätekatalog: Startdaten + eigene Einträge, CSV-Import/-Export. Ändern dürfen Administratoren. */
const DRIVERS = { '': '–', fritzbox_tr064: 'FRITZ!Box (TR-064)', snmp: 'SNMP', asuswrt: 'ASUS (AiMesh)', omada: 'TP-Link Omada', unifi: 'UniFi', proxmox: 'Proxmox' };
const TYPE_KEYS = ['router', 'modem', 'firewall', 'switch', 'ap', 'mesh', 'repeater', 'powerline', 'server', 'hypervisor', 'vm', 'container', 'nas', 'computer',
  'laptop', 'phone', 'tablet', 'tv', 'speaker', 'camera', 'iot', 'printer', 'console', 'ups', 'other'];
const TYPE_DE = { router: 'Router', modem: 'Modem', firewall: 'Firewall', switch: 'Switch', ap: 'Access Point', mesh: 'Mesh-Knoten', repeater: 'Repeater',
  powerline: 'Powerline', server: 'Server', hypervisor: 'Hypervisor', vm: 'VM', container: 'Container', nas: 'NAS', computer: 'Computer', laptop: 'Laptop',
  phone: 'Smartphone', tablet: 'Tablet', tv: 'TV / Medien', speaker: 'Smart Speaker', camera: 'Kamera', iot: 'IoT-Gerät', printer: 'Drucker',
  console: 'Spielkonsole', ups: 'USV', other: 'Sonstiges' };
const catType = k => t(TYPE_DE[k] || k);

async function viewCatalog() {
  crumbs([[t('Katalog')]]);
  const { models } = await api('GET', '/api/catalog');
  const admin = STATE.user.is_admin;
  const f = viewCatalog.f;
  const mans = [...new Set(models.map(m => m.manufacturer))].sort(cmp);
  app.innerHTML = `<div class="page wide"><h1>${t('Katalog')}</h1>
    <p class="sub">${t('Gängige Geräte mit ihren Ports. Ein Katalogmodell legt beim Gerät die Ports an; die Angaben lassen sich je Gerät anpassen. Einträge des Startkatalogs sind nach Herstellerangaben erfasst, aber nicht einzeln geprüft.')}</p>
    <div class="toolbar"><input type="search" id="q" placeholder="${t('Suchen …')}" value="${h(f.q)}">
      <select id="ft"><option value="">${t('Alle Typen')}</option>${TYPE_KEYS.filter(k => models.some(m => m.type === k)).map(k => `<option value="${k}" ${f.type === k ? 'selected' : ''}>${catType(k)}</option>`).join('')}</select>
      <select id="fm"><option value="">${t('Alle Hersteller')}</option>${mans.map(m => `<option ${f.man === m ? 'selected' : ''}>${h(m)}</option>`).join('')}</select>
      <span class="grow"></span><span class="muted" id="cnt"></span>
      <a class="btn sm" href="/api/catalog/export.csv">${t('CSV exportieren')}</a>
      ${admin ? `<a class="btn sm" href="/api/catalog/export.csv?template=1">${t('CSV-Vorlage')}</a><button class="sm" id="imp">${t('CSV importieren')}</button><button class="pri" id="add">${t('+ Eigener Eintrag')}</button>` : ''}
    </div><div id="list"></div><input type="file" id="file" accept=".csv,text/csv" hidden></div>`;
  const status = m => m.custom ? `<span class="badge owner">${t('eigen')}</span>` : m.verified ? `<span class="badge ok">${t('geprüft')}</span>` : `<span class="badge">${t('ungeprüft')}</span>`;
  const cols = [
    { k: 'manufacturer', label: t('Hersteller') }, { k: 'model', label: t('Modell'), html: m => `<b>${h(m.model)}</b>${m.note ? `<small class="muted block">${h(m.note)}</small>` : ''}` },
    { k: 'type', label: t('Typ'), val: m => catType(m.type), html: m => h(catType(m.type)) },
    { k: 'port_summary', label: t('Ports'), cls: 'mono' }, { k: 'wifi', label: t('WLAN') },
    { k: 'driver', label: t('Anbindung'), val: m => DRIVERS[m.driver || ''], html: m => h(DRIVERS[m.driver || ''] || m.driver) },
    { k: 'status', label: t('Status'), val: m => m.custom ? 0 : m.verified ? 1 : 2, html: status },
    { k: 'used', label: t('Verwendet'), cls: 'mono', html: m => m.used || '' },
  ];
  const draw = () => {
    const q = f.q.trim().toLowerCase();
    const rows = models.filter(m => (!f.type || m.type === f.type) && (!f.man || m.manufacturer === f.man)
      && (!q || [m.manufacturer, m.model, m.note, m.wifi, m.port_summary].join(' ').toLowerCase().includes(q)));
    $('#cnt').textContent = t('{n} Einträge', { n: rows.length });
    sortTable($('#list'), cols, rows, { key: 'cat', onRow: admin ? m => catalogDialog(m) : null, empty: t('Nichts gefunden') });
  };
  $('#q').oninput = e => { f.q = e.target.value; draw(); };
  $('#ft').onchange = e => { f.type = e.target.value; draw(); };
  $('#fm').onchange = e => { f.man = e.target.value; draw(); };
  if (admin) {
    $('#add').onclick = () => catalogDialog(null);
    $('#imp').onclick = () => $('#file').click();
    $('#file').onchange = async ev => {
      const file = ev.target.files[0]; if (!file) return;
      const fdata = new FormData(); fdata.append('file', file);
      try {
        const r = await api('POST', '/api/catalog/import/csv', fdata);
        await dialog(t('CSV-Import'), `<p>${t('{n} neu, {u} aktualisiert.', { n: r.new, u: r.updated })}</p>${r.errors.length ? `<p><b>${t('Übersprungen')}</b></p><ul>${r.errors.map(e => `<li>${h(e)}</li>`).join('')}</ul>` : ''}`, { ok: null });
        viewCatalog();
      } catch (e) { toast(e.message, true); }
    };
  }
  draw();
}
viewCatalog.f = { q: '', type: '', man: '' };

async function catalogDialog(m) {
  m = m || { type: 'switch', ports: [{ count: 8, kind: 'rj45', speed: '1G' }] };
  const r = await dialog(m.id ? `${m.manufacturer} ${m.model}` : t('Eigener Katalogeintrag'), `
    ${m.id ? `<div class="dlg-actions"><button type="button" class="sm danger" data-del>${t('Löschen')}</button></div>` : ''}
    <div class="grid2">
      <div><label>${t('Hersteller')}</label><input name="manufacturer" required maxlength="80" value="${h(m.manufacturer || '')}"></div>
      <div><label>${t('Modell')}</label><input name="model" required maxlength="120" value="${h(m.model || '')}"></div>
      <div><label>${t('Typ')}</label><select name="type">${TYPE_KEYS.map(k => `<option value="${k}" ${k === m.type ? 'selected' : ''}>${catType(k)}</option>`).join('')}</select></div>
      <div><label>${t('Anbindung')}</label><select name="driver">${Object.entries(DRIVERS).map(([k, n]) => `<option value="${k}" ${k === (m.driver || '') ? 'selected' : ''}>${h(n)}</option>`).join('')}</select></div>
      <div><label>${t('WLAN')}</label><input name="wifi" maxlength="80" value="${h(m.wifi || '')}" placeholder="${t('z. B. Wi-Fi 6 (2,4/5 GHz)')}"></div>
      <div><label>&nbsp;</label><label class="chk"><input type="checkbox" name="managed" ${m.managed ? 'checked' : ''}> ${t('verwaltbar (managed)')}</label></div>
    </div>
    <h4>${t('Ports')}</h4><div id="pe">${portEditorHtml(m.ports, '')}</div>
    <label>${t('Hinweis')}</label><input name="note" maxlength="500" value="${h(m.note || '')}">
    <label class="chk"><input type="checkbox" name="verified" ${m.verified ? 'checked' : ''}> ${t('gegen Datenblatt geprüft')}</label>
    ${m.id && !m.custom ? `<p class="muted small">${t('Eintrag aus dem Startkatalog. Nach dem Speichern gilt er als eigener Eintrag und wird bei Updates nicht mehr überschrieben.')}</p>` : ''}`, {
    wide: true,
    onOpen: (f, close) => {
      bindPortEditor($('#pe', f));
      const d = $('[data-del]', f);
      if (d) d.onclick = async () => {
        close(null);
        if (!await confirmDlg(t('Katalogeintrag löschen'), t('„{n}“ löschen? Geräte, die ihn nutzen, behalten ihre Ports.', { n: h(m.manufacturer + ' ' + m.model) }), t('Löschen'))) return;
        await api('DELETE', `/api/catalog/${m.id}`); viewCatalog();
      };
    },
    onOk: f => {
      const v = fd(f);
      const body = { ...v, managed: !!v.managed, verified: !!v.verified, ports: readPorts($('#pe', f)) };
      return m.id ? api('PUT', `/api/catalog/${m.id}`, body) : api('POST', '/api/catalog', body);
    },
  });
  if (r) { toast(t('gespeichert')); viewCatalog(); }
}
