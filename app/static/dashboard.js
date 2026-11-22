'use strict';
/* Übersicht eines Profils im HUD-Stil: Kennzahlen, was Aufmerksamkeit braucht, WAN als Balkendiagramm, Internet-Tacho,
   Antwortzeiten, aktivste Ports mit dem Gerät dahinter, gerade aktive Geräte, Infrastruktur als Karten, letzte Änderungen.
   Aktualisiert sich alle 30 Sekunden, solange der Reiter offen ist. */

const devLink = (id, name) => id ? `<a href="#" data-dev="${id}">${h(name)}</a>` : `<span class="mono">${h(name)}</span>`;

function kpi({ label, main, sub = '', cls = '', href = '', vis = '', side = '' }) {
  const tag = href ? `a href="${href}"` : 'div';
  return `<${tag} class="kpi ${cls}"><span class="k-lab">${label}</span>
    <div class="k-row"><div class="k-main">${main}</div>${side}</div>${vis}<span class="k-sub">${sub}</span></${href ? 'a' : 'div'}>`;
}

function kpiTiles(r, pid) {
  const c = r.counts, w = r.wan, sm = r.summary;
  const tiles = [kpi({
    label: t('Geräte online'), main: `<b>${c.online}</b><i>/ ${c.devices}</i>`, href: `#/p/${pid}/geraete`,
    cls: c.offline ? 'warn' : 'ok', vis: hudSegs(c.online, c.devices), sub: c.offline ? t('{n} offline', { n: c.offline }) : t('alle erreichbar'),
  })];
  if (w) {
    const [dn, du] = splitBps(w.rx_bps), [un, uu] = splitBps(w.tx_bps);
    const md = w.max_down || niceMax(w.rx_bps || 1), mu = w.max_up || niceMax(w.tx_bps || 1);
    tiles.push(w.connected === false ? kpi({ label: t('Internet'), main: `<b>${t('getrennt')}</b>`, cls: 'bad fill' }) : kpi({
      label: t('Internet') + ' · ' + h(w.name), main: w.rx_bps != null ? `<span class="ar">↓</span><b>${dn}</b><i>${du}</i>` : `<b>${t('verbunden')}</b>`, cls: 'ok',
      vis: w.rx_bps != null ? `<div class="k-mini"><span>↓</span><div class="fl-bar dn"><i style="width:${Math.min(100, (w.rx_bps || 0) / md * 100).toFixed(1)}%"></i></div>
        <span>↑</span><div class="fl-bar up"><i style="width:${Math.min(100, (w.tx_bps || 0) / mu * 100).toFixed(1)}%"></i></div></div>` : '',
      sub: w.tx_bps != null ? `↑ <b class="mono">${un} ${uu}</b>${w.max_down ? ` · ${t('Leitung')} ${fmtMbit(w.max_down)}` : ''}` : '',
    }));
  }
  const av = c.availability;
  tiles.push(kpi({
    label: t('Verfügbarkeit Infrastruktur'), main: av != null ? `<b>${nf(av, av >= 99.95 ? 0 : 1)}</b><i>%</i>` : '<b>–</b>',
    cls: av == null ? '' : av >= 99.9 ? 'ok' : av >= 98 ? 'warn' : 'bad', side: hudRing(av, { size: 70 }), sub: t('letzte 24 Stunden'),
  }));
  tiles.push(kpi({ label: t('Firmware-Updates'), main: `<b>${c.firmware}</b>`, cls: c.firmware ? 'warn fill' : 'ok', sub: c.firmware ? h(r.firmware.map(x => x.name).slice(0, 3).join(', ')) : t('alles aktuell') }));
  tiles.push(kpi({ label: t('im Posteingang'), main: `<b>${c.inbox}</b>`, cls: c.inbox ? 'info fill' : '', href: `#/p/${pid}/posteingang`, sub: c.inbox ? t('neue Geräte prüfen') : t('nichts Neues') }));
  tiles.push(kpi({ label: t('Änderungen seit gestern'), main: `<b>${sm.changed + sm.created + sm.deleted}</b>`, href: `#/p/${pid}/verlauf`,
    sub: t('{a} neu · {b} geändert · {c} entfernt', { a: sm.created, b: sm.changed, c: sm.deleted }) }));
  return `<div class="kpis">${tiles.join('')}</div>`;
}

