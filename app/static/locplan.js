'use strict';
/* Grundriss/Raumplan und Rack-Ansicht eines Standorts (#/p/<pid>/standorte/<lid>).
   Grundriss: Bild oder Raster, darauf Geräte, Patchfelder/Dosen (Punkte) und Unterstandorte (Rechtecke) – Koordinaten
   relativ 0…1. Rack: Vorderansicht mit Höheneinheiten (HE 1 unten). Bearbeiten: aus der Liste rechts auf den Plan bzw.
   ins Rack ziehen (oder antippen und dann auf die Stelle tippen), verschieben durch Ziehen. */

const LP_PANEL_ICON = 'M2 8h20v8H2zM5 11h2v2H5zM9 11h2v2H9zM13 11h2v2h-2zM17 11h2v2h-2z';
const LP_OUTLET_ICON = 'M5 3h14v18H5zM9 8h6v3H9zM9 14h6v3H9z';
const lpIcon = (path, s = 18) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" aria-hidden="true"><path d="${path}" class="ico"/></svg>`;
const lpDevIcon = (type, s) => lpIcon((typeof ICON !== 'undefined' && (ICON[type] || ICON.other)) || '', s);
const lpState = o => o === 1 ? 'on' : o === 0 ? 'off' : 'unk';

async function locView(ctx, lid) {
  const P = `/api/profiles/${ctx.pid}`, L = `${P}/locations/${lid}`;
  let [v] = await Promise.all([api('GET', `${L}/view`), meta(ctx.pid)]);
  let edit = false, armed = null, q = '';
  const send = async (m, url, body) => {
    try { v = await api(m, url, body); draw(); return true; } catch (e) { toast(e.message, true); return false; }
  };
  const devById = id => v.devices.find(d => d.id === id), panById = id => v.panels.find(p => p.id === id);

  function head() {
    const loc = v.location, isRack = loc.kind === 'rack';
    const crumbs = [`<a href="#/p/${ctx.pid}/standorte">${t('Standorte')}</a>`, ...v.chain.map(c => `<a href="#/p/${ctx.pid}/standorte/${c.id}">${h(c.name)}</a>`), `<b>${h(loc.name)}</b>`];
    const kids = v.children.length ? `<div class="lp-kids"><span class="muted small">${t('Unterstandorte')}:</span>${v.children.map(k =>
      `<a class="chip" href="#/p/${ctx.pid}/standorte/${k.id}">${k.kind === 'rack' ? lpIcon(ICON.server || '', 14) : ''}${h(k.name)}</a>`).join('')}</div>` : '';
    return `<div class="lp-head"><div class="lp-crumbs">${crumbs.join(' <span class="muted">›</span> ')}
        <span class="badge">${isRack ? t('Rack · {n} HE', { n: loc.rack_units }) : t('Grundriss')}</span></div>
      <div class="row">${ctx.canEdit ? `<button type="button" class="${edit ? 'pri' : ''}" data-lpedit>${edit ? t('Fertig') : t('Bearbeiten')}</button>` : ''}</div></div>${kids}`;
  }

  /* ---------- Liste rechts: was sich platzieren lässt ---------- */
  function side(isRack) {
    const onPlan = new Set(v.items.map(i => `${i.kind}:${i.ref_id}`));
    const inRack = new Set(v.rack.filter(i => i.ref_id != null).map(i => `${i.kind}:${i.ref_id}`));
    const placed = k => isRack ? inRack.has(k) : onPlan.has(k);
    const match = s => !q || s.toLowerCase().includes(q);
    const row = (kind, x, icon, sub) => `<div class="lp-src ${armed === `${kind}:${x.id}` ? 'armed' : ''}" draggable="true" data-src="${kind}:${x.id}" title="${h(t('Auf den Plan ziehen oder antippen und dann auf die Stelle tippen'))}">
        ${icon}<span><b>${h(x.name)}</b>${sub ? `<em>${h(sub)}</em>` : ''}</span></div>`;
    const devRow = d => row('device', d, lpDevIcon(d.type, 16), isRack ? (d.rack_name ? t('im Rack {r}', { r: d.rack_name }) : d.location) : d.location);
    const panRow = p => row('panel', p, lpIcon(p.kind === 'outlet' ? LP_OUTLET_ICON : LP_PANEL_ICON, 16), `${p.kind === 'outlet' ? t('Dose') : t('Patchfeld')} · ${t('{n} Ports', { n: p.ports })}`);
    const flag = isRack ? 'near' : 'here';
    const devs = v.devices.filter(d => !placed(`device:${d.id}`) && match(`${d.name} ${d.location} ${typeName(d.type)}`));
    const pans = v.panels.filter(p => !placed(`panel:${p.id}`) && (!isRack || p.kind === 'panel') && match(`${p.name} ${p.location}`));
    const rooms = isRack ? [] : v.children.filter(k => !onPlan.has(`room:${k.id}`) && match(k.name));
    const sec = (title, html, open = true) => html ? `<details class="lp-sec" ${open ? 'open' : ''}><summary>${title}</summary>${html}</details>` : '';
    const near = devs.filter(d => d[flag]), far = devs.filter(d => !d[flag]);
    return `<div class="panel lp-side"><h3>${isRack ? t('Einbauen') : t('Platzieren')}</h3>
      <p class="muted small">${isRack ? t('Gerät oder Patchfeld ins Rack ziehen – oder antippen und dann auf die freie Höheneinheit tippen.') : t('Auf den Grundriss ziehen – oder antippen und dann auf die Stelle tippen. Unterstandorte werden als Rechteck eingezeichnet.')}</p>
      <input type="search" id="lpq" placeholder="${h(t('Suchen …'))}" value="${h(q)}">
      ${isRack ? `<button type="button" class="sm" data-other>+ ${t('Sonstiges (USV, Blende, Ablage …)')}</button>` : ''}
      ${sec(t('Unterstandorte'), rooms.map(k => row('room', k, lpIcon(k.kind === 'rack' ? (ICON.server || '') : 'M3 3h18v18H3z', 16), k.kind === 'rack' ? t('Rack') : '')).join(''))}
      ${sec(isRack ? t('Im selben Raum') : t('An diesem Standort'), near.map(devRow).join('') + pans.filter(p => p[flag]).map(panRow).join(''))}
      ${sec(t('Weitere Geräte ({n})', { n: far.length + pans.filter(p => !p[flag]).length }), far.map(devRow).join('') + pans.filter(p => !p[flag]).map(panRow).join(''), !!q || !near.length)}
      ${!devs.length && !pans.length && !rooms.length ? `<p class="muted small">${t('Alles platziert.')}</p>` : ''}</div>`;
  }

  /* ---------- Grundriss ---------- */
  function planHtml() {
    const pl = v.plan, img = pl.image ? `${L}/plan/image?v=${encodeURIComponent(pl.ver)}` : '';
    const kids = Object.fromEntries(v.children.map(k => [k.id, k]));
    const items = v.items.map(it => {
      const pos = `left:${(it.x * 100).toFixed(3)}%;top:${(it.y * 100).toFixed(3)}%`;
      const rm = edit ? `<button type="button" class="lp-rm" data-rm="${it.kind}:${it.ref_id}" title="${h(t('Vom Plan nehmen'))}">×</button>` : '';
      if (it.kind === 'room') {
        const k = kids[it.ref_id];
        return `<div class="lp-room ${k?.kind === 'rack' ? 'rack' : ''}" data-it="room:${it.ref_id}" style="${pos};width:${(it.w * 100).toFixed(3)}%;height:${(it.h * 100).toFixed(3)}%">
          <span>${h(k?.name || '')}</span>${rm}${edit ? '<i class="lp-rs" data-rs></i>' : ''}</div>`;
      }
      const x = it.kind === 'device' ? devById(it.ref_id) : panById(it.ref_id);
      if (!x) return '';
      const ic = it.kind === 'device' ? lpDevIcon(x.type, 16) : lpIcon(x.kind === 'outlet' ? LP_OUTLET_ICON : LP_PANEL_ICON, 16);
      const tip = it.kind === 'device' ? `${x.name} · ${typeName(x.type)} · ${x.online === 1 ? t('online') : x.online === 0 ? t('offline') : t('noch nicht geprüft')}` : x.name;
      return `<div class="lp-pt ${it.kind} ${it.kind === 'device' ? lpState(x.online) : ''}" data-it="${it.kind}:${it.ref_id}" style="${pos}" title="${h(tip)}">
        <span class="lp-ic">${ic}</span><span class="lp-lbl">${h(x.name)}</span>${rm}</div>`;
    }).join('');
    const ratio = pl.ratio || 4 / 3;
    const tools = edit ? `<div class="row lp-tools"><label class="btn sm">${pl.image ? t('Bild ersetzen') : t('Grundriss-Bild hochladen')}<input type="file" id="lpimg" accept="image/png,image/jpeg,image/webp,image/gif" hidden></label>
        ${pl.image ? `<button type="button" class="sm danger" data-noimg>${t('Bild entfernen')}</button>` : `<label class="small muted">${t('Seitenverhältnis')}</label><select id="lpratio" style="width:auto">${[[4 / 3, '4:3'], [16 / 9, '16:9'], [1, '1:1'], [3 / 4, '3:4'], [2, '2:1']]
          .map(([r, n]) => `<option value="${r}" ${Math.abs(r - ratio) < 0.01 ? 'selected' : ''}>${n}</option>`).join('')}</select>`}
        <span class="muted small">${t('PNG, JPEG, WebP oder GIF, höchstens 8 MB – z. B. ein Foto oder Scan des Grundrisses.')}</span></div>` : '';
    return `${tools}<div class="lp-canvas ${edit ? 'ed' : ''} ${img ? 'img' : 'grid'}" id="lpc" style="aspect-ratio:${ratio}">
        ${img ? `<img src="${img}" alt="" draggable="false" id="lpbg">` : ''}${items}
        ${!v.items.length && !edit ? `<div class="lp-empty">${ctx.canEdit ? t('Noch nichts eingezeichnet – oben auf „Bearbeiten“ tippen.') : t('Noch nichts eingezeichnet.')}</div>` : ''}</div>
      <p class="muted small">${t('Punkte: grün online, rot offline, grau nicht geprüft. Orange Quadrate: Patchfelder und Dosen. Ein Klick auf ein Gerät öffnet es, auf ein Rechteck den Unterstandort.')}</p>`;
  }

  /* ---------- Rack ---------- */
  function rackHtml() {
    const units = v.location.rack_units, used = new Set();
    v.rack.forEach(it => { for (let u = it.u; u < it.u + it.height; u++) used.add(u); });
    const cells = [];
    for (let u = units; u >= 1; u--) {
      cells.push(`<div class="rk-n" style="grid-row:${units - u + 1}">${u}</div><div class="rk-n r" style="grid-row:${units - u + 1}">${u}</div>`);
      if (!used.has(u)) cells.push(`<div class="rk-free" data-u="${u}" style="grid-row:${units - u + 1}"></div>`);
    }
    const blocks = v.rack.map(it => {
      const top = it.u + it.height - 1, row = `${units - top + 1} / span ${it.height}`;
      let name = it.label, sub = '', icon = lpIcon('M4 6h16v12H4z', 16), cls = 'other', ports = '';
      if (it.kind === 'device') {
        const d = devById(it.ref_id);
        name = d?.name || '?'; icon = lpDevIcon(d?.type, 16); cls = `device ${lpState(d?.online)}`; sub = d ? typeName(d.type) : '';
        if (d?.ports) ports = `<span class="rk-ports" title="${h(t('{u} von {n} Ports verbunden', { u: d.ports_used, n: d.ports }))}">${Array.from({ length: Math.min(d.ports, 48) }, (_, i) => `<i class="${i < d.ports_used ? 'u' : ''}"></i>`).join('')}</span>`;
      } else if (it.kind === 'panel') {
        const p = panById(it.ref_id);
        name = p?.name || '?'; icon = lpIcon(LP_PANEL_ICON, 16); cls = 'panel'; sub = t('Patchfeld');
        if (p) ports = `<span class="rk-ports pp" title="${h(t('{u} von {n} Ports belegt', { u: p.ports_used, n: p.ports }))}">${Array.from({ length: Math.min(p.ports, 48) }, (_, i) => `<i class="${i < p.ports_used ? 'u' : ''}"></i>`).join('')}</span>`;
      }
      return `<div class="rk-it ${cls}" data-rk="${it.id}" style="grid-row:${row}" title="${h(`${name} · ${t('HE {a}–{b}', { a: it.u, b: top })}`)}">
        <span class="rk-ic">${icon}</span><span class="rk-name"><b>${h(name)}</b>${sub && it.height > 1 ? `<em>${h(sub)}</em>` : ''}</span>${ports}
        ${it.kind === 'device' ? `<span class="dot ${lpState(devById(it.ref_id)?.online) === 'unk' ? '' : lpState(devById(it.ref_id)?.online)}"></span>` : ''}</div>`;
    }).join('');
    const free = units - used.size;
    return `<div class="rk-wrap"><div class="rk ${edit ? 'ed' : ''}" id="rk" style="grid-template-rows:repeat(${units}, var(--rku))">${cells.join('')}${blocks}</div></div>
      <p class="muted small">${t('{u} von {n} HE belegt, {f} frei. Gezählt wird von unten (HE 1).', { u: used.size, n: units, f: free })}
        ${edit ? t('Blöcke lassen sich nach oben und unten ziehen; ein Klick öffnet Höhe und Ausbau.') : t('Ein Klick auf ein Gerät öffnet es.')}</p>`;
  }

  function draw() {
    const isRack = v.location.kind === 'rack';
    ctx.el.innerHTML = `${head()}<div class="lp-grid ${edit ? 'ed' : ''}"><div class="panel lp-main">${isRack ? rackHtml() : planHtml()}</div>${edit ? side(isRack) : ''}</div>`;
    const eb = $('[data-lpedit]', ctx.el);
    if (eb) eb.onclick = () => { edit = !edit; armed = null; draw(); };
    if (edit) bindSide(isRack);
    isRack ? bindRack() : bindPlan();
    fixBg();
  }

  function bindSide(isRack) {
    const qi = $('#lpq', ctx.el);
    qi.oninput = e => { q = e.target.value.trim().toLowerCase(); const pos = e.target.selectionStart; draw(); const n = $('#lpq', ctx.el); n.focus(); n.setSelectionRange(pos, pos); };
    $$('[data-src]', ctx.el).forEach(s => {
      s.ondragstart = e => { e.dataTransfer.setData('text/plain', s.dataset.src); e.dataTransfer.effectAllowed = 'move'; };
      s.onclick = () => { armed = armed === s.dataset.src ? null : s.dataset.src; $$('[data-src]', ctx.el).forEach(x => x.classList.toggle('armed', x.dataset.src === armed)); };
    });
    const ob = $('[data-other]', ctx.el);
    if (ob) ob.onclick = () => rackItemDialog(null);
  }

  /* Grundriss: ablegen, verschieben, Größe ändern */
  function rel(e, el) { const r = el.getBoundingClientRect(); return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) }; }
  function placeOnPlan(src, p) {
    const [kind, ref] = src.split(':');
    const body = { kind, ref_id: +ref, x: p.x, y: p.y };
    if (kind === 'room') Object.assign(body, { x: Math.max(0, p.x - 0.1), y: Math.max(0, p.y - 0.1), w: 0.2, h: 0.2 });
    armed = null;
    send('PUT', `${L}/plan/items`, body);
  }
  function bindPlan() {
    const c = $('#lpc', ctx.el);
    if (!c) return;
    $$('[data-it]', c).forEach(el => {
      const [kind, ref] = el.dataset.it.split(':');
      if (!edit) {
        el.onclick = () => kind === 'device' ? deviceDialog(ctx, +ref) : kind === 'room' ? (location.hash = `#/p/${ctx.pid}/standorte/${ref}`) : (location.hash = `#/p/${ctx.pid}/verkabelung`);
        return;
      }
      el.onpointerdown = e => {
        if (e.target.closest('[data-rm]')) return;
        e.preventDefault();
        const resize = !!e.target.closest('[data-rs]'), it = v.items.find(i => i.kind === kind && i.ref_id === +ref);
        const start = rel(e, c), o = { ...it };
        el.setPointerCapture(e.pointerId);
        el.classList.add('drag');
        let moved = false;
        el.onpointermove = ev => {
          const p = rel(ev, c), dx = p.x - start.x, dy = p.y - start.y;
          moved = moved || Math.abs(dx) + Math.abs(dy) > 0.003;
          if (resize) { it.w = Math.max(0.03, Math.min(1 - o.x, o.w + dx)); it.h = Math.max(0.03, Math.min(1 - o.y, o.h + dy)); el.style.width = it.w * 100 + '%'; el.style.height = it.h * 100 + '%'; }
          else {
            it.x = Math.min(1 - (o.w || 0), Math.max(0, o.x + dx)); it.y = Math.min(1 - (o.h || 0), Math.max(0, o.y + dy));
            el.style.left = it.x * 100 + '%'; el.style.top = it.y * 100 + '%';
          }
        };
        el.onpointerup = () => {
          el.onpointermove = el.onpointerup = null; el.classList.remove('drag');
          if (moved) send('PUT', `${L}/plan/items`, { kind, ref_id: +ref, x: it.x, y: it.y, w: it.w, h: it.h });
        };
      };
    });
    $$('[data-rm]', c).forEach(b => b.onclick = e => { e.stopPropagation(); const [k, r] = b.dataset.rm.split(':'); send('DELETE', `${L}/plan/items/${k}/${r}`); });
    if (!edit) return;
    c.ondragover = e => { e.preventDefault(); c.classList.add('over'); };
    c.ondragleave = () => c.classList.remove('over');
    c.ondrop = e => { e.preventDefault(); c.classList.remove('over'); const src = e.dataTransfer.getData('text/plain'); if (src) placeOnPlan(src, rel(e, c)); };
    c.onclick = e => { if (armed && !e.target.closest('[data-it]')) placeOnPlan(armed, rel(e, c)); };
    const fi = $('#lpimg', ctx.el);
    if (fi) fi.onchange = async () => {
      const f = fi.files[0];
      if (!f) return;
      if (f.size > 8 * 1024 * 1024) return toast(t('Bild zu groß (höchstens 8 MB)'), true);
      try {
        const r = await fetch(`${L}/plan/image`, { method: 'PUT', body: f, headers: { 'X-Lang': LANG, 'X-Requested-With': 'diktyo', 'Content-Type': 'application/octet-stream' } });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || data.detail || t('Fehler'));
        v = data; draw(); toast(t('gespeichert'));
      } catch (e) { toast(e.message, true); }
    };
    const ni = $('[data-noimg]', ctx.el);
    if (ni) ni.onclick = async () => { if (await confirmDlg(t('Bild entfernen'), t('Das Grundriss-Bild entfernen? Die Platzierungen bleiben.'), t('Entfernen'))) send('DELETE', `${L}/plan/image`); };
    const ra = $('#lpratio', ctx.el);
    if (ra) ra.onchange = () => send('PUT', `${L}/plan`, { ratio: +ra.value });
  }
  function fixBg() {  // Seitenverhältnis des Bildes übernehmen
    const bg = $('#lpbg', ctx.el), c = $('#lpc', ctx.el);
    if (bg && c) { const set = () => { if (bg.naturalWidth) c.style.aspectRatio = `${bg.naturalWidth} / ${bg.naturalHeight}`; }; bg.complete ? set() : bg.addEventListener('load', set); }
  }

  /* Rack: einbauen, verschieben, bearbeiten */
  const unitAt = (e, rk) => { const r = rk.getBoundingClientRect(), n = v.location.rack_units; return Math.max(1, Math.min(n, n - Math.floor((e.clientY - r.top) / (r.height / n)))); };
  function mount(src, u) {
    const [kind, ref] = src.split(':');
    const x = kind === 'device' ? devById(+ref) : panById(+ref);
    let height = x?.height || 1;
    const n = v.location.rack_units, busy = new Set();
    v.rack.forEach(it => { for (let k = it.u; k < it.u + it.height; k++) busy.add(k); });
    const fits = b => b >= 1 && b + height - 1 <= n && Array.from({ length: height }, (_, i) => b + i).every(k => !busy.has(k));
    let base = [u, u - height + 1].find(fits);  // ab der getippten HE nach oben oder nach unten
    if (!base && height > 1 && !busy.has(u)) { height = 1; base = u; }
    armed = null;
    send('POST', `${L}/rack`, { kind, ref_id: +ref, u: base || u, height });
  }
  function bindRack() {
    const rk = $('#rk', ctx.el);
    $$('[data-rk]', rk).forEach(el => {
      const it = v.rack.find(x => x.id === +el.dataset.rk);
      if (!edit) {
        if (it.kind === 'device') el.onclick = () => deviceDialog(ctx, it.ref_id);
        else if (it.kind === 'panel') el.onclick = () => { location.hash = `#/p/${ctx.pid}/verkabelung`; };
        return;
      }
      el.onpointerdown = e => {
        e.preventDefault();
        const r = rk.getBoundingClientRect(), uh = r.height / v.location.rack_units, y0 = e.clientY;
        el.setPointerCapture(e.pointerId); el.classList.add('drag');
        let du = 0;
        el.onpointermove = ev => { du = -Math.round((ev.clientY - y0) / uh); el.style.transform = `translateY(${-du * uh}px)`; };
        el.onpointerup = () => {
          el.onpointermove = el.onpointerup = null; el.classList.remove('drag'); el.style.transform = '';
          if (du) send('PUT', `${L}/rack/${it.id}`, { u: it.u + du });
          else rackItemDialog(it);
        };
      };
    });
    if (!edit) return;
    rk.ondragover = e => { e.preventDefault(); rk.classList.add('over'); };
    rk.ondragleave = () => rk.classList.remove('over');
    rk.ondrop = e => { e.preventDefault(); rk.classList.remove('over'); const src = e.dataTransfer.getData('text/plain'); if (src && !src.startsWith('room:')) mount(src, unitAt(e, rk)); };
    $$('[data-u]', rk).forEach(c => c.onclick = () => { if (armed) mount(armed, +c.dataset.u); });
  }
  async function rackItemDialog(it) {
    const n = v.location.rack_units, isNew = !it, other = !it || it.kind === 'other';
    const name = it ? (it.kind === 'device' ? devById(it.ref_id)?.name : it.kind === 'panel' ? panById(it.ref_id)?.name : it.label) : '';
    const busy = new Set();
    v.rack.forEach(x => { if (x !== it) for (let k = x.u; k < x.u + x.height; k++) busy.add(k); });
    const firstFree = Array.from({ length: n }, (_, i) => n - i).find(u => !busy.has(u)) || 1;
    await dialog(isNew ? t('Sonstiges einbauen') : (name || ''), `
      ${other ? `<label>${t('Bezeichnung')}</label><input name="label" maxlength="60" required value="${h(it?.label || '')}" placeholder="${h(t('z. B. USV, Blende, Kabelführung, Ablage'))}">` : ''}
      <div class="grid2"><div><label>${t('Unterste HE')}</label><input name="u" type="number" min="1" max="${n}" value="${it ? it.u : firstFree}"></div>
        <div><label>${t('Höhe (HE)')}</label><input name="height" type="number" min="1" max="${n}" value="${it ? it.height : 1}"></div></div>
      ${it ? `<p style="margin-top:14px" class="row"><button type="button" class="sm danger" data-out>${t('Ausbauen')}</button>
        ${it.kind === 'device' ? `<button type="button" class="sm" data-open>${t('Gerät öffnen')}</button>` : ''}</p>` : ''}`, {
      onOpen: (f, close) => {
        const o = $('[data-out]', f);
        if (o) o.onclick = () => { close(null); send('DELETE', `${L}/rack/${it.id}`); };
        const op = $('[data-open]', f);
        if (op) op.onclick = () => { close(null); deviceDialog(ctx, it.ref_id); };
      },
      onOk: async f => {
        const x = fd(f), body = { u: +x.u, height: +x.height };
        if (other) body.label = x.label;
        return isNew ? send('POST', `${L}/rack`, { kind: 'other', ...body }) : send('PUT', `${L}/rack/${it.id}`, body);
      },
    });
  }

  draw();
}
