'use strict';
/* Verkabelung: Patchfelder und Netzwerkdosen mit Belegung, Kabelwege (Switch-Port – Patchfeld – Dose – Gerät) mit
   Kabelnummern und Abgleich mit den erkannten Verbindungen. Dazu der Abschnitt im Gerätedialog. */

const CHECK = {
  ok: ['ok', '✓', 'passt zum Netz'],
  mismatch: ['warn', '⚠', 'laut Netz hängt dort etwas anderes'],
  unknown: ['', '–', 'nicht prüfbar (Switch-Port und Gerät angeben, Verbindung muss bekannt sein)'],
};

function runChain(r) {
  const seg = (txt, cls = '') => `<span class="cw-node ${cls}">${txt}</span>`;
  const cab = n => `<span class="cw-cab">${n ? `<b class="mono">${h(n)}</b>` : ''}</span>`;
  // Stationen 0 Switch, 1 Patchfeld, 2 Dose, 3 Gerät; Kabel i liegt zwischen Station i und i+1
  const st = [[r.switch, () => seg(`${h(r.switch)} · ${t('Port')} ${h(r.port_name)}`, 'n-sw')], [r.panel, () => seg(`${h(r.panel)} · ${h(r.panel_port)}`, 'n-pp')],
    [r.outlet, () => seg(`${h(r.outlet)} · ${h(r.outlet_port)}`, 'n-os')], [r.device, () => seg(h(r.device), 'n-dv')]];
  const cables = [r.cable_a, r.cable_b, r.cable_c];
  const idx = st.map((x, i) => x[0] ? i : -1).filter(i => i >= 0);
  return `<span class="cw">${idx.map((i, k) => st[i][1]() + (k < idx.length - 1 ? cab(cables.slice(i, idx[k + 1]).filter(Boolean).join(' / ')) : '')).join('')}</span>`;
}

function panelPorts(p, onEditCls) {
  const n = p.ports, per = n > 12 && p.kind === 'panel' ? Math.ceil(n / 2) : n;
  const box = no => {
    const u = p.used[String(no)];
    return `<button type="button" class="pp-port ${u ? 'used ' + (CHECK[u.check]?.[0] || '') : ''} ${onEditCls}" data-pp="${p.id}" data-port="${no}"
      title="${h(u ? `${no}: ${u.label || t('belegt')}` : `${no}: ${t('frei')}`)}">${no}</button>`;
  };
  const rows = [];
  for (let s = 1; s <= n; s += per) rows.push(`<div class="pp-row">${Array.from({ length: Math.min(per, n - s + 1) }, (_, i) => box(s + i)).join('')}</div>`);
  return `<div class="pp-ports">${rows.join('')}</div>`;
}

