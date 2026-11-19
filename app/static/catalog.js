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
  app.innerHTML = `<div class="page wide"><h1>${t('Katalog')}</h1>${catalogTabs('geraete')}
    <p class="sub">${t('Gängige Geräte mit ihren Ports. Ein Katalogmodell legt beim Gerät die Ports an; die Angaben lassen sich je Gerät anpassen. Einträge des Startkatalogs sind nach Herstellerangaben erfasst, aber nicht einzeln geprüft.')}</p>
    <div class="toolbar"><input type="search" id="q" placeholder="${t('Suchen …')}" value="${h(f.q)}">
      <select id="ft"><option value="">${t('Alle Typen')}</option>${TYPE_KEYS.filter(k => models.some(m => m.type === k)).map(k => `<option value="${k}" ${f.type === k ? 'selected' : ''}>${catType(k)}</option>`).join('')}</select>
      <select id="fm"><option value="">${t('Alle Hersteller')}</option>${mans.map(m => `<option ${f.man === m ? 'selected' : ''}>${h(m)}</option>`).join('')}</select>
      <span class="grow"></span><span class="muted" id="cnt"></span>
      <a class="btn sm" href="/api/catalog/export.csv">${t('CSV exportieren')}</a>
      ${admin ? `<a class="btn sm" href="/api/catalog/export.csv?template=1">${t('CSV-Vorlage')}</a><button class="sm" id="imp">${t('CSV importieren')}</button><button class="sm" id="sysinfo" title="${t('Hersteller und Modell aus dmidecode, lspci & Co. übernehmen')}">${t('Aus Systeminfo')}</button><button class="pri" id="add">${t('+ Eigener Eintrag')}</button>` : ''}
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
    $('#sysinfo').onclick = () => sysinfoDialog();
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

/* Katalogeintrag aus Systeminformationen: auswerten, optional nachschlagen, dann im normalen Dialog prüfen */
async function sysinfoDialog() {
  let res = null;
  const ok = await dialog(t('Katalogeintrag aus Systeminfo'), `
    <p class="muted small">${t('Ausgabe einfügen, z. B. von <span class="mono">dmidecode -t system</span> (Linux/Proxmox), <span class="mono">lspci</span> für die Netzwerkkarten, <span class="mono">hostnamectl</span> oder unter Windows <span class="mono">Get-CimInstance Win32_ComputerSystem | fl</span>. Mehrere Ausgaben dürfen untereinander stehen.')}</p>
    <textarea name="text" rows="11" class="mono" spellcheck="false" placeholder="System Information&#10;        Manufacturer: Dell Inc.&#10;        Product Name: OptiPlex 7040"></textarea>
    <label class="chk"><input type="checkbox" name="lookup" checked> ${t('Im Internet nachschlagen (Wikipedia) – gesendet werden nur Hersteller und Modell, nie Seriennummer oder UUID')}</label>`, {
    ok: t('Auswerten'), wide: true,
    onOk: async f => { const v = fd(f); res = await api('POST', '/api/catalog/from-sysinfo', { text: v.text, lookup: !!v.lookup, lang: LANG }); return true; },
  });
  if (!ok || !res) return;
  if (res.existing) {
    toast(t('„{n}“ steht schon im Katalog – Eintrag geöffnet.', { n: `${res.existing.manufacturer} ${res.existing.model}` }));
    return catalogDialog(res.existing);
  }
  const s = res.suggestion, i = res.info;
  const facts = [i.family && `${t('Familie')}: ${i.family}`, i.sku && `SKU: ${i.sku}`, i.chassis && `${t('Gehäuse')}: ${i.chassis}`,
    i.nics?.length ? `${t('Netzwerk')}: ${i.nics.join(', ')}` : t('Keine Netzwerkkarte angegeben – 1× RJ45 1G angenommen (lspci-Ausgabe ergänzt das)')].filter(Boolean);
  const intro = `<div class="hint-box small"><b>${t('Erkannt')}:</b> ${h(facts.join(' · '))}
    ${res.lookup ? `<br><b>${t('Gefunden')}:</b> <a href="${h(res.lookup.url)}" target="_blank" rel="noopener">${h(res.lookup.title)} (Wikipedia)</a>` : ''}
    ${res.ignored.length ? `<br><span class="muted">${t('Seriennummer und UUID gehören zum einzelnen Gerät und werden nicht in den Katalog übernommen.')}</span>` : ''}
    ${i.virtual ? `<br><span class="warnc">${t('Das ist eine virtuelle Maschine – meist besser direkt als Gerät vom Typ „VM“ anlegen.')}</span>` : ''}
    <br><span class="muted">${t('Bitte prüfen und ergänzen (Ports, WLAN), dann speichern.')}</span></div>`;
  return catalogDialog(s, intro);
}

async function catalogDialog(m, intro = '') {
  m = m || { type: 'switch', ports: [{ count: 8, kind: 'rj45', speed: '1G' }] };
  const r = await dialog(m.id ? `${m.manufacturer} ${m.model}` : t('Eigener Katalogeintrag'), `${intro}
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
      const body = { ...v, managed: !!v.managed, verified: !!v.verified, ports: readPorts($('#pe', f)), source: m.source || '' };
      return m.id ? api('PUT', `/api/catalog/${m.id}`, body) : api('POST', '/api/catalog', body);
    },
  });
  if (r) { toast(t('gespeichert')); viewCatalog(); }
}

