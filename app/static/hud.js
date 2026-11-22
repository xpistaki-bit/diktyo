'use strict';
/* HUD-Bausteine für Übersicht und Integrationen: Balkendiagramm, Tacho, Ring, Segmentbalken, Flussbalken, Sparkline.
   Beschriftungen sind HTML statt SVG-Text: Sie bleiben bei jeder Breite gleich groß und lesbar; das SVG darf sich dehnen. */

const nf = (v, d = 0) => (+v).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE', { maximumFractionDigits: d });
/* Zahl und Einheit getrennt, damit die Zahl groß und die Einheit klein dargestellt werden kann */
function splitBps(v) {
  if (v == null || isNaN(v)) return ['–', ''];
  const u = [[1e9, 'Gbit/s'], [1e6, 'Mbit/s'], [1e3, 'kbit/s']].find(([f]) => v >= f) || [1, 'bit/s'];
  const x = v / u[0];
  return [nf(x, x < 10 ? 1 : 0), u[1]];
}
function splitBytes(v) {
  if (v == null || isNaN(v)) return ['–', ''];
  const u = [[1e12, 'TB'], [1e9, 'GB'], [1e6, 'MB'], [1e3, 'kB']].find(([f]) => v >= f) || [1, 'B'];
  const x = v / u[0];
  return [nf(x, x < 10 ? 1 : 0), u[1]];
}
function niceMax(v) {
  if (!(v > 0)) return 1;
  const e = 10 ** Math.floor(Math.log10(v)), m = v / e;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * e;
}
const bigVal = ([num, unit], cls = '') => `<span class="hval ${cls}"><b>${num}</b>${unit ? `<i>${unit}</i>` : ''}</span>`;
const timeLabel = (ts, since) => new Date(ts * 1000).toLocaleString(LANG === 'en' ? 'en-GB' : 'de-DE',
  since >= 86400 ? { weekday: 'short', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' });

/* Balkendiagramm über die Zeit. mirror: erste Reihe nach oben, zweite nach unten (je eigene Skala, z. B. Download/Upload). */
function hudBars(series, since, { height = 220, fmt = fmtBps, mirror = false, step, t1 } = {}) {
  const W = 1000, H = 100, now = t1 || Date.now() / 1000, t0 = now - since;
  const n = Math.max(1, ...series.map(s => s.points.length));
  const st = step || since / Math.max(n, 24);
  const bw = Math.max(1.5, Math.min(14, st / since * W * .55));
  const x = ts => Math.min(W - bw, Math.max(0, (ts - t0) / since * W - bw / 2));
  const mx = series.map(s => niceMax(Math.max(0, ...s.points.map(p => p[1]))));
  const tip = (s, p) => `<title>${h(timeLabel(p[0], 86400))} · ${h(s.name)}: ${h(fmt(p[1]))}</title>`;
  const two = mirror && series.length === 2;
  const mid = two ? 62 : H;  // Nulllinie
  let rects = '', labels = [], grid = [];
  if (two) {
    const [a, b] = series;
    rects += a.points.map(p => { const hh = p[1] / mx[0] * (mid - 1); return `<rect x="${x(p[0]).toFixed(1)}" y="${(mid - hh).toFixed(2)}" width="${bw.toFixed(1)}" height="${hh.toFixed(2)}" fill="${a.color}">${tip(a, p)}</rect>`; }).join('');
    rects += b.points.map(p => { const hh = p[1] / mx[1] * (H - mid - 1); return `<rect x="${x(p[0]).toFixed(1)}" y="${mid + .6}" width="${bw.toFixed(1)}" height="${hh.toFixed(2)}" fill="${b.color}" opacity=".85">${tip(b, p)}</rect>`; }).join('');
    labels = [[0, fmt(mx[0])], [mid / 2, fmt(mx[0] / 2)], [mid, '0'], [(mid + H) / 2, fmt(mx[1] / 2)], [H, fmt(mx[1])]];
    grid = [0, mid / 2, (mid + H) / 2, H];
  } else {
    const m = Math.max(...mx);
    series.forEach((s, i) => {
      const w = i ? bw * .5 : bw, off = i ? bw * .25 : 0;
      rects += s.points.map(p => { const hh = p[1] / m * (H - 1); return `<rect x="${(x(p[0]) + off).toFixed(1)}" y="${(H - hh).toFixed(2)}" width="${w.toFixed(1)}" height="${hh.toFixed(2)}" fill="${s.color}" ${i ? '' : 'opacity=".9"'}>${tip(s, p)}</rect>`; }).join('');
    });
    labels = [[0, fmt(m)], [H / 4, fmt(m * .75)], [H / 2, fmt(m / 2)], [H * .75, fmt(m / 4)], [H, '0']];
    grid = [0, H / 4, H / 2, H * .75];
  }
  const empty = series.every(s => !s.points.length);
  return `<div class="hbc" style="--h:${height}px">
      <div class="hb-y">${labels.map(([y, l]) => `<span style="top:${y}%">${h(l)}</span>`).join('')}</div>
      <div class="hb-plot"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
        ${grid.map(y => `<line x1="0" x2="${W}" y1="${y}" y2="${y}" class="hb-grid"/>`).join('')}
        <line x1="0" x2="${W}" y1="${mid}" y2="${mid}" class="hb-zero"/>${rects}</svg>
        ${empty ? `<div class="hb-empty">${t('Noch keine Messwerte – sie entstehen mit jeder Abfrage.')}</div>` : ''}</div>
      <div></div><div class="hb-x"><span>${h(timeLabel(t0, since))}</span><span>${h(timeLabel(t0 + since / 2, since))}</span><span>${h(timeLabel(now, since))}</span></div>
    </div>
    <div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${h(s.name)}</span>`).join('')}</div>`;
}

async function drawBars(el, pid, keys, names, since, opts = {}) {
  const r = await api('GET', `/api/profiles/${pid}/metrics?keys=${keys.join(',')}&since=${since}&points=${opts.points || 96}`);
  const colors = opts.colors || ['#00E5FF', '#19F5C8', '#2D7BFF', '#FFB020'];
  el.innerHTML = hudBars(keys.map((k, i) => ({ name: names[i], color: colors[i % colors.length], points: r.series[k] || [] })), since, { step: r.step, ...opts });
}

/* Tacho (240°) mit großer Zahl in der Mitte. frac 0..1; cls ok/warn/bad färbt den Bogen. */
function hudGauge(value, max, { label = '', fmt = splitBps, cls = '', sub = '' } = {}) {
  const frac = value == null || !max ? 0 : Math.max(0, Math.min(1, value / max));
  const R = 78, C = 100, A0 = 150, SW = 240;
  const pt = (a, r = R) => [C + r * Math.cos(a * Math.PI / 180), C + r * Math.sin(a * Math.PI / 180)];
  const arc = (a1, a2, r = R) => { const [x1, y1] = pt(a1, r), [x2, y2] = pt(a2, r); return `M${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${a2 - a1 > 180 ? 1 : 0} 1 ${x2.toFixed(2)},${y2.toFixed(2)}`; };
  const ticks = Array.from({ length: 25 }, (_, i) => { const a = A0 + SW * i / 24, [x1, y1] = pt(a, 92), [x2, y2] = pt(a, i % 6 ? 88 : 84); return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`; }).join('');
  const [num, unit] = fmt(value);
  return `<div class="gauge ${cls}"><div class="g-dial"><svg viewBox="0 0 200 150" aria-hidden="true">
      <g class="g-ticks">${ticks}</g><path d="${arc(A0, A0 + SW)}" class="g-track"/>
      ${frac > 0.002 ? `<path d="${arc(A0, A0 + SW * frac)}" class="g-val"/>` : ''}</svg>
    <div class="g-txt"><span class="g-lab">${h(label)}</span><b>${num}</b><i>${unit}</i></div></div>
    ${sub ? `<div class="g-sub">${sub}</div>` : ''}</div>`;
}

