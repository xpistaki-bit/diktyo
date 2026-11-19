'use strict';
/* Topologie: Gesamtbaum und Detailansicht (Frontplatte mit Ports). Nutzt die Hilfen aus app.js, inventory.js, scan.js, integrations.js. */
const MSTYLE = { lan: ['#00E5FF', ''], wlan: ['#19F5C8', '7 6'], mesh: ['#2D7BFF', '2 5'], virtual: ['#7FA6C4', '1 4'] };
const ICON = {  // 24×24, Linien
  router: 'M3 14h18v6H3zM7 14V9M17 14V9M6 17h.01M10 17h.01M5 6a6 6 0 0 1 4-3M19 6a6 6 0 0 0-4-3',
  modem: 'M3 14h18v6H3zM6 17h.01M10 17h.01M12 14V6',
  firewall: 'M3 5h18v14H3zM3 10h18M3 15h18M9 5v5M15 10v5M9 15v4',
  switch: 'M2 8h20v8H2zM5 12h1M8 12h1M11 12h1M14 12h1M17 12h1',
  ap: 'M12 13v8M8 21h8M8.5 9.5a5 5 0 0 1 7 0M5.5 6.5a9 9 0 0 1 13 0M12 13h.01',
  mesh: 'M12 4a3 3 0 1 1 0 .01M5 17a3 3 0 1 1 0 .01M19 17a3 3 0 1 1 0 .01M12 7l-6 8M12 7l6 8M7 18h10',
  repeater: 'M7 21h10l-2-8H9zM12 13V9M8.5 7.5a5 5 0 0 1 7 0',
  powerline: 'M6 3h12v14H6zM10 17v4M14 17v4M10 8h4',
  server: 'M4 3h16v6H4zM4 11h16v6H4zM8 6h.01M8 14h.01M4 19h16',
  hypervisor: 'M3 4h18v12H3zM7 20h10M12 16v4M7 8h4v4H7zM13 8h4v4h-4z',
  vm: 'M4 4h16v12H4zM8 20h8M12 16v4M8 8l4 4 4-4',
  container: 'M3 7l9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10',
  nas: 'M5 3h14v18H5zM5 9h14M5 15h14M9 6h.01M9 12h.01M9 18h.01',
  computer: 'M3 4h18v12H3zM8 20h8M12 16v4',
  laptop: 'M5 5h14v10H5zM2 19h20l-2-4H4z',
  phone: 'M7 2h10v20H7zM11 18h2',
  tablet: 'M5 2h14v20H5zM11 18h2',
  tv: 'M2 5h20v13H2zM8 21h8',
  speaker: 'M7 2h10v20H7zM12 15a3 3 0 1 1 0 .01M12 7h.01',
  camera: 'M2 7h14v10H2zM16 10l6-3v10l-6-3',
  iot: 'M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4',
  printer: 'M6 9V3h12v6M6 18H3v-8h18v8h-3M6 14h12v7H6z',
  console: 'M6 9h12a4 4 0 0 1 0 8H6a4 4 0 0 1 0-8zM8 13h3M9.5 11.5v3M16 12h.01M18 14h.01',
  ups: 'M5 3h14v18H5zM13 7l-3 5h4l-3 5',
  other: 'M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zM12 16h.01M10 9a2 2 0 1 1 3 2c-1 .5-1 1-1 2',
  globe: 'M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zM2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20M4.5 6.5h15M4.5 17.5h15',
};
/* Vollbild: Topologie füllt den Bildschirm unter der Kopfzeile */
function fullscreenToggle(box, btn, onChange) {
  const set = on => {
    box.classList.toggle('full', on);
    box.style.top = on ? `${$('.bar').getBoundingClientRect().bottom}px` : '';
    btn.textContent = on ? t('Normalgröße') : t('Vollbild');
    btn.title = on ? t('Zurück zur Normalgröße (Esc)') : t('Topologie auf den ganzen Bildschirm vergrößern');
    document.body.classList.toggle('topo-fs', on);
    tabTopology.full = on;
    onChange && onChange();
  };
  btn.onclick = () => set(!box.classList.contains('full'));
  const esc = ev => { if (ev.key === 'Escape' && box.classList.contains('full') && !$('#dlg').open) set(false); };
  document.addEventListener('keydown', esc);
  const obs = new MutationObserver(() => { if (!document.body.contains(box)) { document.removeEventListener('keydown', esc); document.body.classList.remove('topo-fs'); obs.disconnect(); } });
  obs.observe(document.body, { childList: true, subtree: true });
  if (tabTopology.full) set(true);
}
const icon = (type, x, y, s = 22) => `<g transform="translate(${x},${y}) scale(${s / 24})"><path d="${ICON[type] || ICON.other}" class="ico"/></g>`;
const statusCls = o => o == null ? 'unk' : o ? 'on' : 'off';
const esc = s => h(s);  // h kommt aus app.js, das nach dieser Datei geladen wird