/* ---------------------------------------------------------------- Erkennungsregeln */
const RULE_FIELDS = [['vendor', 'Hersteller (MAC)'], ['hostname', 'Hostname'], ['mdns', 'mDNS'], ['ssdp', 'UPnP'], ['http', 'Weboberfläche']];
function catalogTabs(active) {
  return `<nav class="tabs"><a href="#/katalog" class="${active === 'geraete' ? 'on' : ''}">${t('Geräte')}</a><a href="#/katalog/regeln" class="${active === 'regeln' ? 'on' : ''}">${t('Erkennungsregeln')}</a></nav>`;
}
const condText = c => [...RULE_FIELDS.filter(([k]) => c[k]).map(([k, n]) => `${t(n)} ~ ${c[k]}`), c.ports ? t('Ports {p} offen', { p: c.ports.join('+') }) : '',
  c.any_ports ? t('einer der Ports {p} offen', { p: c.any_ports.join('/') }) : '', c.random ? t('zufällige MAC') : ''].filter(Boolean).join(' · ');

async function viewRules() {
  crumbs([[t('Katalog'), '#/katalog'], [t('Erkennungsregeln')]]);
  const { rules } = await api('GET', '/api/rules');
  const admin = STATE.user.is_admin;
  const f = viewRules.f;
  app.innerHTML = `<div class="page wide"><h1>${t('Katalog')}</h1>${catalogTabs('regeln')}
    <p class="sub">${t('Regeln, mit denen der Netzscan unbekannte Geräte einordnet. Eine Regel trifft zu, wenn alle ihre Bedingungen zutreffen (reguläre Ausdrücke, Groß-/Kleinschreibung egal); die Regel mit dem höchsten Gewicht gewinnt.')}</p>
    <div class="toolbar"><input type="search" id="q" placeholder="${t('Suchen …')}" value="${h(f.q)}"><span class="grow"></span><span class="muted" id="cnt"></span>
      <a class="btn sm" href="/api/rules/export.csv">${t('CSV exportieren')}</a>
      ${admin ? `<button class="sm" id="imp">${t('CSV importieren')}</button><button class="pri" id="add">${t('+ Eigene Regel')}</button>` : ''}</div>
    <div id="list"></div><input type="file" id="file" accept=".csv,text/csv" hidden></div>`;
  const cols = [
    { k: 'label', label: t('Erkannt als'), html: r => `<b>${h(LANG === 'en' ? r.label_en || r.label : r.label)}</b>` },
    { k: 'type', label: t('Typ'), val: r => catType(r.type), html: r => h(catType(r.type)) },
    { k: 'cond', label: t('Bedingungen'), cls: 'small', val: r => condText(r.cond), html: r => `<span class="mono">${h(condText(r.cond))}</span>` },
    { k: 'weight', label: t('Gewicht'), cls: 'mono' },
    { k: 'custom', label: t('Status'), val: r => r.custom ? 0 : 1, html: r => r.custom ? `<span class="badge owner">${t('eigen')}</span>` : `<span class="badge">${t('Standard')}</span>` },
  ];
  const draw = () => {
    const q = f.q.trim().toLowerCase();
    const rows = rules.filter(r => !q || [r.label, r.label_en, r.type, condText(r.cond)].join(' ').toLowerCase().includes(q));
    $('#cnt').textContent = t('{n} Einträge', { n: rows.length });
    sortTable($('#list'), cols, rows, { key: 'rules', initial: { k: 'weight', dir: -1 }, onRow: admin ? r => ruleDialog(r) : null });
  };
  $('#q').oninput = e => { f.q = e.target.value; draw(); };
  if (admin) {
    $('#add').onclick = () => ruleDialog(null);
    $('#imp').onclick = () => $('#file').click();
    $('#file').onchange = async ev => {
      const file = ev.target.files[0]; if (!file) return;
      const fdata = new FormData(); fdata.append('file', file);
      try {
        const r = await api('POST', '/api/rules/import/csv', fdata);
        await dialog(t('CSV-Import'), `<p>${t('{n} neu, {u} aktualisiert.', { n: r.new, u: r.updated })}</p>${r.errors.length ? `<ul>${r.errors.map(e => `<li>${h(e)}</li>`).join('')}</ul>` : ''}`, { ok: null });
        viewRules();
      } catch (e) { toast(e.message, true); }
    };
  }
  draw();
}
viewRules.f = { q: '' };

