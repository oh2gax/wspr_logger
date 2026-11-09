// Analysis page, second set of cards (/api/analysis/more): where you are heard, distance distribution,
// band opening and closing, season against season, SNR by hour and distance, unusual days, stations per
// month and the most loyal reporters.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, analysis-more, info, wprs, main.

'use strict';

let _amData = null;
let _amSeq = 0;
let _amGeoMetric = 'stations';     // 'stations' | 'reports'
let _amSeasonMetric = 'median';    // 'median' | 'dx'
const AM_CARDS = ['amGeoCard', 'amDistCard', 'amOpenCard', 'amSeasonCard', 'amSnrHourCard', 'amSnrDistCard',
                  'amUnusualCard', 'amOpenEvCard', 'amMonthlyCard', 'amLoyalCard'];
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const YEAR_COLORS = ['#38bdf8', '#f59e0b', '#a78bfa', '#4ade80', '#f87171', '#94a3b8'];   // newest year first

// Called by loadAnalysis(): the cards load on their own, so the rest of the page is not held up.
async function loadAnalysisMore() {
    const seq = ++_amSeq;
    AM_CARDS.forEach(id => document.getElementById(id).classList.add('am-loading'));
    let data = null;
    try {
        const r = await fetch(`/api/analysis/more?days=${_anDays}&band=${currentBand}`);
        data = await r.json();
    } catch(e) { data = null; }
    if (seq !== _amSeq) return;
    AM_CARDS.forEach(id => document.getElementById(id).classList.remove('am-loading'));
    _amData = data;
    renderAnalysisMore();
}

function renderAnalysisMore() {
    const d = _amData, show = !!(d && !d.empty);
    AM_CARDS.forEach(id => { document.getElementById(id).style.display = show ? '' : 'none'; });
    if (!show) return;
    drawPolar(); drawDistHist(); drawOpenClose(); drawSeasons();
    drawSnrCharts(); drawUnusual(); drawOpenings(); drawMonthly(); drawLoyal();
}

function setGeoMetric(m) {
    _amGeoMetric = m;
    document.getElementById('amGeoSt').classList.toggle('active', m === 'stations');
    document.getElementById('amGeoRep').classList.toggle('active', m === 'reports');
    drawPolar();
}

function setSeasonMetric(m) {
    _amSeasonMetric = m;
    document.getElementById('amSeaN').classList.toggle('active', m === 'median');
    document.getElementById('amSeaDx').classList.toggle('active', m === 'dx');
    drawSeasons();
}

const amHour = h => h === null || h === undefined ? '—' :
    String(Math.floor(h)).padStart(2, '0') + ':' + String(Math.round((h % 1) * 60) % 60).padStart(2, '0');

