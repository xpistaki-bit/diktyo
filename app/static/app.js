'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let LANG = (() => { try { return localStorage.getItem('dk_lang'); } catch { return null; } })() || ((navigator.language || 'de').startsWith('de') ? 'de' : 'en');
/* t('Deutscher Text {n}', {n: 3}) – Deutsch ist der Schlüssel, Englisch steht in i18n.js */
function t(s, v) {
  let o = LANG === 'en' ? (window.I18N_EN[s] ?? s) : s;
  if (v) for (const k in v) o = o.replaceAll('{' + k + '}', v[k]);
  return o;
}
const app = $('#app');
let STATE = { version: '', repo: 'https://github.com/xpistaki-bit/diktyo', user: null, first_run: false, registration_open: false, mail_enabled: false, min_pw: 8 };
const ROLE = { owner: 'Besitzer', edit: 'Bearbeiten', view: 'Lesen' };
const fmtDate = s => s ? new Date(s).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { dateStyle: 'medium', timeStyle: 'short' }) : '–';

function toast(msg, err) {
  const d = $('#dlg'), de = d.open && $('.dlg-err', d);
  if (de && err) { de.textContent = msg; de.classList.add('on'); clearTimeout(toast.d); toast.d = setTimeout(() => de.classList.remove('on'), 8000); return; }
  const el = $('#toast'); el.textContent = msg; el.className = 'on' + (err ? ' err' : '');
  clearTimeout(toast.t); toast.t = setTimeout(() => el.className = '', err ? 5000 : 2400);
}
async function api(method, url, body) {
  const opt = { method, headers: { 'X-Lang': LANG, 'X-Requested-With': 'diktyo' } };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(url, opt);
  const data = (r.headers.get('content-type') || '').includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    const e = new Error(data?.error || data?.detail || (t('Fehler') + ' ' + r.status)); e.status = r.status;
    if (r.status === 401 && !url.startsWith('/api/auth/')) { STATE.user = null; drawHeader(); route(); }
    throw e;
  }
  return data;
}
function dialog(title, html, { ok = t('Speichern'), onOk, onOpen, wide, danger } = {}) {
  return new Promise(res => {
    const d = $('#dlg'), f = $('#dlgform');
    d.classList.toggle('wide', !!wide);
    f.innerHTML = `<h3>${h(title)}</h3><div class="c">${html}</div><div class="dlg-err" role="alert"></div><div class="f"><button type="button" data-x>${ok ? t('Abbrechen') : t('Schließen')}</button>${ok ? `<button class="${danger ? 'danger' : 'pri'}" type="submit">${h(ok)}</button>` : ''}</div>`;
    const sc = document.querySelector('main'), y0 = sc ? sc.scrollTop : 0;
    // beim Schließen gibt der Browser den Fokus an den auslösenden Knopf zurück und scrollt dorthin – Position halten
    const close = v => { d.close(); if (sc) sc.scrollTop = y0; f.onsubmit = null; res(v); };
    $('[data-x]', f).onclick = () => close(null);
    d.oncancel = () => res(null);
    f.onsubmit = async ev => {
      ev.preventDefault();
      try { const v = onOk ? await onOk(f) : true; if (v !== false) close(v ?? true); } catch (e) { toast(e.message, true); }
    };
    d.showModal();
    onOpen && onOpen(f, close);
    const first = $('input:not([type=hidden]),select,textarea', f); first && first.focus();
  });
}
const confirmDlg = (title, text, ok) => dialog(title, `<p>${text}</p>`, { ok, danger: true });
const showSecret = (title, text, secret) => dialog(title, `<p>${h(text)}</p><div class="secret">${h(secret)}</div><p class="muted">${t('Das Passwort wird nur jetzt angezeigt.')}</p>`, { ok: null });
const fd = f => Object.fromEntries(new FormData(f).entries());
function crumbs(parts) { $('#crumbs').innerHTML = parts.map(([txt, href]) => href ? `<a href="${href}">${h(txt)}</a>` : h(txt)).join(' › '); }