async function tabCabling(ctx) {
  const P = `/api/profiles/${ctx.pid}`;
  let o = await api('GET', `${P}/cabling`);
  const { locations } = await api('GET', `${P}/locations`);
  let q = '';
  const draw = () => {
    const panels = o.panels.filter(p => p.kind === 'panel'), outlets = o.panels.filter(p => p.kind === 'outlet');
    const card = p => `<div class="panel pp-card"><div class="hud-h"><h3>${h(p.name)}${p.location ? `<em>${h(p.location)}</em>` : ''}</h3>
        <span class="row"><span class="hint">${Object.keys(p.used).length} / ${p.ports}</span>${ctx.canEdit ? `<button type="button" class="sm" data-ppedit="${p.id}">${t('Bearbeiten')}</button>` : ''}</span></div>
        ${panelPorts(p, ctx.canEdit ? 'ed' : '')}${p.note ? `<p class="muted small">${h(p.note)}</p>` : ''}</div>`;
    const ql = q.toLowerCase();
    const runs = o.runs.filter(r => !ql || [r.switch, r.port_name, r.panel, r.outlet, r.device, r.cable_a, r.cable_b, r.cable_c, r.note].join(' ').toLowerCase().includes(ql));
    const ck = r => { const [cls, ic, txt] = CHECK[r.check]; return `<span class="ck ${cls}" title="${h(t(txt))}${r.check === 'mismatch' ? ': ' + h(r.peers.map(x => x.name).join(', ')) : ''}">${ic}${r.check === 'mismatch' ? ' ' + h(r.peers.map(x => x.name).join(', ')) : ''}</span>`; };
    ctx.el.innerHTML = `<div class="toolbar"><input type="search" id="cq" placeholder="${h(t('Suchen: Port, Patchfeld, Dose, Kabelnummer, Gerät …'))}" value="${h(q)}">
        <span class="grow"></span>${ctx.canEdit ? `<button type="button" data-addpanel="panel">+ ${t('Patchfeld')}</button><button type="button" data-addpanel="outlet">+ ${t('Dose')}</button>
        <button type="button" class="pri" data-addrun>+ ${t('Kabelweg')}</button>` : ''}</div>
      ${!o.panels.length && !o.runs.length ? `<div class="panel"><div class="hud-h"><h3>${t('Verkabelung dokumentieren')}</h3></div>
        <p>${t('Hier hältst du fest, welcher Switch-Port über welches Patchfeld und welche Netzwerkdose zu welchem Gerät führt – mit den Nummern auf den Kabeln.')}</p>
        <ol class="muted"><li>${t('Patchfelder und Dosen anlegen (Name, Standort, Anzahl Ports).')}</li><li>${t('Kabelwege eintragen: Switch-Port → Patchkabel → Patchfeld-Port → Verlegekabel → Dose → Anschlusskabel → Gerät. Jeder Teil ist optional.')}</li>
        <li>${t('díktyo vergleicht jeden Kabelweg mit der erkannten Verbindung am Switch-Port und markiert Abweichungen.')}</li></ol></div>` : ''}
      ${panels.length ? `<h2>${t('Patchfelder')}</h2><div class="pp-grid">${panels.map(card).join('')}</div>` : ''}
      ${outlets.length ? `<h2>${t('Netzwerkdosen')}</h2><div class="pp-grid os">${outlets.map(card).join('')}</div>` : ''}
      ${o.runs.length ? `<h2>${t('Kabelwege')} <small class="muted">(${o.runs.length})</small></h2><div id="runs"></div>` : ''}`;
    if ($('#runs', ctx.el)) sortTable($('#runs', ctx.el), [
      { k: 'path', label: t('Weg'), val: r => `${r.switch} ${String(r.switch_port || 0).padStart(4, '0')} ${r.panel} ${String(r.panel_port || 0).padStart(4, '0')}`, html: runChain },
      { k: 'check', label: t('Abgleich'), val: r => ({ mismatch: 0, unknown: 1, ok: 2 })[r.check], html: ck },
      { k: 'note', label: t('Notiz'), html: r => `<span class="small muted">${h(r.note)}</span>` },
    ], runs, { key: 'cab', initial: { k: 'path', dir: 1 }, onRow: r => ctx.canEdit && runDialog(r), empty: t('Kein Kabelweg passt zur Suche.') });
    const cq = $('#cq', ctx.el);
    cq.oninput = e => { q = e.target.value; const pos = e.target.selectionStart; draw(); const n = $('#cq', ctx.el); n.focus(); n.setSelectionRange(pos, pos); };
    $$('[data-addpanel]', ctx.el).forEach(b => b.onclick = () => panelDialog({ kind: b.dataset.addpanel }));
    $$('[data-ppedit]', ctx.el).forEach(b => b.onclick = () => panelDialog(o.panels.find(p => p.id === +b.dataset.ppedit)));
    const ar = $('[data-addrun]', ctx.el);
    if (ar) ar.onclick = () => runDialog({});
    $$('.pp-port.ed', ctx.el).forEach(b => b.onclick = () => {
      const p = o.panels.find(x => x.id === +b.dataset.pp), u = p.used[b.dataset.port];
      if (u) return runDialog(o.runs.find(r => r.id === u.run));
      runDialog(p.kind === 'panel' ? { panel_id: p.id, panel_port: +b.dataset.port } : { outlet_id: p.id, outlet_port: +b.dataset.port });
    });
  };

  const send = async (method, url, body, msg) => {
    try { o = await api(method, `${P}${url}`, body); if (msg) toast(msg); draw(); return true; } catch (e) { toast(e.message, true); return false; }
  };

  async function panelDialog(p) {
    const isNew = !p.id, outlet = p.kind === 'outlet';
    const title = isNew ? (outlet ? t('Neue Dose') : t('Neues Patchfeld')) : h(p.name);
    const res = await dialog(title, `<label>${t('Name')}</label><input name="name" required maxlength="80" value="${h(p.name || '')}" placeholder="${h(outlet ? t('z. B. Dose Wohnzimmer 2') : t('z. B. PP1 Keller'))}">
      <div class="grid2"><div><label>${t('Ports')}</label><input name="ports" type="number" min="1" max="96" value="${p.ports || (outlet ? 2 : 24)}"></div>
        <div><label>${t('Standort')}</label><select name="location_id"><option value="">–</option>${locations.map(l => `<option value="${l.id}" ${l.id === p.location_id ? 'selected' : ''}>${h(l.path)}</option>`).join('')}</select></div></div>
      <label>${t('Notiz')}</label><input name="note" maxlength="500" value="${h(p.note || '')}">
      ${isNew ? '' : `<p style="margin-top:14px"><button type="button" class="sm danger" data-ppdel>${outlet ? t('Dose löschen') : t('Patchfeld löschen')}</button></p>`}`,
    {
      onOpen: (f, close) => {
        const del = $('[data-ppdel]', f);
        if (del) del.onclick = async () => {
          close(null);
          if (await confirmDlg(t('Löschen'), t('„{n}“ löschen? Kabelwege bleiben erhalten, nur ohne diesen Teil.', { n: h(p.name) }), t('Löschen')))
            send('DELETE', `/cabling/panels/${p.id}`, null, t('gelöscht'));
        };
      },
      onOk: async f => { const v = fd(f); v.kind = p.kind; return await send(isNew ? 'POST' : 'PUT', isNew ? '/cabling/panels' : `/cabling/panels/${p.id}`, v, t('gespeichert')) ? true : false; },
    });
    return res;
  }

  async function runDialog(r) {
    const isNew = !r.id;
    const pans = kind => o.panels.filter(p => p.kind === kind);
    const opt = (list, cur, lab = x => x.name) => `<option value="">–</option>` + list.map(x => `<option value="${x.id}" ${x.id === cur ? 'selected' : ''}>${h(lab(x))}</option>`).join('');
    const html = `<p class="muted small">${t('Jeder Teil ist optional – z. B. Switch direkt auf eine Dose oder Patchfeld direkt auf ein Gerät im Rack.')}</p>
      <div class="cw-form">
        <div class="cw-st"><span class="cw-ic sw">⇄</span><div class="grid2"><div><label>${t('Switch / Router')}</label><select name="switch_id">${opt(o.switches, r.switch_id)}</select></div>
          <div><label>${t('Port')}</label><select name="switch_port"></select></div></div></div>
        <div class="cw-cb"><label>${t('Patchkabel-Nr.')}</label><input name="cable_a" maxlength="60" value="${h(r.cable_a || '')}" placeholder="${h(t('z. B. P-05'))}"></div>
        <div class="cw-st"><span class="cw-ic pp">▦</span><div class="grid2"><div><label>${t('Patchfeld')}</label><select name="panel_id">${opt(pans('panel'), r.panel_id)}</select></div>
          <div><label>${t('Port')}</label><select name="panel_port"></select></div></div></div>
        <div class="cw-cb"><label>${t('Verlegekabel-Nr.')}</label><input name="cable_b" maxlength="60" value="${h(r.cable_b || '')}" placeholder="${h(t('z. B. K-012'))}"></div>
        <div class="cw-st"><span class="cw-ic os">◫</span><div class="grid2"><div><label>${t('Dose')}</label><select name="outlet_id">${opt(pans('outlet'), r.outlet_id)}</select></div>
          <div><label>${t('Anschluss')}</label><select name="outlet_port"></select></div></div></div>
        <div class="cw-cb"><label>${t('Anschlusskabel-Nr.')}</label><input name="cable_c" maxlength="60" value="${h(r.cable_c || '')}"></div>
        <div class="cw-st"><span class="cw-ic dv">▣</span><div><label>${t('Gerät')}</label><select name="device_id">${opt(o.devices, r.device_id)}</select></div></div><p class="muted small cw-peer" id="cwpeer"></p>
      </div>
      <label>${t('Notiz')}</label><input name="note" maxlength="500" value="${h(r.note || '')}">
      ${isNew ? '' : `<p style="margin-top:14px"><button type="button" class="sm danger" data-rundel>${t('Kabelweg löschen')}</button></p>`}`;
    return dialog(isNew ? t('Neuer Kabelweg') : t('Kabelweg bearbeiten'), html, {
      wide: true,
      onOpen: (f, close) => {
        const s = n => $(`[name=${n}]`, f);
        const usedBy = (kind, id) => new Set(o.runs.filter(x => x.id !== r.id && x[kind + '_id'] === id).map(x => x[kind + '_port']));
        const fillSw = () => {
          const sw = o.switches.find(x => x.id === +s('switch_id').value), used = usedBy('switch', +s('switch_id').value);
          s('switch_port').innerHTML = sw ? `<option value="">–</option>` + sw.ports.map(p => `<option value="${p.no}" ${p.no === r.switch_port ? 'selected' : ''} ${used.has(p.no) ? 'disabled' : ''}>${h(p.name)}${p.peers.length ? ' → ' + h(p.peers.join(', ')) : ''}${used.has(p.no) ? ' · ' + t('schon eingetragen') : ''}</option>`).join('') : '';
          s('switch_port').disabled = !sw;
          peer();
        };
        const fillPan = (kind, sel, portSel, cur) => {
          const p = o.panels.find(x => x.id === +s(sel).value), used = usedBy(kind, +s(sel).value);
          s(portSel).innerHTML = p ? `<option value="">–</option>` + Array.from({ length: p.ports }, (_, i) => i + 1).map(n => `<option value="${n}" ${n === cur ? 'selected' : ''} ${used.has(n) ? 'disabled' : ''}>${n}${used.has(n) ? ' · ' + t('belegt') : ''}</option>`).join('') : '';
          s(portSel).disabled = !p;
        };
        const peer = () => {
          const sw = o.switches.find(x => x.id === +s('switch_id').value), p = sw?.ports.find(x => x.no === +s('switch_port').value);
          $('#cwpeer', f).textContent = p?.peers.length ? t('Laut Netz an diesem Port: {n}', { n: p.peers.join(', ') }) : '';
          if (p?.peers.length === 1 && !s('device_id').value) {  // Gerät vom Switch-Port vorschlagen
            const d = o.devices.find(x => x.name === p.peers[0]);
            if (d) s('device_id').value = d.id;
          }
        };
        s('switch_id').onchange = () => { r.switch_port = null; fillSw(); };
        s('switch_port').onchange = peer;
        s('panel_id').onchange = () => fillPan('panel', 'panel_id', 'panel_port', null);
        s('outlet_id').onchange = () => fillPan('outlet', 'outlet_id', 'outlet_port', null);
        fillSw(); fillPan('panel', 'panel_id', 'panel_port', r.panel_port); fillPan('outlet', 'outlet_id', 'outlet_port', r.outlet_port);
        const del = $('[data-rundel]', f);
        if (del) del.onclick = async () => { close(null); if (await confirmDlg(t('Kabelweg löschen'), t('Diesen Kabelweg löschen?'), t('Löschen'))) send('DELETE', `/cabling/runs/${r.id}`, null, t('gelöscht')); };
      },
      onOk: async f => await send(isNew ? 'POST' : 'PUT', isNew ? '/cabling/runs' : `/cabling/runs/${r.id}`, fd(f), t('gespeichert')) ? true : false,
    });
  }

  draw();
}
window.INV.verkabelung = tabCabling;

/* im Gerätedialog: Kabelwege des Geräts (als Endgerät oder als Switch) */
async function cableBox(ctx, did, el) {
  let r;
  try { r = await api('GET', `/api/profiles/${ctx.pid}/devices/${did}/cabling`); } catch { return; }
  if (!r.runs.length) { el.innerHTML = ''; return; }
  const runs = [...r.runs].sort((a, b) => (a.switch_port || 0) - (b.switch_port || 0));
  el.innerHTML = `<h4>${t('Verkabelung')} <a class="small" href="#/p/${ctx.pid}/verkabelung">${t('alle Kabelwege')} →</a></h4>
    <div class="cw-list">${runs.slice(0, 48).map(x => `<div class="cw-line">${runChain(x)}${x.check !== 'unknown' ? `<span class="ck ${CHECK[x.check][0]}" title="${h(t(CHECK[x.check][2]))}">${CHECK[x.check][1]}</span>` : ''}</div>`).join('')}</div>`;
}