// ── Where you are heard: polar chart drawn on a canvas ─────────────────────
function drawPolar() {
    const g = _amData.geo, cv = document.getElementById('amPolar'), col = anColors();
    const W = Math.min(Math.max(cv.parentElement.clientWidth, 260), 420), H = W;
    const dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + 'px'; cv.style.height = H + 'px';
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const cx = W / 2, cy = H / 2, R = W / 2 - 26, nr = g.rings.length - 1, ns = g.sectors;
    const grid = _amGeoMetric === 'reports' ? g.reports : g.stations;
    const max = Math.max(1, ...grid.flat());
    const rad = i => R * (i + (i ? 0.35 : 0)) / (nr + 0.35);         // the innermost ring is a little wider
    for (let r = 0; r < nr; r++) {
        for (let k = 0; k < ns; k++) {
            const v = grid[r][k];
            const a0 = (k - 0.5) * 2 * Math.PI / ns - Math.PI / 2, a1 = (k + 0.5) * 2 * Math.PI / ns - Math.PI / 2;
            ctx.beginPath();
            ctx.arc(cx, cy, rad(r + 1), a0, a1);
            ctx.arc(cx, cy, rad(r), a1, a0, true);
            ctx.closePath();
            ctx.fillStyle = v ? heatColor(Math.sqrt(v / max)) : (isDark ? 'rgba(128,128,128,0.08)' : 'rgba(128,128,128,0.10)');
            ctx.fill();
            ctx.strokeStyle = isDark ? 'rgba(17,24,39,0.9)' : 'rgba(255,255,255,0.9)';
            ctx.lineWidth = 1;
            ctx.stroke();
        }
    }
    ctx.fillStyle = col.text; ctx.font = '10px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ['N', 'E', 'S', 'W'].forEach((t, i) => {
        const a = i * Math.PI / 2 - Math.PI / 2;
        ctx.fillText(t, cx + Math.cos(a) * (R + 13), cy + Math.sin(a) * (R + 13));
    });
    ctx.textAlign = 'left';
    for (let r = 1; r < nr; r++) {                                    // ring labels along the NE diagonal
        const a = -Math.PI / 4 - 0.12, rr = rad(r);
        const km = g.rings[r] >= 1000 ? (g.rings[r] / 1000) + 'k' : g.rings[r];
        ctx.fillStyle = isDark ? 'rgba(229,231,235,0.85)' : 'rgba(30,41,59,0.85)';
        ctx.fillText(km, cx + Math.cos(a) * rr + 2, cy + Math.sin(a) * rr);
    }
    cv._geo = { cx, cy, rad, nr, ns, grid };
    const top = g.sector_share.map((v, k) => [v, COMPASS[k]]).sort((a, b) => b[0] - a[0]).slice(0, 3);
    document.getElementById('amGeoSum').textContent =
        `${g.stations_total.toLocaleString('en-GB')} stations (callsign and locator). Busiest directions: ` +
        top.map(([v, n]) => `${n} ${v} %`).join(', ') + `. Within 1000 km ${g.ring_share[0]} %, 1000–3000 km ` +
        `${(g.ring_share[1] + g.ring_share[2]).toFixed(1)} %, beyond 6000 km ${(g.ring_share[4] + g.ring_share[5]).toFixed(1)} % of the stations.`;
    if (!cv._wired) {
        cv._wired = true;
        const tip = document.getElementById('amPolarTip');
        cv.addEventListener('mousemove', e => {
            const L = cv._geo, rc = cv.getBoundingClientRect();
            const x = e.clientX - rc.left - L.cx, y = e.clientY - rc.top - L.cy, dist = Math.hypot(x, y);
            let ring = -1;
            for (let r = 0; r < L.nr; r++) if (dist >= L.rad(r) && dist < L.rad(r + 1)) ring = r;
            if (ring < 0) { tip.style.display = 'none'; return; }
            const brg = (Math.atan2(x, -y) * 180 / Math.PI + 360) % 360;
            const k = Math.floor(((brg + 180 / L.ns) % 360) / (360 / L.ns));
            const rings = _amData.geo.rings, st = _amData.geo.stations[ring][k], rp = _amData.geo.reports[ring][k];
            const hi = rings[ring + 1] > 20000 ? '+' : '–' + rings[ring + 1].toLocaleString('en-GB');
            tip.textContent = `${COMPASS[k]} · ${rings[ring].toLocaleString('en-GB')}${hi} km: ${st} station${st === 1 ? '' : 's'}, ` +
                `${(100 * rp / Math.max(1, _amData.geo.reports_total)).toFixed(1)} % of reports`;
            tip.style.display = 'block';
            tip.style.left = Math.min(e.clientX - cv.parentElement.getBoundingClientRect().left + 12, cv.parentElement.clientWidth - 230) + 'px';
            tip.style.top = (e.clientY - cv.parentElement.getBoundingClientRect().top + 12) + 'px';
        });
        cv.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
    }
}

