'use strict';
/* Netzscan und Posteingang. Nutzt die Hilfen aus app.js und inventory.js. */
const MODE = {
  passive: ['Passiv', 'Nur mithören: ARP-Tabelle, mDNS, UPnP, DNS-Namen. Keine Pings, keine Port-Abfragen.'],
  light: ['Leicht', 'Zusätzlich Ping und ca. 20 typische Ports je Adresse, Titel der Weboberflächen.'],
  full: ['Voll', 'Zusätzlich ca. 60 Ports, NetBIOS-Namen und Diensterkennung mit nmap. Dauert einige Minuten.'],
};
const SCHEDULE = [[0, 'nur von Hand'], [1, 'stündlich'], [6, 'alle 6 Stunden'], [12, 'alle 12 Stunden'], [24, 'täglich'], [168, 'wöchentlich']];
const REASON = {
  vendor: 'Hersteller (MAC): {v}', hostname: 'Name: {v}', mdns: 'mDNS: {v}', ssdp: 'UPnP: {v}', http: 'Weboberfläche: {v}', port: 'Port {v} offen',
  random: 'zufällige MAC-Adresse', model: 'Modell erkannt: {v}', fingerbank: 'Fingerbank: {v}', own: 'dieser Rechner',
};
const identLabel = i => i ? (LANG === 'en' ? i.label_en || i.label : i.label) : '';
function reasonsHtml(i) {
  if (!i || !i.reasons) return '';
  return i.reasons.map(r => `<span class="reason">${h(t(REASON[r.k] || r.k, { v: r.v }))}${r.score ? ` (${r.score})` : ''}</span>`).join('');
}
function confBar(c) {
  const cls = c >= 75 ? 'hi' : c >= 45 ? 'mid' : 'lo';
  return `<span class="conf ${cls}" title="${t('Sicherheit der Vermutung')}"><i style="width:${c}%"></i></span><span class="mono small">${c} %</span>`;
}
const ago = s => {
  if (!s) return '';
  const m = Math.round((Date.now() - new Date(s)) / 60000);
  return m < 1 ? t('gerade eben') : m < 60 ? t('vor {n} min', { n: m }) : m < 1440 ? t('vor {n} h', { n: Math.round(m / 60) }) : fmtDate(s);
};
const onlineDot = d => d.online == null ? `<span class="dot" title="${t('noch nicht geprüft')}"></span>`
  : `<span class="dot ${d.online ? 'on' : 'off'}" title="${d.online ? t('online') : t('offline')}${d.last_seen ? ' · ' + t('zuletzt gesehen') + ' ' + h(fmtDate(d.last_seen)) : ''}"></span>`;