/* ---------------------------------------------------------------- Zoom und Verschieben */
function panZoom(svg, vp, state, fit) {
  const apply = () => vp.setAttribute('transform', `translate(${state.tx},${state.ty}) scale(${state.s})`);
  apply();
  let drag = null;
  svg.addEventListener('pointerdown', ev => {
    if (ev.target.closest('.tn,.tg,.port,.card')) return;
    drag = { x: ev.clientX, y: ev.clientY, tx: state.tx, ty: state.ty };
    svg.setPointerCapture(ev.pointerId); svg.classList.add('dragging');
  });
  svg.addEventListener('pointermove', ev => {
    if (!drag) return;
    const k = svg.viewBox.baseVal.width / svg.clientWidth;
    state.tx = drag.tx + (ev.clientX - drag.x) * k; state.ty = drag.ty + (ev.clientY - drag.y) * k; apply();
  });
  const end = () => { drag = null; svg.classList.remove('dragging'); };
  svg.addEventListener('pointerup', end); svg.addEventListener('pointercancel', end);
  svg.addEventListener('wheel', ev => {
    ev.preventDefault();
    const r = svg.getBoundingClientRect(), k = svg.viewBox.baseVal.width / r.width;
    const mx = (ev.clientX - r.left) * k, my = (ev.clientY - r.top) * k;
    const f = ev.deltaY < 0 ? 1.15 : 1 / 1.15, ns = Math.min(3, Math.max(0.15, state.s * f));
    state.tx = mx - (mx - state.tx) * ns / state.s; state.ty = my - (my - state.ty) * ns / state.s; state.s = ns; apply();
  }, { passive: false });
  return {
    zoom: f => { const W = svg.viewBox.baseVal.width / 2, H = svg.viewBox.baseVal.height / 2, ns = Math.min(3, Math.max(0.15, state.s * f));
      state.tx = W - (W - state.tx) * ns / state.s; state.ty = H - (H - state.ty) * ns / state.s; state.s = ns; apply(); },
    fit: () => { Object.assign(state, fit()); apply(); },
  };
}