function issuesPanel(r, pid) {
  const c = r.counts;
  const issues = [
    ...r.offline.map(x => `<li class="bad"><span class="ic">●</span><span>${devLink(x.id, x.name)} ${t('ist offline')}</span></li>`),
    ...r.broken.map(x => `<li class="bad"><span class="ic">⚠</span><span><a href="#/p/${pid}/integrationen">${h(x.name)}</a>: ${h(x.error)}</span></li>`),
    ...r.failed.map(x => `<li class="bad"><span class="ic">⚡</span><span>${h(t(x.label))}: ${h(x.message || '')}</span></li>`),
    ...r.firmware.map(x => `<li class="warn"><span class="ic">⬆</span><span>${devLink(x.id, x.name)}: ${t('Firmware {a} → {b}', { a: h(x.installed || '?'), b: h(x.latest || t('neue Version')) })}</span></li>`),
    ...(c.inbox ? [`<li class="info"><span class="ic">✚</span><a href="#/p/${pid}/posteingang">${c.inbox === 1 ? t('1 neues Gerät im Posteingang') : t('{n} neue Geräte im Posteingang', { n: c.inbox })}</a></li>`] : []),
    ...(r.speed?.slow ? [`<li class="warn"><span class="ic">⇣</span><span>${t('Internet langsam: zuletzt ↓ {d}, Leitung ↓ {l}', { d: fmtMbit(r.speed.last.down_bps), l: fmtMbit(r.speed.line_down) })}</span></li>`] : []),
    ...(c.quarantine ? [`<li class="warn"><span class="ic">⛔</span><a href="#/p/${pid}/integrationen">${t('{n} in Quarantäne', { n: c.quarantine })}</a></li>`] : []),
  ];
  return `<div class="panel s3"><div class="hud-h"><h3>${t('Braucht Aufmerksamkeit')}</h3>${issues.length ? `<span class="hint">${issues.length}</span>` : ''}</div>
    ${issues.length ? `<ul class="ov-issues">${issues.slice(0, 14).join('')}</ul>` : `<div class="allok"><b>✓</b>${t('Alles in Ordnung.')}</div>`}</div>`;
}

function wanPanel(w, since) {
  if (!w) return `<div class="panel s5"><div class="hud-h"><h3>${t('WAN-Traffic')}</h3></div>
    <p class="muted">${t('Kommt aus der FRITZ!Box-, ASUS-, UniFi-, MikroTik- oder OPNsense-Integration.')}</p></div>`;
  return `<div class="panel s5"><div class="hud-h"><h3>${t('WAN-Traffic')}<em>${h(w.name)}</em></h3>${rangeButtons(since)}</div>
    <div class="wan-wrap"><div class="wan-now">
        <div class="hstat"><span>↓ ${t('Download')} · ${t('jetzt')}</span>${bigVal(splitBps(w.rx_bps))}</div>
        <div class="hstat" style="border-left-color:var(--teal)"><span>↑ ${t('Upload')} · ${t('jetzt')}</span>${bigVal(splitBps(w.tx_bps))}</div>
        ${w.max_down ? `<div class="hstat" style="border-left-color:var(--dim)"><span>${t('Leitung')}</span><b>${nf(w.max_down / 1e6)}</b><i>/ ${nf((w.max_up || 0) / 1e6)} Mbit/s</i></div>` : ''}
      </div><div data-ch="wan"></div></div></div>`;
}

function speedHud(sp, canEdit, pid) {
  const l = sp?.last;
  const head = `<div class="hud-h"><h3>${t('Internet-Geschwindigkeit')}</h3>${canEdit ? `<button class="sm" data-speedrun>${t('Jetzt messen')}</button>` : ''}</div><div data-speedjob></div>`;
  if (!l) return `<div class="panel s4" id="speedpanel">${head}<p class="muted">${t('Noch keine Messung. „Jetzt messen“ prüft Ping, Download und Upload des díktyo-Rechners gegen speed.cloudflare.com (einige hundert MB Datenverkehr). Automatische Messungen: Integrationen → Speedtest.')}</p></div>`;
  const pts = sp.points.map(p => [Date.parse(p[0]) / 1000, p[1], p[2]]).filter(p => !isNaN(p[0]));
  const maxD = sp.line_down || niceMax(Math.max(...pts.map(p => p[1] || 0), l.down_bps || 0));
  const maxU = sp.line_up || niceMax(Math.max(...pts.map(p => p[2] || 0), l.up_bps || 0));
  const q = (v, m) => !sp.line_down ? '' : v >= .8 * m ? '' : v >= .5 * m ? 'warn' : 'bad';
  const since = pts.length > 1 ? Math.max(3600, pts[pts.length - 1][0] - pts[0][0]) * 1.04 : 86400;
  const t1 = pts.length ? pts[pts.length - 1][0] + since * .02 : undefined;
  return `<div class="panel s4" id="speedpanel">${head}
    <div class="sp-top">
      ${hudGauge(l.down_bps, maxD, { label: '↓ ' + t('Download'), cls: q(l.down_bps, maxD), sub: sp.line_down ? `${t('von')} ${fmtMbit(maxD)}` : '' })}
      ${hudGauge(l.up_bps, maxU, { label: '↑ ' + t('Upload'), cls: 'up ' + q(l.up_bps, maxU), sub: sp.line_up ? `${t('von')} ${fmtMbit(maxU)}` : '' })}
      <div class="hstats"><div class="hstat"><span>${t('Ping')}</span><b>${l.ping_ms != null ? nf(l.ping_ms, l.ping_ms < 10 ? 1 : 0) : '–'}</b><i>ms</i></div>
        ${l.jitter_ms != null ? `<div class="hstat"><span>${t('Jitter')}</span><b>${nf(l.jitter_ms, 1)}</b><i>ms</i></div>` : ''}</div>
    </div>
    <p class="muted small" style="margin:4px 0 0">${h(fmtDate(l.ts))} · ${h(l.server)}${l.scheduled ? ' · ' + t('geplant') : ''}</p>
    ${pts.length > 1 ? hudBars([{ name: t('Download'), color: '#00E5FF', points: pts.map(p => [p[0], p[1]]) }, { name: t('Upload'), color: '#19F5C8', points: pts.map(p => [p[0], p[2]]) }],
      since, { height: 120, mirror: true, fmt: v => fmtMbit(v).replace(' Mbit/s', ''), step: since / Math.max(pts.length, 12), t1 }) : ''}
    <p class="small" style="margin:6px 0 0"><a href="#/p/${pid}/integrationen">${t('Einstellungen und Verlauf')} →</a></p></div>`;
}