// ── Distance distribution ──────────────────────────────────────────────────
function drawDistHist() {
    const h = _amData.dist, col = anColors();
    const labels = h.stations.map((_, i) => ((i * h.step) / 1000).toFixed(i * h.step % 1000 ? 1 : 0) + 'k');
    const marks = { id: 'amDistMarks', afterDatasetsDraw(ch) {
        const x = ch.scales.x, a = ch.chartArea, c = ch.ctx;
        c.save(); c.setLineDash([4, 4]); c.strokeStyle = col.text; c.lineWidth = 1;
        [6000, 10000].forEach(km => {
            const i = km / h.step;
            if (i >= h.stations.length) return;
            const px = (x.getPixelForValue(i - 1) + x.getPixelForValue(i)) / 2;
            c.beginPath(); c.moveTo(px, a.top); c.lineTo(px, a.bottom); c.stroke();
        });
        c.restore();
    } };
    anChart('amDist', {
        type: 'bar', plugins: [marks],
        data: { labels, datasets: [
            { type: 'bar', label: 'Stations', data: h.stations.map(v => v || null), yAxisID: 'y', backgroundColor: 'rgba(56,189,248,0.7)' },
            { type: 'line', label: '% of reports', data: h.report_share, yAxisID: 'y2', borderColor: '#4ade80', backgroundColor: '#4ade80',
              borderWidth: 2, pointRadius: 0, tension: 0 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                       tooltip: { callbacks: { title: it => { const i = it[0].dataIndex; return `${(i * h.step).toLocaleString('en-GB')}–${((i + 1) * h.step).toLocaleString('en-GB')} km`; } } } },
            scales: {
                x:  { ticks: { color: col.text, font: { size: 10 }, maxTicksLimit: 11, maxRotation: 0 }, grid: { display: false },
                      title: { display: true, text: 'distance from home', color: col.text, font: { size: 10 } } },
                y:  { type: 'logarithmic', ticks: { color: col.text, font: { size: 10 }, callback: v => [1, 10, 100, 1000, 10000].includes(v) ? v : '' },
                      grid: { color: col.grid }, title: { display: true, text: 'stations', color: col.text, font: { size: 10 } } },
                y2: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { color: col.text, font: { size: 10 }, callback: v => v + '%' } },
            }
        }
    });
    document.getElementById('amDistSum').textContent =
        `Median distance ${h.median_km ? h.median_km.toLocaleString('en-GB') : '—'} km; ` +
        `${h.beyond6000} stations beyond 6000 km and ${h.beyond10000} beyond 10 000 km, of ${h.total.toLocaleString('en-GB')}.`;
}

// ── Band opening and closing ───────────────────────────────────────────────
function drawOpenClose() {
    const o = _amData.open, col = anColors(), days = o.days;
    document.getElementById('amOpenSub').textContent =
        `First (green) and last (orange) transmission of each UTC day heard by ${o.threshold} or more stations; ` +
        `grey lines: sunrise and sunset at the home square. Median opening ${amHour(o.median_open)}, closing ${amHour(o.median_close)} UTC. ` +
        `Days without such a transmission are left out.`;
    const pt = days.length > 250 ? 1.5 : 2.5;
    anChart('amOpen', {
        type: 'line',
        data: { labels: days.map(x => x.date), datasets: [
            { label: 'Opening', data: days.map(x => x.open), showLine: false, pointRadius: pt, borderColor: '#4ade80', backgroundColor: '#4ade80' },
            { label: 'Closing', data: days.map(x => x.close), showLine: false, pointRadius: pt, borderColor: '#f59e0b', backgroundColor: '#f59e0b' },
            { label: 'Sunrise', data: days.map(x => x.rise), borderColor: '#94a3b8', borderDash: [4, 3], borderWidth: 1.2, pointRadius: 0, spanGaps: false },
            { label: 'Sunset',  data: days.map(x => x.set),  borderColor: '#64748b', borderDash: [4, 3], borderWidth: 1.2, pointRadius: 0, spanGaps: false },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                       tooltip: { callbacks: { label: it => `${it.dataset.label}: ${amHour(it.raw)} UTC`,
                                               afterBody: it => `${days[it[0].dataIndex].slots} transmissions heard by ${o.threshold}+ stations` } } },
            scales: {
                x: { ticks: { color: col.text, font: { size: 10 }, maxTicksLimit: 14, maxRotation: 0 }, grid: { display: false } },
                y: { min: 0, max: 24, ticks: { color: col.text, font: { size: 10 }, stepSize: 3, callback: v => String(v).padStart(2, '0') + ':00' },
                     grid: { color: col.grid }, title: { display: true, text: 'UTC', color: col.text, font: { size: 10 } } },
            }
        }
    });
}