/* ---------------------------------------------------------------- Gesamtbaum */
async function tabTopology(ctx) {
  if (ctx.sub) return topoDetail(ctx, +ctx.sub);
  const P = `/api/profiles/${ctx.pid}`;
  const exp = tabTopology.expanded[ctx.pid] || (tabTopology.expanded[ctx.pid] = new Set());
  const data = await api('GET', `${P}/topology?expanded=${[...exp].join(',')}`);
  if (!data.nodes.length) {
    ctx.el.innerHTML = `<div class="panel empty-box">${t('Noch keine bestätigten Geräte. Übernimm Geräte aus dem Posteingang oder lege sie an; Verbindungen entstehen über „Anschluss“ im Gerätedialog oder automatisch über die Integrationen.')}</div>`;
    return;
  }
  const NW = data.node_w, NH = data.node_h, PAD = 40;
  const VW = Math.max(900, data.width + PAD * 2), VH = Math.max(420, data.height + PAD * 2);
  ctx.el.innerHTML = `<div class="topo-box" id="tbox"><div class="toolbar topo-tools">
      <button class="pri sm" id="qping">${t('Schnell-Ping')}</button>
      <button class="sm" id="expall">${t('Alle Gruppen aufklappen')}</button><button class="sm" id="colall">${t('Alle zuklappen')}</button>
      <span class="grow"></span>
      <span class="legend topo-legend">${Object.entries(MSTYLE).map(([k, [c, d]]) => `<span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="${c}" stroke-width="2" stroke-dasharray="${d}"/></svg>${t(MEDIUM_SHORT[k])}</span>`).join('')}</span>
      <button class="sm" id="zout" title="${t('Verkleinern')}">−</button><button class="sm" id="zfit">${t('Einpassen')}</button><button class="sm" id="zin" title="${t('Vergrößern')}">+</button>
      <span class="muted small" id="stamp"></span><button class="sm" id="fs">${t('Vollbild')}</button></div>
    <div class="topo-wrap"><svg id="topo" viewBox="0 0 ${VW} ${VH}" class="topo"><g id="vp"></g></svg><aside class="topo-side panel" id="side" hidden></aside></div></div>`;
  const svg = $('#topo', ctx.el), vp = $('#vp', ctx.el);
  const byId = Object.fromEntries(data.nodes.map(n => [n.id, n]));
  const draw = () => {
    const edges = data.edges.map(e => {
      const a = byId[e.source], b = byId[e.target];
      if (!a || !b) return '';
      const x1 = a.x + NW + PAD, y1 = a.y + PAD, x2 = b.x + PAD, y2 = b.y + PAD, mx = (x1 + x2) / 2;
      if (e.medium === 'wan') {
        const cls = e.connected === 1 ? 'wan up' : e.connected === 0 ? 'wan down' : 'wan unk';
        const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
        const lbl = e.rx_bps != null
          ? `<text x="${cx}" y="${cy - 9}" text-anchor="middle" class="wanlabel">↓ ${esc(fmtBps(e.rx_bps))}</text>
             <text x="${cx}" y="${cy + 19}" text-anchor="middle" class="wanlabel up">↑ ${esc(fmtBps(e.tx_bps))}</text>`
          : e.connected === 0 ? `<text x="${cx}" y="${cy - 9}" text-anchor="middle" class="wanlabel">${t('getrennt')}</text>` : '';
        return `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" class="${cls}"/>${lbl}`;
      }
      const [col, dash] = MSTYLE[e.medium] || MSTYLE.lan;
      return `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none" stroke="${col}" stroke-width="1.6" stroke-dasharray="${dash}" opacity=".85"/>
        ${e.label ? `<text x="${x1 + 8}" y="${y1 - 5}" class="elabel">${esc(e.label)}</text>` : ''}${e.child_label ? `<text x="${x2 - 8}" y="${y2 - 5}" class="elabel" text-anchor="end">${esc(e.child_label)}</text>` : ''}`;
    }).join('');
    const nodes = data.nodes.map(n => {
      const x = n.x + PAD, y = n.y + PAD - NH / 2;
      if (n.kind === 'internet') {
        const st = n.online === 1 ? t('verbunden') : n.online === 0 ? t('getrennt') : t('Status unbekannt');
        return `<g class="tn inet ${statusCls(n.online)}" data-id="internet" transform="translate(${x},${y})">
          <rect width="${NW}" height="${NH}" rx="24" class="tn-box"/>${icon('globe', 12, 12, 24)}
          <text x="46" y="21" class="tn-name">${t('Internet')}</text>
          <text x="46" y="37" class="tn-sub">${esc(st)}${n.max_down ? ` · ${fmtBps(n.max_down)}` : ''}</text>
          <circle cx="${NW - 16}" cy="${NH / 2}" r="5" class="tn-dot"/>
          <title>${esc(n.source ? t('Quelle: {n}', { n: n.source }) : t('Kein WAN-Status – FRITZ!Box-Integration einrichten'))}</title></g>`;
      }
      if (n.kind === 'group') {
        const [col] = MSTYLE[n.medium] || MSTYLE.lan;
        return `<g class="tg" data-id="${n.id}" transform="translate(${x},${y})"><rect width="${NW}" height="${NH}" rx="8" class="tg-box" style="stroke:${col}"/>
          ${icon(n.medium === 'virtual' ? 'vm' : 'phone', 12, 13)}<text x="44" y="21" class="tn-name">${esc(t(n.medium === 'virtual' ? '{n} VMs / Container' : '{n} WLAN-Geräte', { n: n.count }))}</text>
          <text x="44" y="37" class="tn-sub">${t('{n} online', { n: n.online_count })} · ${t('aufklappen')}</text><text x="${NW - 18}" y="30" class="tg-plus">+</text>
          <title>${esc(n.names.join(', '))}</title></g>`;
      }
      const infra = n.ports_total > 0;
      return `<g class="tn ${statusCls(n.online)}${tabTopology.sel === n.device_id ? ' sel' : ''}" data-id="${n.id}" data-dev="${n.device_id}" transform="translate(${x},${y})">
        <rect width="${NW}" height="${NH}" rx="8" class="tn-box"/>${icon(n.type, 12, 13)}
        <text x="44" y="21" class="tn-name">${esc(n.name.length > 24 ? n.name.slice(0, 23) + '…' : n.name)}</text>
        <text x="44" y="37" class="tn-sub">${esc(n.ip || typeName(n.type))}${infra ? ` · ${n.ports_used}/${n.ports_total}` : ''}</text>
        <circle cx="${NW - 14}" cy="14" r="5" class="tn-dot"/>
        ${exp.has(`${n.device_id}:wlan`) || exp.has(`${n.device_id}:virtual`) ? `<text x="${NW - 18}" y="40" class="tg-plus small" data-collapse="${n.device_id}">−</text>` : ''}</g>`;
    }).join('');
    const sep = data.loose_from ? `<text x="${PAD}" y="${data.loose_from + PAD - NH / 2 - 10}" class="tsep">${t('Ohne Verbindung')}</text>` : '';
    vp.innerHTML = edges + sep + nodes;
    $$('.tn:not(.inet)', vp).forEach(g => g.addEventListener('click', ev => {
      const c = ev.target.closest('[data-collapse]');
      if (c) { exp.delete(`${c.dataset.collapse}:wlan`); exp.delete(`${c.dataset.collapse}:virtual`); return ctx.reload(); }
      side(+g.dataset.dev);
    }));
    $$('.tn:not(.inet)', vp).forEach(g => g.addEventListener('dblclick', () => { const n = byId[g.dataset.id]; if (n.ports_total || n.children) location.hash = `#/p/${ctx.pid}/topologie/${n.device_id}`; }));
    $$('.tg', vp).forEach(g => g.addEventListener('click', () => { const n = byId[g.dataset.id]; exp.add(`${n.parent}:${n.medium}`); ctx.reload(); }));
  };
  draw();
  const fit = () => {
    const r = svg.getBoundingClientRect(), s = Math.min(1.2, Math.max(0.2, Math.min(VW / (data.width + PAD * 2), VH / (data.height + PAD * 2))));
    return { s, tx: (VW - (data.width + PAD * 2) * s) / 2, ty: (VH - (data.height + PAD * 2) * s) / 2, r };
  };
  const st = tabTopology.view[ctx.pid] || (tabTopology.view[ctx.pid] = fit());
  const pz = panZoom(svg, vp, st, fit);
  fullscreenToggle($('#tbox', ctx.el), $('#fs', ctx.el), () => setTimeout(() => pz.fit(), 50));
  $('#zin', ctx.el).onclick = () => pz.zoom(1.25); $('#zout', ctx.el).onclick = () => pz.zoom(1 / 1.25); $('#zfit', ctx.el).onclick = () => pz.fit();
  $('#expall', ctx.el).onclick = () => { data.nodes.filter(n => n.kind === 'group').forEach(n => exp.add(`${n.parent}:${n.medium}`)); ctx.reload(); };
  $('#colall', ctx.el).onclick = () => { exp.clear(); ctx.reload(); };
  $('#stamp', ctx.el).textContent = t('Stand {d}', { d: new Date().toLocaleTimeString(LANG === 'en' ? 'en-GB' : 'de-DE') });

  async function side(did) {
    tabTopology.sel = did;
    $$('.tn', vp).forEach(g => g.classList.toggle('sel', +g.dataset.dev === did));
    const d = await api('GET', `${P}/devices/${did}`);
    const el = $('#side', ctx.el);
    el.hidden = false;
    el.innerHTML = `<div class="row between"><b>${esc(d.name)}</b><button class="sm link" data-close>✕</button></div>
      <p class="muted small" style="margin:2px 0 8px">${esc(typeName(d.type))}${d.manufacturer || d.model ? ' · ' + esc(`${d.manufacturer} ${d.model}`.trim()) : ''}</p>
      <div class="kvt2">${[[t('Status'), `${onlineDot(d)} ${d.online ? t('online') : d.online === 0 ? t('offline') : t('noch nicht geprüft')}`],
        [t('IP'), d.ips.map(i => esc(i.address)).join('<br>')], [t('MAC'), esc(d.mac)], [t('Standort'), esc(d.location)],
        [t('Anschluss'), d.uplink ? `${esc(uplinkText(d.uplink))} <span class="badge">${t(MEDIUM_SHORT[d.uplink.medium])}</span>` : ''],
        [t('zuletzt gesehen'), d.last_seen ? esc(fmtDate(d.last_seen)) : '']].filter(r => r[1]).map(([k, v]) => `<div><span>${k}</span><span class="mono">${v}</span></div>`).join('')}</div>
      ${d.ident_full?.label ? `<p class="small muted">${t('Erkannt als')}: ${esc(identLabel(d.ident_full))}</p>` : ''}
      <div class="row" style="margin-top:10px">${ctx.canEdit ? `<button class="sm" data-edit>${t('Bearbeiten')}</button>` : `<button class="sm" data-edit>${t('Details')}</button>`}
        ${d.ports.length || d.connected.length ? `<a class="btn sm pri" href="#/p/${ctx.pid}/topologie/${d.id}">${t('Detailansicht')}</a>` : ''}
        <button class="sm" data-ping>${t('Ping')}</button></div>`;
    $('[data-close]', el).onclick = () => { el.hidden = true; tabTopology.sel = null; $$('.tn', vp).forEach(g => g.classList.remove('sel')); };
    $('[data-edit]', el).onclick = () => deviceDialog(ctx, d.id);
    $('[data-ping]', el).onclick = () => quickPing(ctx, [d.id]).then(() => side(did));
  }
  $('#qping', ctx.el).onclick = async ev => { ev.target.disabled = true; await quickPing(ctx); ev.target.disabled = false; refresh(); };
  if (tabTopology.sel && data.nodes.some(n => n.device_id === tabTopology.sel)) side(tabTopology.sel);

  // Online-Status laufend aktualisieren, solange die Ansicht offen ist
  async function refresh() {
    if (!document.body.contains(svg)) return;
    try {
      const fresh = await api('GET', `${P}/topology?expanded=${[...exp].join(',')}`);
      if (fresh.nodes.length !== data.nodes.length) return ctx.reload();
      fresh.nodes.forEach(n => { if (byId[n.id]) Object.assign(byId[n.id], { online: n.online, online_count: n.online_count, rx_bps: n.rx_bps, tx_bps: n.tx_bps }); });
      fresh.edges.forEach(e => { const o = data.edges.find(x => x.source === e.source && x.target === e.target); if (o) Object.assign(o, e); });
      draw();
      $('#stamp', ctx.el).textContent = t('Stand {d}', { d: new Date().toLocaleTimeString(LANG === 'en' ? 'en-GB' : 'de-DE') });
    } catch { }
  }
  clearInterval(tabTopology.timer);
  tabTopology.timer = setInterval(() => { if (!document.body.contains(svg)) return clearInterval(tabTopology.timer); refresh(); }, 30000);
}
tabTopology.expanded = {}; tabTopology.view = {}; tabTopology.sel = null;

