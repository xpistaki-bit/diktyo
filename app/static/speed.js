'use strict';
/* Geschwindigkeitsmessungen: Internet-Speedtest (Übersicht, Integrationen) und iperf3 zu einem Gerät (Gerätedialog).
   Die Messungen laufen im Hintergrunddienst; hier wird der Auftrag gestartet und sein Fortschritt angezeigt. */

const fmtMbit = v => v == null ? '–' : `${(v / 1e6).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: v < 1e7 ? 1 : 0 })} Mbit/s`;
const SCHED_NAME = { 0: 'aus (nur von Hand)', 24: 'täglich', 12: 'alle 12 Stunden', 6: 'alle 6 Stunden', 3: 'alle 3 Stunden' };

async function pollJob(jid, onTick, isAlive = () => true) {
  for (;;) {
    let j;
    try { j = await api('GET', `/api/jobs/${jid}`); } catch (e) { return { status: 'error', message: e.message }; }
    if (j.status === 'done' || j.status === 'error' || !isAlive()) return j;
    onTick(j);
    await new Promise(r => setTimeout(r, 1500));
  }
}

function jobLine(j) {
  return `<div class="scanprog"><div class="meter"><i style="width:${j.progress || 0}%"></i></div><span class="mono small">${j.progress || 0} %</span></div>
    <p class="muted small" style="margin:2px 0 0">${h(j.status === 'queued' ? t('wartet auf den Hintergrunddienst …') : t(j.message || 'misst …'))}</p>`;
}

function speedChart(points, height = 120) {
  const pts = points.map(p => [Date.parse(p[0]) / 1000, p[1], p[2]]).filter(p => !isNaN(p[0]));
  if (pts.length < 2) return '';
  const since = Math.max(86400, Date.now() / 1000 - pts[0][0] + 3600);
  return chartSvg([{ name: t('Download'), color: '#00E5FF', points: pts.map(p => [p[0], p[1]]) },
    { name: t('Upload'), color: '#19F5C8', points: pts.map(p => [p[0], p[2]]) }], since, { height });
}

/* Übersicht: letzte Messung, Verlauf, „Jetzt messen“ */
function speedPanel(sp, canEdit, pid) {
  const l = sp?.last;
  const line = sp?.line_down ? `<small class="muted">${t('Leitung laut Router')}: ↓ ${fmtMbit(sp.line_down)}${sp.line_up ? ' · ↑ ' + fmtMbit(sp.line_up) : ''}</small>` : '';
  return `<div class="panel" id="speedpanel"><div class="row between"><h3 style="margin:0">${t('Internet-Geschwindigkeit')}</h3>
      ${canEdit ? `<button class="sm" data-speedrun>${t('Jetzt messen')}</button>` : ''}</div>
    <div data-speedjob></div>
    ${l ? `<div class="speed-now"><span>↓ <b class="mono">${fmtMbit(l.down_bps)}</b></span><span>↑ <b class="mono">${fmtMbit(l.up_bps)}</b></span>
        <span>${t('Ping')} <b class="mono">${fmtMs(l.ping_ms)}</b></span>${l.jitter_ms != null ? `<span>${t('Jitter')} <b class="mono">${fmtMs(l.jitter_ms)}</b></span>` : ''}</div>
      <p class="muted small" style="margin:2px 0 6px">${h(fmtDate(l.ts))} · ${h(l.server)}${l.scheduled ? ' · ' + t('geplant') : ''}</p>
      ${line}<div class="chartbox">${speedChart(sp.points)}</div>`
    : `<p class="muted small">${t('Noch keine Messung. „Jetzt messen“ prüft Ping, Download und Upload des díktyo-Rechners gegen speed.cloudflare.com (einige hundert MB Datenverkehr). Automatische Messungen: Integrationen → Speedtest.')}</p>`}
    <p class="small" style="margin:6px 0 0"><a href="#/p/${pid}/integrationen">${t('Einstellungen und Verlauf')} →</a></p></div>`;
}