function rttPanel(rtt) {
  const cls = v => v == null ? '' : v >= 50 ? 'bad' : v >= 15 ? 'warn' : '';
  return `<div class="panel s4"><div class="hud-h"><h3>${t('Antwortzeiten Infrastruktur')}</h3><span class="hint">${t('Ø 24 Stunden')}</span></div>
    ${rtt.length ? rtt.map(x => `<div class="rrow ${x.online === 0 ? 'bad' : cls(x.avg)}">
        <div class="rr-name"><span class="dot ${x.online === 1 ? 'on' : x.online === 0 ? 'off' : ''}"></span> ${devLink(x.id, x.name)}<small>${h(typeName(x.type))}</small></div>
        ${hudSpark(x.spark)}
        <div class="rr-val">${bigVal(x.avg != null ? [nf(x.avg, x.avg < 10 ? 1 : 0), 'ms'] : ['–', ''])}<small>${x.max != null ? `max ${fmtMs(x.max)}` : ''}</small></div></div>`).join('')
    : `<p class="muted">${t('Entsteht mit der Online-Überwachung.')}</p>`}</div>`;
}

function portsPanel(ports) {
  if (!ports.length) return `<div class="panel s4"><div class="hud-h"><h3>${t('Aktivste Ports')}</h3></div>
    <p class="muted">${t('Kommt aus Switch-, MikroTik- oder OPNsense-Integrationen.')}</p></div>`;
  const groups = [...new Set(ports.map(p => p.device))];
  const max = Math.max(...ports.map(p => Math.max(p.in_bps || 0, p.out_bps || 0)));
  const one = groups.length === 1;
  const row = p => {
    const peers = p.peers || [];
    const who = peers.length ? peers.slice(0, 2).map(x => devLink(x.id, x.name)).join(', ') + (peers.length > 2 ? ` +${peers.length - 2}` : '') : `<span class="muted">${t('unbekannt')}</span>`;
    const extra = [!/^port\s*\d+$/i.test(p.name) && p.name !== String(p.port_no) ? p.name : '', p.speed ? fmtLink(p.speed) : ''].filter(Boolean).join(' · ');
    return hudFlow({ label: `<span class="pbadge">${h(String(p.port_no))}</span>${who}`, sub: h(extra), down: p.out_bps, up: p.in_bps, max });
  };
  return `<div class="panel s4"><div class="hud-h"><h3>${t('Aktivste Ports')}${one ? `<em>${devLink(ports[0].device_id, groups[0])}</em>` : ''}</h3><span class="hint">${t('↓ zum Gerät · ↑ vom Gerät')}</span></div>
    ${one ? ports.map(row).join('') : groups.map(g => `<div class="grp">${h(g)}</div>${ports.filter(p => p.device === g).map(row).join('')}`).join('')}</div>`;
}

function livePanel(rows) {
  if (!rows?.length) return '';
  const srcs = [...new Set(rows.map(x => x.source))];
  const max = Math.max(...rows.map(x => Math.max(x.down, x.up)));
  return `<div class="panel s4"><div class="hud-h"><h3>${t('Gerade aktiv')}${srcs.length === 1 ? `<em>${t('über {s}', { s: h(srcs[0]) })}</em>` : ''}</h3></div>
    ${rows.map(x => hudFlow({ label: devLink(x.device_id, x.name), sub: srcs.length > 1 ? h(x.source) : '', down: x.down, up: x.up, max })).join('')}</div>`;
}

function todayPanel(rows) {
  if (!rows?.length) return '';
  const max = Math.max(...rows.map(x => Math.max(x.rx, x.tx)));
  return `<div class="panel s4"><div class="hud-h"><h3>${t('Top-Verbraucher (24 h)')}<em>ASUS Traffic Analyzer</em></h3></div>
    ${rows.map(x => hudFlow({ label: devLink(x.device_id, x.name), down: x.rx, up: x.tx, max, fmt: splitBytes })).join('')}</div>`;
}

