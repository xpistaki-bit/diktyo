'use strict';
/* VLAN-Plan: welcher Port in welchem VLAN – Produktiv (Ist, bei SNMP-Switches vom Switch gelesen) und Plan (Soll).
   Port-Ansicht je Gerät mit VLAN-Farben, Mehrfachauswahl zum Zuweisen, Umstellungsliste, Hinweise, VLAN-Matrix.
   díktyo schreibt nichts auf die Switches. */

async function tabVlans(ctx) {
  await meta(ctx.pid);
  const P = `/api/profiles/${ctx.pid}`;
  const ui = tabVlans.ui[ctx.pid] || (tabVlans.ui[ctx.pid] = { mode: 'prod', view: 'ports', sel: new Set() });
  let st = await api('GET', `${P}/vlanplan`);
  if (!st.plan) ui.mode = 'prod';

  const vmap = () => Object.fromEntries(st.vlans.map(v => [v.id, v]));
  const key = () => ui.mode === 'plan' ? 'plan' : 'prod';
  const editable = sw => ctx.canEdit && (ui.mode === 'plan' || !sw.snmp);
  const vlabel = v => `${v.vid}${v.name ? ' · ' + v.name : ''}`;
  const memb = (m, vm) => m ? `${m.u && vm[m.u] ? 'U ' + vm[m.u].vid : 'U –'}${m.t.length ? ' · T ' + m.t.map(x => vm[x]?.vid).join(',') : ''}` : '–';
  const differs = p => p.plan && (p.plan.u !== p.prod.u || p.plan.t.join() !== p.prod.t.join());

  const save = async (method, url, body, msg) => {
    try { st = await api(method, `${P}${url}`, body); if (msg) toast(msg); draw(); return st; } catch (e) { toast(e.message, true); return null; }
  };

  function portTile(sw, p, vm) {
    const m = p[key()] || { u: null, t: [] };
    const u = vm[m.u];
    const stripes = m.t.map(x => vm[x]).filter(Boolean).map(v => `<i style="background:${v.color}" title="tagged ${h(vlabel(v))}"></i>`).join('');
    const peer = p.peers.map(x => x.name).join(', ');
    const tip = `${t('Port')} ${p.name}${peer ? ' → ' + peer : ''}\n${t('Untagged')}: ${u ? vlabel(u) : '–'}\n${t('Tagged')}: ${m.t.map(x => vm[x] ? vlabel(vm[x]) : '').join(', ') || '–'}`
      + (ui.mode === 'plan' && differs(p) ? `\n${t('Produktiv')}: ${memb(p.prod, vm)}` : '');
    return `<button type="button" class="vp-port ${ui.sel.has(p.id) ? 'sel' : ''} ${editable(sw) ? 'ed' : ''} ${ui.mode === 'plan' && differs(p) ? 'chg' : ''} ${m.t.length ? 'trunk' : ''}"
        data-vp="${p.id}" data-sw="${sw.id}" title="${h(tip)}" style="${u ? `--vc:${u.color}` : ''}">
      <span class="vp-no">${h(p.name)}</span><span class="vp-u">${u ? u.vid : '–'}</span><span class="vp-t">${stripes}</span>
      <span class="vp-peer">${h(peer)}</span></button>`;
  }

  function legend(vm) {
    const count = {};
    st.switches.forEach(s => s.ports.forEach(p => { const m = p[key()]; if (!m) return; if (m.u) (count[m.u] = count[m.u] || [0, 0])[0]++; m.t.forEach(x => (count[x] = count[x] || [0, 0])[1]++); }));
    return `<div class="vp-legend">${st.vlans.filter(v => ui.mode === 'plan' || !v.planned).map(v => `<button type="button" class="vp-chip ${v.planned ? 'planned' : ''}" data-vl="${v.id}" style="--vc:${v.color}">
        <i></i><b class="mono">${v.vid}</b><span>${h(v.name || '')}</span>
        <small class="muted">${v.planned ? `<em>${t('geplant')}</em> · ` : ''}${v.subnets.length ? h(v.subnets.join(', ')) : `<span class="vp-nosub">${t('kein Subnetz – zuordnen')}</span>`} · ${count[v.id] ? `${count[v.id][0]} U / ${count[v.id][1]} T` : t('ungenutzt')}</small></button>`).join('')}
      ${ctx.canEdit ? `<button type="button" class="sm" data-addvl>+ ${ui.mode === 'plan' ? t('VLAN (geplant)') : t('VLAN')}</button>` : ''}</div>`;
  }

  function selBar(vm) {
    if (!ui.sel.size) return '';
    const vl = st.vlans.filter(v => ui.mode === 'plan' || !v.planned);
    return `<div class="vp-selbar"><b>${ui.sel.size === 1 ? t('1 Port gewählt') : t('{n} Ports gewählt', { n: ui.sel.size })}</b>
      <label>${t('Untagged')} <select id="vpu"><option value="keep">${t('unverändert')}</option><option value="">${t('kein VLAN')}</option>${vl.map(v => `<option value="${v.id}">${h(vlabel(v))}</option>`).join('')}</select></label>
      <span class="vp-tg">${t('Tagged')}: ${vl.map(v => `<button type="button" class="vp-tri" data-tri="${v.id}" data-s="0" style="--vc:${v.color}" title="${h(t('Klick: hinzufügen → entfernen → unverändert'))}">${v.vid}</button>`).join('')}</span>
      <span class="grow"></span><button type="button" class="pri sm" data-apply>${t('Zuweisen')}</button><button type="button" class="sm" data-clear>${t('Auswahl aufheben')}</button></div>`;
  }

  function changeList(vm) {
    if (ui.mode !== 'plan') return '';
    if (!st.diff.length) return `<div class="panel"><div class="hud-h"><h3>${t('Umstellungsliste')}</h3></div><p class="muted">${t('Plan und produktiver Stand sind gleich – noch nichts umzustellen.')}</p></div>`;
    const snmp = new Set(st.switches.filter(s => s.snmp).map(s => s.id));
    const peers = Object.fromEntries(st.switches.flatMap(s => s.ports.map(p => [p.id, p.peers.map(x => x.name).join(', ')])));
    return `<div class="panel"><div class="hud-h"><h3>${t('Umstellungsliste')}</h3><span class="hint">${t('{n} Ports', { n: st.diff.length })}</span></div>
      <p class="muted small">${t('Das ist am Switch umzustellen. Bei Switches mit SNMP hakt sich ein Port von selbst ab, sobald der Switch den neuen Stand meldet; sonst „umgesetzt“ klicken.')}</p>
      <div class="table-wrap"><table class="compact"><thead><tr><th>${t('Gerät')}</th><th>${t('Port')}</th><th>${t('angeschlossen')}</th><th>${t('Produktiv')}</th><th></th><th>${t('Plan')}</th><th></th></tr></thead><tbody>
      ${st.diff.map(d => `<tr><td>${h(d.device)}</td><td class="mono">${h(d.port)}</td><td>${h(peers[d.interface_id] || '')}</td>
        <td class="mono">${memb(d.prod, vm)}</td><td>→</td><td class="mono"><b>${memb(d.plan, vm)}</b></td>
        <td>${snmp.has(d.device_id) ? `<span class="muted small">${t('wartet auf den Switch')}</span>` : ctx.canEdit ? `<button type="button" class="sm" data-adopt="${d.interface_id}">✓ ${t('umgesetzt')}</button>` : ''}</td></tr>`).join('')}
      </tbody></table></div></div>`;
  }

  function warnings() {
    const w = st.warnings[ui.mode === 'plan' ? 'plan' : 'prod'];
    if (!w.length) return '';
    return `<div class="panel"><div class="hud-h"><h3>${t('Hinweise')}</h3><span class="hint">${w.length}</span></div>
      <ul class="ov-issues">${w.map(x => `<li class="${x.level === 'warn' ? 'warn' : 'info'}"><span class="ic">${x.level === 'warn' ? '⚠' : 'ℹ'}</span><span>${h(x.text)}</span></li>`).join('')}</ul></div>`;
  }

  function matrix(vm) {
    const vl = st.vlans.filter(v => ui.mode === 'plan' || !v.planned);
    const rows = st.switches.flatMap(s => s.ports.filter(p => { const m = p[key()]; return m && (m.u || m.t.length); }).map(p => [s, p]));
    if (!rows.length) return `<p class="muted">${t('Noch keine Ports mit VLAN.')}</p>`;
    return `<div class="table-wrap vp-matrix"><table class="compact"><thead><tr><th>${t('Gerät')}</th><th>${t('Port')}</th><th>${t('angeschlossen')}</th>
      ${vl.map(v => `<th class="vp-mh" style="--vc:${v.color}" title="${h(vlabel(v))}">${v.vid}<small>${h(v.name || '')}</small></th>`).join('')}</tr></thead><tbody>
      ${rows.map(([s, p]) => { const m = p[key()]; return `<tr class="${ui.mode === 'plan' && differs(p) ? 'chg' : ''}"><td>${h(s.name)}</td><td class="mono">${h(p.name)}</td><td>${h(p.peers.map(x => x.name).join(', '))}</td>
        ${vl.map(v => `<td class="vp-mc" style="--vc:${v.color}">${m.u === v.id ? '<b class="u">U</b>' : m.t.includes(v.id) ? '<b class="t">T</b>' : ''}</td>`).join('')}</tr>`; }).join('')}
      </tbody></table></div><p class="muted small">${t('U = untagged (Zugangs-VLAN des Ports), T = tagged (Trunk, z. B. zu Switch, Access Point, Router oder Hypervisor).')}</p>`;
  }

  function swPanel(s, vm) {
    return `<div class="panel vp-sw"><div class="hud-h"><h3>${h(s.name)}<em>${h(typeName(s.type))}</em></h3>
      <span class="row">${s.snmp ? `<span class="badge" title="${h(t('Produktiver Stand kommt per SNMP vom Switch und lässt sich hier nicht ändern.'))}">${t('vom Switch (SNMP)')}</span>` : `<span class="badge">${t('von Hand')}</span>`}
      ${editable(s) && s.ports.length ? `<button type="button" class="sm" data-selall="${s.id}">${t('alle wählen')}</button>` : ''}</span></div>
      ${s.ports.length ? `<div class="vp-ports">${s.ports.map(p => portTile(s, p, vm)).join('')}</div>` : ''}
      ${s.guests?.length ? `<div class="vp-guests"><span class="vp-gh">${t('VMs und Container (Proxmox)')}</span>
        ${s.guests.map(g => { const v = vm[g.vlan_id]; return `<a href="#" class="vp-guest" data-gdev="${g.id}" style="${v ? `--vc:${v.color}` : ''}" title="${h(g.bridge ? 'Bridge ' + g.bridge : '')}">
          <b class="mono">${g.vid ? g.vid : '–'}</b><span>${h(g.name)}</span><small>${g.vid ? (v ? h(v.name || '') : t('VLAN fehlt in díktyo')) : t('ohne Tag (VLAN des Host-Ports)')}</small></a>`; }).join('')}</div>` : ''}</div>`;
  }

  function draw() {
    const vm = vmap();
    const planBar = ui.mode === 'plan' ? (st.plan
      ? `<div class="vp-planbar"><b>${t('PLAN-MODUS')}</b><span>${t('Änderungen betreffen nur den Plan – nicht das Netz.')} ${st.plan.note ? '· ' + h(st.plan.note) : ''}
          · ${st.diff.length ? t('{n} Ports weichen vom produktiven Stand ab', { n: st.diff.length }) : t('keine Abweichung')}</span><span class="grow"></span>
          ${ctx.canEdit ? `<button type="button" class="sm" data-finish>${t('Plan abschließen')}</button><button type="button" class="sm danger" data-discard>${t('Plan verwerfen')}</button>` : ''}</div>` : '') : '';
    const noPlan = ui.mode === 'plan' && !st.plan;
    const anyData = st.switches.some(s => s.ports.some(p => p.prod.u || p.prod.t.length));
    ctx.el.innerHTML = `<div class="vp-top">
        <div class="seg vp-mode"><button type="button" data-mode="prod" class="${ui.mode === 'prod' ? 'on' : ''}">● ${t('Produktiv')}</button>
          <button type="button" data-mode="plan" class="${ui.mode === 'plan' ? 'on plan' : ''}">✎ ${t('Plan')}${st.diff.length ? ` <span class="count">${st.diff.length}</span>` : ''}</button></div>
        <div class="seg"><button type="button" data-view="ports" class="${ui.view === 'ports' ? 'on' : ''}">${t('Ports')}</button><button type="button" data-view="matrix" class="${ui.view === 'matrix' ? 'on' : ''}">${t('Matrix')}</button></div>
        <span class="grow"></span><span class="muted small">${ui.mode === 'prod' ? t('Ist-Stand: bei Switches mit SNMP vom Switch gelesen, sonst von Hand gepflegt.') : ''}</span></div>
      ${planBar}
      ${noPlan ? `<div class="panel vp-start"><div class="hud-h"><h3>${t('VLAN-Umstellung planen')}</h3></div>
          <p>${t('Der Plan startet als Kopie des produktiven Stands. Darin legst du neue VLANs an und ordnest Ports neu zu, ohne dass sich am Netz etwas ändert. díktyo zeigt dann eine Umstellungsliste Port für Port und prüft den Plan (Adressen, Uplinks).')}</p>
          ${!anyData ? `<p class="warnc small">${t('Noch kein produktiver Stand erfasst. Für Switches mit SNMP-Integration liest díktyo ihn bei der nächsten Abfrage, sonst zuerst im Modus „Produktiv“ eintragen (z. B. alle Ports VLAN 1).')}</p>` : ''}
          ${ctx.canEdit ? `<label>${t('Worum geht es? (optional)')}</label><input id="vpnote" maxlength="300" placeholder="${h(t('z. B. IoT und Gäste trennen'))}"><p><button type="button" class="pri" data-start>${t('Plan starten')}</button></p>` : ''}</div>` : `
      ${legend(vm)}
      ${ui.view === 'matrix' ? matrix(vm) : `<div class="vp-switches">${st.switches.filter(s => s.infra).map(s => swPanel(s, vm)).join('') || `<p class="muted">${t('Noch keine Geräte mit Ports (Switch, Router).')}</p>`}</div>
        ${st.switches.some(s => !s.infra) ? `<details class="vp-more" ${ui.more ? 'open' : ''}><summary><b>${t('Endgeräte mit eigenem Netzwerkport ({n})', { n: st.switches.filter(s => !s.infra).length })}</b>
            <span class="muted small">${t('PC, Laptop … – ihr VLAN legt meist der Switch-Port fest. Ist ein Gerät eigentlich ein Server oder Hypervisor, den Typ im Gerätedialog ändern.')}</span></summary>
          <div class="vp-switches">${st.switches.filter(s => !s.infra).map(s => swPanel(s, vm)).join('')}</div></details>` : ''}`}
      ${warnings()}${changeList(vm)}`}
      ${selBar(vm)}`;
    bind();
  }

  function bind() {
    const el = ctx.el;
    $$('[data-mode]', el).forEach(b => b.onclick = () => { ui.mode = b.dataset.mode; ui.sel.clear(); draw(); });
    $$('[data-view]', el).forEach(b => b.onclick = () => { ui.view = b.dataset.view; draw(); });
    $$('[data-gdev]', el).forEach(a => a.onclick = ev => { ev.preventDefault(); deviceDialog(ctx, +a.dataset.gdev); });
    const more = $('.vp-more', el);
    if (more) more.ontoggle = () => { ui.more = more.open; };
    const sb = $('[data-start]', el);
    if (sb) sb.onclick = async () => { if (await save('POST', '/vlanplan/plan', { note: $('#vpnote', el).value }, t('Plan angelegt'))) { ui.mode = 'plan'; draw(); } };
    const fin = $('[data-finish]', el);
    if (fin) fin.onclick = async () => {
      const snmpOpen = st.diff.filter(d => st.switches.find(s => s.id === d.device_id)?.snmp).length;
      const txt = t('Plan abschließen: Bei von Hand gepflegten Geräten wird der Plan zum produktiven Stand, geplante VLANs werden normale VLANs.')
        + (snmpOpen ? ' ' + t('{n} Ports an SNMP-Switches sind laut Switch noch nicht umgestellt – sie fallen aus dem Plan heraus.', { n: snmpOpen }) : '');
      if (!await confirmDlg(t('Plan abschließen'), h(txt), t('Abschließen'))) return;
      if (await save('POST', '/vlanplan/plan/finish', null, t('Plan abgeschlossen'))) { ui.mode = 'prod'; draw(); }
    };
    const dis = $('[data-discard]', el);
    if (dis) dis.onclick = async () => {
      if (!await confirmDlg(t('Plan verwerfen'), t('Plan verwerfen? Alle geplanten Zuordnungen und nur geplanten VLANs werden gelöscht. Der produktive Stand bleibt.'), t('Verwerfen'))) return;
      if (await save('DELETE', '/vlanplan/plan', null, t('Plan verworfen'))) { ui.mode = 'prod'; draw(); }
    };
    $$('.vp-port.ed', el).forEach(b => b.onclick = ev => {
      const id = +b.dataset.vp;
      if (ev.shiftKey && tabVlans.last && tabVlans.last.sw === b.dataset.sw) {  // Bereich wählen
        const all = $$(`.vp-port.ed[data-sw="${b.dataset.sw}"]`, el).map(x => +x.dataset.vp);
        const [a, z] = [all.indexOf(tabVlans.last.id), all.indexOf(id)].sort((x, y) => x - y);
        all.slice(a, z + 1).forEach(x => ui.sel.add(x));
      } else ui.sel.has(id) ? ui.sel.delete(id) : ui.sel.add(id);
      tabVlans.last = { id, sw: b.dataset.sw };
      draw();
    });
    $$('[data-selall]', el).forEach(b => b.onclick = () => {
      const ids = st.switches.find(s => s.id === +b.dataset.selall).ports.map(p => p.id);
      const allSel = ids.every(x => ui.sel.has(x));
      ids.forEach(x => allSel ? ui.sel.delete(x) : ui.sel.add(x)); draw();
    });
    $$('[data-tri]', el).forEach(b => b.onclick = () => {
      const s = (+b.dataset.s + 1) % 3; b.dataset.s = s;
      b.classList.toggle('add', s === 1); b.classList.toggle('rem', s === 2);
      b.textContent = (s === 1 ? '+' : s === 2 ? '−' : '') + st.vlans.find(v => v.id === +b.dataset.tri).vid;
    });
    const ap = $('[data-apply]', el);
    if (ap) ap.onclick = async () => {
      const tagged = {};
      $$('[data-tri]', el).forEach(b => { if (b.dataset.s === '1') tagged[b.dataset.tri] = true; if (b.dataset.s === '2') tagged[b.dataset.tri] = false; });
      const u = $('#vpu', el).value;
      if (u === 'keep' && !Object.keys(tagged).length) return toast(t('Nichts gewählt: Untagged-VLAN oder Tagged-VLANs angeben'), true);
      if (await save('PUT', '/vlanplan/ports', { mode: ui.mode, ports: [...ui.sel], untagged: u === 'keep' ? 'keep' : (u ? +u : null), tagged }, t('zugewiesen'))) { ui.sel.clear(); draw(); }
    };
    const cl = $('[data-clear]', el);
    if (cl) cl.onclick = () => { ui.sel.clear(); draw(); };
    $$('[data-adopt]', el).forEach(b => b.onclick = () => save('POST', `/vlanplan/plan/adopt/${b.dataset.adopt}`, null, t('übernommen')));
    $$('[data-vl]', el).forEach(b => b.onclick = () => ctx.canEdit && vlanEdit(st.vlans.find(v => v.id === +b.dataset.vl)));
    const av = $('[data-addvl]', el);
    if (av) av.onclick = () => vlanEdit({ planned: ui.mode === 'plan' });
  }

  async function vlanEdit(v) {
    const isNew = !v.id;
    let subnets = [];
    try { subnets = (await api('GET', `${P}/subnets`)).subnets; } catch { }
    const vids = Object.fromEntries(st.vlans.map(x => [x.id, x.vid]));
    const ok = await dialog(isNew ? (v.planned ? t('Neues VLAN (geplant)') : t('Neues VLAN')) : `VLAN ${v.vid}`, `
      <div class="grid2"><div><label>${t('VLAN-ID')}</label><input name="vid" type="number" min="1" max="4094" required value="${h(v.vid || '')}"></div>
        <div><label>${t('Name')}</label><input name="name" maxlength="80" value="${h(v.name || '')}" placeholder="${h(t('z. B. IoT'))}"></div></div>
      <div class="grid2"><div><label>${t('Farbe')}</label><input name="color" type="color" value="${h(v.color || '#00E5FF')}"></div><div></div></div>
      <label>${t('Beschreibung')}</label><input name="description" maxlength="2000" value="${h(v.description || '')}">
      ${isNew && v.planned ? `<p class="muted small">${t('Das VLAN gibt es zunächst nur im Plan. Verwirfst du den Plan, fällt es weg.')}</p>` : ''}
      <label>${t('Subnetze dieses VLANs')}</label>
      ${subnets.length ? `<div class="vp-subs">${subnets.map(s => `<label class="chk"><input type="checkbox" data-sub="${s.id}" ${v.id && s.vlan_id === v.id ? 'checked' : ''}>
          <span class="mono">${h(s.cidr)}</span> ${h(s.name || '')}${s.vlan_id && s.vlan_id !== v.id && vids[s.vlan_id] ? ` <span class="muted small">(${t('jetzt VLAN {n}', { n: vids[s.vlan_id] })})</span>` : ''}</label>`).join('')}</div>`
        : `<p class="muted small">${t('Noch keine Subnetze – unter IPAM anlegen.')}</p>`}
      <p class="muted small">${t('Mit Subnetz prüft der Plan auch, ob die Adressen der Geräte zum neuen VLAN passen. Neue Subnetze legst du unter IPAM an.')}</p>
      ${isNew ? '' : `<p><button type="button" class="sm danger" data-vldel>${t('VLAN löschen')}</button></p>`}`, {
      onOpen: (f, close) => {
        const d = $('[data-vldel]', f);
        if (d) d.onclick = async () => {
          close(null);
          if (!await confirmDlg(t('VLAN löschen'), t('VLAN {n} löschen? Es verschwindet aus allen Port-Zuordnungen (produktiv und Plan).', { n: v.vid }), t('Löschen'))) return;
          try { await api('DELETE', `${P}/vlans/${v.id}`); st = await api('GET', `${P}/vlanplan`); draw(); } catch (e) { toast(e.message, true); }
        };
      },
      onOk: async f => {
        const body = fd(f); if (isNew) body.planned = !!v.planned;
        if (subnets.length) body.subnets = $$('[data-sub]', f).filter(x => x.checked).map(x => +x.dataset.sub);
        await (isNew ? api('POST', `${P}/vlans`, body) : api('PUT', `${P}/vlans/${v.id}`, body));
        return true;
      },
    });
    if (ok) { st = await api('GET', `${P}/vlanplan`); draw(); }
  }

  draw();
}
tabVlans.ui = {};
window.INV.vlanplan = tabVlans;