// ── Season against season ──────────────────────────────────────────────────
function drawSeasons() {
    const s = _amData.seasons, col = anColors(), dx = _amSeasonMetric === 'dx';
    document.getElementById('amSeasonSub').textContent = dx
        ? 'Share of snapshots with a station beyond 6000 km, by month and year (always the whole history; months with too little data are empty).'
        : 'Median stations heard per snapshot in the daytime (08–17 UTC), by month and year (always the whole history; months with too little data are empty).';
    anChart('amSeason', {
        type: 'bar',
        data: { labels: s.months.map(m => MONTHS[m - 1]), datasets: s.years.map((y, i) => ({
            label: String(y), data: (dx ? s.dx : s.median)[y], backgroundColor: YEAR_COLORS[(s.years.length - 1 - i) % YEAR_COLORS.length] })) },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                       tooltip: { callbacks: { label: it => `${it.dataset.label}: ${it.raw === null ? 'no data' : it.raw + (dx ? ' %' : ' stations')}`,
                                               afterLabel: it => `${s.days[it.dataset.label][it.dataIndex]} days with data` } } },
            scales: {
                x: { ticks: { color: col.text, font: { size: 10 } }, grid: { display: false } },
                y: { beginAtZero: true, ticks: { color: col.text, font: { size: 10 }, callback: v => dx ? v + '%' : v }, grid: { color: col.grid },
                     title: { display: true, text: dx ? '% of snapshots' : 'stations heard', color: col.text, font: { size: 10 } } },
            }
        }
    });
}

