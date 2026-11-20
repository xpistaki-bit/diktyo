'use strict';
/* Eigenes Konto: zweiter Faktor (Authenticator-App) und angemeldete Sitzungen. */

function recoveryDialog(codes) {
  const text = codes.join('\n');
  return dialog(t('Wiederherstellungscodes'), `<p>${t('Jeder Code ersetzt einmal den Code aus der App – z. B. wenn das Handy verloren ist. Sicher aufbewahren (Passwort-Manager oder ausgedruckt). Sie werden nur jetzt angezeigt.')}</p>
    <div class="secret recovery">${codes.map(c => `<span>${h(c)}</span>`).join('')}</div>
    <div class="row" style="margin-top:8px"><button type="button" class="sm" data-copy>${t('Kopieren')}</button>
      <a class="btn sm" download="diktyo-wiederherstellungscodes.txt" href="data:text/plain;charset=utf-8,${encodeURIComponent(`díktyo – ${t('Wiederherstellungscodes')} (${STATE.user.email})\n\n${text}\n`)}">${t('Als Datei')}</a></div>`, {
    ok: null, onOpen: f => { $('[data-copy]', f).onclick = () => navigator.clipboard?.writeText(text).then(() => toast(t('kopiert'))); },
  });
}

async function accountSecurity(el) {
  let s, ss;
  try { [s, ss] = await Promise.all([api('GET', '/api/auth/2fa'), api('GET', '/api/auth/sessions')]); } catch (e) { el.innerHTML = `<p class="errtxt">${h(e.message)}</p>`; return; }
  const ua = x => {
    const b = /Firefox\/[\d.]+/.exec(x) || /Edg\/[\d.]+/.exec(x) || /Chrome\/[\d.]+/.exec(x) || /Version\/[\d.]+.*Safari/.exec(x);
    const os = /Windows|Android|iPhone|iPad|Mac OS X|Linux/.exec(x);
    return [b ? b[0].split('/')[0].replace('Version', 'Safari').replace('Edg', 'Edge') : '', os ? os[0].replace('Mac OS X', 'macOS') : ''].filter(Boolean).join(' · ') || x.slice(0, 40) || '–';
  };
  const when = sec => fmtDate(new Date(sec * 1000).toISOString());
  el.innerHTML = `<div class="panel"><h3>${t('Zweiter Faktor (Authenticator-App)')}</h3>
      ${s.enabled ? `<p><span class="badge ok">${t('eingeschaltet')}</span> ${t('Bei der Anmeldung fragt díktyo nach dem Passwort zusätzlich einen Code aus der App.')}
          <span class="muted">${t('{n} Wiederherstellungscodes übrig', { n: s.recovery_left })}</span></p>
        <div class="row"><button class="sm" data-rc>${t('Neue Wiederherstellungscodes')}</button><button class="sm danger" data-off>${t('Ausschalten')}</button></div>`
      : `<p class="muted">${t('Schützt díktyo zusätzlich mit einem Code aus einer Authenticator-App (z. B. Aegis, 2FAS, Google Authenticator, Bitwarden). Empfohlen, denn díktyo speichert Zugangsdaten für Router, Switches und Server.')}</p>
        <button class="pri" data-on>${t('Einrichten')}</button>`}</div>
    <div class="panel" style="margin-top:14px"><div class="row between"><h3 style="margin:0">${t('Angemeldete Sitzungen')}</h3>
        ${ss.sessions.length > 1 ? `<button class="sm" data-others>${t('Alle anderen abmelden')}</button>` : ''}</div>
      <div class="table-wrap" style="margin-top:8px"><table class="compact"><thead><tr><th>${t('Browser')}</th><th>${t('Adresse')}</th><th>${t('Angemeldet')}</th><th>${t('Zuletzt aktiv')}</th><th></th></tr></thead><tbody>
        ${ss.sessions.map(x => `<tr data-sid="${h(x.id)}"><td>${h(ua(x.user_agent))}${x.current ? ` <span class="badge ok">${t('diese Sitzung')}</span>` : ''}</td>
          <td class="mono small">${h(x.ip || '–')}</td><td class="mono small">${h(when(x.created))}</td><td class="mono small">${h(when(x.last_seen))}</td>
          <td class="act">${x.current ? '' : `<button class="sm" data-kill>${t('Abmelden')}</button>`}</td></tr>`).join('')}</tbody></table></div></div>`;

  const pwField = `<label>${t('Passwort')}</label><input name="password" type="password" autocomplete="current-password" required>`;
  const on = $('[data-on]', el);
  if (on) on.onclick = async () => {
    const setup = await dialog(t('Zweiten Faktor einrichten'), `<p>${t('Zur Sicherheit zuerst das Passwort.')}</p>${pwField}`, {
      ok: t('Weiter'), onOk: f => api('POST', '/api/auth/2fa/setup', fd(f)),
    });
    if (!setup) return;
    const codes = await dialog(t('Zweiten Faktor einrichten'), `<div class="totp-setup"><div class="qr">${setup.qr}</div>
      <div><p style="margin-top:0">${t('1. QR-Code mit der Authenticator-App scannen – oder den Schlüssel von Hand eingeben.')}</p>
        <label>${t('Schlüssel')}</label><div class="secret">${h(setup.secret)}</div>
        <p>${t('2. Den 6-stelligen Code aus der App eingeben.')}</p>
        <label>${t('Code aus der App')}</label><input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" required pattern="[0-9 ]{6,8}"></div></div>`, {
      ok: t('Einschalten'), wide: true, onOk: async f => (await api('POST', '/api/auth/2fa/enable', fd(f))).recovery,
    });
    if (!codes) return;
    STATE.user.totp = true;
    toast(t('Zweiter Faktor eingeschaltet'));
    await recoveryDialog(codes);
    accountSecurity(el);
  };
  const rc = $('[data-rc]', el);
  if (rc) rc.onclick = async () => {
    const codes = await dialog(t('Neue Wiederherstellungscodes'), `<p>${t('Die bisherigen Codes werden dabei ungültig.')}</p>${pwField}`, {
      ok: t('Erzeugen'), onOk: async f => (await api('POST', '/api/auth/2fa/recovery', fd(f))).recovery,
    });
    if (codes) { await recoveryDialog(codes); accountSecurity(el); }
  };
  const off = $('[data-off]', el);
  if (off) off.onclick = async () => {
    const ok = await dialog(t('Zweiten Faktor ausschalten'), `<p>${t('Danach reicht wieder das Passwort zur Anmeldung.')}</p>${pwField}
      <label>${t('Code aus der App oder Wiederherstellungscode')}</label><input name="code" autocomplete="one-time-code" required>`, {
      ok: t('Ausschalten'), danger: true, onOk: f => api('POST', '/api/auth/2fa/disable', fd(f)),
    });
    if (ok) { STATE.user.totp = false; toast(t('Zweiter Faktor ausgeschaltet')); accountSecurity(el); }
  };
  $$('[data-kill]', el).forEach(b => b.onclick = async () => {
    try { await api('DELETE', `/api/auth/sessions/${b.closest('tr').dataset.sid}`); accountSecurity(el); } catch (e) { toast(e.message, true); }
  });
  const others = $('[data-others]', el);
  if (others) others.onclick = async () => {
    try { const r = await api('DELETE', '/api/auth/sessions/others'); toast(t('{n} Sitzungen abgemeldet', { n: r.removed })); accountSecurity(el); } catch (e) { toast(e.message, true); }
  };
}