async function ruleDialog(r) {
  r = r || { label: '', label_en: '', type: 'iot', weight: 70, cond: {} };
  const c = r.cond;
  const res = await dialog(r.id ? t('Regel bearbeiten') : t('Eigene Regel'), `
    ${r.id ? `<div class="dlg-actions"><button type="button" class="sm danger" data-del>${t('Löschen')}</button></div>` : ''}
    <div class="grid2">
      <div><label>${t('Erkannt als (Deutsch)')}</label><input name="label" required value="${h(r.label)}" placeholder="${t('z. B. Saugroboter')}"></div>
      <div><label>${t('Erkannt als (Englisch)')}</label><input name="label_en" value="${h(r.label_en)}"></div>
      <div><label>${t('Typ')}</label><select name="type">${TYPE_KEYS.map(k => `<option value="${k}" ${k === r.type ? 'selected' : ''}>${catType(k)}</option>`).join('')}</select></div>
      <div><label>${t('Gewicht (1–99)')}</label><input name="weight" type="number" min="1" max="99" value="${h(r.weight)}"></div>
    </div>
    <h4>${t('Bedingungen (alle müssen zutreffen)')}</h4>
    <div class="grid2">${RULE_FIELDS.map(([k, n]) => `<div><label>${t(n)}</label><input name="${k}" class="mono" value="${h(c[k] || '')}" placeholder="${k === 'vendor' ? 'roborock|dreame' : ''}"></div>`).join('')}
      <div><label>${t('Alle diese Ports offen')}</label><input name="ports" class="mono" value="${h((c.ports || []).join(', '))}" placeholder="8123"></div>
      <div><label>${t('Einer dieser Ports offen')}</label><input name="any_ports" class="mono" value="${h((c.any_ports || []).join(', '))}" placeholder="9100, 631"></div>
      <div><label>&nbsp;</label><label class="chk"><input type="checkbox" name="random" ${c.random ? 'checked' : ''}> ${t('zufällige MAC-Adresse')}</label></div></div>
    <p class="muted small">${t('Reguläre Ausdrücke, z. B. „echo|alexa“. Leere Felder werden nicht geprüft.')}</p>
    ${r.id && !r.custom ? `<p class="muted small">${t('Standardregel. Nach dem Speichern gilt sie als eigene Regel und wird bei Updates nicht mehr überschrieben.')}</p>` : ''}`, {
    wide: true,
    onOpen: (f, close) => {
      const d = $('[data-del]', f);
      if (d) d.onclick = async () => { close(null); if (await confirmDlg(t('Regel löschen'), t('„{n}“ löschen?', { n: h(r.label) }), t('Löschen'))) { await api('DELETE', `/api/rules/${r.id}`); viewRules(); } };
    },
    onOk: f => { const v = fd(f); v.random = !!v.random; return r.id ? api('PUT', `/api/rules/${r.id}`, v) : api('POST', '/api/rules', v); },
  });
  if (res) { toast(t('gespeichert')); viewRules(); }
}