/* ---------------------------------------------------------------- Posteingang */
async function tabInbox(ctx) {
  await meta(ctx.pid);
  const P = `/api/profiles/${ctx.pid}`;
  const { devices } = await api('GET', `${P}/devices`);
  const inbox = devices.filter(d => d.status === 'discovered').sort((a, b) => (b.ident?.confidence || 0) - (a.ident?.confidence || 0) || ipNum(a.ips[0]?.address) - ipNum(b.ips[0]?.address));
  const ignored = devices.filter(d => d.status === 'ignored');
  ctx.el.innerHTML = `
    <p class="muted" style="margin-top:0">${t('Hier landen Geräte, die der Netzscan neu gefunden hat. Übernimm sie in die Geräteliste, bearbeite sie vorher oder ignoriere sie; ignorierte Geräte werden bei späteren Scans wiedererkannt und nicht erneut gemeldet.')}</p>
    ${inbox.length ? `<div class="toolbar">${ctx.canEdit ? `<label class="chk" style="margin:0"><input type="checkbox" id="all"> ${t('alle')}</label>
      <button class="pri sm" data-bulk="confirm">${t('Auswahl übernehmen')}</button><button class="sm" data-bulk="ignore">${t('Auswahl ignorieren')}</button>` : ''}
      <span class="grow"></span><span class="muted">${t('{n} neue Geräte', { n: inbox.length })}</span></div>` : ''}
    <div class="inbox">${inbox.length ? inbox.map(d => `<div class="inrow panel" data-id="${d.id}">
        ${ctx.canEdit ? `<input type="checkbox" data-sel>` : ''}
        <div class="guess"><b>${h(identLabel(d.ident) || t('Unbekanntes Gerät'))}</b> ${d.ident ? confBar(d.ident.confidence || 0) : ''}
          <div class="reasons">${reasonsHtml(d.ident)}</div>
          ${d.ident?.also?.length ? `<small class="muted">${t('Oder')}: ${d.ident.also.map(a => h(LANG === 'en' ? a.label_en : a.label)).join(', ')}</small>` : ''}</div>
        <div class="facts"><span class="mono">${d.ips.map(i => h(i.address)).join(', ')}</span><span class="mono muted">${h(d.mac) || '–'}</span>
          <span>${h(d.name)}</span><span class="muted small">${t('zuletzt gesehen')} ${h(ago(d.last_seen))}</span></div>
        ${ctx.canEdit ? `<div class="acts"><button class="pri sm" data-act="confirm">${t('Übernehmen')}</button><button class="sm" data-act="edit">${t('Bearbeiten')}</button><button class="sm" data-act="ignore">${t('Ignorieren')}</button></div>` : ''}
      </div>`).join('') : `<div class="panel empty-box">${t('Keine neuen Geräte.')} <a href="#/p/${ctx.pid}/netzscan">${t('Netzscan starten')}</a></div>`}</div>
    ${ignored.length ? `<details class="ignored"><summary>${t('Ignorierte Geräte')} (${ignored.length})</summary>
      <div class="table-wrap"><table class="compact"><tbody>${ignored.map(d => `<tr data-id="${d.id}"><td>${h(d.name)}</td><td class="mono">${d.ips.map(i => h(i.address)).join(', ')}</td><td class="mono">${h(d.mac)}</td><td>${h(identLabel(d.ident))}</td>
        <td class="act">${ctx.canEdit ? `<button class="sm" data-act="restore">${t('Zurück in den Posteingang')}</button><button class="sm danger" data-act="delete">${t('Löschen')}</button>` : ''}</td></tr>`).join('')}</tbody></table></div></details>` : ''}`;
  const act = async (action, ids) => {
    try { await api('POST', `${P}/inbox`, { action, ids }); toast(t('gespeichert')); ctx.reload(); } catch (e) { toast(e.message, true); }
  };
  $$('[data-act]', ctx.el).forEach(b => b.onclick = () => {
    const id = +b.closest('[data-id]').dataset.id;
    if (b.dataset.act === 'edit') return deviceDialog(ctx, id);
    act(b.dataset.act, [id]);
  });
  const all = $('#all', ctx.el);
  if (all) all.onchange = () => $$('[data-sel]', ctx.el).forEach(x => x.checked = all.checked);
  $$('[data-bulk]', ctx.el).forEach(b => b.onclick = () => {
    const ids = $$('[data-sel]', ctx.el).filter(x => x.checked).map(x => +x.closest('[data-id]').dataset.id);
    if (!ids.length) return toast(t('Bitte Geräte auswählen'), true);
    act(b.dataset.bulk, ids);
  });
}