/* Ring für Prozentwerte (Verfügbarkeit) */
function hudRing(pct, { size = 64, label = '' } = {}) {
  const r = 26, c = 2 * Math.PI * r, f = pct == null ? 0 : Math.max(0, Math.min(1, pct / 100));
  const cls = pct == null ? 'none' : pct >= 99.9 ? 'ok' : pct >= 98 ? 'warn' : 'bad';
  const txt = pct == null ? '–' : nf(pct, pct >= 99.95 ? 0 : pct >= 99 ? 2 : 1);
  return `<div class="ring ${cls}" style="--s:${size}px"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="${r}" class="r-track"/>
      <circle cx="32" cy="32" r="${r}" class="r-val" stroke-dasharray="${(c * f).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 32 32)"/></svg>
    <span><b>${txt}</b>${pct == null ? '' : '<i>%</i>'}</span>${label ? `<small>${h(label)}</small>` : ''}</div>`;
}

/* Segmentbalken: n von total (z. B. Geräte online) */
function hudSegs(n, total, segs = 24) {
  const on = total ? Math.round(n / total * segs) : 0;
  return `<div class="segs">${Array.from({ length: segs }, (_, i) => `<i class="${i < on ? 'on' : total ? 'off' : ''}"></i>`).join('')}</div>`;
}

/* Fluss-Zeile: Name links, zwei Balken (↓/↑), Werte rechts gut lesbar */
function hudFlow({ label, sub = '', down, up, max, fmt = splitBps }) {
  const w = v => v ? Math.max(1.5, Math.min(100, v / max * 100)) : 0;
  const [dn, du] = fmt(down), [un, uu] = fmt(up);
  return `<div class="flow"><div class="fl-name">${label}${sub ? `<small>${sub}</small>` : ''}</div>
    <div class="fl-bars"><div class="fl-bar dn"><i style="width:${w(down).toFixed(1)}%"></i></div><div class="fl-bar up"><i style="width:${w(up).toFixed(1)}%"></i></div></div>
    <div class="fl-val"><span class="dn">↓ <b>${dn}</b> <i>${du}</i></span><span class="up">↑ <b>${un}</b> <i>${uu}</i></span></div></div>`;
}

/* Sparkline ohne Beschriftung (Verlauf in einer Zeile) */
function hudSpark(vals, { max, cls = '' } = {}) {
  if (!vals || vals.length < 2) return `<div class="spark ${cls} none"></div>`;
  const m = max || Math.max(...vals) * 1.1 || 1, n = vals.length - 1;
  const pts = vals.map((v, i) => `${(i / n * 100).toFixed(2)},${(30 - v / m * 28).toFixed(2)}`).join(' ');
  return `<div class="spark ${cls}"><svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
    <polygon points="0,30 ${pts} 100,30" class="sp-area"/><polyline points="${pts}" class="sp-line"/></svg></div>`;
}
