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

/* Anmeldung über OIDC: im eigenen Konto verknüpfen/lösen */
async function oidcAccount(el) {
  let r;
  try { r = await api('GET', '/api/auth/oidc/me'); } catch { return; }
  if (!r.enabled) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="panel" style="margin-top:14px"><h3>${t('Anmeldung über {n}', { n: h(r.label) })}</h3>
    ${r.linked ? `<p><span class="badge ok">${t('verknüpft')}</span> ${t('Du kannst dich mit deinem Konto bei {n} anmelden.', { n: h(r.label) })}</p>
      <button class="sm danger" data-unlink>${t('Verknüpfung lösen')}</button>`
      : `<p class="muted">${t('Verknüpft dein díktyo-Konto mit deinem Konto bei {n} – auch wenn die E-Mail-Adressen verschieden sind.', { n: h(r.label) })}</p>
      <a class="btn pri sm" href="/api/auth/oidc/start?link=1">${t('Mit {n} verknüpfen', { n: h(r.label) })}</a>`}</div>`;
  const ul = $('[data-unlink]', el);
  if (ul) ul.onclick = async () => {
    if (!await confirmDlg(t('Verknüpfung lösen'), t('Danach meldest du dich wieder mit E-Mail-Adresse und Passwort an.'), t('Lösen'))) return;
    try { await api('DELETE', '/api/auth/oidc/link'); oidcAccount(el); } catch (e) { toast(e.message, true); }
  };
}

/* Administratoren: OIDC-Anbieter einrichten (Authentik, Keycloak, Logto …) */
async function oidcSettings(el) {
  let s;
  try { s = await api('GET', '/api/settings/oidc'); } catch (e) { el.innerHTML = `<p class="errtxt">${h(e.message)}</p>`; return; }
  const chk = (k, label, hint = '') => `<label class="chk"><input type="checkbox" name="${k}" ${s[k] ? 'checked' : ''}> ${label}</label>${hint ? `<p class="muted small" style="margin:0 0 6px 26px">${hint}</p>` : ''}`;
  el.innerHTML = `<form class="panel" id="oidcf">
    <p class="muted" style="margin-top:0">${t('Anmeldung über einen eigenen Identity Provider per OpenID Connect – z. B. Authentik, Keycloak, Logto, Zitadel oder Authelia. Die Anmeldung mit Passwort bleibt daneben möglich. Den zweiten Faktor übernimmt dann der Anbieter.')}</p>
    ${chk('enabled', `<b>${t('Eingeschaltet')}</b>`)}
    <label>${t('Redirect-URI – beim Anbieter eintragen')}</label>
    <div class="row"><input readonly class="mono" value="${h(s.redirect_uri)}"><button type="button" class="sm" data-copyru>${t('Kopieren')}</button></div>
    ${s.app_url_set ? '' : `<p class="warnc small">${t('Hinter einem Reverse-Proxy oder mit HTTPS bitte unter „E-Mail-Versand“ die Adresse der Weboberfläche eintragen – sonst stimmt die Redirect-URI nicht.')}</p>`}
    <div class="grid2">
      <div><label>${t('Name auf dem Anmeldeknopf')}</label><input name="label" maxlength="40" value="${h(s.label)}" placeholder="Authentik"></div>
      <div><label>${t('Scopes')}</label><input name="scopes" value="${h(s.scopes)}"></div>
    </div>
    <label>${t('Aussteller (Issuer-URL)')}</label><input name="issuer" class="mono" value="${h(s.issuer)}" placeholder="https://auth.example.com/application/o/diktyo/">
    <div class="grid2">
      <div><label>${t('Client-ID')}</label><input name="client_id" class="mono" autocomplete="off" value="${h(s.client_id)}"></div>
      <div><label>${t('Client-Secret')}</label><input name="client_secret" type="password" autocomplete="new-password" value="${h(s.client_secret)}" placeholder="${h(t('leer bei öffentlichem Client (nur PKCE)'))}"></div>
    </div>
    <h4>${t('Konten')}</h4>
    ${chk('auto_create', t('Konten automatisch anlegen'), t('Wer sich beim Anbieter anmelden darf, bekommt ein díktyo-Konto (ohne Profile, bis jemand sie teilt). Aus: nur bestehende Konten.'))}
    ${chk('trust_email', t('E-Mail-Adresse auch ohne Bestätigung vertrauen'), t('Bestehende Konten werden über die E-Mail-Adresse verknüpft, wenn der Anbieter sie als bestätigt meldet. Nur einschalten, wenn bei deinem Anbieter niemand eine fremde Adresse eintragen kann.'))}
    <div class="grid2">
      <div><label>${t('Nur Mitglieder der Gruppe (optional)')}</label><input name="require_group" value="${h(s.require_group)}" placeholder="diktyo"></div>
      <div><label>${t('Administratoren: Gruppe (optional)')}</label><input name="admin_group" value="${h(s.admin_group)}" placeholder="diktyo-admins"></div>
      <div><label>${t('Gruppen stehen im Claim')}</label><input name="groups_claim" value="${h(s.groups_claim)}" placeholder="groups"></div>
      <div style="align-self:end">${chk('verify_tls', t('TLS-Zertifikat des Anbieters prüfen'))}</div>
    </div>
    <details class="oidc-help"><summary>${t('Hinweise für Authentik, Keycloak und Logto')}</summary>
      <p><b>Authentik:</b> ${t('Anwendung mit Provider „OAuth2/OpenID“ anlegen (vertraulich), Redirect-URI eintragen. Issuer: https://<host>/application/o/<slug>/ – Gruppen kommen im Claim „groups“.')}</p>
      <p><b>Keycloak:</b> ${t('Client „OpenID Connect“, Client authentication an, Standard-Flow, Redirect-URI eintragen. Issuer: https://<host>/realms/<realm>. Für Gruppen einen Mapper „Group Membership“ (Claim „groups“, ohne vollen Pfad) zum Client hinzufügen.')}</p>
      <p><b>Logto:</b> ${t('Anwendung „Traditional Web“, Redirect-URI eintragen. Issuer: https://<host>/oidc. Für Rollen den Scope „roles“ ergänzen und als Gruppen-Claim „roles“ eintragen.')}</p>
    </details>
    <div class="row" style="margin-top:14px"><button class="pri">${t('Speichern')}</button><button type="button" data-oidctest>${t('Verbindung testen')}</button></div>
    <div id="oidcres"></div></form>`;
  const f = $('#oidcf', el);
  $('[data-copyru]', el).onclick = () => navigator.clipboard?.writeText(s.redirect_uri).then(() => toast(t('kopiert')));
  const body = () => { const v = fd(f); ['enabled', 'auto_create', 'trust_email', 'verify_tls'].forEach(k => v[k] = !!f[k].checked); return v; };
  f.onsubmit = async ev => {
    ev.preventDefault();
    try { s = await api('PUT', '/api/settings/oidc', body()); toast(t('gespeichert')); STATE.oidc = { enabled: s.enabled && !!s.issuer && !!s.client_id, label: s.label || 'SSO' }; }
    catch (e) { toast(e.message, true); }
  };
  $('[data-oidctest]', el).onclick = async () => {
    const res = $('#oidcres', el);
    try {
      await api('PUT', '/api/settings/oidc', body());
      const r = await api('POST', '/api/settings/oidc/test');
      res.innerHTML = `<div class="oidc-res small"><p class="okc">✓ ${t('Anbieter erreichbar, {n} Schlüssel', { n: r.keys })}</p>
        <p>${t('Aussteller')}: <span class="mono">${h(r.issuer)}</span></p><p>${t('Anmeldung')}: <span class="mono">${h(r.authorization_endpoint)}</span></p>
        <p>Token: <span class="mono">${h(r.token_endpoint)}</span></p>${r.algs.length ? `<p>${t('Signatur')}: <span class="mono">${h(r.algs.join(', '))}</span></p>` : ''}
        <p class="muted">${t('Zum vollständigen Test in einem privaten Fenster „Anmelden mit …“ ausprobieren.')}</p></div>`;
    } catch (e) { res.innerHTML = `<p class="errtxt">${h(e.message)}</p>`; }
  };
}

/* Updates: neue Version auf GitHub, Update per Knopf (Installation per setup.sh, z. B. Proxmox-LXC), sonst Anleitung */
async function updatePanel(el) {
  let r;
  try { r = await api('GET', '/api/update'); } catch (e) { el.innerHTML = `<p class="errtxt">${h(e.message)}</p>`; return; }
  const draw = () => {
    const c = r.check || {}, st = r.status || {}, busy = ['queued', 'running'].includes(st.state) && Date.now() / 1000 - (st.ts || 0) < 1800;
    const notes = (c.notes || []).map(n => `<li><b class="mono">v${h(n.version)}</b> ${h(n.title)}</li>`).join('');
    el.innerHTML = `<div class="panel upd">
      <div class="upd-head"><div><span class="muted small">${t('Installiert')}</span><b class="mono">v${h(r.installed)}</b></div>
        <div><span class="muted small">${t('Auf GitHub')}</span><b class="mono">${c.latest ? 'v' + h(c.latest) : '–'}</b></div>
        <div class="grow">${c.error ? `<span class="warnc small">${h(ts(c.error))}</span>` : c.available ? `<span class="badge warn">${t('Update verfügbar')}</span>`
          : c.latest ? `<span class="badge ok">${t('aktuell')}</span>` : ''}<br><span class="muted small">${c.checked ? t('geprüft {d}', { d: h(ago(c.checked)) }) : t('noch nicht geprüft')} · ${h(r.repo)} (${h(r.branch)})</span></div>
        <button type="button" class="sm" data-ucheck ${busy ? 'disabled' : ''}>${t('Nach Updates suchen')}</button></div>
      ${notes ? `<h4>${t('Was ist neu')}</h4><ul class="upd-notes">${notes}</ul>` : ''}
      ${r.kind === 'systemd' ? `
        ${busy || st.state ? `<div class="upd-st ${st.state || ''}"><b>${{ queued: t('angefordert'), running: t('läuft'), done: t('fertig'), error: t('Fehler') }[st.state] || ''}</b> ${h(ts(st.message || ''))}</div>` : ''}
        ${r.log?.length && (busy || st.state === 'error') ? `<pre class="upd-log">${h(r.log.join('\n'))}</pre>` : ''}
        ${c.available ? `<p class="muted small">${t('Vor dem Update sichert díktyo die Datenbank (die letzten drei Sicherungen bleiben in /var/lib/diktyo). Während der Installation ist díktyo etwa ein bis drei Minuten nicht erreichbar.')}</p>
          <button type="button" class="pri" data-ustart ${busy ? 'disabled' : ''}>${t('Jetzt auf v{v} aktualisieren', { v: h(c.latest) })}</button>` : ''}`
      : r.kind === 'docker' ? `<p class="muted small">${t('Docker: auf dem Docker-Host im Ordner von díktyo aktualisieren:')}</p><pre class="upd-log">git pull\ndocker compose up -d --build</pre>`
      : `<p class="muted small">${t('Diese Installation hat noch keinen Update-Dienst. Einmal wie bisher auf dem Proxmox-Host aktualisieren – danach geht es hier per Knopf:')}</p>
         <pre class="upd-log">CTID=&lt;ID&gt; bash -c "$(curl -fsSL https://raw.githubusercontent.com/${h(r.repo)}/${h(r.branch)}/install/update-proxmox.sh)"</pre>`}</div>`;
    $('[data-ucheck]', el).onclick = async () => { try { r = await api('POST', '/api/update/check'); STATE.update = { available: r.check?.available, latest: r.check?.latest }; drawHeader(); draw(); } catch (e) { toast(e.message, true); } };
    const go = $('[data-ustart]', el);
    if (go) go.onclick = async () => {
      if (!await confirmDlg(t('díktyo aktualisieren'), t('Auf Version {v} aktualisieren? díktyo sichert vorher die Datenbank und ist während der Installation kurz nicht erreichbar.', { v: h(r.check.latest) }), t('Aktualisieren'))) return;
      try { r = await api('POST', '/api/update/start'); draw(); follow(r.check.latest); } catch (e) { toast(e.message, true); }
    };
    if (busy && !updatePanel.following) follow(c.latest);
  };
  // Fortschritt verfolgen: Status und Protokoll; während des Neustarts ist díktyo kurz weg; fertig, wenn die neue Version läuft
  const follow = target => {
    updatePanel.following = true;
    const tick = async () => {
      try {
        const s = await (await fetch('/api/state')).json();
        if (target && s.version === target) { updatePanel.following = false; toast(t('díktyo läuft jetzt in Version {v}', { v: target })); setTimeout(() => location.reload(), 1200); return; }
        try { r = await api('GET', '/api/update'); draw(); } catch { }
        if (r.status?.state === 'error') { updatePanel.following = false; return; }
      } catch {
        const st = $('.upd-st', el); if (st) st.innerHTML = `<b>${t('läuft')}</b> ${t('díktyo startet neu …')}`;
      }
      setTimeout(tick, 2500);
    };
    setTimeout(tick, 2000);
  };
  draw();
}
