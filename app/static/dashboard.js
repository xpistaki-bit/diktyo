'use strict';
/* Übersicht eines Profils: Kennzahlen, was Aufmerksamkeit braucht, Diagramme (WAN, Antwortzeiten, aktivste Ports),
   Infrastruktur und letzte Änderungen. Aktualisiert sich alle 30 Sekunden, solange der Reiter offen ist. */

async function tabOverview(ctx) {
  await meta(ctx.pid);
  const P = `/api/profiles/${ctx.pid}`;
  const since = () => tabOverview.since || 86400;
  ctx.el.innerHTML = `<div id="ov"><p class="muted">${t('lade …')}</p></div>`;
  const render = async () => {
    let r;
    try { r = await api('GET', `${P}/dashboard`); } catch (e) { $('#ov', ctx.el).innerHTML = `<p class="errtxt">${h(e.message)}</p>`; return; }
    const c = r.counts, w = r.wan;
    const tile = (val, label, cls = '', sub = '', href = '') => `<${href ? `a href="${href}"` : 'div'} class="ov-tile ${cls}"><b>${val}</b><span>${label}</span>${sub ? `<small>${sub}</small>` : ''}</${href ? 'a' : 'div'}>`;
    const inet = w ? (w.connected === false ? tile(t('getrennt'), t('Internet'), 'bad') : tile(w.rx_bps != null ? `↓ ${fmtBps(w.rx_bps)}` : t('verbunden'), t('Internet'), 'ok',
      w.tx_bps != null ? `↑ ${fmtBps(w.tx_bps)}` : '')) : '';
    const issues = [
      ...r.offline.map(x => `<li class="bad"><span>●</span><a href="#" data-dev="${x.id}">${h(x.name)}</a> ${t('ist offline')}</li>`),
      ...r.broken.map(x => `<li class="bad"><span>⚠</span><a href="#/p/${ctx.pid}/integrationen">${h(x.name)}</a>: ${h(x.error)}</li>`),
      ...r.failed.map(x => `<li class="bad"><span>⚡</span>${h(t(x.label))}: ${h(x.message || '')}</li>`),
      ...r.firmware.map(x => `<li class="warn"><span>⬆</span><a href="#" data-dev="${x.id}">${h(x.name)}</a>: ${t('Firmware {a} → {b}', { a: h(x.installed || '?'), b: h(x.latest || t('neue Version')) })}</li>`),
      ...(c.inbox ? [`<li class="info"><span>✚</span><a href="#/p/${ctx.pid}/posteingang">${c.inbox === 1 ? t('1 neues Gerät im Posteingang') : t('{n} neue Geräte im Posteingang', { n: c.inbox })}</a></li>`] : []),
      ...(r.speed?.slow ? [`<li class="warn"><span>⇣</span>${t('Internet langsam: zuletzt ↓ {d}, Leitung ↓ {l}', { d: fmtMbit(r.speed.last.down_bps), l: fmtMbit(r.speed.line_down) })}</li>`] : []),
      ...(c.quarantine ? [`<li class="warn"><span>⛔</span><a href="#/p/${ctx.pid}/integrationen">${t('{n} in Quarantäne', { n: c.quarantine })}</a></li>`] : []),
    ];
    const sm = r.summary;
    // Neu aufbauen ohne Flackern: erst abseits fertig zeichnen (auch die Diagramme), dann in einem Schritt austauschen
    const box = document.createElement('div');
    box.innerHTML = `
      <div class="ov-tiles">
        ${tile(`${c.online}<small>/${c.devices}</small>`, t('Geräte online'), c.offline ? 'warn' : 'ok', c.offline ? t('{n} offline', { n: c.offline }) : t('alle erreichbar'), `#/p/${ctx.pid}/geraete`)}
        ${inet}
        ${tile(c.availability != null ? `${c.availability.toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: 1 })} %` : '–', t('Verfügbarkeit Infrastruktur'), c.availability == null ? '' : c.availability >= 99.9 ? 'ok' : c.availability >= 98 ? 'warn' : 'bad', t('letzte 24 Stunden'))}
        ${tile(c.firmware, t('Firmware-Updates'), c.firmware ? 'warn' : 'ok')}
        ${tile(c.inbox, t('im Posteingang'), c.inbox ? 'info' : '', '', `#/p/${ctx.pid}/posteingang`)}
        ${tile(sm.changed + sm.created + sm.deleted, t('Änderungen seit gestern'), '', '', `#/p/${ctx.pid}/verlauf`)}
      </div>
      <div class="ov-grid">
        <div class="panel"><h3>${t('Braucht Aufmerksamkeit')}</h3>${issues.length ? `<ul class="ov-issues">${issues.slice(0, 14).join('')}</ul>` : `<p class="okc">✓ ${t('Alles in Ordnung.')}</p>`}</div>
        <div class="panel"><div class="row between"><h3 style="margin:0">${w ? h(w.name) + ' · ' + t('WAN-Traffic') : t('WAN-Traffic')}</h3>${rangeButtons(since())}</div>
          ${w ? '<div class="chartbox" data-ch="wan"></div>' : `<p class="muted small">${t('Kommt aus der FRITZ!Box-, ASUS-, UniFi-, MikroTik- oder OPNsense-Integration.')}</p>`}</div>
        ${speedPanel(r.speed, ctx.canEdit, ctx.pid)}
        ${r.dns ? `<div class="panel"><div class="row between"><h3 style="margin:0">${h(r.dns.name)}</h3><a class="small" href="#/p/${ctx.pid}/integrationen">${t('Details')} →</a></div>
          <div class="speed-now"><span>${t('Anfragen')} <b class="mono">${fmtInt(r.dns.summary.queries)}</b></span><span>${t('blockiert')} <b class="mono">${fmtInt(r.dns.summary.blocked)}</b></span>
            <span><b class="mono">${(r.dns.summary.pct ?? 0).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE')} %</b></span>
            ${r.dns.info?.blocking === false ? `<span class="warnc">${t('Filter ausgeschaltet')}</span>` : ''}</div>
          <div class="chartbox" data-ch="dns"></div>
          ${r.dns.top.length ? `<p class="small" style="margin:6px 0 2px"><b>${t('Meistblockiert je Gerät')}</b></p>${r.dns.top.map(x => `<div class="small">${x.device_id ? `<a href="#" data-dev="${x.device_id}">${h(x.label)}</a>` : `<span class="mono">${h(x.label)}</span>`}
            <span class="mono muted"> · ${fmtInt(x.blocked)} ${t('von')} ${fmtInt(x.queries)}</span></div>`).join('')}` : ''}</div>` : ''}
        <div class="panel"><h3>${t('Antwortzeiten Infrastruktur')}</h3>${r.rtt.length ? '<div class="chartbox" data-ch="rtt"></div>' : `<p class="muted small">${t('Entsteht mit der Online-Überwachung.')}</p>`}</div>
        <div class="panel"><h3>${t('Aktivste Ports')}</h3>${r.ports.length ? r.ports.map((p, i) => `<div class="small"><b>${h(p.device)}</b> · ${t('Port')} ${h(p.name)} · <span class="mono">↓ ${fmtBps(p.out_bps)} ↑ ${fmtBps(p.in_bps)}</span></div><div class="chartbox" data-ch="port${i}"></div>`).join('')
          : `<p class="muted small">${t('Kommt aus Switch- (SNMP), MikroTik- oder OPNsense-Integrationen.')}</p>`}</div>
        ${r.top_today?.length ? `<div class="panel"><h3>${t('Top-Verbraucher (24 h)')}</h3><div class="table-wrap"><table class="compact"><tbody>${r.top_today.map(x => `<tr>
            <td>${x.device_id ? `<a href="#" data-dev="${x.device_id}">${h(x.name)}</a>` : `<span class="mono small">${h(x.mac)}</span>`}</td>
            <td class="mono small">↓ ${fmtBytes(x.rx)}</td><td class="mono small">↑ ${fmtBytes(x.tx)}</td><td class="mono small"><b>${fmtBytes(x.rx + x.tx)}</b></td></tr>`).join('')}</tbody></table></div>
          <p class="muted small">${t('Aus dem Traffic Analyzer des ASUS-Routers.')}</p></div>` : ''}
        ${r.top_now?.length ? `<div class="panel"><h3>${t('Gerade aktiv')}</h3><div class="table-wrap"><table class="compact"><tbody>${r.top_now.map(x => `<tr>
            <td>${x.device_id ? `<a href="#" data-dev="${x.device_id}">${h(x.name)}</a>` : `<span class="mono small">${h(x.mac)}</span>`}</td>
            <td class="mono small">↓ ${fmtBps(x.down)}</td><td class="mono small">↑ ${fmtBps(x.up)}</td><td class="muted small">${h(x.source)}</td></tr>`).join('')}</tbody></table></div></div>` : ''}
        <div class="panel"><h3>${t('Infrastruktur')}</h3>${r.infra.length ? `<div class="table-wrap"><table class="compact"><tbody>${r.infra.map(x => `<tr>
            <td><span class="dot ${x.online === 1 ? 'on' : x.online === 0 ? 'off' : ''}"></span> <a href="#" data-dev="${x.id}">${h(x.name)}</a>${x.fw_update ? ' <span class="badge fwup">⬆</span>' : ''}</td>
            <td class="mono small">${fmtPct(x.a24)}</td><td class="mono small">${fmtMs(x.rtt)}</td></tr>`).join('')}</tbody></table></div>` : `<p class="muted small">${t('Noch keine Router, Switches oder Access Points bestätigt.')}</p>`}</div>
        <div class="panel"><div class="row between"><h3 style="margin:0">${t('Letzte Änderungen')}</h3><a class="small" href="#/p/${ctx.pid}/verlauf">${t('Verlauf')} →</a></div>
          ${r.recent.length ? histList(r.recent) : `<p class="muted small">${t('Keine Änderungen in den letzten 7 Tagen.')}</p>`}</div>
      </div>
      <p class="muted small" id="ovstamp"></p>`;
    $$('[data-dev]', box).forEach(a => a.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +a.dataset.dev); });
    $$('[data-hdev]', box).forEach(a => a.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +a.dataset.hdev); });
    const charts = () => {
      const s = since();
      return Promise.allSettled([
        w && drawChart($('[data-ch=wan]', box), ctx.pid, w.keys, [t('Download'), t('Upload')], s, { height: 130 }),
        r.dns && drawChart($('[data-ch=dns]', box), ctx.pid, r.dns.keys, [t('Anfragen/min'), t('blockiert/min')], s, { fmt: v => fmtInt(Math.round(v)), height: 100 }),
        r.rtt.length && drawChart($('[data-ch=rtt]', box), ctx.pid, r.rtt.map(x => x.key), r.rtt.map(x => x.name), s, { fmt: fmtMs, height: 130 }),
        ...r.ports.map((p, i) => drawChart($(`[data-ch=port${i}]`, box), ctx.pid, p.keys, [t('empfangen'), t('gesendet')], s, { height: 90 })),
      ]);
    };
    bindSpeedRun(ctx, box, () => render());
    $$('[data-range]', box).forEach(b => b.onclick = () => { tabOverview.since = +b.dataset.range; $$('[data-range]', box).forEach(x => x.classList.toggle('on', x === b)); charts(); });
    await charts();
    const ov = $('#ov', ctx.el);
    if (!ov) return;
    ov.replaceChildren(...box.childNodes);
    $('#ovstamp', ctx.el).textContent = t('Stand {d} · aktualisiert sich alle 30 Sekunden', { d: new Date().toLocaleTimeString(LANG === 'en' ? 'en-GB' : 'de-DE') });
  };
  await render();
  clearInterval(tabOverview.timer);
  tabOverview.timer = setInterval(() => {
    if (!document.body.contains(ctx.el) || !location.hash.match(/\/p\/\d+(\/uebersicht)?$/)) return clearInterval(tabOverview.timer);
    if (!$('#dlg').open) render();
  }, 30000);
}
window.INV.uebersicht = tabOverview;