function infraPanel(infra, pid) {
  return `<div class="panel s8"><div class="hud-h"><h3>${t('Infrastruktur')}</h3><span class="hint">${t('Verfügbarkeit 24 Stunden · Antwortzeit')}</span></div>
    ${infra.length ? `<div class="icards">${infra.map(x => `<a href="#" class="icard ${x.online === 1 ? 'on' : x.online === 0 ? 'off' : ''}" data-dev="${x.id}">
        <div class="ic-top"><span>${h(typeName(x.type))}</span>${x.fw_update ? `<span class="badge fwup">⬆ ${t('Update')}</span>` : `<span class="dot ${x.online === 1 ? 'on' : x.online === 0 ? 'off' : ''}"></span>`}</div>
        <div class="ic-name">${h(x.name)}</div>
        <div class="ic-bot">${hudRing(x.a24?.pct ?? null, { size: 58 })}<div class="ic-meta">
          ${x.online === 0 ? `<span class="offl">${t('offline')}</span>` : `<span>RTT <b>${fmtMs(x.rtt)}</b></span>`}
          <span>7 ${t('Tage')} <b>${x.a7 ? nf(x.a7.pct, x.a7.pct >= 99.95 ? 0 : 1) + ' %' : '–'}</b></span></div></div></a>`).join('')}</div>`
    : `<p class="muted">${t('Noch keine Router, Switches oder Access Points bestätigt.')}</p>`}</div>`;
}

function dnsPanel(dns, pid) {
  if (!dns) return '';
  return `<div class="panel s4"><div class="hud-h"><h3>${t('DNS-Filter')}<em>${h(dns.name)}</em></h3><a class="small" href="#/p/${pid}/integrationen">${t('Details')} →</a></div>
    <div class="sp-top" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="hstat"><span>${t('Anfragen')}</span><b>${fmtInt(dns.summary.queries)}</b></div>
      <div class="hstat" style="border-left-color:var(--warn)"><span>${t('blockiert')}</span><b>${fmtInt(dns.summary.blocked)}</b></div>
      <div class="hstat"><span>${t('Anteil')}</span><b>${nf(dns.summary.pct ?? 0, 1)}</b><i>%</i></div></div>
    ${dns.info?.blocking === false ? `<p class="warnc">${t('Filter ausgeschaltet')}</p>` : ''}
    <div data-ch="dns"></div>
    ${dns.top.length ? `<div class="grp" style="margin-top:10px">${t('Meistblockiert je Gerät')}</div>${dns.top.map(x => `<div class="small">${devLink(x.device_id, x.label)}
      <span class="mono muted"> · ${fmtInt(x.blocked)} ${t('von')} ${fmtInt(x.queries)}</span></div>`).join('')}` : ''}</div>`;
}

/* ---------- angeheftete Diagramme ---------- */
const PIN_FMT = {
  bps: fmtBps, ms: fmtMs, W: fmtW, count: v => fmtInt(Math.round(v)),
  pct: v => `${nf(v, 1)} %`,
};
const PIN_SPLIT = { bps: splitBps, ms: v => [v == null ? '–' : nf(v, v < 10 ? 1 : 0), 'ms'], W: v => { const s = fmtW(v).split(' '); return [s[0], s[1] || '']; },
  count: v => [v == null ? '–' : fmtInt(Math.round(v)), ''], pct: v => [v == null ? '–' : nf(v, 1), '%'] };
const PIN_COLORS = ['#00E5FF', '#19F5C8', '#2D7BFF', '#FFB020'];

function pinPanel(it) {
  const p = it.pin;
  return `<div class="panel s${it.size} pinned"><div class="hud-h"><h3>${PIN_ICON} ${h(p.title)}</h3><span class="pin-now" data-now></span></div><div data-pin></div></div>`;
}

async function drawPin(el, pid, p, since) {
  const box = $('[data-pin]', el), now = $('[data-now]', el);
  const r = await api('GET', `/api/profiles/${pid}/metrics?keys=${p.keys.join(',')}&since=${since}&points=${p.style === 'bars' ? 96 : 200}`);
  const series = p.keys.map((k, i) => ({ name: t(p.names[i] || ''), color: PIN_COLORS[i % 4], points: r.series[k] || [] }));
  const fmt = PIN_FMT[p.unit] || fmtBps;
  box.innerHTML = p.style === 'line' ? chartSvg(series, since, { height: 200, fmt }) : hudBars(series, since, { height: 200, fmt, mirror: p.mirror, step: r.step });
  now.innerHTML = series.map(s => { const last = s.points.length ? s.points[s.points.length - 1][1] : null;
    return `<span class="pn" style="--c:${s.color}"><small>${h(s.name)}</small>${bigVal((PIN_SPLIT[p.unit] || splitBps)(last))}</span>`; }).join('');
}