/* ---------------------------------------------------------------- Netzscan */
async function tabScan(ctx) {
  const P = `/api/profiles/${ctx.pid}`;
  const r = await api('GET', `${P}/scan`);
  const s = r.settings, w = r.worker;
  const running = r.jobs.find(j => j.status === 'queued' || j.status === 'running');
  const chosen = new Set(s.targets.length ? s.targets : r.default_targets);
  const nets = [...r.subnets.map(x => ({ cidr: x.cidr, label: x.name || t('Subnetz') })), ...r.local.map(x => ({ cidr: x.cidr, label: t('Schnittstelle {n}', { n: x.ifname }) }))];
  for (const c of chosen) if (!nets.some(n => n.cidr === c)) nets.push({ cidr: c, label: t('eigene Angabe') });
  const dis = ctx.canEdit ? '' : 'disabled';
  ctx.el.innerHTML = `
    ${!w.running ? `<div class="panel warnbox">${t('Der Hintergrunddienst läuft nicht. Scans werden erst ausgeführt, wenn er läuft (LXC: systemctl status diktyo-worker).')}</div>` : ''}
    <div class="grid-out">
      <form class="panel" id="scanform"><h3>${t('Einstellungen')}</h3>
        <label>${t('Modus')}</label>
        ${Object.entries(MODE).map(([k, [n, d]]) => `<label class="chk mode"><input type="radio" name="mode" value="${k}" ${s.mode === k ? 'checked' : ''} ${dis}> <span><b>${t(n)}</b><br><small class="muted">${t(d)}</small></span></label>`).join('')}
        <label>${t('Netze')}</label>
        <div id="nets">${nets.map(n => `<label class="chk"><input type="checkbox" data-net="${h(n.cidr)}" ${chosen.has(n.cidr) ? 'checked' : ''} ${dis}> <span class="mono">${h(n.cidr)}</span> <span class="muted small">${h(n.label)}</span></label>`).join('') || `<p class="muted">${t('Kein Netz bekannt.')}</p>`}</div>
        <div class="row" style="margin-top:6px"><input id="addnet" class="mono" placeholder="192.168.10.0/24" style="max-width:200px" ${dis}><button type="button" class="sm" id="addnetb" ${dis}>${t('+ Netz')}</button></div>
        <small class="muted">${t('Ohne Auswahl werden die Subnetze aus dem IPAM gescannt, sonst die Netze der eigenen Schnittstellen. Neue Netze werden im IPAM angelegt.')}</small>
        <label>${t('Ausnahmen (nie aktiv abfragen)')}</label><textarea name="exclude" rows="2" class="mono" placeholder="192.168.178.50, 192.168.178.64/28" ${dis}>${h(s.exclude.join(', '))}</textarea>
        <small class="muted">${t('Für empfindliche Geräte, z. B. ältere Kameras. Sie erscheinen trotzdem, wenn sie sich per ARP oder mDNS zeigen.')}</small>
        <div class="grid2">
          <div><label>${t('Automatisch scannen')}</label><select name="schedule_hours" ${dis}>${SCHEDULE.map(([v, n]) => `<option value="${v}" ${+s.schedule_hours === v ? 'selected' : ''}>${t(n)}</option>`).join('')}</select></div>
          <div><label>${t('Externe Erkennung')}</label><label class="chk"><input type="checkbox" name="fingerbank" ${s.fingerbank ? 'checked' : ''} ${r.fingerbank_configured ? '' : 'disabled'} ${dis}> Fingerbank</label>
            <small class="muted">${r.fingerbank_configured ? t('Sendet MAC-Adresse und Hostname an fingerbank.org.') : t('API-Schlüssel unter Einstellungen → Erkennung hinterlegen.')}</small></div>
        </div>
        ${ctx.canEdit ? `<div class="row" style="margin-top:14px"><button class="pri">${t('Speichern')}</button></div>` : ''}
      </form>
      <div class="panel"><h3>${t('Scan')}</h3>
        <div id="runbox">${running ? '' : `<p class="muted">${t('Der Scan findet Geräte, erkennt sie und legt neue im Posteingang ab. Vorhandene Geräte werden aktualisiert; manuelle Angaben bleiben unangetastet.')}</p>`}</div>
        ${ctx.canEdit ? `<button class="pri" id="runscan" ${running ? 'disabled' : ''}>${t('Jetzt scannen')}</button>` : ''}
        <p class="muted small" style="margin-top:12px">${t('Herstellerliste')}: ${r.oui.entries ? t('{n} Einträge, Stand {d}', { n: r.oui.entries.toLocaleString(), d: h(r.oui.updated) }) : t('wird beim ersten Scan geladen')}
          · nmap: ${w.nmap ? t('ja') : t('nein')} · ${t('Betriebssystem-Erkennung')}: ${w.raw ? t('ja') : t('nein')}</p>
      </div>
    </div>
    <h2>${t('Verlauf')}</h2>
    <div class="table-wrap"><table class="compact"><thead><tr><th>${t('Start')}</th><th>${t('Modus')}</th><th>${t('Netze')}</th><th>${t('Dauer')}</th><th>${t('Geräte')}</th><th>${t('neu')}</th><th>${t('offline')}</th><th>${t('Status')}</th></tr></thead><tbody>
      ${r.jobs.length ? r.jobs.map(j => `<tr><td class="mono">${fmtDate(j.created)}${j.params.scheduled ? ` <span class="badge">${t('geplant')}</span>` : ''}</td><td>${t(MODE[j.result.mode || j.params.mode]?.[0] || '–')}</td>
        <td class="mono">${h((j.result.targets || j.params.targets || []).join(', '))}</td>
        ${j.status === 'error' ? `<td colspan="4" class="errtxt">${h(j.message)}</td>` : `<td class="mono">${j.result.duration ? j.result.duration + ' s' : ''}</td>
        <td class="mono">${j.result.hosts ?? ''}</td><td class="mono">${j.result.new ? `<a href="#/p/${ctx.pid}/posteingang">${j.result.new}</a>` : (j.result.new ?? '')}</td><td class="mono">${j.result.offline ?? ''}</td>`}
        <td>${j.status === 'done' ? `<span class="badge ok">${t('fertig')}</span>` : j.status === 'error' ? `<span class="badge err" title="${h(j.message)}">${t('Fehler')}</span>` : `<span class="badge">${t(j.status === 'running' ? 'läuft' : 'wartet')}</span>`}</td></tr>`).join('')
        : `<tr><td colspan="8" class="empty">${t('Noch kein Scan.')}</td></tr>`}
    </tbody></table></div>`;

  const collect = () => {
    const f = $('#scanform', ctx.el), v = fd(f);
    return { mode: v.mode, targets: $$('[data-net]', ctx.el).filter(x => x.checked).map(x => x.dataset.net),
      exclude: (v.exclude || '').split(/[\s,;]+/).filter(Boolean), schedule_hours: +v.schedule_hours, fingerbank: !!v.fingerbank };
  };
  const sf = $('#scanform', ctx.el);
  sf.onsubmit = async ev => { ev.preventDefault(); try { await api('PUT', `${P}/scan`, collect()); toast(t('gespeichert')); ctx.reload(); } catch (e) { toast(e.message, true); } };
  const an = $('#addnetb', ctx.el);
  if (an) an.onclick = () => {
    const v = $('#addnet', ctx.el).value.trim(); if (!v) return;
    $('#nets', ctx.el).insertAdjacentHTML('beforeend', `<label class="chk"><input type="checkbox" data-net="${h(v)}" checked> <span class="mono">${h(v)}</span> <span class="muted small">${t('eigene Angabe')}</span></label>`);
    $('#addnet', ctx.el).value = '';
  };
  const watch = async jid => {
    const box = $('#runbox', ctx.el);
    for (;;) {
      if (!document.body.contains(box)) return;  // Reiter gewechselt
      let j;
      try { j = await api('GET', `/api/jobs/${jid}`); } catch { return; }
      if (j.status === 'done' || j.status === 'error') {
        if (j.status === 'done') toast(t('Scan fertig: {n} Geräte, {m} neu', { n: j.result.hosts, m: j.result.new }));
        else toast(t('Scan fehlgeschlagen: {e}', { e: j.message }), true);
        return ctx.reload();
      }
      box.innerHTML = `<div class="scanprog"><div class="meter"><i style="width:${j.progress}%"></i></div><span class="mono">${j.progress} %</span></div>
        <p class="muted small">${h(j.status === 'queued' ? t('wartet auf den Hintergrunddienst …') : j.message)}</p>`;
      await new Promise(res => setTimeout(res, 1500));
    }
  };
  const rb = $('#runscan', ctx.el);
  if (rb) rb.onclick = async () => {
    rb.disabled = true;
    try { await api('PUT', `${P}/scan`, collect()); const res = await api('POST', `${P}/scan/run`, {}); watch(res.job.id); }
    catch (e) { toast(e.message, true); rb.disabled = false; }
  };
  if (running) watch(running.id);
}

window.INV.posteingang = tabInbox;
window.INV.netzscan = tabScan;