async function quickPing(ctx, ids) {
  try {
    const r = await api('POST', `/api/profiles/${ctx.pid}/ping`, ids ? { device_ids: ids } : {});
    toast(t('Ping: {n} von {m} online', { n: r.online, m: r.checked }));
    return r;
  } catch (e) { toast(e.message, true); }
}

/* ---------------------------------------------------------------- Detailansicht mit Frontplatte */
async function topoDetail(ctx, did) {
  const P = `/api/profiles/${ctx.pid}`;
  const d = await api('GET', `${P}/devices/${did}`);
  const ports = d.ports, rj = ports.filter(p => !p.kind.startsWith('sfp')), sfp = ports.filter(p => p.kind.startsWith('sfp'));
  const twoRows = rj.length > 8, cols = twoRows ? Math.ceil(rj.length / 2) : rj.length;
  const PW = 36, PH = 30, PG = 8, LEFT = 190, SG = sfp.length ? 30 : 0;
  const sfpCols = twoRows ? Math.ceil(sfp.length / 2) : sfp.length;
  const chassisW = Math.max(420, LEFT + cols * (PW + PG) + SG + sfpCols * (PW + 8 + PG) + 30);
  const chassisH = twoRows ? 2 * PH + 3 * PG + 26 : PH + 2 * PG + 34;
  const CARD_W = 128, CARD_H = 44, LEVEL = 54, LEVELS = 4;
  // Wie viele Kartenebenen oben und unten gebraucht werden (bestimmt die Höhe der Zeichnung)
  const colOf = (p, i, list, off = 0) => (twoRows ? Math.floor(i / 2) : i) + off;
  const topOf = i => twoRows ? i % 2 === 0 : i % 2 === 0;
  const need = { top: -1, bot: -1 };
  [[rj, 0], [sfp, cols]].forEach(([list, off]) => list.forEach((p, i) => {
    if (!p.peer) return;
    const lvl = colOf(p, i, list, off) % LEVELS;
    if (topOf(i)) need.top = Math.max(need.top, lvl); else need.bot = Math.max(need.bot, lvl);
  }));
  const topH = need.top < 0 ? 20 : 40 + (need.top + 1) * LEVEL;
  const cx0 = 40, cy0 = 20 + topH;
  // Positionen der Ports
  const pos = {};
  // row = obere/untere Portreihe am Gerät, top = Seite der Karte; bei einer Reihe stehen alle Beschriftungen oben
  rj.forEach((p, i) => {
    const col = twoRows ? Math.floor(i / 2) : i, upper = !twoRows || i % 2 === 0;
    pos[p.id] = { x: cx0 + LEFT + col * (PW + PG), y: cy0 + 14 + (upper ? 0 : PH + PG), upper, top: topOf(i), col };
  });
  sfp.forEach((p, i) => {
    const col = twoRows ? Math.floor(i / 2) : i, upper = !twoRows || i % 2 === 0;
    pos[p.id] = { x: cx0 + LEFT + cols * (PW + PG) + SG + col * (PW + 8 + PG), y: cy0 + 14 + (upper ? 0 : PH + PG), upper, top: topOf(i), col: cols + col, sfp: true };
  });
  const botH = need.bot < 0 ? 30 : 40 + (need.bot + 1) * LEVEL;
  const VW = Math.max(760, chassisW + 80), VH = cy0 + chassisH + botH;
  // Karten der angeschlossenen Geräte: oben für die obere Portreihe, unten für die untere, gestaffelt in drei Ebenen
  const cards = [];
  ports.forEach(p => {
    if (!p.peer) return;
    const ps = pos[p.id], lvl = ps.col % LEVELS, w = ps.sfp ? PW + 8 : PW;
    const x = Math.min(VW - CARD_W - 10, Math.max(10, ps.x + w / 2 - CARD_W / 2));
    const y = ps.top ? cy0 - 40 - lvl * LEVEL - CARD_H : cy0 + chassisH + 40 + lvl * LEVEL;
    cards.push({ p, x, y, px: ps.x + w / 2, py: ps.top ? (ps.upper ? ps.y : ps.y - PG) : (ps.upper ? ps.y + PH + PG : ps.y + PH) });
  });
  const live = ports.some(p => p.live);
  const portCls = p => p.peer ? 'conn' : p.live ? (p.live.oper === 'up' ? 'up' : 'down') : 'free';
  const wired = d.connected.filter(k => k.medium === 'lan' && !k.port_name), wl = d.connected.filter(k => k.medium === 'wlan' || k.medium === 'mesh'),
    vm = d.connected.filter(k => k.medium === 'virtual');
  const svgBody = `
    ${cards.map(c => `<path d="M${c.px},${c.py} L${c.px},${c.y < c.py ? c.y + CARD_H + 8 : c.y - 8} L${c.x + CARD_W / 2},${c.y < c.py ? c.y + CARD_H : c.y}" class="cline ${c.p.peer.direction === 'up' ? 'up' : ''}"/>`).join('')}
    <g class="chassis"><rect x="${cx0}" y="${cy0}" width="${chassisW}" height="${chassisH}" rx="6"/>
      <text x="${cx0 + 16}" y="${cy0 + 26}" class="ch-name">${esc(d.name.length > 20 ? d.name.slice(0, 19) + '…' : d.name)}</text>
      <text x="${cx0 + 16}" y="${cy0 + 44}" class="ch-sub">${esc(`${d.manufacturer} ${d.model}`.trim().slice(0, 26))}</text>
      <text x="${cx0 + 16}" y="${cy0 + 60}" class="ch-sub">${esc((d.ips[0] || {}).address || '')}</text>
      <circle cx="${cx0 + chassisW - 16}" cy="${cy0 + 14}" r="4" class="tn-dot ${statusCls(d.online)}"/></g>
    ${ports.map(p => { const ps = pos[p.id], w = ps.sfp ? PW + 8 : PW; return `<g class="port ${portCls(p)}${p.poe ? ' poe' : ''}" data-port="${p.id}" transform="translate(${ps.x},${ps.y})">
      <rect width="${w}" height="${PH}" rx="3"/>${ps.sfp ? '' : `<rect x="${w / 2 - 7}" y="${ps.upper ? PH - 7 : 0}" width="14" height="7" class="notch"/>`}
      <text x="${w / 2}" y="${ps.upper ? -5 : PH + 13}" text-anchor="middle" class="pnum">${esc(p.name)}</text>${p.poe ? `<text x="${w - 4}" y="11" text-anchor="end" class="poe-mark">⚡</text>` : ''}
      <title>${esc(p.name)}${p.peer ? ' → ' + esc(p.peer.device_name) : ''}</title></g>`; }).join('')}
    ${cards.map(c => { const pe = c.p.peer; return `<g class="card ${statusCls(null)}" data-dev="${pe.device_id}" data-port="${c.p.id}" transform="translate(${c.x},${c.y})">
      <rect width="${CARD_W}" height="${CARD_H}" rx="6" class="${pe.direction === 'up' ? 'card-up' : ''}"/>${icon(pe.type || 'other', 8, 11, 20)}
      <text x="34" y="18" class="tn-name sm">${esc(pe.device_name.length > 14 ? pe.device_name.slice(0, 13) + '…' : pe.device_name)}</text>
      <text x="34" y="33" class="tn-sub sm">${pe.direction === 'up' ? '↑ ' + t('Uplink') : esc(pe.ip || '')}</text></g>`; }).join('')}`;
  ctx.el.innerHTML = `<div class="topo-box" id="tbox"><div class="toolbar"><a class="btn sm" href="#/p/${ctx.pid}/topologie">← ${t('Gesamtansicht')}</a><b>${esc(d.name)}</b>
      <span class="muted small">${ports.length ? t('{n} Ports, {m} belegt', { n: ports.length, m: ports.filter(p => p.peer).length }) : ''}${live ? ' · ' + t('Status per SNMP') : ''}</span>
      <span class="grow"></span><button class="pri sm" id="pingall">${t('Schnell-Ping')}</button><button class="sm" id="fs">${t('Vollbild')}</button>
      <span class="legend topo-legend"><span><i class="lg conn"></i>${t('belegt')}</span>${live ? `<span><i class="lg up"></i>${t('Link, Gerät unbekannt')}</span><span><i class="lg down"></i>${t('kein Link')}</span>` : `<span><i class="lg free"></i>${t('frei')}</span>`}</span></div>
    <div class="topo-wrap detail">${ports.length ? `<svg viewBox="0 0 ${VW} ${VH}" class="topo face">${svgBody}</svg>` : `<div class="panel empty-box">${t('Dieses Gerät hat keine Ports. Ports kommen aus dem Katalogmodell oder lassen sich im Gerätedialog anlegen.')}</div>`}
      <aside class="topo-side panel" id="side">${d.uplink && !d.uplink.local_port_id ? `<p class="small"><b>${t('Uplink')}:</b> ${esc(uplinkText(d.uplink))}</p>` : ''}
        ${[[t('WLAN / Mesh'), wl], [t('Virtuell'), vm], [t('LAN ohne Port'), wired]].filter(([, l]) => l.length).map(([n, l]) => `<details open><summary>${n} (${l.length})</summary>
          <ul class="clist">${l.map(k => `<li data-dev="${k.id}"><span class="dot ${statusCls(null)}"></span>${esc(k.name)} <span class="mono muted small">${esc(k.ip)}</span></li>`).join('')}</ul></details>`).join('')
        || `<p class="muted small">${t('Klicke auf einen Port oder ein Gerät.')}</p>`}<div id="pinfo"></div></aside></div></div>`;
  fullscreenToggle($('#tbox', ctx.el), $('#fs', ctx.el));
  // Online-Status der Karten aus der Geräteliste
  const { devices } = await api('GET', `${P}/devices`);
  const on = Object.fromEntries(devices.map(x => [x.id, x.online]));
  $$('[data-dev]', ctx.el).forEach(el => {
    const o = on[+el.dataset.dev];
    el.classList.remove('unk'); el.classList.add(statusCls(o));
    const dot = $('.dot', el); if (dot) dot.className = `dot ${o == null ? '' : o ? 'on' : 'off'}`;
  });
  const info = pid_ => {
    const p = ports.find(x => x.id === pid_);
    $$('.port', ctx.el).forEach(g => g.classList.toggle('sel', +g.dataset.port === pid_));
    const pe = p.peer, lv = p.live;
    $('#pinfo', ctx.el).innerHTML = `<h4>${t('Port')} ${esc(p.name)}</h4><div class="kvt2">
      ${[[t('Art'), `${esc(p.kind.toUpperCase())} ${esc(p.speed)}${p.poe ? ' · PoE' : ''}`],
        lv ? [t('Link'), lv.oper === 'up' ? `<span class="okc">${lv.speed >= 1000 ? lv.speed / 1000 + ' Gbit/s' : lv.speed + ' Mbit/s'}</span>` : `<span class="offc">${t('kein Link')}</span>`] : null,
        lv && lv.in_bps != null ? ['↓ / ↑', `${fmtBps(lv.in_bps)} / ${fmtBps(lv.out_bps)}`] : null,
        lv && lv.macs ? [t('gelernt'), t('{n} MAC-Adressen', { n: lv.macs })] : null,
        lv && lv.lldp ? ['LLDP', `${esc(lv.lldp.name)}${lv.lldp.port ? ' · ' + esc(lv.lldp.port) : ''}`] : null,
        [t('Verbunden mit'), pe ? `<b>${esc(pe.device_name)}</b>${pe.direction === 'up' ? ` <span class="badge">${t('Uplink')}</span>` : ''}` : '–'],
        pe ? [t('IP'), esc(pe.ip)] : null, pe ? [t('MAC'), esc(pe.mac)] : null].filter(Boolean).map(([k, v]) => `<div><span>${k}</span><span class="mono">${v}</span></div>`).join('')}</div>
      ${pe ? `<div class="row" style="margin-top:8px"><button class="sm" data-open="${pe.device_id}">${t('Gerät öffnen')}</button>
        <a class="btn sm" href="#/p/${ctx.pid}/topologie/${pe.device_id}">${t('Detailansicht')}</a></div>` : ''}`;
    const ob = $('[data-open]', ctx.el); if (ob) ob.onclick = () => deviceDialog(ctx, +ob.dataset.open);
  };
  $$('.port', ctx.el).forEach(g => g.addEventListener('click', () => info(+g.dataset.port)));
  $$('.card', ctx.el).forEach(g => g.addEventListener('click', () => info(+g.dataset.port)));
  $$('.card', ctx.el).forEach(g => g.addEventListener('dblclick', () => { location.hash = `#/p/${ctx.pid}/topologie/${g.dataset.dev}`; }));
  $$('.clist li', ctx.el).forEach(li => li.onclick = () => deviceDialog(ctx, +li.dataset.dev));
  $('#pingall', ctx.el).onclick = async ev => {
    ev.target.disabled = true;
    await quickPing(ctx, [did, ...ports.filter(p => p.peer).map(p => p.peer.device_id), ...d.connected.map(k => k.id)]);
    ctx.reload();
  };
}

window.INV.topologie = tabTopology;