/* Dialog: Diagramm anheften oder bearbeiten */
async function pinDialog(pid, cands, cur) {
  const groups = [...new Set(cands.map(c => c.group))];
  const sel = cur ? -1 : 0;
  const html = `${cur ? '' : `<label>${t('Messreihe')}</label><select name="cand" required>${groups.map(g => `<optgroup label="${h(t(g))}">${cands.map((c, i) => c.group === g ? `<option value="${i}">${h(c.title)}</option>` : '').join('')}</optgroup>`).join('')}</select>`}
    <label>${t('Titel')}</label><input name="title" maxlength="80" value="${h(cur ? cur.pin.title : cands[0]?.title || '')}">
    <div class="grid2"><div><label>${t('Darstellung')}</label><select name="style"><option value="bars">${t('Balken')}</option><option value="line">${t('Linie')}</option></select></div>
      <div><label>${t('Breite')}</label><select name="size">${[[3, 'schmal'], [4, 'ein Drittel'], [6, 'halb'], [8, 'zwei Drittel'], [12, 'ganze Breite']].map(([v, n]) => `<option value="${v}">${t(n)}</option>`).join('')}</select></div></div>
    <p class="muted small">${t('Angeheftete Diagramme folgen dem Zeitraum des WAN-Diagramms. Mit „Anpassen“ lassen sie sich verschieben, umbenennen und entfernen.')}</p>`;
  return dialog(cur ? t('Diagramm bearbeiten') : t('Diagramm anheften'), html, {
    ok: cur ? t('Übernehmen') : t('Anheften'),
    onOpen: f => {
      const c0 = cur ? cur.pin : cands[0];
      f.style.value = c0?.style || 'bars'; f.size.value = String(cur ? cur.size : 6);
      if (f.cand) f.cand.onchange = () => { const c = cands[+f.cand.value]; f.title.value = c.title; f.style.value = c.style; };
    },
    onOk: f => {
      const v = fd(f);
      const base = cur ? cur.pin : cands[+v.cand];
      return { pin: { ...base, title: v.title.trim() || base.title, style: v.style }, size: +v.size };
    },
  });
}

/* ---------- Wachliste ---------- */
const WATCH_FIELD = { ips: 'IP-Adresse', mac: 'MAC', name: 'Name', uplink: 'Anschluss' };

function watchEvent(e) {
  const when = `<span class="muted">${h(ago(e.ts))}</span>`;
  if (e.kind === 'offline') return `<li class="bad"><span class="ic">▼</span><span>${t('ausgefallen')} ${when}</span></li>`;
  if (e.kind === 'online') return `<li class="ok"><span class="ic">▲</span><span>${t('wieder online')} ${when}</span></li>`;
  return `<li class="warn"><span class="ic">⇄</span><span>${t(WATCH_FIELD[e.field] || e.field)}: <span class="mono">${h(e.old)}</span> → <b class="mono">${h(e.new)}</b> ${when}</span></li>`;
}

function watchPanel(w, canEdit, editing) {
  if (!w || !w.items.length) return editing ? `<div class="panel s4"><div class="hud-h"><h3>${t('Wachliste')}</h3></div>
    <p class="muted">${t('Noch leer. Im Gerätedialog mit „Beobachten“ ein System auf die Wachliste setzen – das Feld meldet dann Ausfälle und Wechsel von IP, MAC, Name oder Anschluss.')}</p></div>` : '';
  const label = { down: t('offline'), changed: t('geändert'), ok: t('OK') };
  const rows = w.items.map(x => `<div class="wl-item ${x.state}">
      <div class="wl-head"><span class="wl-dot"></span><span class="wl-name">${devLink(x.id, x.name)}${x.note ? ` <span class="muted small">· ${h(x.note)}</span>` : ''}</span>
        <span class="mono small wl-ip">${h(x.ip || '')}</span><span class="wl-st">${label[x.state]}</span>
        ${canEdit && x.state === 'changed' ? `<button type="button" class="sm" data-wack="${x.id}">${t('Quittieren')}</button>` : ''}</div>
      ${x.state === 'down' && x.last_seen ? `<div class="muted small wl-sub">${t('zuletzt gesehen')} ${h(ago(x.last_seen))}</div>` : ''}
      ${x.events.length ? `<ul class="ov-issues wl-ev">${x.events.slice(0, 4).map(watchEvent).join('')}</ul>` : ''}</div>`).join('');
  return `<div class="panel s4 watch ${w.alarms ? 'alarm' : ''}"><div class="hud-h"><h3>${t('Wachliste')}</h3><span class="row">
      ${w.alarms ? `<span class="hint bad">${w.alarms === 1 ? t('1 Alarm') : t('{n} Alarme', { n: w.alarms })}</span>` : `<span class="hint ok">✓ ${t('alles ruhig')}</span>`}
      ${canEdit && w.items.some(x => x.events.length) ? `<button type="button" class="sm" data-wack="0">${t('Alle quittieren')}</button>` : ''}</span></div>
    <div class="wl">${rows}</div></div>`;
}