// ── SNR by hour and by distance ────────────────────────────────────────────
function amSnrChart(id, labels, rows, xTitle) {
    const col = anColors();
    anChart(id, {
        type: 'bar',
        data: { labels, datasets: [
            { type: 'bar', label: '25–75 %', data: rows.map(r => r && r.p25 !== null ? [r.p25, r.p75] : null),
              backgroundColor: 'rgba(56,189,248,0.25)', borderWidth: 0, barPercentage: 1.0, categoryPercentage: 1.0, order: 2 },
            { type: 'line', label: 'Median', data: rows.map(r => r ? r.median : null), borderColor: col.accent, backgroundColor: col.accent,
              borderWidth: 2, pointRadius: 2, tension: 0.25, order: 1 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                       tooltip: { callbacks: { label: it => it.dataset.type === 'bar' ? `25–75 %: ${it.raw[0]} … ${it.raw[1]} dB` : `Median: ${it.raw} dB`,
                                               afterBody: it => { const r = rows[it[0].dataIndex]; return r ? `${r.reports.toLocaleString('en-GB')} reports · mean ${r.mean} dB` : ''; } } } },
            scales: {
                x: { ticks: { color: col.text, font: { size: 10 }, maxRotation: 0 }, grid: { display: false },
                     title: { display: true, text: xTitle, color: col.text, font: { size: 10 } } },
                y: { suggestedMin: -32, suggestedMax: 0, ticks: { color: col.text, font: { size: 10 } }, grid: { color: col.grid },
                     title: { display: true, text: 'SNR (dB)', color: col.text, font: { size: 10 } } },
            }
        }
    });
}

function drawSnrCharts() {
    const s = _amData.snr;
    amSnrChart('amSnrHour', Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')), s.hour, 'UTC hour');
    amSnrChart('amSnrDist', s.dist.map(r => (r.lo / 1000) + '–' + (r.lo / 1000 + 1) + 'k'), s.dist, 'distance (km)');
}

// ── Unusual days ───────────────────────────────────────────────────────────
function drawUnusual() {
    const u = _amData.unusual;
    const row = (x, best) => `<tr><td>${x.date}</td>` +
        `<td style="color:${best ? '#4ade80' : '#f59e0b'}">${x.index}</td><td>${x.avg_n}</td>` +
        `<td>${best ? x.max_km.toLocaleString('en-GB') : (x.k_max === null ? '—' : x.k_max)}</td>` +
        `<td><button class="an-btn" title="Open this day in the History Player" ` +
        `onclick="openReplayAt('${best ? x.peak_ts : x.date + ' 12:00:00'}')">&#9654;</button></td></tr>`;
    const empty = '<tr><td colspan="5" class="no-data">Not enough data</td></tr>';
    document.getElementById('amBestBody').innerHTML = u.best.length ? u.best.map(x => row(x, true)).join('') : empty;
    document.getElementById('amWorstBody').innerHTML = u.worst.length ? u.worst.map(x => row(x, false)).join('') : empty;
    document.getElementById('amUnusualSub').textContent =
        `Daytime (06–18 UTC) stations heard against what is typical for that month and hour (100 = typical), ` +
        `${u.days_rated} days rated. Avg = stations heard per snapshot. ▶ opens the day in the History Player.`;
}

// ── Unusual DX openings (from 2026-11-09) ──────────────────────────────────
function drawOpenings() {
    const o = _amData.openings || { events: [] }, ev = o.events || [];
    const hh = h => String(h).padStart(2, '0');
    document.getElementById('amOpenEvBody').innerHTML = ev.length ? ev.map(e => {
        const opening = e.kind === 'opening';
        const usual = opening ? `on ${e.p} % of days` : `${e.median == null ? '—' : Math.round(e.median)} stations`;
        return `<tr><td>${e.day}</td><td>${hh(e.from_h)}${e.to_h > e.from_h ? '–' + hh(e.to_h + 1) : ''}</td>` +
            `<td><strong>${escHtml(e.name)}</strong></td>` +
            `<td style="color:${opening ? '#a855f7' : '#4ade80'}">${opening ? '★ opening' : '▲ strong'}</td>` +
            `<td title="${escHtml(e.calls.join(', '))}">${e.stations} <span style="color:var(--text-muted)">${escHtml(e.calls.slice(0, 3).join(', '))}${e.calls.length > 3 ? ' …' : ''}</span></td>` +
            `<td style="color:var(--text-muted)">${usual}</td>` +
            `<td><button class="an-btn" title="Open this moment in the History Player" ` +
            `onclick="openReplayAt('${e.day} ${hh(e.from_h)}:30:00')">&#9654;</button></td></tr>`;
    }).join('') : '<tr><td colspan="7" class="no-data">No unusual openings in this period</td></tr>';
    document.getElementById('amOpenEvSub').innerHTML =
        `A region beyond 6000 km heard at an hour when, at this time of year (±${o.season_days || 45} days, any year), it is heard ` +
        `on fewer than ${o.p_open || 2.5} % of days (<b style="color:#a855f7">opening</b>), or by many more stations than ever usual at that hour ` +
        `(<b style="color:#4ade80">strong</b>). ${ev.length} in this period` +
        (o.per_week != null ? `; about ${o.per_week} a week over the whole history` : '') +
        `. Usually = how often the region is heard then, or its usual stations. &#9654; opens the moment in the History Player.`;
}

// ── Stations per month ─────────────────────────────────────────────────────
function drawMonthly() {
    const m = _amData.monthly, col = anColors();
    anChart('amMonthly', {
        type: 'bar',
        data: { labels: m.map(x => x.month), datasets: [
            { label: 'Stations', data: m.map(x => x.stations), backgroundColor: 'rgba(56,189,248,0.7)' },
            { label: 'New stations', data: m.map(x => x.new), backgroundColor: 'rgba(74,222,128,0.8)' },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } } },
            scales: {
                x: { ticks: { color: col.text, font: { size: 10 }, maxRotation: 0, autoSkip: true }, grid: { display: false } },
                y: { beginAtZero: true, ticks: { color: col.text, font: { size: 10 }, precision: 0 }, grid: { color: col.grid } },
            }
        }
    });
}

// ── Most loyal reporters ───────────────────────────────────────────────────
function drawLoyal() {
    const l = _amData.loyal;
    document.getElementById('amLoyalBody').innerHTML = l.length ? l.map((x, i) =>
        `<tr><td>${i + 1}</td><td><strong>${escHtml(x.callsign)}</strong> <span style="color:var(--text-muted)">${escHtml(x.country || '')} ${escHtml(x.grid || '')}</span></td>` +
        `<td>${x.share} % <span style="color:var(--text-muted)">(${x.snapshots.toLocaleString('en-GB')})</span></td>` +
        `<td>${x.dist ? x.dist.toLocaleString('en-GB') + ' km' : '—'}</td><td>${x.snr} / ${x.snr_max > 0 ? '+' : ''}${x.snr_max} dB</td>` +
        `<td>${x.first}</td></tr>`).join('')
        : '<tr><td colspan="6" class="no-data">No data</td></tr>';
}

window.addEventListener('resize', () => {
    if (_amData && !_amData.empty && document.getElementById('analysis-view').classList.contains('active')) drawPolar();
});
