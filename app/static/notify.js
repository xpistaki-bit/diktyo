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

/* Prometheus / Grafana: Endpunkt mit Token je Profil, Beispiel für prometheus.yml, Grafana-Dashboard zum Importieren */
async function promPanel(ctx, el) {
  const P = `/api/profiles/${ctx.pid}/prometheus`;
  let r;
  try { r = await api('GET', `${P}/settings`); } catch (e) { el.innerHTML = `<p class="errtxt">${h(e.message)}</p>`; return; }
  const url = new URL(P, location.origin);
  const yml = (tok) => `scrape_configs:
  - job_name: diktyo
    scrape_interval: 60s
    scheme: ${url.protocol.replace(':', '')}
    metrics_path: ${url.pathname}
    authorization:
      type: Bearer
      credentials: ${tok || '<TOKEN>'}
    static_configs:
      - targets: ['${url.host}']`;
  const draw = (tok = '') => {
    el.innerHTML = `<div class="panel"><h3>${t('Prometheus / Grafana')}</h3>
      <p class="muted small" style="margin-top:0">${t('Stellt die Messwerte dieses Profils für Prometheus bereit – Geräte online/offline, Antwortzeit, Verfügbarkeit, WAN, Switch-Ports, DNS, Speedtest, Integrationen, Firmware, Wachliste. Grafana zeigt sie dann mit dem fertigen Dashboard an.')}</p>
      <p>${r.enabled ? `<span class="badge ok">${t('eingeschaltet')}</span> <span class="muted small">${t('Token seit {d}', { d: h(fmtDate(r.created)) })}${r.last_scrape ? ' · ' + t('zuletzt abgefragt {d}', { d: h(ago(r.last_scrape)) }) : ' · ' + t('noch nicht abgefragt')}</span>`
        : `<span class="badge">${t('aus')}</span> <span class="muted small">${t('Zum Einschalten ein Token erzeugen.')}</span>`}</p>
      <label>${t('Adresse für Prometheus')}</label><div class="row"><input readonly value="${h(url.href)}" class="mono"><button type="button" class="sm" data-copyurl>${t('Kopieren')}</button></div>
      ${tok ? `<div class="prom-tok"><b>${t('Neues Token – wird nur jetzt angezeigt:')}</b><div class="secret">${h(tok)}</div></div>` : ''}
      <label>${t('Eintrag für prometheus.yml')}</label><textarea readonly rows="11" class="mono small prom-yml">${h(yml(tok))}</textarea>
      <div class="row" style="margin-top:6px"><button type="button" class="sm" data-copyyml>${t('Kopieren')}</button>
        <a class="btn sm" href="${P}/grafana.json" download>${t('Grafana-Dashboard herunterladen')}</a></div>
      <p class="muted small">${t('In Grafana: Prometheus als Datenquelle anlegen, dann Dashboards → Neu → Importieren und die Datei hochladen. Prometheus muss díktyo über diese Adresse erreichen können.')}</p>
      ${ctx.isOwner ? `<div class="row" style="margin-top:10px"><button type="button" class="${r.enabled ? '' : 'pri'} sm" data-promtok>${r.enabled ? t('Neues Token (altes wird ungültig)') : t('Token erzeugen')}</button>
        ${r.enabled ? `<button type="button" class="sm danger" data-promoff>${t('Ausschalten')}</button>` : ''}</div>` : `<p class="muted small">${t('Token erzeugen kann nur, wer das Profil besitzt.')}</p>`}</div>`;
    const copy = text => navigator.clipboard?.writeText(text).then(() => toast(t('kopiert')), () => toast(t('Kopieren nicht möglich – bitte markieren'), true));
    $('[data-copyurl]', el).onclick = () => copy(url.href);
    $('[data-copyyml]', el).onclick = () => copy(yml(tok));
    const nt = $('[data-promtok]', el);
    if (nt) nt.onclick = async () => {
      if (r.enabled && !await confirmDlg(t('Neues Token'), t('Ein neues Token erzeugen? Das bisherige funktioniert dann nicht mehr – in prometheus.yml ersetzen.'), t('Erzeugen'))) return;
      try { const x = await api('POST', `${P}/token`); r = x; draw(x.token); } catch (e) { toast(e.message, true); }
    };
    const off = $('[data-promoff]', el);
    if (off) off.onclick = async () => {
      if (!await confirmDlg(t('Prometheus ausschalten'), t('Token löschen? Prometheus bekommt dann keine Messwerte mehr.'), t('Ausschalten'))) return;
      try { r = await api('DELETE', `${P}/token`); draw(); } catch (e) { toast(e.message, true); }
    };
  };
  draw();
}