/* im Gerätedialog: auf die Wachliste setzen, Zustand und Ereignisse seit dem Quittieren */
async function watchBox(ctx, did, el) {
  const P = `/api/profiles/${ctx.pid}`;
  let w;
  try { w = await api('GET', `${P}/watch`); } catch { el.innerHTML = ''; return; }
  const x = w.items.find(i => i.id === did);
  if (!x && !ctx.canEdit) { el.innerHTML = ''; return; }
  const label = { down: t('offline'), changed: t('geändert seit dem letzten Quittieren'), ok: t('keine Auffälligkeiten') };
  el.innerHTML = `<h4>${t('Wachliste')}</h4>
    <div class="row between wl-box ${x ? x.state : ''}"><span>${x ? `<span class="wl-dot"></span> <b>${t('Wird beobachtet')}</b> · ${label[x.state]}${x.note ? ` · <span class="muted">${h(x.note)}</span>` : ''}`
      : `<span class="muted small">${t('Beobachtete Systeme erscheinen in der Übersicht und melden Ausfälle sowie Wechsel von IP, MAC, Name oder Anschluss – bis jemand quittiert.')}</span>`}</span>
      ${ctx.canEdit ? `<span class="row">${x && x.events.length ? `<button type="button" class="sm" data-wack>${t('Quittieren')}</button>` : ''}
        ${x ? '' : `<input data-wnote maxlength="200" placeholder="${h(t('Notiz (optional, z. B. „Quorum-Knoten“)'))}">`}
        <button type="button" class="sm ${x ? '' : 'pri'}" data-wtoggle>${x ? t('Nicht mehr beobachten') : '👁 ' + t('Beobachten')}</button></span>` : ''}</div>
    ${x && x.events.length ? `<ul class="ov-issues wl-ev">${x.events.map(watchEvent).join('')}</ul>` : ''}`;
  const tg = $('[data-wtoggle]', el);
  if (tg) tg.onclick = async () => {
    const note = $('[data-wnote]', el)?.value || '';
    try { await api('PUT', `${P}/devices/${did}/watch`, { watch: !x, note }); toast(x ? t('Von der Wachliste genommen') : t('Auf der Wachliste')); watchBox(ctx, did, el); }
    catch (e) { toast(e.message, true); }
  };
  const ak = $('[data-wack]', el);
  if (ak) ak.onclick = async () => { try { await api('POST', `${P}/watch/ack`, { device_id: did }); watchBox(ctx, did, el); } catch (e) { toast(e.message, true); } };
}

/* ---------- Übersicht ---------- */
const BUILTIN_NAME = { wan: 'WAN-Traffic', speed: 'Internet-Geschwindigkeit', issues: 'Braucht Aufmerksamkeit', watch: 'Wachliste', ports: 'Aktivste Ports', live: 'Gerade aktiv',
  today: 'Top-Verbraucher (24 h)', rtt: 'Antwortzeiten Infrastruktur', infra: 'Infrastruktur', dns: 'DNS-Filter', recent: 'Letzte Änderungen' };
const SIZE_NAME = [[3, 'S'], [4, 'M'], [5, 'M+'], [6, 'L'], [8, 'XL'], [12, '▭']];