function bindSpeedRun(ctx, root, done) {
  const b = $('[data-speedrun]', root);
  if (!b) return;
  const box = $('[data-speedjob]', root);
  const watch = async jid => {
    b.disabled = true;
    const j = await pollJob(jid, x => { box.innerHTML = jobLine(x); }, () => document.body.contains(box));
    if (!document.body.contains(box)) return;
    box.innerHTML = '';
    b.disabled = false;
    if (j.status === 'error') toast(t('Messung fehlgeschlagen: {e}', { e: j.message }), true);
    else { toast(t('Messung fertig: ↓ {d} · ↑ {u}', { d: fmtMbit(j.result.down_bps), u: fmtMbit(j.result.up_bps) })); done && done(); }
  };
  b.onclick = async () => {
    try {
      const r = await api('POST', `/api/profiles/${ctx.pid}/speedtest/run`, {});
      if (!r.worker) toast(t('Der Hintergrunddienst läuft nicht – die Messung startet, sobald er wieder da ist.'), true);
      watch(r.job.id);
    } catch (e) { toast(e.message, true); }
  };
  return watch;
}

/* Integrationen: Zeitplan, Einstellungen, Verlauf */
async function speedSettings(ctx, el) {
  const P = `/api/profiles/${ctx.pid}`;
  let r;
  try { r = await api('GET', `${P}/speedtest`); } catch (e) { el.innerHTML = `<p class="errtxt">${h(e.message)}</p>`; return; }
  const s = r.settings, dis = ctx.canEdit ? '' : 'disabled';
  const rows = r.history.slice(0, 15);
  el.innerHTML = `<div class="panel"><div class="row between"><h3 style="margin:0">${t('Speedtest')}</h3>${ctx.canEdit ? `<button class="sm" data-speedrun>${t('Jetzt messen')}</button>` : ''}</div>
    <p class="muted small" style="margin-top:4px">${t('Misst Ping, Download und Upload vom díktyo-Rechner ins Internet (gegen speed.cloudflare.com). Das Ergebnis gilt für díktyos Weg – steht díktyo hinter einem weiteren Router, misst es dessen Anbindung mit. Je Messung fließen einige hundert MB.')}</p>
    <div data-speedjob></div>
    <form class="grid3" id="speedform">
      <div><label>${t('Automatisch messen')}</label><select name="schedule_hours" ${dis}>${r.schedules.map(v => `<option value="${v}" ${v === s.schedule_hours ? 'selected' : ''}>${t(SCHED_NAME[v])}</option>`).join('')}</select></div>
      <div><label>${t('Parallele Verbindungen')}</label><select name="streams" ${dis}>${[1, 2, 4, 6, 8].map(v => `<option ${v === s.streams ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
      <div><label>${t('Dauer je Richtung')}</label><select name="seconds" ${dis}>${[5, 8, 12, 20].map(v => `<option value="${v}" ${v === s.seconds ? 'selected' : ''}>${v} s</option>`).join('')}</select></div>
    </form>
    ${r.history.length > 1 ? `<div class="chartbox">${speedChart(r.history.slice().reverse().map(x => [x.ts, x.down_bps, x.up_bps]), 130)}</div>` : ''}
    ${rows.length ? `<div class="table-wrap"><table class="compact"><thead><tr><th>${t('Zeit')}</th><th>↓</th><th>↑</th><th>${t('Ping')}</th><th>${t('Jitter')}</th><th>${t('Server')}</th></tr></thead><tbody>
      ${rows.map(x => `<tr><td class="mono small">${h(fmtDate(x.ts))}${x.scheduled ? ` <span class="badge">${t('geplant')}</span>` : ''}</td><td class="mono small">${fmtMbit(x.down_bps)}</td><td class="mono small">${fmtMbit(x.up_bps)}</td>
        <td class="mono small">${fmtMs(x.ping_ms)}</td><td class="mono small">${fmtMs(x.jitter_ms)}</td><td class="small">${h(x.server)}</td></tr>`).join('')}</tbody></table></div>
      ${r.history.length > rows.length ? `<p class="muted small">${t('{n} Messungen gespeichert, die letzten 15 sind aufgeführt.', { n: r.history.length })}</p>` : ''}` : ''}</div>`;
  $$('#speedform select', el).forEach(sel => sel.onchange = async () => {
    try { await api('PUT', `${P}/speedtest`, fd($('#speedform', el))); toast(t('gespeichert')); } catch (e) { toast(e.message, true); }
  });
  const watch = bindSpeedRun(ctx, el, () => speedSettings(ctx, el));
  if (r.job && watch) watch(r.job.id);
}

/* Gerätedialog: iperf3 zwischen díktyo und dem Gerät */
async function iperfBox(ctx, d, el) {
  const P = `/api/profiles/${ctx.pid}/devices/${d.id}/iperf`;
  let r;
  try { r = await api('GET', P); } catch { el.innerHTML = ''; return; }
  const last = r.history[0];
  el.innerHTML = `<h4>${t('Durchsatz messen (iperf3)')}</h4>
    ${last ? `<div class="speed-now"><span>díktyo → ${h(d.name)} <b class="mono">${fmtMbit(last.up_bps)}</b></span><span>${h(d.name)} → díktyo <b class="mono">${fmtMbit(last.down_bps)}</b></span>
      ${last.ping_ms ? `<span>RTT <b class="mono">${fmtMs(last.ping_ms)}</b></span>` : ''}</div>
      <p class="muted small" style="margin:2px 0 6px">${h(fmtDate(last.ts))} · ${h(last.server)}${last.detail?.retransmits_up ? ' · ' + t('{n} Wiederholungen', { n: last.detail.retransmits_up }) : ''}</p>` : ''}
    ${r.history.length > 1 ? `<details><summary class="small">${t('Verlauf')} (${r.history.length})</summary><div class="table-wrap"><table class="compact"><tbody>
      ${r.history.map(x => `<tr><td class="mono small">${h(fmtDate(x.ts))}</td><td class="mono small">→ ${fmtMbit(x.up_bps)}</td><td class="mono small">← ${fmtMbit(x.down_bps)}</td><td class="mono small">${h(x.server)}</td></tr>`).join('')}</tbody></table></div></details>` : ''}
    ${!r.available ? `<p class="warnc small">${t('iperf3 ist auf dem díktyo-Rechner nicht installiert (apt install iperf3; ab díktyo 0.19 installiert der Installer es mit).')}</p>` : ''}
    ${ctx.canEdit ? `<div class="row" style="margin-top:6px"><label class="small" style="margin:0">${t('Port')}</label><input data-iport type="number" value="5201" min="1" max="65535" style="max-width:100px">
      <button type="button" class="sm" data-irun ${r.available ? '' : 'disabled'}>${t('Messen')}</button></div>
      <div data-ijob></div>
      <p class="muted small">${t('Auf dem Gerät muss ein iperf3-Server laufen, z. B. „iperf3 -s“ (Linux, NAS, Proxmox; Port 5201). díktyo misst dann in beide Richtungen.')}</p>` : ''}`;
  const box = $('[data-ijob]', el), b = $('[data-irun]', el);
  const watch = async jid => {
    if (b) b.disabled = true;
    const j = await pollJob(jid, x => { box.innerHTML = jobLine(x); }, () => document.body.contains(el));
    if (!document.body.contains(el)) return;
    if (j.status === 'error') toast(t('Messung fehlgeschlagen: {e}', { e: j.message }), true);
    iperfBox(ctx, d, el);
  };
  if (b) b.onclick = async () => {
    try { const x = await api('POST', P, { port: +$('[data-iport]', el).value || 5201 }); watch(x.job.id); } catch (e) { toast(e.message, true); }
  };
  if (r.job) watch(r.job.id);
}