/* Anmeldung, zweiter Schritt */
function viewTotp(ticket) {
  authFrame(t('Code aus der Authenticator-App'), t('Für dieses Konto ist der zweite Faktor eingeschaltet.'),
    `<form id="f"><label>${t('6-stelliger Code')}</label><input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="20" required>
      <p class="hint">${t('Kein Zugriff auf die App? Einen Wiederherstellungscode (xxxx-xxxx-xxxx) eingeben.')}</p>
      <div class="actions"><a href="#/" data-back>${t('Zurück')}</a><button class="pri">${t('Anmelden')}</button></div></form>`);
  $('[data-back]').onclick = ev => { ev.preventDefault(); viewLogin('login'); };
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    try {
      const r = await api('POST', '/api/auth/login/totp', { ticket, code: fd(ev.target).code });
      if (r.recovery_used) toast(t('Wiederherstellungscode verbraucht – noch {n} übrig. Unter Einstellungen lassen sich neue erzeugen.', { n: r.recovery_left }));
      afterAuth(r.user);
    } catch (e) {
      toast(e.message, true);
      if (/abgelaufen|expired|Passwort/.test(e.message)) viewLogin('login');
      else { const i = $('input[name=code]'); i.value = ''; i.focus(); }
    }
  };
  $('input[name=code]').focus();
}