async function tabOverview(ctx) {
  await meta(ctx.pid);
  const P = `/api/profiles/${ctx.pid}`;
  const since = () => tabOverview.since || 86400;
  const st = tabOverview.st = { edit: false, items: null, r: null, cands: null };
  ctx.el.innerHTML = `<div id="ov"><p class="muted">${t('lade …')}</p></div>`;

  const builtins = r => ({
    wan: () => wanPanel(r.wan, since()), speed: () => speedHud(r.speed, ctx.canEdit, ctx.pid), issues: () => issuesPanel(r, ctx.pid),
    watch: () => watchPanel(r.watch, ctx.canEdit, st.edit),
    ports: () => portsPanel(r.ports), live: () => livePanel(r.top_now), today: () => todayPanel(r.top_today), rtt: () => rttPanel(r.rtt),
    infra: () => infraPanel(r.infra, ctx.pid), dns: () => dnsPanel(r.dns, ctx.pid),
    recent: () => `<div class="panel s4"><div class="hud-h"><h3>${t('Letzte Änderungen')}</h3><a class="small" href="#/p/${ctx.pid}/verlauf">${t('Verlauf')} →</a></div>
      ${r.recent.length ? histList(r.recent) : `<p class="muted">${t('Keine Änderungen in den letzten 7 Tagen.')}</p>`}</div>`,
  });

  const ctl = (it, i, n) => !st.edit ? '' : `<div class="w-ctl" data-ctl="${h(it.id)}">
      <span class="w-grip" title="${h(t('Ziehen zum Verschieben'))}">⠿</span>
      <button type="button" class="sm" data-mv="-1" ${i ? '' : 'disabled'} title="${h(t('nach vorne'))}">◀</button>
      <button type="button" class="sm" data-mv="1" ${i < n - 1 ? '' : 'disabled'} title="${h(t('nach hinten'))}">▶</button>
      <select data-sz title="${h(t('Breite'))}">${SIZE_NAME.map(([v, l]) => `<option value="${v}" ${v === it.size ? 'selected' : ''}>${l}</option>`).join('')}</select>
      ${it.pin ? `<button type="button" class="sm" data-ped title="${h(t('Bearbeiten'))}">✎</button><button type="button" class="sm danger" data-prm title="${h(t('Entfernen'))}">✕</button>`
        : `<button type="button" class="sm" data-hide>${it.hidden ? t('Einblenden') : t('Ausblenden')}</button>`}</div>`;

  const paint = async () => {
    const r = st.r, items = st.edit ? st.items : r.layout.items, mk = builtins(r);
    const box = document.createElement('div');
    const visible = items.filter(it => st.edit || !it.hidden);
    const grid = document.createElement('div');
    grid.className = 'ovg';
    visible.forEach((it, i) => {
      let html = it.pin ? pinPanel(it) : mk[it.id] ? mk[it.id]() : '';
      if (!html && st.edit) html = `<div class="panel s4"><div class="hud-h"><h3>${t(BUILTIN_NAME[it.id] || it.id)}</h3></div><p class="muted">${t('Zurzeit keine Daten – das Feld erscheint, sobald es etwas zu zeigen gibt.')}</p></div>`;
      if (!html) return;
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      const el = tmp.firstElementChild;
      el.className = el.className.replace(/\bs\d+\b/, '') + ` s${it.size}` + (st.edit ? ' editing' : '') + (it.hidden ? ' w-hidden' : '');
      el.dataset.w = it.id;
      if (st.edit) { el.draggable = true; el.insertAdjacentHTML('afterbegin', ctl(it, i, visible.length)); }
      grid.appendChild(el);
    });
    const bar = ctx.canEdit ? (st.edit
      ? `<div class="ov-bar editing"><b>${t('Übersicht anpassen')}</b><span class="muted small">${t('Felder ziehen oder mit ◀ ▶ verschieben, Breite wählen, ausblenden.')}</span><span class="grow"></span>
          <button type="button" class="sm" data-addpin>${PIN_ICON} ${t('Diagramm anheften')}</button><button type="button" class="sm danger" data-reset>${t('Zurücksetzen')}</button>
          <button type="button" class="sm" data-cancel>${t('Abbrechen')}</button><button type="button" class="sm pri" data-done>${t('Fertig')}</button></div>`
      : `<div class="ov-bar"><span class="grow"></span><button type="button" class="sm" data-addpin>${PIN_ICON} ${t('Diagramm anheften')}</button><button type="button" class="sm" data-ovedit>${t('Anpassen')}</button></div>`) : '';
    box.innerHTML = `${bar}${kpiTiles(r, ctx.pid)}<p class="muted small" id="ovstamp"></p>`;
    box.insertBefore(grid, $('#ovstamp', box));
    $$('[data-dev]', box).forEach(a => a.onclick = ev => { ev.preventDefault(); if (!st.edit) deviceDialog(ctx, +a.dataset.dev); });
    $$('[data-hdev]', box).forEach(a => a.onclick = ev => { ev.preventDefault(); if (!st.edit) deviceDialog(ctx, +a.dataset.hdev); });
    // Diagramme: Elemente vor dem Umhängen merken
    const elWan = $('[data-ch=wan]', box), elDns = $('[data-ch=dns]', box);
    const pins = items.filter(it => it.pin && (st.edit || !it.hidden)).map(it => [$(`[data-w="${it.id}"]`, box), it.pin]).filter(x => x[0]);
    const charts = () => {
      const s = since();
      return Promise.allSettled([
        elWan && drawBars(elWan, ctx.pid, r.wan.keys, [t('Download'), t('Upload')], s, { height: 300, mirror: true }),
        elDns && drawBars(elDns, ctx.pid, r.dns.keys, [t('Anfragen/min'), t('blockiert/min')], s, { fmt: v => fmtInt(Math.round(v)), height: 120, colors: ['#00E5FF', '#FFB020'] }),
        ...pins.map(([el, p]) => drawPin(el, ctx.pid, p, s)),
      ]);
    };
    $$('[data-wack]', box).forEach(b => b.onclick = async () => {
      try { await api('POST', `${P}/watch/ack`, +b.dataset.wack ? { device_id: +b.dataset.wack } : {}); toast(t('quittiert')); render(); } catch (e) { toast(e.message, true); }
    });
    bindSpeedRun(ctx, box, () => render());
    $$('[data-range]', box).forEach(b => b.onclick = () => { tabOverview.since = +b.dataset.range; $$('[data-range]', ctx.el).forEach(x => x.classList.toggle('on', x === b)); charts(); });
    bindEdit(box);
    await charts();
    const ov = $('#ov', ctx.el);
    if (!ov) return;
    ov.replaceChildren(...box.childNodes);
    $('#ovstamp', ctx.el).textContent = st.edit ? '' : t('Stand {d} · aktualisiert sich alle 30 Sekunden', { d: new Date().toLocaleTimeString(LANG === 'en' ? 'en-GB' : 'de-DE') });
  };

  const save = async (body) => {
    try { const l = await api('PUT', `${P}/dashboard/layout`, body); st.r.layout = l; return l; } catch (e) { toast(e.message, true); return null; }
  };
  const addPin = async () => {
    if (!st.cands) st.cands = (await api('GET', `${P}/dashboard/layout?lang=${LANG}`)).candidates;
    if (!st.cands.length) return toast(t('Noch keine Messreihen – sie entstehen mit den Integrationen und der Online-Überwachung.'), true);
    const v = await pinDialog(ctx.pid, st.cands);
    if (!v) return;
    if (st.edit) { st.items.push({ id: 'p_' + Math.random().toString(16).slice(2, 10).padEnd(8, '0'), size: v.size, pin: v.pin }); return paint(); }
    try { st.r.layout = await api('POST', `${P}/dashboard/pins`, v); toast(t('An die Übersicht angeheftet')); paint(); } catch (e) { toast(e.message, true); }
  };

  function bindEdit(box) {
    const b = sel => $(sel, box);
    if (b('[data-addpin]')) b('[data-addpin]').onclick = addPin;
    if (b('[data-ovedit]')) b('[data-ovedit]').onclick = () => { st.edit = true; st.items = structuredClone(st.r.layout.items); paint(); };
    if (b('[data-cancel]')) b('[data-cancel]').onclick = () => { st.edit = false; paint(); };
    if (b('[data-done]')) b('[data-done]').onclick = async () => { if (await save({ items: st.items })) { st.edit = false; toast(t('gespeichert')); paint(); } };
    if (b('[data-reset]')) b('[data-reset]').onclick = async () => {
      if (!await confirmDlg(t('Übersicht zurücksetzen'), t('Reihenfolge, Breiten und ausgeblendete Felder auf den Standard zurücksetzen und alle angehefteten Diagramme entfernen?'), t('Zurücksetzen'))) return;
      if (await save({ reset: true })) { st.edit = false; paint(); }
    };
    if (!st.edit) return;
    const idx = id => st.items.findIndex(x => x.id === id);
    const move = (from, to) => { const [x] = st.items.splice(from, 1); st.items.splice(to, 0, x); paint(); };
    // ◀ ▶ verschieben unter den sichtbaren Feldern: Nachbar im angezeigten Raster suchen
    $$('[data-ctl]', box).forEach(c => {
      const id = c.dataset.ctl, it = st.items[idx(id)];
      $$('[data-mv]', c).forEach(btn => btn.onclick = () => {
        const shown = $$('.ovg>[data-w]', ctx.el).map(e => e.dataset.w);
        const nb = shown[shown.indexOf(id) + +btn.dataset.mv];
        if (nb) move(idx(id), idx(nb));
      });
      $('[data-sz]', c).onchange = e => { it.size = +e.target.value; paint(); };
      const hide = $('[data-hide]', c);
      if (hide) hide.onclick = () => { it.hidden = !it.hidden; paint(); };
      const ped = $('[data-ped]', c);
      if (ped) ped.onclick = async () => { const v = await pinDialog(ctx.pid, [], it); if (v) { it.pin = v.pin; it.size = v.size; paint(); } };
      const prm = $('[data-prm]', c);
      if (prm) prm.onclick = () => { st.items.splice(idx(id), 1); paint(); };
    });
    // Ziehen und Ablegen
    let drag = null;
    $$('.panel.editing', box).forEach(el => {
      el.addEventListener('dragstart', e => { drag = el.dataset.w; el.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', drag); });
      el.addEventListener('dragend', () => { el.classList.remove('dragging'); $$('.drop-at').forEach(x => x.classList.remove('drop-at')); });
      el.addEventListener('dragover', e => { if (drag && drag !== el.dataset.w) { e.preventDefault(); el.classList.add('drop-at'); } });
      el.addEventListener('dragleave', () => el.classList.remove('drop-at'));
      el.addEventListener('drop', e => { e.preventDefault(); if (drag && drag !== el.dataset.w) move(idx(drag), idx(el.dataset.w)); drag = null; });
    });
  }

  const render = async () => {
    try { st.r = await api('GET', `${P}/dashboard`); } catch (e) { $('#ov', ctx.el).innerHTML = `<p class="errtxt">${h(e.message)}</p>`; return; }
    await paint();
  };
  await render();
  clearInterval(tabOverview.timer);
  tabOverview.timer = setInterval(() => {
    if (!document.body.contains(ctx.el) || !location.hash.match(/\/p\/\d+(\/uebersicht)?$/)) return clearInterval(tabOverview.timer);
    if (!$('#dlg').open && !st.edit) render();
  }, 30000);
}
window.INV.uebersicht = tabOverview;

/* Neon-Pin (eigenes Symbol statt Emoji) */
const PIN_ICON = '<svg class="pin-ic" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 22.5 5.6 12.9A7.6 7.6 0 1 1 18.4 12.9Z"/><circle cx="12" cy="8.6" r="3"/></svg>';

/* „An die Übersicht anheften“ aus Gerätedialog und Integrationskarten */
function pinBtn(pin) {
  return `<button type="button" class="sm pinbtn" data-pin='${h(JSON.stringify(pin))}' title="${h(t('An die Übersicht anheften'))}">${PIN_ICON}</button>`;
}
async function pinNow(pid, pin) {
  try { await api('POST', `/api/profiles/${pid}/dashboard/pins`, { pin, size: 6 }); toast(t('An die Übersicht angeheftet')); return true; }
  catch (e) { toast(e.message, true); return false; }
}
document.addEventListener('click', async ev => {
  const b = ev.target.closest('.pinbtn');
  if (!b) return;
  const pid = (location.hash.match(/#\/p\/(\d+)/) || [])[1];
  if (pid && await pinNow(pid, JSON.parse(b.dataset.pin))) b.disabled = true;
});
