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
  const el = $('#toast'); el.textContent = msg; el.className = 'on' + (err ? ' err' : '');
  clearTimeout(toast.t); toast.t = setTimeout(() => el.className = '', err ? 5000 : 2400);
}
async function api(method, url, body) {
  const opt = { method, headers: { 'X-Lang': LANG, 'X-Requested-With': 'diktyo' } };
  if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
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
    f.innerHTML = `<h3>${h(title)}</h3><div class="c">${html}</div><div class="f"><button type="button" data-x>${ok ? t('Abbrechen') : t('Schließen')}</button>${ok ? `<button class="${danger ? 'danger' : 'pri'}" type="submit">${h(ok)}</button>` : ''}</div>`;
    const close = v => { d.close(); f.onsubmit = null; res(v); };
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
function drawHeader() {
  document.documentElement.lang = LANG;
  const u = STATE.user, sect = location.hash.replace(/^#\/?/, '').split('/')[0];
  $('#nav').innerHTML = `<a class="gh" href="${h(STATE.repo)}" target="_blank" rel="noopener" title="${t('Projekt auf GitHub')}">${ghIcon}<span>${STATE.version ? 'v' + h(STATE.version) : 'GitHub'}</span></a>`
    + (u ? `<a href="#/" class="${sect === '' || sect === 'p' ? 'on' : ''}">${t('Profile')}</a><a href="#/einstellungen" class="${sect === 'einstellungen' ? 'on' : ''}">${t('Einstellungen')}</a><span class="who" title="${h(u.email)}">${h(u.email)}</span><button class="sm" data-logout>${t('Abmelden')}</button>` : '')
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
    if (!STATE.user) { crumbs([]); return STATE.first_run ? viewSetup() : viewLogin(p[0] === 'registrieren' ? 'register' : p[0] === 'vergessen' ? 'forgot' : 'login'); }
    if (p[0] === 'p' && p[1]) await viewProfile(+p[1]);
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
     <div class="actions"><span></span><button class="pri">${t('Konto anlegen')}</button></div></form>`);
  $('#f').onsubmit = async ev => {
    ev.preventDefault(); const v = fd(ev.target);
    if (v.password !== v.password2) return toast(t('Die Passwörter stimmen nicht überein'), true);
    try { afterAuth((await api('POST', '/api/auth/register', { email: v.email, password: v.password })).user); } catch (e) { toast(e.message, true); }
  };
  $('input', app).focus();
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
        <b>${h(p.name)}</b>${p.description ? `<p>${h(p.description)}</p>` : '<p></p>'}
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

async function viewProfile(pid) {
  const r = await api('GET', `/api/profiles/${pid}`);
  const p = r.profile, isOwner = p.role === 'owner', canEdit = p.role !== 'view';
  const owners = r.members.filter(m => m.role === 'owner').length;
  crumbs([[t('Profile'), '#/'], [p.name]]);
  const modules = [
    ['Geräte', 'Router, Switches, Access Points, Server, VMs, IoT – mit IP, MAC, Standort und Notizen.'],
    ['IPAM', 'Subnetze, VLANs, IP-Adressen, freie Adressen und Konflikte.'],
    ['Topologie', 'Gesamtbaum und Detailansicht mit Switch-Frontplatte und Ports.'],
    ['Netzscan', 'Automatische Erkennung mit Vorschlag, was ein unbekanntes Gerät sein könnte.'],
    ['Integrationen', 'FRITZ!Box, Zyxel (SNMP), ASUS AiMesh, Proxmox, Home Assistant.'],
    ['Ausgabe', 'Tabellen, CSV und PDF mit wählbarem Inhalt.'],
  ];
  app.innerHTML = `<div class="page">
    <div class="row" style="justify-content:space-between;align-items:flex-start">
      <div><h1>${h(p.name)}</h1><p class="sub">${p.description ? h(p.description) : t('Keine Beschreibung')}</p></div>
      <div class="row"><span class="badge ${p.role}">${t(ROLE[p.role])}</span>
        ${canEdit ? `<button class="sm" data-edit>${t('Bearbeiten')}</button>` : ''}
        ${isOwner ? `<button class="sm danger" data-del>${t('Löschen')}</button>` : ''}</div>
    </div>
    <h2>${t('Module')}</h2>
    <div class="modules">${modules.map(([n, d]) => `<div class="module"><b>${t(n)}</b>${t(d)}</div>`).join('')}</div>
    <p class="muted" style="margin-top:10px">${t('Diese Module werden gerade gebaut und erscheinen mit den nächsten Versionen.')}</p>
    <h2>${t('Mitglieder')}</h2>
    <div class="table-wrap"><table><thead><tr><th>${t('E-Mail-Adresse')}</th><th>${t('Rolle')}</th><th></th></tr></thead><tbody>
      ${r.members.map(m => `<tr data-uid="${m.user_id}"><td>${h(m.email)}${m.user_id === STATE.user.id ? ` <span class="muted">(${t('du')})</span>` : ''}</td>
        <td>${isOwner ? `<select data-role style="max-width:160px">${Object.keys(ROLE).map(k => `<option value="${k}" ${k === m.role ? 'selected' : ''}>${t(ROLE[k])}</option>`).join('')}</select>` : `<span class="badge ${m.role}">${t(ROLE[m.role])}</span>`}</td>
        <td class="act">${isOwner && m.user_id !== STATE.user.id ? `<button class="sm danger" data-rm>${t('Entfernen')}</button>` : ''}${m.user_id === STATE.user.id && p.member && !(m.role === 'owner' && owners === 1) ? `<button class="sm" data-leave>${t('Verlassen')}</button>` : ''}</td></tr>`).join('')}
    </tbody></table></div>
    ${isOwner ? `<form class="row" id="share" style="margin-top:12px"><input name="email" type="email" required placeholder="${t('E-Mail-Adresse eines vorhandenen Kontos')}" style="flex:1;min-width:220px">
      <select name="role" style="width:auto">${['view', 'edit', 'owner'].map(k => `<option value="${k}">${t(ROLE[k])}</option>`).join('')}</select>
      <button class="pri">${t('Teilen')}</button></form>
      <p class="muted">${t('Lesen: nur ansehen. Bearbeiten: Geräte und Netz ändern. Besitzer: zusätzlich teilen und löschen.')}</p>` : ''}
  </div>`;
  const reload = () => viewProfile(pid);
  const ed = $('[data-edit]', app);
  if (ed) ed.onclick = async () => { if (await profileDialog(t('Profil bearbeiten'), p, t('Speichern'), v => api('PUT', `/api/profiles/${pid}`, v))) reload(); };
  const del = $('[data-del]', app);
  if (del) del.onclick = async () => {
    if (!await confirmDlg(t('Profil löschen'), t('Profil „{n}“ mit allen Daten endgültig löschen?', { n: h(p.name) }), t('Löschen'))) return;
    await api('DELETE', `/api/profiles/${pid}`); toast(t('Profil gelöscht')); location.hash = '#/';
  };
  $$('[data-role]', app).forEach(s => s.onchange = async () => {
    try { await api('PUT', `/api/profiles/${pid}/members/${s.closest('tr').dataset.uid}`, { role: s.value }); toast(t('gespeichert')); } catch (e) { toast(e.message, true); }
    reload();
  });
  $$('[data-rm]', app).forEach(b => b.onclick = async () => {
    try { await api('DELETE', `/api/profiles/${pid}/members/${b.closest('tr').dataset.uid}`); reload(); } catch (e) { toast(e.message, true); }
  });
  const lv = $('[data-leave]', app);
  if (lv) lv.onclick = async () => {
    if (!await confirmDlg(t('Profil verlassen'), t('Du verlierst den Zugriff auf „{n}“, bis dich ein Besitzer wieder einlädt.', { n: h(p.name) }), t('Verlassen'))) return;
    try { await api('DELETE', `/api/profiles/${pid}/members/${STATE.user.id}`); location.hash = '#/'; } catch (e) { toast(e.message, true); }
  };
  const sh = $('#share', app);
  if (sh) sh.onsubmit = async ev => {
    ev.preventDefault();
    try { await api('POST', `/api/profiles/${pid}/members`, fd(ev.target)); toast(t('Profil geteilt')); reload(); } catch (e) { toast(e.message, true); }
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
    </form>` : ''}
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
}

/* ---------------------------------------------------------------- Start */
(async () => {
  try { STATE = { ...STATE, ...await (await fetch('/api/state')).json() }; } catch { }
  if (STATE.user?.lang && STATE.user.lang !== LANG) { LANG = STATE.user.lang; try { localStorage.setItem('dk_lang', LANG); } catch { } }
  route();
})();