const ghIcon = '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="currentColor"><path d="M8 0a8 8 0 0 0-2.53 15.59c.4.07.55-.17.55-.38v-1.33c-2.23.48-2.7-1.07-2.7-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.06-.49.06-.49.8.06 1.23.83 1.23.83.72 1.22 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.65-.89-3.65-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48v2.2c0 .21.15.46.55.38A8 8 0 0 0 8 0z"/></svg>';
const homeIcon = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-8 9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/></svg>';
function homeHref() {
  let last = null;
  try { last = localStorage.getItem('dk_last_profile'); } catch { }
  return last ? `#/p/${last}` : '#/';
}
function drawHeader() {
  document.documentElement.lang = LANG;
  const u = STATE.user, sect = location.hash.replace(/^#\/?/, '').split('/')[0];
  $('#nav').innerHTML = `<a class="gh" href="${h(STATE.repo)}" target="_blank" rel="noopener" title="${t('Projekt auf GitHub')}">${ghIcon}<span>${STATE.version ? 'v' + h(STATE.version) : 'GitHub'}</span></a>`
    + (u ? `<a href="${homeHref()}" class="home" title="${t('Zum zuletzt geöffneten Profil')}">${homeIcon}<span>${t('Home')}</span></a><a href="#/" class="${sect === '' ? 'on' : ''}">${t('Profile')}</a><a href="#/katalog" class="${sect === 'katalog' ? 'on' : ''}">${t('Katalog')}</a><a href="#/einstellungen" class="${sect === 'einstellungen' ? 'on' : ''}">${t('Einstellungen')}</a><span class="who" title="${h(u.email)}">${h(u.email)}</span><button class="sm" data-logout>${t('Abmelden')}</button>` : '')
    + `<span class="lang" role="group" aria-label="Sprache / Language"><button data-l="de" class="${LANG === 'de' ? 'on' : ''}">DE</button><button data-l="en" class="${LANG === 'en' ? 'on' : ''}">EN</button></span>`;
  $$('#nav [data-l]').forEach(b => b.onclick = () => {
    LANG = b.dataset.l; try { localStorage.setItem('dk_lang', LANG); } catch { }
    if (STATE.user) api('PUT', '/api/auth/me', { lang: LANG }).catch(() => { });
    drawHeader(); route();
  });
  const lo = $('#nav [data-logout]');
  if (lo) lo.onclick = async () => { await api('POST', '/api/auth/logout'); STATE.user = null; location.hash = '#/'; drawHeader(); route(); };
}

/* ---------------------------------------------------------------- Router */
async function route() {
  const p = location.hash.replace(/^#\/?/, '').split('/');
  drawHeader();
  try {
    if (p[0] === 'reset' && p[1]) return viewReset(p[1]);
    if (!STATE.user) { crumbs([]); return STATE.first_run ? (p[0] === 'wiederherstellen' ? viewRestore() : viewSetup()) : viewLogin(p[0] === 'registrieren' ? 'register' : p[0] === 'vergessen' ? 'forgot' : 'login'); }
    if (p[0] === 'p' && p[1]) await viewProfile(+p[1], p[2] || 'uebersicht', p[3]);
    else if (p[0] === 'katalog') await (p[1] === 'regeln' ? viewRules() : viewCatalog());
    else if (p[0] === 'einstellungen') await viewSettings();
    else await viewProfiles();
  } catch (e) {
    if (e.status === 401) return;
    app.innerHTML = `<div class="page"><h1>${t('Das hat nicht geklappt')}</h1><p class="sub">${h(e.message)}</p><a class="btn" href="#/">${t('Zur Übersicht')}</a></div>`;
  }
}
window.addEventListener('hashchange', route);

/* ---------------------------------------------------------------- Anmeldung */
function authFrame(title, sub, body) {
  app.innerHTML = `<div class="auth"><div class="panel">
    <div class="logo"><img src="/logo.svg" alt="" width="44" height="44"><div><b>díktyo</b><small>${t('Netzwerk-Dokumentation für dein Heimnetz')}</small></div></div>
    <h3>${h(title)}</h3>${sub ? `<p class="sub">${sub}</p>` : ''}${body}</div></div>`;
}
const pwHint = () => t('Mindestens {n} Zeichen', { n: STATE.min_pw });

async function afterAuth(user) {
  STATE.user = user; STATE.first_run = false;
  if (user.lang && user.lang !== LANG) { LANG = user.lang; try { localStorage.setItem('dk_lang', LANG); } catch { } }
  location.hash = '#/'; route();
}

function viewSetup() {
  authFrame(t('Ersteinrichtung'), t('Lege das erste Konto an. Es wird Administrator und kann weitere Konten anlegen.'),
    `<form id="f"><label>${t('E-Mail-Adresse')}</label><input name="email" type="email" autocomplete="username" required>
     <label>${t('Passwort')}</label><input name="password" type="password" autocomplete="new-password" minlength="${STATE.min_pw}" required placeholder="${h(pwHint())}">
     <label>${t('Passwort wiederholen')}</label><input name="password2" type="password" autocomplete="new-password" required>
     <div class="actions"><span></span><button class="pri">${t('Konto anlegen')}</button></div></form>
     <p class="hint">${t('Umzug oder Neuinstallation?')} <a href="#/wiederherstellen">${t('Aus einer Sicherung wiederherstellen')}</a></p>`);
  $('#f').onsubmit = async ev => {
    ev.preventDefault(); const v = fd(ev.target);
    if (v.password !== v.password2) return toast(t('Die Passwörter stimmen nicht überein'), true);
    try { afterAuth((await api('POST', '/api/auth/register', { email: v.email, password: v.password })).user); } catch (e) { toast(e.message, true); }
  };
  $('input', app).focus();
}

function viewRestore() {
  authFrame(t('Aus Sicherung wiederherstellen'), t('Übernimmt Konten, Profile, Geräte und Einstellungen aus einer díktyo-Sicherung (ZIP). Danach meldest du dich mit deinem bisherigen Konto an.'),
    `<form id="f"><label>${t('Sicherungsdatei (ZIP)')}</label><input name="file" type="file" accept=".zip,application/zip" required>
     <label>${t('Backup-Passphrase (falls vergeben)')}</label><input name="passphrase" type="password" autocomplete="off">
     <p class="hint">${t('Ohne Passphrase werden Konten und Daten übernommen, gespeicherte Zugangsdaten (z. B. SMTP-Passwort) aber nicht.')}</p>
     <div class="actions"><a href="#/">${t('Zurück')}</a><button class="pri">${t('Wiederherstellen')}</button></div></form>`);
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const btn = $('button.pri', ev.target); btn.disabled = true;
    try {
      const r = await api('POST', '/api/restore', new FormData(ev.target));
      STATE.first_run = false;
      toast(t('Wiederhergestellt: {u} Konten, {p} Profile, {d} Geräte', { u: r.users, p: r.profiles, d: r.devices }));
      location.hash = '#/';
    } catch (e) { toast(e.message, true); btn.disabled = false; }
  };
}

function viewLogin(mode) {
  if (mode === 'register' && STATE.registration_open) {
    authFrame(t('Konto anlegen'), '', `<form id="f"><label>${t('E-Mail-Adresse')}</label><input name="email" type="email" autocomplete="username" required>
      <label>${t('Passwort')}</label><input name="password" type="password" autocomplete="new-password" minlength="${STATE.min_pw}" required placeholder="${h(pwHint())}">
      <label>${t('Passwort wiederholen')}</label><input name="password2" type="password" autocomplete="new-password" required>
      <div class="actions"><a href="#/">${t('Zur Anmeldung')}</a><button class="pri">${t('Konto anlegen')}</button></div></form>`);
    $('#f').onsubmit = async ev => {
      ev.preventDefault(); const v = fd(ev.target);
      if (v.password !== v.password2) return toast(t('Die Passwörter stimmen nicht überein'), true);
      try { afterAuth((await api('POST', '/api/auth/register', { email: v.email, password: v.password })).user); } catch (e) { toast(e.message, true); }
    };
  } else if (mode === 'forgot') {
    authFrame(t('Passwort vergessen'), STATE.mail_enabled ? t('Gib deine E-Mail-Adresse ein. Du bekommst einen Link, mit dem du ein neues Passwort wählen kannst.') : '',
      STATE.mail_enabled
        ? `<form id="f"><label>${t('E-Mail-Adresse')}</label><input name="email" type="email" autocomplete="username" required>
           <div class="actions"><a href="#/">${t('Zur Anmeldung')}</a><button class="pri">${t('Link senden')}</button></div></form>`
        : `<p>${t('Der E-Mail-Versand ist nicht eingerichtet. Ein Administrator kann dir unter „Einstellungen → Benutzer“ ein neues Passwort geben, oder es wird auf dem Server gesetzt:')}</p>
           <div class="secret">diktyo reset-password ${h(t('deine@adresse.de'))}</div>
           <p class="hint">${t('Docker:')} <span class="mono">docker compose exec diktyo python -m app.cli reset-password …</span></p>
           <div class="actions"><a href="#/">${t('Zur Anmeldung')}</a></div>`);
    const f = $('#f');
    if (f) f.onsubmit = async ev => {
      ev.preventDefault();
      try { await api('POST', '/api/auth/forgot', fd(ev.target)); toast(t('Falls es ein Konto mit dieser Adresse gibt, ist der Link unterwegs.')); location.hash = '#/'; } catch (e) { toast(e.message, true); }
    };
  } else {
    authFrame(t('Anmelden'), '', `<form id="f"><label>${t('E-Mail-Adresse')}</label><input name="email" type="email" autocomplete="username" required>
      <label>${t('Passwort')}</label><input name="password" type="password" autocomplete="current-password" required>
      <div class="actions"><a href="#/vergessen">${t('Passwort vergessen?')}</a><button class="pri">${t('Anmelden')}</button></div></form>
      ${STATE.registration_open ? `<p class="hint">${t('Noch kein Konto?')} <a href="#/registrieren">${t('Konto anlegen')}</a></p>` : ''}`);
    $('#f').onsubmit = async ev => {
      ev.preventDefault();
      try { afterAuth((await api('POST', '/api/auth/login', fd(ev.target))).user); } catch (e) { toast(e.message, true); }
    };
  }
  const first = $('input', app); first && first.focus();
}

function viewReset(token) {
  crumbs([]);
  authFrame(t('Neues Passwort wählen'), '', `<form id="f"><label>${t('Neues Passwort')}</label><input name="password" type="password" autocomplete="new-password" minlength="${STATE.min_pw}" required placeholder="${h(pwHint())}">
    <label>${t('Passwort wiederholen')}</label><input name="password2" type="password" autocomplete="new-password" required>
    <div class="actions"><a href="#/">${t('Zur Anmeldung')}</a><button class="pri">${t('Speichern')}</button></div></form>`);
  $('#f').onsubmit = async ev => {
    ev.preventDefault(); const v = fd(ev.target);
    if (v.password !== v.password2) return toast(t('Die Passwörter stimmen nicht überein'), true);
    try {
      await api('POST', '/api/auth/reset', { token, password: v.password });
      STATE.user = null; toast(t('Passwort geändert. Bitte neu anmelden.')); location.hash = '#/';
    } catch (e) { toast(e.message, true); }
  };
  $('input', app).focus();
}

/* ---------------------------------------------------------------- Profile */
async function viewProfiles() {
  crumbs([]);
  const { profiles } = await api('GET', '/api/profiles');
  app.innerHTML = `<div class="page"><h1>${t('Profile')}</h1>
    <p class="sub">${t('Ein Profil ist ein Netz bzw. Standort, zum Beispiel Zuhause, Eltern oder Ferienhaus. Profile lassen sich mit anderen Konten teilen.')}</p>
    <div class="cards">${profiles.map(p => `<button class="card" data-id="${p.id}">
        <b>${h(p.name)}</b>${p.description ? `<p>${h(p.description)}</p>` : ''}
        <span class="row"><span class="badge ${p.role}">${t(ROLE[p.role])}</span>${!p.member ? `<span class="badge admin">${t('Admin-Zugriff')}</span>` : ''}
        <small>${p.members === 2 ? t('geteilt mit 1 Konto') : p.members > 2 ? t('geteilt mit {n} Konten', { n: p.members - 1 }) : t('nicht geteilt')}</small></span>
      </button>`).join('')}
      <button class="card new" data-new>${t('+ Neues Profil')}</button></div></div>`;
  $$('[data-id]', app).forEach(b => b.onclick = () => location.hash = `#/p/${b.dataset.id}`);
  $('[data-new]', app).onclick = async () => {
    const r = await profileDialog(t('Neues Profil'), {}, t('Anlegen'), v => api('POST', '/api/profiles', v));
    if (r) location.hash = `#/p/${r.profile.id}`;
  };
}

function profileDialog(title, p, ok, save) {
  return dialog(title, `<label>${t('Name')}</label><input name="name" required maxlength="120" value="${h(p.name || '')}" placeholder="${t('z. B. Zuhause')}">
    <label>${t('Beschreibung (optional)')}</label><textarea name="description" rows="3" maxlength="2000" placeholder="${t('z. B. Adresse, Anschluss, Besonderheiten')}">${h(p.description || '')}</textarea>`,
    { ok, onOk: f => save(fd(f)) });
}

const TABS = [['uebersicht', 'Übersicht'], ['geraete', 'Geräte'], ['topologie', 'Topologie'], ['verlauf', 'Verlauf'], ['posteingang', 'Posteingang'], ['netzscan', 'Netzscan'], ['integrationen', 'Integrationen'], ['ipam', 'IPAM'], ['standorte', 'Standorte'], ['ausgabe', 'Ausgabe'], ['freigabe', 'Freigabe']];
async function viewProfile(pid, tab, sub, keep = null) {
  if (!TABS.some(x => x[0] === tab)) tab = 'uebersicht';
  let r;
  try { r = await api('GET', `/api/profiles/${pid}`); } catch (e) {
    if (e.status === 404) { try { localStorage.removeItem('dk_last_profile'); } catch { } }
    throw e;
  }
  try { localStorage.setItem('dk_last_profile', String(pid)); } catch { }
  drawHeader();
  const p = r.profile, isOwner = p.role === 'owner', canEdit = p.role !== 'view';
  crumbs([[t('Profile'), '#/'], [p.name]]);
  app.innerHTML = `<div class="page wide">
    <div class="row between top">
      <div><h1>${h(p.name)}</h1>${p.description ? `<p class="sub">${h(p.description)}</p>` : ''}</div>
      <div class="row"><span class="badge ${p.role}">${t(ROLE[p.role])}</span>
        ${canEdit ? `<button class="sm" data-edit>${t('Bearbeiten')}</button>` : ''}
        ${isOwner ? `<button class="sm danger" data-del>${t('Löschen')}</button>` : ''}</div>
    </div>
    <nav class="tabs">${TABS.map(([k, n]) => `<a href="#/p/${pid}/${k}" class="${k === tab ? 'on' : ''}">${t(n)}${k === 'posteingang' && r.inbox ? ` <span class="count">${r.inbox}</span>` : ''}</a>`).join('')}</nav>
    <div id="tab"></div></div>`;
  const ed = $('[data-edit]', app);
  if (ed) ed.onclick = async () => { if (await profileDialog(t('Profil bearbeiten'), p, t('Speichern'), v => api('PUT', `/api/profiles/${pid}`, v))) viewProfile(pid, tab); };
  const del = $('[data-del]', app);
  if (del) del.onclick = async () => {
    if (!await confirmDlg(t('Profil löschen'), t('Profil „{n}“ mit allen Daten endgültig löschen?', { n: h(p.name) }), t('Löschen'))) return;
    await api('DELETE', `/api/profiles/${pid}`); toast(t('Profil gelöscht')); location.hash = '#/';
  };
  // Neu laden (nach dem Speichern, automatische Aktualisierung) ohne Sprung nach oben: Höhe halten, bis Diagramme da sind
  const scroller = () => document.querySelector('main') || document.scrollingElement;  // gescrollt wird <main>, nicht das Fenster
  const reload = () => viewProfile(pid, tab, sub, { y: scroller().scrollTop, h: ($('#tab') || {}).offsetHeight || 0 });
  const ctx = { pid, p, members: r.members, canEdit, isOwner, sub, el: $('#tab'), reload };
  if (keep) { ctx.el.style.minHeight = keep.h + 'px'; scroller().scrollTop = keep.y; }
  if (tab === 'freigabe') renderSharing(ctx); else await window.INV[tab](ctx);
  if (keep) {
    scroller().scrollTop = keep.y;
    setTimeout(() => { if (document.body.contains(ctx.el)) ctx.el.style.minHeight = ''; }, 2500);
  }
}

function renderSharing(ctx) {
  const { pid, p, isOwner } = ctx;
  const owners = ctx.members.filter(m => m.role === 'owner').length;
  ctx.el.innerHTML = `
    <div class="table-wrap"><table><thead><tr><th>${t('E-Mail-Adresse')}</th><th>${t('Rolle')}</th><th></th></tr></thead><tbody>
      ${ctx.members.map(m => `<tr data-uid="${m.user_id}"><td>${h(m.email)}${m.user_id === STATE.user.id ? ` <span class="muted">(${t('du')})</span>` : ''}</td>
        <td>${isOwner ? `<select data-role style="max-width:160px">${Object.keys(ROLE).map(k => `<option value="${k}" ${k === m.role ? 'selected' : ''}>${t(ROLE[k])}</option>`).join('')}</select>` : `<span class="badge ${m.role}">${t(ROLE[m.role])}</span>`}</td>
        <td class="act">${isOwner && m.user_id !== STATE.user.id ? `<button class="sm danger" data-rm>${t('Entfernen')}</button>` : ''}${m.user_id === STATE.user.id && p.member && !(m.role === 'owner' && owners === 1) ? `<button class="sm" data-leave>${t('Verlassen')}</button>` : ''}</td></tr>`).join('')}
    </tbody></table></div>
    ${isOwner ? `<form class="row" id="share" style="margin-top:12px"><input name="email" type="email" required placeholder="${t('E-Mail-Adresse eines vorhandenen Kontos')}" style="flex:1;min-width:220px">
      <select name="role" style="width:auto">${['view', 'edit', 'owner'].map(k => `<option value="${k}">${t(ROLE[k])}</option>`).join('')}</select>
      <button class="pri">${t('Teilen')}</button></form>` : ''}
    <p class="muted">${t('Lesen: nur ansehen. Bearbeiten: Geräte und Netz ändern. Besitzer: zusätzlich teilen und löschen.')}</p>`;
  $$('[data-role]', ctx.el).forEach(s => s.onchange = async () => {
    try { await api('PUT', `/api/profiles/${pid}/members/${s.closest('tr').dataset.uid}`, { role: s.value }); toast(t('gespeichert')); } catch (e) { toast(e.message, true); }
    ctx.reload();
  });
  $$('[data-rm]', ctx.el).forEach(b => b.onclick = async () => {
    try { await api('DELETE', `/api/profiles/${pid}/members/${b.closest('tr').dataset.uid}`); ctx.reload(); } catch (e) { toast(e.message, true); }
  });
  const lv = $('[data-leave]', ctx.el);
  if (lv) lv.onclick = async () => {
    if (!await confirmDlg(t('Profil verlassen'), t('Du verlierst den Zugriff auf „{n}“, bis dich ein Besitzer wieder einlädt.', { n: h(p.name) }), t('Verlassen'))) return;
    try { await api('DELETE', `/api/profiles/${pid}/members/${STATE.user.id}`); location.hash = '#/'; } catch (e) { toast(e.message, true); }
  };
  const sh = $('#share', ctx.el);
  if (sh) sh.onsubmit = async ev => {
    ev.preventDefault();
    try { await api('POST', `/api/profiles/${pid}/members`, fd(ev.target)); toast(t('Profil geteilt')); ctx.reload(); } catch (e) { toast(e.message, true); }
  };
}

/* ---------------------------------------------------------------- Einstellungen */
async function viewSettings() {
  crumbs([[t('Einstellungen')]]);
  const u = STATE.user;
  const [ul, st] = u.is_admin ? await Promise.all([api('GET', '/api/users'), api('GET', '/api/settings')]) : [null, null];
  const smtp = st?.smtp || {};
  app.innerHTML = `<div class="page"><h1>${t('Einstellungen')}</h1><p class="sub">${h(u.email)}${u.is_admin ? ` · <span class="badge admin">${t('Administrator')}</span>` : ''}</p>
    <h2>${t('Mein Konto')}</h2>
    <form class="panel" id="pw"><div class="grid2">
      <div><label>${t('Aktuelles Passwort')}</label><input name="current" type="password" autocomplete="current-password" required></div>
      <div><label>${t('Neues Passwort')}</label><input name="password" type="password" autocomplete="new-password" minlength="${STATE.min_pw}" required placeholder="${h(pwHint())}"></div>
      <div><label>${t('Passwort wiederholen')}</label><input name="password2" type="password" autocomplete="new-password" required></div>
    </div><div class="row" style="margin-top:14px"><button class="pri">${t('Passwort ändern')}</button><span class="muted">${t('Andere Sitzungen werden dabei abgemeldet.')}</span></div></form>
    ${u.is_admin ? `
    <h2>${t('Konten')}</h2>
    <div class="table-wrap"><table><thead><tr><th>${t('E-Mail-Adresse')}</th><th>${t('Rolle')}</th><th>${t('Profile')}</th><th>${t('Letzte Anmeldung')}</th><th></th></tr></thead><tbody>
      ${ul.users.map(x => `<tr data-uid="${x.id}"><td>${h(x.email)}${x.id === u.id ? ` <span class="muted">(${t('du')})</span>` : ''}</td>
        <td>${x.is_admin ? `<span class="badge admin">${t('Administrator')}</span>` : `<span class="badge">${t('Benutzer')}</span>`}</td>
        <td class="mono">${x.profiles}</td><td class="mono">${fmtDate(x.last_login)}</td>
        <td class="act">${x.id !== u.id ? `<button class="sm" data-admin="${x.is_admin ? 0 : 1}">${x.is_admin ? t('Admin entziehen') : t('Zum Admin machen')}</button><button class="sm" data-newpw>${t('Neues Passwort')}</button><button class="sm danger" data-deluser>${t('Löschen')}</button>` : ''}</td></tr>`).join('')}
    </tbody></table></div>
    <div class="row" style="margin-top:12px"><button class="pri" data-adduser>${t('+ Konto anlegen')}</button>
      <label class="chk" style="margin:0"><input type="checkbox" id="regopen" ${st.registration_open ? 'checked' : ''}> ${t('Selbstregistrierung erlauben')}</label></div>

    <h2>${t('E-Mail-Versand')}</h2>
    <form class="panel" id="smtp"><p class="muted" style="margin-top:0">${t('Für „Passwort vergessen“. Ohne E-Mail-Versand setzt ein Administrator Passwörter in der Benutzerliste oder auf dem Server.')}</p>
      <div class="grid2">
        <div><label>${t('SMTP-Server')}</label><input name="host" value="${h(smtp.host || '')}" placeholder="smtp.example.com"></div>
        <div><label>${t('Port')}</label><input name="port" inputmode="numeric" value="${h(smtp.port || '587')}"></div>
        <div><label>${t('Verschlüsselung')}</label><select name="security">${[['starttls', 'STARTTLS'], ['ssl', 'SSL/TLS'], ['none', t('keine')]].map(([k, n]) => `<option value="${k}" ${(smtp.security || 'starttls') === k ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
        <div><label>${t('Benutzername')}</label><input name="user" autocomplete="off" value="${h(smtp.user || '')}"></div>
        <div><label>${t('Passwort')}</label><input name="password" type="password" autocomplete="new-password" value="${h(smtp.password || '')}"></div>
        <div><label>${t('Absender')}</label><input name="sender" value="${h(smtp.sender || '')}" placeholder="diktyo@example.com"></div>
      </div>
      <label>${t('Adresse der Weboberfläche (für Links in E-Mails, optional)')}</label><input name="app_url" value="${h(smtp.app_url || '')}" placeholder="http://192.168.178.50:8090">
      <div class="row" style="margin-top:14px"><button class="pri">${t('Speichern')}</button><button type="button" data-test ${smtp.host ? '' : 'disabled'}>${t('Testmail an mich senden')}</button></div>
    </form>
    <h2>${t('Erkennung')}</h2><div id="detection"></div>
    <h2>${t('Sicherung')}</h2><div id="backup"></div>` : ''}
  </div>`;

  $('#pw').onsubmit = async ev => {
    ev.preventDefault(); const v = fd(ev.target);
    if (v.password !== v.password2) return toast(t('Die Passwörter stimmen nicht überein'), true);
    try { await api('POST', '/api/auth/password', { current: v.current, password: v.password }); ev.target.reset(); toast(t('Passwort geändert')); } catch (e) { toast(e.message, true); }
  };
  if (!u.is_admin) return;
  const reload = () => viewSettings();
  const uidOf = el => +el.closest('tr').dataset.uid;
  const emailOf = el => el.closest('tr').firstElementChild.firstChild.textContent;
  $$('[data-admin]', app).forEach(b => b.onclick = async () => { try { await api('PUT', `/api/users/${uidOf(b)}`, { is_admin: b.dataset.admin === '1' }); reload(); } catch (e) { toast(e.message, true); } });
  $$('[data-newpw]', app).forEach(b => b.onclick = async () => {
    if (!await confirmDlg(t('Neues Passwort'), t('Für {e} wird ein neues Passwort erzeugt. Alle Sitzungen dieses Kontos werden abgemeldet.', { e: h(emailOf(b)) }), t('Erzeugen'))) return;
    try { const r = await api('PUT', `/api/users/${uidOf(b)}`, { new_password: true }); await showSecret(t('Neues Passwort'), emailOf(b), r.password); } catch (e) { toast(e.message, true); }
  });
  $$('[data-deluser]', app).forEach(b => b.onclick = async () => {
    if (!await confirmDlg(t('Konto löschen'), t('{e} endgültig löschen? Profile, deren einziger Besitzer dieses Konto ist, gehen an dich über.', { e: h(emailOf(b)) }), t('Löschen'))) return;
    try { await api('DELETE', `/api/users/${uidOf(b)}`); reload(); } catch (e) { toast(e.message, true); }
  });
  $('[data-adduser]', app).onclick = async () => {
    const r = await dialog(t('Konto anlegen'), `<label>${t('E-Mail-Adresse')}</label><input name="email" type="email" required>
      <label>${t('Passwort (leer lassen für ein zufälliges)')}</label><input name="password" type="password" autocomplete="new-password">
      <label class="chk"><input type="checkbox" name="is_admin"> ${t('Administrator')}</label>`,
      { ok: t('Anlegen'), onOk: f => { const v = fd(f); return api('POST', '/api/users', { email: v.email, password: v.password || undefined, is_admin: !!v.is_admin }); } });
    if (!r) return;
    if (r.password) await showSecret(t('Konto angelegt'), r.user.email, r.password); else toast(t('Konto angelegt'));
    reload();
  };
  $('#regopen').onchange = async ev => {
    try { await api('PUT', '/api/settings', { registration_open: ev.target.checked }); STATE.registration_open = ev.target.checked; toast(t('gespeichert')); } catch (e) { toast(e.message, true); }
  };
  $('#smtp').onsubmit = async ev => {
    ev.preventDefault();
    try { await api('PUT', '/api/settings', { smtp: fd(ev.target) }); toast(t('gespeichert')); STATE.mail_enabled = !!fd(ev.target).host; reload(); } catch (e) { toast(e.message, true); }
  };
  $('[data-test]', app).onclick = async () => {
    try { const r = await api('POST', '/api/settings/smtp/test'); toast(t('Testmail an {e} gesendet', { e: r.to })); } catch (e) { toast(e.message, true); }
  };
  await renderDetection($('#detection'));
  const aiBox = document.createElement('div'); aiBox.id = 'aibox'; $('#detection').after(aiBox);
  await renderAI(aiBox);
  await renderBackup($('#backup'));
}

async function renderDetection(el) {
  const r = await api('GET', '/api/settings/detection');
  el.innerHTML = `<form class="panel stack" id="det">
    <div class="grid2">
      <div><label>${t('Fingerbank-API-Schlüssel (optional)')}</label><input name="fingerbank_key" type="password" autocomplete="off" value="${h(r.fingerbank_key)}">
        <small class="muted">${t('Kostenlos auf fingerbank.org. Wird nur genutzt, wenn er in einem Profil unter Netzscan eingeschaltet ist; dann gehen MAC-Adresse und Hostname an fingerbank.org.')}</small></div>
      <div><label>${t('Herstellerliste (IEEE)')}</label><p style="margin:4px 0">${r.oui.entries ? t('{n} Einträge, Stand {d}', { n: r.oui.entries.toLocaleString(), d: h(r.oui.updated) }) : t('noch nicht geladen')}</p>
        <button type="button" class="sm" id="ouiup">${t('Jetzt aktualisieren')}</button>
        <small class="muted block">${t('Wird zur Laufzeit von der IEEE geladen und alle 30 Tage erneuert.')}</small></div>
      <div><label>${t('Messwerte aufbewahren')}</label><select id="mdays">${[1, 2, 3, 7, 14].map(v => `<option value="${v}" ${v === r.metrics_days ? 'selected' : ''}>${t('{n} Tage', { n: v })}</option>`).join('')}</select>
        <small class="muted block">${t('WAN- und Port-Traffic. Standard 2 Tage, höchstens 14.')}</small></div>
    </div>
    <p class="muted small" style="margin:0">${t('Hintergrunddienst')}: ${r.worker.running ? `<span class="okc">${t('läuft')}</span>` : `<span class="offc">${t('läuft nicht')}</span>`} · nmap: ${r.worker.nmap ? t('ja') : t('nein')} · ${t('Betriebssystem-Erkennung')}: ${r.worker.raw ? t('ja') : t('nein')}</p>
    <div class="row"><button class="pri">${t('Speichern')}</button></div></form>`;
  $('#mdays', el).onchange = async ev => { try { await api('PUT', '/api/settings/metrics', { days: +ev.target.value }); toast(t('gespeichert')); } catch (e) { toast(e.message, true); } };
  $('#det', el).onsubmit = async ev => { ev.preventDefault(); try { await api('PUT', '/api/settings/detection', fd(ev.target)); toast(t('gespeichert')); renderDetection(el); } catch (e) { toast(e.message, true); } };
  $('#ouiup', el).onclick = async ev => {
    ev.target.disabled = true;
    try { const x = await api('POST', '/api/settings/oui/update'); toast(t('{n} Einträge geladen', { n: x.entries.toLocaleString() })); renderDetection(el); }
    catch (e) { toast(e.message, true); ev.target.disabled = false; }
  };
}

/* KI (Claude API) für die Katalog-Recherche */
async function renderAI(el) {
  const r = await api('GET', '/api/settings/ai');
  el.innerHTML = `<h2>${t('KI-Recherche (Claude API)')}</h2><form class="panel stack" id="aif">
    <p class="muted small" style="margin:0">${t('Optional. Im Katalog recherchiert Claude mit der Websuche Datenblätter (Ports, WLAN, Eckdaten) und schlägt einen Eintrag mit Quellen vor. Gesendet werden nur Hersteller, Modell und erkannte Eckdaten – nie Seriennummern, IP-Adressen oder Daten aus deinem Netz. Die Kosten trägt dein Anthropic-Konto (meist wenige Cent je Recherche).')}</p>
    <div class="grid2">
      <div><label>${t('API-Schlüssel')}</label><input name="key" type="password" autocomplete="off" value="${h(r.key)}" placeholder="sk-ant-…">
        <small class="muted">${t('Aus der Claude Console (platform.claude.com → API Keys). Wird verschlüsselt gespeichert.')}</small></div>
      <div><label>${t('Modell')}</label><select name="model">${r.models.map(m => `<option value="${m.id}" ${m.id === r.model ? 'selected' : ''}>${h(m.name)} – $${m.price_in}/$${m.price_out} ${t('je 1 Mio. Token')}</option>`).join('')}</select>
        <small class="muted">${t('Standard: Claude Opus 5.5 (beste Recherche). Dazu kommen 1 Cent je Websuche (höchstens 5 je Recherche).')}</small></div>
    </div>
    <div class="row"><button class="pri">${t('Speichern')}</button><button type="button" class="sm" data-aitest>${t('Schlüssel testen')}</button><span class="small" id="aires"></span></div></form>`;
  $('#aif', el).onsubmit = async ev => { ev.preventDefault(); try { await api('PUT', '/api/settings/ai', fd(ev.target)); toast(t('gespeichert')); renderAI(el); } catch (e) { toast(e.message, true); } };
  $('[data-aitest]', el).onclick = async ev => {
    ev.target.disabled = true; const out = $('#aires', el); out.className = 'small muted'; out.textContent = t('prüfe …');
    try { const x = await api('POST', '/api/settings/ai/test', fd($('#aif', el))); out.className = 'small okc'; out.textContent = '✓ ' + t('Schlüssel ok ({m})', { m: x.model }); }
    catch (e) { out.className = 'small errtxt'; out.textContent = '✗ ' + e.message; }
    ev.target.disabled = false;
  };
}

/* Sicherung: Ziele wie bei PanelAtlas (Ordner/NAS, WebDAV, rclone), tägliche Sicherung, Passphrase für Zugangsdaten */
const TARGET = { local: 'Ordner / NAS', webdav: 'WebDAV (z. B. Nextcloud)', rclone: 'rclone (Google Drive, OneDrive, S3 …)' };
async function renderBackup(el) {
  const { settings: s, last } = await api('GET', '/api/backup');
  const row = tg => `<div class="target panel" data-type="${tg.type}">
      <div class="row between"><b>${t(TARGET[tg.type])}</b><button type="button" class="sm danger" data-rmt>${t('Entfernen')}</button></div>
      ${tg.type === 'local' ? `<label>${t('Pfad im Container')}</label><input data-f="path" value="${h(tg.path || '')}" placeholder="/mnt/sicherung">`
      : tg.type === 'webdav' ? `<label>${t('Adresse')}</label><input data-f="url" value="${h(tg.url || '')}" placeholder="https://cloud.example.com/remote.php/dav/files/NAME/diktyo">
        <div class="grid2"><div><label>${t('Benutzername')}</label><input data-f="user" value="${h(tg.user || '')}"></div><div><label>${t('Passwort')}</label><input data-f="password" type="password" autocomplete="new-password" value="${h(tg.password || '')}"></div></div>`
      : `<label>${t('rclone-Ziel')}</label><input data-f="remote" value="${h(tg.remote || '')}" placeholder="gdrive:diktyo">
        <small class="muted">${t('Form „Name:Ordner“, z. B. gdrive:diktyo. Der Name ist eine in rclone eingerichtete Verbindung.')} <span data-remotes></span></small>
        <div class="row" style="margin-top:6px"><button type="button" class="sm" data-gdrive>${t('Google Drive verbinden')}</button></div>`}</div>`;
  el.innerHTML = `<form class="panel stack" id="bk">
    <p class="muted" style="margin:0">${t('Jede Sicherung ist eine ZIP-Datei mit allen Konten, Profilen, Geräten und Einstellungen sowie einem PDF und CSV je Profil.')}</p>
    <div id="targets" class="stack">${s.targets.map(row).join('') || `<p class="muted" id="notargets">${t('Noch kein Sicherungsziel.')}</p>`}</div>
    <div class="row"><select id="newt" style="width:auto">${Object.keys(TARGET).map(k => `<option value="${k}">${t(TARGET[k])}</option>`).join('')}</select><button type="button" class="sm" id="addt">${t('+ Ziel hinzufügen')}</button></div>
    <div class="grid2">
      <div><label>${t('Automatisch sichern')}</label><select name="auto_hours">${[[0, 'aus'], [12, 'alle 12 Stunden'], [24, 'täglich'], [168, 'wöchentlich']].map(([v, n]) => `<option value="${v}" ${+s.auto_hours === v ? 'selected' : ''}>${t(n)}</option>`).join('')}</select>
        <small class="muted">${t('Nur wenn sich seit der letzten Sicherung etwas geändert hat.')}</small></div>
      <div><label>${t('Backup-Passphrase')}</label><input name="passphrase" type="password" autocomplete="new-password" value="${h(s.passphrase)}" placeholder="${t('mindestens 8 Zeichen')}">
        <small class="muted">${t('Verschlüsselt gespeicherte Zugangsdaten in der Sicherung. Ohne Passphrase bleiben sie draußen. Gut aufheben: ohne sie lassen sich die Zugangsdaten nicht wiederherstellen.')}</small></div>
    </div>
    <div class="row"><button class="pri">${t('Speichern')}</button><button type="button" id="runbk">${t('Jetzt sichern')}</button>
      <a class="btn" href="/api/backup/download">${t('Sicherung herunterladen')}</a><button type="button" id="impbk">${t('Profile aus Sicherung importieren')}</button>
      <input type="file" id="impfile" accept=".zip,application/zip" hidden></div>
    ${last ? `<div class="last"><b>${t('Letzte Sicherung')}:</b> ${fmtDate(last.time)} · ${(last.size / 1024).toFixed(0)} KB
      <ul>${last.results.map(r => `<li class="${r.ok ? 'ok' : 'err'}">${r.ok ? '✓' : '✗'} ${h(r.target)} – ${h(r.detail)}</li>`).join('')}</ul></div>` : ''}
  </form>`;
  const bindRm = () => {
    $$('[data-rmt]', el).forEach(b => b.onclick = () => b.closest('.target').remove());
    $$('[data-gdrive]', el).forEach(b => b.onclick = () => gdriveDialog(b.closest('.target')));
    rcloneInfo();
  };
  async function rcloneInfo() {
    if (!$('[data-remotes]', el)) return;
    try {
      const r = await api('GET', '/api/backup/rclone');
      $$('[data-remotes]', el).forEach(s => s.textContent = r.remotes == null ? t('rclone ist nicht installiert.')
        : r.remotes.length ? t('Eingerichtet: {n}', { n: r.remotes.map(x => `${x.name} (${x.type})`).join(', ') }) : t('Noch keine Verbindung eingerichtet.'));
    } catch { }
  }
  async function gdriveDialog(target) {
    const res = await dialog(t('Google Drive verbinden'), `<ol class="steps">
        <li>${t('Auf deinem PC (mit Browser) rclone installieren: <b>rclone.org/downloads</b> – unter Windows reicht die entpackte rclone.exe.')}</li>
        <li>${t('Dort in der Eingabeaufforderung bzw. im Terminal ausführen:')}<pre>rclone authorize "drive"</pre></li>
        <li>${t('Im Browser mit dem Google-Konto anmelden, in dem die Sicherungen landen sollen, und zustimmen.')}</li>
        <li>${t('rclone zeigt danach eine Zeile <b>{"access_token": …}</b> – die komplette Zeile kopieren und hier einfügen.')}</li></ol>
      <div class="grid2"><div><label>${t('Name der Verbindung')}</label><input name="name" value="gdrive" maxlength="32"></div></div>
      <label>${t('Token aus rclone authorize')}</label><textarea name="token" rows="4" class="mono" placeholder='{"access_token":"ya29…","token_type":"Bearer","refresh_token":"1//…","expiry":"…"}'></textarea>
      <p class="muted small">${t('díktyo erhält nur Zugriff auf Dateien, die es selbst in Google Drive anlegt (nicht auf deine übrigen Dateien). Das Token liegt in der rclone-Konfiguration im Datenverzeichnis von díktyo.')}</p>`,
      { ok: t('Verbinden'), wide: true, onOk: f => api('POST', '/api/backup/rclone/drive', fd(f)) });
    if (!res) return;
    const inp = $('[data-f=remote]', target);
    if (inp && (!inp.value || !inp.value.startsWith(res.name + ':'))) inp.value = res.remote;
    toast(t('Google Drive verbunden – Ziel {r}. Jetzt speichern.', { r: res.remote }));
    rcloneInfo();
  }
  bindRm();
  $('#addt', el).onclick = () => { const n = $('#notargets', el); if (n) n.remove(); $('#targets', el).insertAdjacentHTML('beforeend', row({ type: $('#newt', el).value })); bindRm(); };
  const collect = () => ({
    targets: $$('.target', el).map(d => Object.fromEntries([['type', d.dataset.type], ...$$('[data-f]', d).map(i => [i.dataset.f, i.value.trim()])])),
    auto_hours: +$('[name=auto_hours]', el).value, passphrase: $('[name=passphrase]', el).value,
  });
  $('#bk', el).onsubmit = async ev => {
    ev.preventDefault();
    try { await api('PUT', '/api/backup', collect()); toast(t('gespeichert')); renderBackup(el); } catch (e) { toast(e.message, true); }
  };
  $('#runbk', el).onclick = async ev => {
    ev.target.disabled = true;
    try { await api('PUT', '/api/backup', collect()); const r = await api('POST', '/api/backup/run'); toast(r.results.every(x => x.ok) ? t('Sicherung erstellt') : t('Sicherung mit Fehlern, siehe unten'), !r.results.every(x => x.ok)); renderBackup(el); }
    catch (e) { toast(e.message, true); ev.target.disabled = false; }
  };
  $('#impbk', el).onclick = () => $('#impfile', el).click();
  $('#impfile', el).onchange = async ev => {
    const file = ev.target.files[0]; if (!file) return;
    const fdata = new FormData(); fdata.append('file', file);
    try { const r = await api('POST', '/api/backup/import', fdata); toast(t('{p} Profile mit {d} Geräten importiert', { p: r.profiles, d: r.devices })); } catch (e) { toast(e.message, true); }
    ev.target.value = '';
  };
}

/* ---------------------------------------------------------------- Start */
(async () => {
  try { STATE = { ...STATE, ...await (await fetch('/api/state')).json() }; } catch { }
  if (STATE.user?.lang && STATE.user.lang !== LANG) { LANG = STATE.user.lang; try { localStorage.setItem('dk_lang', LANG); } catch { } }
  route();
})();
