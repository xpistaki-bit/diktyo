'use strict';
/* Benachrichtigungen je Profil: E-Mail und ntfy, welche Ereignisse, Testnachricht. */

const NOTIFY_KIND = {
  device_offline: 'Gerät offline', device_online: 'Gerät wieder online', new_device: 'Neues Gerät', quarantined: 'Quarantäne',
  firmware_update: 'Firmware-Update', action_undo_failed: 'Zurückschalten fehlgeschlagen', schedule_failed: 'Zeitplan fehlgeschlagen',
  speed_slow: 'Internet langsam', backup_failed: 'Konfigurations-Backup fehlgeschlagen', integration_failed: 'Integration gestört',
  watch_change: 'Wachliste: Ausfall oder Änderung',
};

async function notifySettings(ctx, el) {
  const P = `/api/profiles/${ctx.pid}/notify`;
  let r;
  try { r = await api('GET', P); } catch (e) { el.innerHTML = `<p class="errtxt">${h(e.message)}</p>`; return; }
  const s = r.settings, dis = ctx.canEdit ? '' : 'disabled';
  el.innerHTML = `<form class="panel" id="notifyform"><h3>${t('Benachrichtigungen')}</h3>
    <p class="muted small" style="margin-top:0">${t('Meldet Ereignisse dieses Profils per E-Mail oder ntfy (Push aufs Handy) – zusätzlich zu Home Assistant. Mehrere Ereignisse werden höchstens einmal pro Minute zu einer Nachricht gebündelt.')}</p>
    ${r.last_error ? `<p class="errtxt small">${t('Letzter Versand')}: ${h(r.last_error)}</p>` : r.last_sent ? `<p class="muted small">${t('Zuletzt verschickt {d}', { d: h(fmtDate(new Date(r.last_sent * 1000).toISOString())) })}</p>` : ''}
    <div class="grid2">
      <div><label class="chk"><input type="checkbox" name="email" ${s.email ? 'checked' : ''} ${dis}> <b>${t('E-Mail')}</b></label>
        <label>${t('Empfänger (leer = Besitzer des Profils)')}</label><input name="email_to" value="${h(s.email_to)}" placeholder="ich@example.com, du@example.com" ${dis}>
        ${r.mail_enabled ? '' : `<small class="warnc">${t('E-Mail-Versand ist noch nicht eingerichtet (Einstellungen → E-Mail-Versand, nur Administratoren).')}</small>`}</div>
      <div><label class="chk"><input type="checkbox" name="ntfy" ${s.ntfy ? 'checked' : ''} ${dis}> <b>ntfy</b></label>
        <div class="grid2" style="gap:0 10px"><div><label>${t('Server')}</label><input name="ntfy_url" value="${h(s.ntfy_url)}" placeholder="https://ntfy.sh" ${dis}></div>
          <div><label>${t('Thema (Topic)')}</label><input name="ntfy_topic" value="${h(s.ntfy_topic)}" placeholder="diktyo-${Math.random().toString(36).slice(2, 10)}" ${dis}></div></div>
        <label>${t('Zugangstoken (optional, bei geschütztem Thema)')}</label><input name="ntfy_token" type="password" autocomplete="off" value="${h(s.ntfy_token)}" ${dis}>
        <small class="muted">${t('In der ntfy-App das gleiche Thema abonnieren. Bei ntfy.sh kann jeder ein Thema lesen, der den Namen kennt – einen schwer erratbaren Namen wählen oder einen eigenen ntfy-Server nutzen.')}</small></div>
    </div>
    <label>${t('Melden bei')}</label>
    <div class="kinds">${r.kinds.map(k => `<label class="chk"><input type="checkbox" name="k_${k}" ${s.kinds.includes(k) ? 'checked' : ''} ${dis}> ${t(NOTIFY_KIND[k] || k)}</label>`).join('')}</div>
    <label class="chk"><input type="checkbox" name="only_infra_offline" ${s.only_infra_offline ? 'checked' : ''} ${dis}> ${t('offline/online nur für Infrastruktur (Router, Switches, Access Points, Server, NAS)')}</label>
    <div class="grid2"><div><label>${t('Sprache der Nachrichten')}</label><select name="lang" ${dis}><option value="de" ${s.lang === 'de' ? 'selected' : ''}>Deutsch</option><option value="en" ${s.lang === 'en' ? 'selected' : ''}>English</option></select></div></div>
    ${ctx.canEdit ? `<div class="row" style="margin-top:14px"><button class="pri">${t('Speichern')}</button><button type="button" data-ntest>${t('Testnachricht senden')}</button><span class="small" id="ntestres"></span></div>` : ''}
  </form>`;
  const f = $('#notifyform', el);
  const collect = () => {
    const v = fd(f);
    return { email: !!v.email, ntfy: !!v.ntfy, email_to: v.email_to, ntfy_url: v.ntfy_url, ntfy_topic: v.ntfy_topic, ntfy_token: v.ntfy_token, lang: v.lang,
      only_infra_offline: !!v.only_infra_offline, kinds: r.kinds.filter(k => v[`k_${k}`]) };
  };
  f.onsubmit = async ev => {
    ev.preventDefault();
    try { await api('PUT', P, collect()); toast(t('gespeichert')); notifySettings(ctx, el); } catch (e) { toast(e.message, true); }
  };
  const tb = $('[data-ntest]', f);
  if (tb) tb.onclick = async () => {
    const v = collect();
    if (!v.email && !v.ntfy) return toast(t('Bitte E-Mail oder ntfy einschalten'), true);
    tb.disabled = true; $('#ntestres', f).textContent = t('sende …'); $('#ntestres', f).className = 'small muted';
    try {
      const res = await api('POST', `${P}/test`, v);
      const parts = Object.entries(res).map(([k, x]) => `${k === 'email' ? t('E-Mail') : 'ntfy'}: ${x === 'ok' ? '✓' : '✗ ' + x}`);
      $('#ntestres', f).textContent = parts.join(' · ');
      $('#ntestres', f).className = Object.values(res).every(x => x === 'ok') ? 'small okc' : 'small errtxt';
    } catch (e) { $('#ntestres', f).textContent = '✗ ' + e.message; $('#ntestres', f).className = 'small errtxt'; }
    tb.disabled = false;
  };
}
