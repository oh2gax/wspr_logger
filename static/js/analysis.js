// Analysis page: charts, DX outlook, grey-line card and the ionosonde day view.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, analysis-more, info, wprs, main.

'use strict';

// ── Propagation analysis page ──────────────────────────────────────────────
let _anData = null;
let _anDays = 90;
let _anHeatMetric = 'n';
let _anCharts = {};
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

// While the server computes (several seconds for a period not asked for in the last 10 minutes):
// the first time a message with the seconds waited in place of the cards; on a period change the
// cards stay, dimmed, with "Loading …" beside the period buttons.  A slower answer for an earlier
// period never replaces a newer one.
let _anSeq = 0, _anWaitTimer = null;
const AN_PERIOD_NAMES = {30: '30 days', 90: '90 days', 180: '6 months', 365: '1 year', 0: 'the whole history'};

function anBusy(on) {
    const empty = document.getElementById('anEmpty'), body = document.getElementById('anBody');
    const per = document.getElementById('anPeriod');
    clearInterval(_anWaitTimer); _anWaitTimer = null;
    body.classList.toggle('an-busy', on && !!_anData);
    if (!on) { per.classList.remove('an-loading-lbl'); return; }
    const t0 = Date.now(), what = AN_PERIOD_NAMES[_anDays] || `${_anDays} days`;
    if (_anData && !_anData.empty) {                    // a period change: keep the cards
        per.classList.add('an-loading-lbl');
        per.innerHTML = `<span class="an-spin"></span>Loading ${what}…`;
        return;
    }
    body.style.display = 'none';
    empty.style.display = 'block';
    const draw = () => {
        const s = Math.round((Date.now() - t0) / 1000);
        empty.innerHTML = `<div class="an-wait"><span class="an-spin"></span><b>Computing the propagation analysis of ${what}…</b>` +
            `<div>The server goes through every stored snapshot. The first opening can take a few seconds` +
            (s >= 2 ? ` (${s} s so far)` : '') + `; after that the page opens at once.</div></div>`;
    };
    draw();
    _anWaitTimer = setInterval(draw, 1000);
}

async function loadAnalysis() {
    const seq = ++_anSeq;
    loadAnalysisMore();                 // the second set of cards loads on its own (analysis-more.js)
    anBusy(true);
    let data;
    try {
        const r = await fetch(`/api/analysis?days=${_anDays}&band=${currentBand}`);
        if (!r.ok) throw new Error(r.status);
        data = await r.json();
    } catch(e) {
        if (seq !== _anSeq) return;
        anBusy(false);
        showToast('Failed to load analysis', 'err');
        if (_anData) renderAnalysis(); else document.getElementById('anEmpty').textContent = 'Could not load the analysis. Try again in a moment.';
        return;
    }
    if (seq !== _anSeq) return;         // the period was changed meanwhile: that answer is on its way
    anBusy(false);
    _anData = data;
    renderAnalysis();
}

function setAnalysisDays(d) {
    _anDays = d;
    [[30,'anP30'],[90,'anP90'],[180,'anP180'],[365,'anP365'],[0,'anP0']].forEach(([n,id]) =>
        document.getElementById(id).classList.toggle('active-qb', n === d));
    loadAnalysis();
}

function setHeatMetric(m) {
    _anHeatMetric = m;
    document.getElementById('anHmN').classList.toggle('active',  m === 'n');
    document.getElementById('anHmMx').classList.toggle('active', m === 'dist');
    drawHeatmap();
}

// ── DX outlook card ────────────────────────────────────────────────────────
function drawOutlook() {
    const o = _anData.outlook, card = document.getElementById('anOutlookCard');
    if (!o || !o.zones || !o.zones.length) { card.style.display = 'none'; return; }
    card.style.display = '';
    const mufTxt = o.muf ? `MUF ${o.muf.toFixed(1)} MHz` + (o.muf_class ? ` (${o.muf_class} for this hour)` : '') : 'no recent MUF reading';
    const kTxt = o.k != null ? `K-index ${o.k} (${o.k_class})` : 'no recent K reading';
    document.getElementById('anOlCond').textContent = o.adjusted
        ? `Adjusted for the present conditions, assumed to persist: ${mufTxt}, ${kTxt}.`
        : `Showing how often it has happened in that hour of the day (present MUF and K are not applied, see the note). Now: ${mufTxt}, ${kTxt}.`;
    const model = _anData.outlook_model || { zones: {} };
    const hours = o.zones[0].cells.map(c => c.hour);
    let html = '<tr><th></th>' + hours.map((h, i) => `<th>${String(h).padStart(2, '0')}${i === 0 ? '<br>now' : ''}</th>`).join('') + '<th>next 3 h</th><th>best in 12 h</th></tr>';
    for (const z of o.zones) {
        const zm = model.zones[z.zone] || {};
        const lm = (zm.lift_muf || {})[o.muf_class] ?? 1, lk = (zm.lift_k || {})[o.k_class] ?? 1;
        html += `<tr><td class="ol-name">${escHtml(z.name)}</td>` + z.cells.map(c => {
            const a = Math.min(1, c.p / 0.6) * 0.85;
            return `<td class="ol-cell" style="background:rgba(74,222,128,${a.toFixed(2)})" ` +
                `title="usual for this hour ${(c.base * 100).toFixed(0)} %${o.adjusted ? ` · MUF ×${lm} · K ×${lk}` : ''}">${Math.round(c.p * 100)}</td>`;
        }).join('') + `<td style="text-align:center"><span class="ol-pill ${z.label}">${z.label}</span></td>` +
            `<td style="text-align:center;white-space:nowrap;color:var(--text-secondary)">${String(z.best_hour).padStart(2, '0')} UTC · ${Math.round(z.best_p * 100)} %</td></tr>`;
    }
    document.getElementById('anOlTable').innerHTML = html;
    const sk = (_anData.outlook_model || {}).skill;
    document.getElementById('anOlNote').textContent =
        'Cells show percent, from the whole history (the period buttons do not change them). A descriptive estimate from this station’s own history, not a physical forecast. ' +
        (sk ? (o.adjusted
              ? `The MUF and K adjustment is applied because it helped in a back-test (fitted before ${sk.split}, scored on the ${sk.test_days} later days, 6 hours ahead): Brier score ${sk.brier_model} against ${sk.brier_climatology} for the hour of the day alone, ${(sk.skill * 100).toFixed(1)} % better, a small gain.`
              : `The MUF and K adjustment was tested (fitted before ${sk.split}, scored on the ${sk.test_days} later days, 6 hours ahead) and did not beat the hour of the day alone (Brier ${sk.brier_model} against ${sk.brier_climatology}), so it is not applied.`)
             : 'Too little history for a back-test yet, so only the hour of the day is used.');
}

// ── Grey-line card ─────────────────────────────────────────────────────────
const GL_COLORS = { n_america: '#f59e0b', africa: '#4ade80', pacific: '#f87171', s_america: '#a78bfa', asia: '#2dd4bf' };

function sunLinesPlugin(marks) {
    return { id: 'sunLines', beforeDatasetsDraw(ch) {
        const ctx = ch.ctx, ca = ch.chartArea, x = ch.scales.x;
        const px = t => Math.min(Math.max(x.getPixelForValue(t - 0.5), ca.left), ca.right);
        ctx.save();
        for (const m of marks) {
            if (!m.t) continue;
            const [q1, md, q3] = m.t, band = (a, b) => { ctx.fillStyle = m.color + '30'; ctx.fillRect(px(a), ca.top, px(b) - px(a), ca.bottom - ca.top); };
            if (q1 <= q3) band(q1, q3); else { band(q1, 24); band(0, q3); }
            ctx.strokeStyle = m.color; ctx.lineWidth = 1.5; ctx.setLineDash(m.dash);
            const xm = px(md); ctx.beginPath(); ctx.moveTo(xm, ca.top); ctx.lineTo(xm, ca.bottom); ctx.stroke();
            ctx.setLineDash([]); ctx.fillStyle = m.color; ctx.font = '10px sans-serif';
            ctx.fillText(m.lbl, Math.min(xm + 3, ca.right - 16), ca.top + 10);
        }
        ctx.restore();
    } };
}

function drawGreyline() {
    const g = _anData.greyline, card = document.getElementById('anGlCard');
    if (!g || !g.zones || !g.zones.length) { card.style.display = 'none'; return; }
    card.style.display = '';
    const c = anColors();
    document.getElementById('anGlSub').textContent =
        `Bars: share of days with a reporter beyond 6000 km from the region, by UTC hour. Lines: sunrise (▲) and sunset (▼), median and quartiles over the period, ` +
        `at home (grey, H) and at the far end (colour, F: the median position of the region's reporters).`;
    document.getElementById('anGlBody').innerHTML = g.zones.map((z, i) =>
        `<div><div class="an-gl-title">${escHtml(z.name)} <span>· ${z.days} days · far end ≈ ${Math.abs(z.lat)}°${z.lat >= 0 ? 'N' : 'S'} ${Math.abs(z.lon)}°${z.lon >= 0 ? 'E' : 'W'}</span></div>` +
        `<div class="an-chart" style="height:170px;"><canvas id="anGl${i}"></canvas></div><div class="an-gl-stat" id="anGlStat${i}"></div></div>`).join('');
    g.zones.forEach((z, i) => {
        const col = GL_COLORS[z.zone] || c.accent;
        const marks = [
            { t: g.home.rise, color: '#94a3b8', dash: [4, 3], lbl: 'H▲' }, { t: g.home.set, color: '#94a3b8', dash: [4, 3], lbl: 'H▼' },
            { t: z.far.rise, color: col, dash: [], lbl: 'F▲' }, { t: z.far.set, color: col, dash: [], lbl: 'F▼' },
        ];
        anChart('anGl' + i, {
            type: 'bar',
            data: { labels: [...Array(24).keys()], datasets: [{ data: z.by_hour.map(v => v ?? 0), backgroundColor: col + 'cc', borderWidth: 0 }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { callbacks: { label: it => `${it.parsed.y} % of days at ${String(it.label).padStart(2, '0')} UTC` } } },
                scales: {
                    x: { ticks: { color: c.text, maxRotation: 0, callback: (v, k) => (k % 3 === 0 ? k : '') }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { color: c.text, callback: v => v + '%' }, grid: { color: c.grid } },
                },
            },
            plugins: [sunLinesPlugin(marks)],
        });
        const clear = z.z !== null && z.z >= 2 && z.ratio >= 1.1;
        document.getElementById('anGlStat' + i).innerHTML =
            `Twilight at either end in <b>${z.tw_obs_pct} %</b> of its DX hours; the same hours on the other days: ${z.tw_exp_pct} %` +
            (z.ratio ? ` (×${z.ratio}, z = ${z.z})` : '') + `. ` +
            (clear ? 'DX is somewhat more likely when the terminator is on the path.' : 'No clear grey-line preference beyond the hour of the day.');
    });
    document.getElementById('anGlNote').textContent =
        `Twilight means the sun within ±${g.twilight_deg}° of the horizon. The comparison keeps the UTC hour fixed and asks whether DX favours the days on which the terminator happens to be there; ` +
        `z is the number of standard errors between the observed and the expected count (about 2 or more is a real difference). Home is ${g.home.loc}; the far end is one position per region.`;
}

function drawExcluded() {
    const ex = _anData.excluded || [], el = document.getElementById('anExcluded');
    el.textContent = ex.length
        ? 'Left out as implausible (the reported distance contradicts the station’s own grid by more than 500 km): ' +
          ex.map(o => `${o.callsign} (${o.grid}): ${o.reported_km.toLocaleString('en-GB')} km reported, ${o.grid_km.toLocaleString('en-GB')} km by grid`).join('; ') + '.'
        : '';
}


function renderAnalysis() {
    const d = _anData, empty = document.getElementById('anEmpty'), body = document.getElementById('anBody');
    if (!d || d.empty) {
        body.style.display = 'none';
        empty.style.display = 'block';
        empty.textContent = (d && d.enabled === false)
            ? 'The replay database is disabled in config.ini ([replay] enabled = true), so there is nothing to analyse.'
            : 'No replay data stored yet.';
        return;
    }
    empty.style.display = 'none';
    body.style.display = 'block';
    const sm = d.summary;
    document.getElementById('anPeriod').textContent = `${sm.from} → ${sm.to}`;
    const fmt = n => n.toLocaleString();
    const corr = (sm.corr_muf_raw ?? '—') + ' raw / ' + (sm.corr_muf_rel ?? '—') + ' vs. typical hour';
    document.getElementById('anSummary').innerHTML = [
        ['Snapshots', fmt(sm.snapshots), '', `over ${sm.days} days`],
        ['Avg reporters', sm.avg_n, 'g', 'stations heard per hour'],
        ['Reporter > 6000 km', sm.pct_dx + ' %', 'g', 'of snapshots'],
        ['Farthest reporter', fmt(sm.best_dist), 'g', `km · ${sm.best_ts} UTC`],
        ['Reporters ~ MUF', corr, 'sm2', 'correlation (−1 … 1)'],
    ].map(([l, v, c, u]) => `<div class="stat-card"><div class="stat-card-lbl">${l}</div>` +
        `<div class="stat-card-val ${c}">${v}</div><div class="stat-card-unit">${u}</div></div>`).join('');

    drawHeatmap();
    drawProfileChart();
    drawBinChart('anMuf', d.bins.muf, b => `${b.lo}–${b.hi}`, 'MUF (MHz)');
    drawBinChart('anK',   d.bins.k,   b => `K${b.lo}`,        'K-index');
    drawBinChart('anSfi', d.bins.sfi, b => `${b.lo}–${b.hi}`, 'SFI');

    document.getElementById('anStormTitle').textContent = `Geomagnetic storm days (K ≥ ${sm.storm_k})`;
    document.getElementById('anStormBody').innerHTML = d.storms.length
        ? d.storms.map(s => `<tr><td>${s.date}</td><td>${s.k_max} <span style="color:var(--text-muted)">@${s.k_time}</span></td>` +
            `<td>${s.avg_n}</td><td style="color:${s.index >= 100 ? '#4ade80' : '#f59e0b'}">${s.index} %</td><td>${s.snapshots}</td>` +
            `<td><button class="an-btn" title="Open the moment of the K maximum in the History Player" ` +
            `onclick="openReplayAt('${s.date} ${s.k_time}:00')">&#9654;</button></td></tr>`).join('')
        : '<tr><td colspan="6" class="no-data">No storm days in this period</td></tr>';

    renderNowCard(d.now);
    drawOutlook();
    drawDxCharts();
    drawGreyline();
    drawExcluded();
    const period = { 0: 'all history', 180: 'last 6 months', 365: 'last year' }[_anDays] || `last ${_anDays} days`;
    document.getElementById('anRecTitle').textContent = `Farthest reporters (${period})`;
    document.getElementById('anRecBody').innerHTML = (d.records || []).length
        ? d.records.map((r, i) => `<tr><td>${i + 1}</td><td><strong>${escHtml(r.callsign)}</strong> ` +
            `<span style="color:var(--text-muted)">${escHtml(r.country || '')} ${escHtml(r.grid || '')}</span></td>` +
            `<td>${r.distance.toLocaleString()} km</td><td>${r.timestamp.slice(0, 16)}</td>` +
            `<td><button class="an-btn" title="Open in the History Player" onclick="openReplayAt('${r.timestamp}')">&#9654;</button></td></tr>`).join('')
        : '<tr><td colspan="5" class="no-data">No data</td></tr>';

    // Ionosonde view: in day mode keep the selected day if it is still in range, else the latest day;
    // the other modes have their own period, so they are only redrawn (or loaded the first time)
    const dates = d.heatmap.dates;
    if (_ionoMode === 'day') loadIonoDay(_ionoDate && dates.includes(_ionoDate) ? _ionoDate : dates[dates.length - 1]);
    else if (_ionoData) drawIonoChart();
    else setIonoMode(_ionoMode);
    if (_amData) renderAnalysisMore();      // e.g. after a theme change: redraw with the new colours
}

function renderNowCard(n) {
    const fmt = v => (v === null || v === undefined) ? '—' : v;
    if (!n) return;
    const hh = String(n.hour).padStart(2, '0');
    document.getElementById('anNowSub').textContent =
        `${hh}:00 UTC · Juliusruh MUF ${n.muf ? n.muf.toFixed(1) + ' MHz' : 'not available'}`;
    document.getElementById('anNowLive').textContent = fmt(n.live_n);
    const t = n.typical, m = n.typical_muf;
    document.getElementById('anNowTyp').textContent = t ? fmt(t.median) : '—';
    document.getElementById('anNowTypSub').textContent = t ? `usual range ${t.p25}–${t.p75} · ${t.count.toLocaleString()} snapshots` : '';
    document.getElementById('anNowMuf').textContent = m ? fmt(m.median) : '—';
    document.getElementById('anNowMufSub').textContent = m
        ? `usual range ${m.p25}–${m.p75} · ${m.count.toLocaleString()} snapshots`
        : 'not enough history at this MUF';
    const v = document.getElementById('anNowVerdict');
    const txt = { above: 'Better than usual', typical: 'Typical', below: 'Below usual' }[n.verdict] || '—';
    v.textContent = txt;
    v.className = 'an-now-val' + (n.verdict === 'above' ? ' good' : n.verdict === 'below' ? ' bad' : '');
    document.getElementById('anNowBasis').textContent = n.verdict
        ? (n.verdict_basis === 'muf' ? 'vs. similar MUF at this hour' : 'vs. this hour of day') : '';
}

function drawDxCharts() {
    const d = _anData, col = anColors();
    anChart('anDxHour', {
        type: 'bar',
        data: { labels: d.dx_hour.map(x => String(x.hour).padStart(2, '0')), datasets: [
            { type: 'bar', label: '% snapshots with reporter > 6000 km', data: d.dx_hour.map(x => x.pct_dx), yAxisID: 'y',
              backgroundColor: 'rgba(74,222,128,0.7)' },
            { type: 'line', label: 'Avg farthest reporter (km)', data: d.dx_hour.map(x => x.avg_max), yAxisID: 'y2',
              borderColor: col.accent, backgroundColor: col.accent, borderWidth: 2, pointRadius: 2, tension: 0.3 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                       tooltip: { callbacks: { afterBody: it => `${d.dx_hour[it[0].dataIndex].count.toLocaleString()} snapshots` } } },
            scales: {
                x:  { ticks: { color: col.text, font: { size: 10 } }, grid: { display: false },
                      title: { display: true, text: 'UTC hour', color: col.text, font: { size: 10 } } },
                y:  { beginAtZero: true, ticks: { color: col.text, font: { size: 10 } }, grid: { color: col.grid },
                      title: { display: true, text: '% of snapshots', color: col.text, font: { size: 10 } } },
                y2: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { color: col.text, font: { size: 10 } },
                      title: { display: true, text: 'km', color: col.text, font: { size: 10 } } },
            }
        }
    });
    anChart('anDxMonth', {
        type: 'bar',
        data: { labels: d.dx_month.map(x => x.month), datasets: [
            { type: 'bar', label: 'Avg stations heard', data: d.dx_month.map(x => x.avg_n), yAxisID: 'y',
              backgroundColor: 'rgba(56,189,248,0.7)' },
            { type: 'line', label: '% snapshots with reporter > 6000 km', data: d.dx_month.map(x => x.pct_dx), yAxisID: 'y2',
              borderColor: '#4ade80', backgroundColor: '#4ade80', borderWidth: 2, pointRadius: 3, tension: 0.25 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                       tooltip: { callbacks: { afterBody: it => { const x = d.dx_month[it[0].dataIndex];
                           return `${x.days} days · ${x.count.toLocaleString()} snapshots` + (x.avg_sfi ? ` · avg SFI ${x.avg_sfi}` : ''); } } } },
            scales: {
                x:  { ticks: { color: col.text, font: { size: 10 } }, grid: { display: false } },
                y:  { beginAtZero: true, ticks: { color: col.text, font: { size: 10 } }, grid: { color: col.grid },
                      title: { display: true, text: 'stations', color: col.text, font: { size: 10 } } },
                y2: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { color: col.text, font: { size: 10 } },
                      title: { display: true, text: '% > 6000 km', color: col.text, font: { size: 10 } } },
            }
        }
    });
}

// ── Ionosonde view (Juliusruh MUF / foF2 vs reporters) ─────────────────────
// One day (every snapshot), the last 30 d / 90 d / 6 m / 1 yr / all, or a custom range of days.
// Longer periods come back from /api/iono averaged over buckets (3 h ... 2 days), at most 500 bars.
let _ionoMode = 'day';          // 'day' | 30 | 90 | 180 | 365 | 0 | 'custom'
let _ionoDate = null;           // the day shown in 'day' mode
let _ionoData = null;           // the last /api/iono answer
let _ionoSeq  = 0;              // only the newest request may draw

const IONO_BTNS = [['day','ioDay'],[30,'io30'],[90,'io90'],[180,'io180'],[365,'io365'],[0,'io0'],['custom','ioCustom']];

function setIonoMode(m) {
    _ionoMode = m;
    IONO_BTNS.forEach(([k, id]) => document.getElementById(id).classList.toggle('active', k === m));
    document.getElementById('anIonoDayCtl').style.display   = m === 'day'    ? 'flex' : 'none';
    document.getElementById('anIonoRangeCtl').style.display = m === 'custom' ? 'flex' : 'none';
    const dates = (_anData && _anData.heatmap) ? _anData.heatmap.dates : [];
    const last = dates.length ? dates[dates.length - 1] : todayStr();
    if (m === 'day') {
        loadIonoDay(_ionoDate || last);
    } else if (m === 'custom') {
        const f = document.getElementById('anIonoFrom'), t = document.getElementById('anIonoTo');
        if (!t.value) t.value = _ionoDate || last;
        if (!f.value) { const d = new Date(t.value + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() - 13); f.value = d.toISOString().slice(0, 10); }
        loadIonoCustom();
    } else {
        fetchIono(`days=${m}`);
    }
}

async function fetchIono(query) {
    const seq = ++_ionoSeq;
    let data = null;
    try {
        const r = await fetch(`/api/iono?${query}&band=${currentBand}`);
        data = await r.json();
        if (data.error) { showToast(data.error, 'err'); data = null; }
    } catch(e) { data = null; }
    if (seq !== _ionoSeq) return;          // a newer request was made meanwhile
    _ionoData = data;
    drawIonoChart();
}

function loadIonoDay(date) {
    if (!date) return;
    _ionoDate = date;
    document.getElementById('anIonoDate').value = date;
    fetchIono(`from=${date}&to=${date}`);
}

function loadIonoCustom() {
    const f = document.getElementById('anIonoFrom').value, t = document.getElementById('anIonoTo').value;
    if (!f || !t) return;
    if (t < f) { showToast('The last day is before the first day', 'err'); return; }
    fetchIono(`from=${f}&to=${t}`);
}

function shiftIonoDay(dir) {
    if (!_anData || _anData.empty) return;
    const dates = _anData.heatmap.dates, i = dates.indexOf(_ionoDate);
    const j = i < 0 ? dates.length - 1 : i + dir;
    if (j >= 0 && j < dates.length) loadIonoDay(dates[j]);
}

function ionoBucketText(min) {
    return min >= 1440 ? (min / 1440) + (min === 1440 ? ' day' : ' days') : min >= 60 ? (min / 60) + ' h' : min + ' min';
}

function drawIonoChart() {
    const col = anColors(), d = _ionoData, pts = (d && d.points) || [];
    const has = pts.some(p => p.n !== null || p.muf !== null);
    document.getElementById('anIonoEmpty').style.display = has ? 'none' : 'block';
    document.getElementById('anIono').parentElement.style.display = has ? 'block' : 'none';
    const raw = d && d.bucket_min <= 10;
    const sub = document.getElementById('anIonoSub');
    sub.textContent = !d ? '' : (raw
        ? 'Bars: stations heard in the 60 minutes before each snapshot. Lines: MUF (D=3000 km) and foF2 in MHz measured at Juliusruh.'
        : `${d.from} → ${d.to}, averaged over ${ionoBucketText(d.bucket_min)}: bars = average stations heard per snapshot, lines = average MUF (D=3000 km) and foF2 in MHz at Juliusruh.`) +
        ' MUF and foF2 exist only for the live-logged days (from May 2026); foF2 only after the Juliusruh monitor page became its source.';
    if (!has) { if (_anCharts.anIono) { _anCharts.anIono.destroy(); delete _anCharts.anIono; } return; }
    const oneDay = d.from === d.to;
    const label = t => d.bucket_min >= 1440 ? t.slice(0, 10) : oneDay ? t.slice(11, 16) : t.slice(5, 16);
    const datasets = [
        { type: 'bar', label: raw ? 'Stations heard' : 'Stations heard (average)', data: pts.map(p => p.n), yAxisID: 'y',
          backgroundColor: 'rgba(56,189,248,0.55)', categoryPercentage: raw ? 0.8 : 1.0, barPercentage: raw ? 0.9 : 1.0 },
    ];
    if (d.has_muf) {
        datasets.push({ type: 'line', label: 'MUF D=3000 km (MHz)', data: pts.map(p => p.muf), yAxisID: 'y2', borderColor: '#f59e0b',
                        backgroundColor: '#f59e0b', borderWidth: 2, pointRadius: pts.length > 200 ? 0 : 1.5, tension: 0.25, spanGaps: raw });
    }
    if (d.has_fof2) {
        datasets.push({ type: 'line', label: 'foF2 (MHz)', data: pts.map(p => p.fof2), yAxisID: 'y2', borderColor: '#4ade80',
                        backgroundColor: '#4ade80', borderWidth: 2, pointRadius: pts.length > 200 ? 0 : 1.5, tension: 0.25, spanGaps: raw });
    }
    anChart('anIono', {
        type: 'bar',
        data: { labels: pts.map(p => label(p.t)), datasets },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                       tooltip: { callbacks: {
                           title: it => { const p = pts[it[0].dataIndex]; return raw ? p.t + ' UTC' : `${p.t} UTC + ${ionoBucketText(d.bucket_min)}`; },
                           afterBody: it => raw ? '' : `${pts[it[0].dataIndex].snaps} snapshots averaged` } } },
            scales: {
                x:  { ticks: { color: col.text, font: { size: 10 }, maxTicksLimit: oneDay ? 24 : 16, maxRotation: 0, autoSkip: true }, grid: { display: false },
                      title: { display: true, text: 'UTC', color: col.text, font: { size: 10 } } },
                y:  { beginAtZero: true, ticks: { color: col.text, font: { size: 10 }, precision: 0 }, grid: { color: col.grid },
                      title: { display: true, text: 'stations heard', color: col.text, font: { size: 10 } } },
                y2: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { color: col.text, font: { size: 10 } },
                      title: { display: true, text: 'MHz', color: col.text, font: { size: 10 } } },
            }
        }
    });
}

// Open the History Player at a given moment (used by the Analysis tables)
async function openReplayAt(ts) {
    showView('map');
    const date = ts.slice(0, 10);
    if (_replayActive) await replayLoadDate(date, ts);
    else await enterReplay(date, ts);
}

function anColors() {
    const cs = getComputedStyle(document.documentElement);
    return { text: cs.getPropertyValue('--text-secondary').trim() || '#9ca3af',
             grid: cs.getPropertyValue('--border').trim() || '#374151',
             accent: cs.getPropertyValue('--accent').trim() || '#38bdf8' };
}

function anChart(id, cfg) {
    if (_anCharts[id]) _anCharts[id].destroy();
    cfg.options = cfg.options || {};
    cfg.options.animation = false;    // draw immediately; large datasets, no need to animate
    _anCharts[id] = new Chart(document.getElementById(id).getContext('2d'), cfg);
}

function heatColor(t) {
    const lo = isDark ? [31,41,55] : [226,232,240];
    const stops = [lo, [3,105,161], [56,189,248], [74,222,128], [250,204,21]];
    t = Math.max(0, Math.min(1, t)) * (stops.length - 1);
    const i = Math.min(Math.floor(t), stops.length - 2), f = t - i;
    const c = stops[i].map((v, k) => Math.round(v + (stops[i+1][k] - v) * f));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function drawHeatmap() {
    const cv = document.getElementById('anHeat');
    if (!cv || !_anData || _anData.empty) return;
    const hm = _anData.heatmap, grid = _anHeatMetric === 'dist' ? hm.mx : hm.n;
    const W = Math.max(cv.parentElement.clientWidth, 300);
    const left = 34, top = 6, bottom = 20, cellH = 14, H = top + 24 * cellH + bottom;
    const dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + 'px'; cv.style.height = H + 'px';
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const nd = hm.dates.length, cw = (W - left - 4) / nd;
    const vals = grid.flat().filter(v => v !== null && v > 0).sort((a, b) => a - b);
    const vmax = vals.length ? vals[Math.min(vals.length - 1, Math.floor(vals.length * 0.97))] : 1;
    const col = anColors();
    for (let h = 0; h < 24; h++) {
        for (let i = 0; i < nd; i++) {
            const v = grid[h][i];
            ctx.fillStyle = v === null ? 'rgba(128,128,128,0.10)' : heatColor(v / vmax);
            ctx.fillRect(left + i * cw, top + h * cellH, Math.ceil(cw), cellH - 1);
        }
    }
    ctx.fillStyle = col.text; ctx.font = '10px sans-serif'; ctx.textBaseline = 'middle'; ctx.textAlign = 'right';
    for (let h = 0; h < 24; h += 3) ctx.fillText(String(h).padStart(2, '0'), left - 5, top + h * cellH + cellH / 2);
    ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    let lastLbl = -100;
    hm.dates.forEach((d, i) => {
        if (d.slice(8) === '01' || i === 0) {
            const x = left + i * cw;
            if (x - lastLbl > 34) { ctx.fillText(MONTHS[+d.slice(5, 7) - 1], x, top + 24 * cellH + 4); lastLbl = x; }
        }
    });
    document.getElementById('anHeatMax').textContent =
        (_anHeatMetric === 'dist' ? Math.round(vmax).toLocaleString() + ' km' : Math.round(vmax) + ' stations') + ' (97th percentile)';
    cv._lay = { left, top, cw, cellH, nd, grid, dates: hm.dates };

    if (!cv._wired) {
        cv._wired = true;
        const tip = document.getElementById('anTip');
        cv.addEventListener('mousemove', e => {
            const L = cv._lay, rc = cv.getBoundingClientRect();
            const x = e.clientX - rc.left, y = e.clientY - rc.top;
            const i = Math.floor((x - L.left) / L.cw), h = Math.floor((y - L.top) / L.cellH);
            if (i < 0 || i >= L.nd || h < 0 || h > 23) { tip.style.display = 'none'; return; }
            const v = L.grid[h][i];
            const unit = _anHeatMetric === 'dist' ? ' km farthest' : ' stations (avg)';
            tip.textContent = `${L.dates[i]} ${String(h).padStart(2, '0')}:00 UTC — ` + (v === null ? 'no data' : v.toLocaleString() + unit);
            tip.style.display = 'block';
            tip.style.left = Math.min(x + 12, rc.width - 220) + 'px';
            tip.style.top  = (y + 14) + 'px';
        });
        cv.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
    }
}

function drawProfileChart() {
    const d = _anData, col = anColors();
    const labels = Array.from({length: 24}, (_, h) => String(h).padStart(2, '0'));
    // The 25-75 % range is drawn as floating bars (one per hour) rather than a filled
    // line band: line datasets without visible points broke the Chart.js layout here.
    anChart('anProfile', {
        type: 'bar',
        data: { labels, datasets: [
            { type: 'bar', label: '25–75 % range', data: d.profile.map(p => [p.p25, p.p75]),
              backgroundColor: 'rgba(56,189,248,0.22)', borderWidth: 0,
              barPercentage: 1.0, categoryPercentage: 1.0, order: 3 },
            { type: 'line', label: 'Median', data: d.profile.map(p => p.median), borderColor: col.accent,
              backgroundColor: col.accent, borderWidth: 2, pointRadius: 2, tension: 0.3, order: 2 },
            { type: 'line', label: d.latest.is_today ? `Today (${d.latest.date})` : `Latest day (${d.latest.date})`,
              data: d.latest.n, borderColor: '#f59e0b', backgroundColor: '#f59e0b',
              borderWidth: 2, pointRadius: 2, tension: 0.3, spanGaps: false, order: 1 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                       tooltip: { callbacks: { label: it => it.dataset.type === 'bar'
                           ? `25–75 %: ${it.raw[0]} – ${it.raw[1]}` : `${it.dataset.label}: ${it.formattedValue}` } } },
            scales: {
                x: { ticks: { color: col.text, font: { size: 10 } }, grid: { display: false },
                     title: { display: true, text: 'UTC hour', color: col.text, font: { size: 10 } } },
                y: { beginAtZero: true, ticks: { color: col.text, font: { size: 10 } }, grid: { color: col.grid },
                     title: { display: true, text: 'stations heard (60 min)', color: col.text, font: { size: 10 } } },
            }
        }
    });
}

function drawBinChart(id, bins, labelFn, xTitle) {
    const col = anColors();
    // dashed reference line at index 100 ("typical for the hour"), drawn by a tiny plugin
    const typical = { id: 'typical100', afterDatasetsDraw(chart) {
        const py = chart.scales.y.getPixelForValue(100), a = chart.chartArea;
        if (!(py >= a.top && py <= a.bottom)) return;
        const c = chart.ctx; c.save(); c.setLineDash([4, 4]); c.strokeStyle = col.text; c.lineWidth = 1;
        c.beginPath(); c.moveTo(a.left, py); c.lineTo(a.right, py); c.stroke(); c.restore();
    } };
    anChart(id, {
        type: 'bar',
        plugins: [typical],
        data: { labels: bins.map(labelFn), datasets: [
            { type: 'bar', label: 'Reporters vs. typical (%)', data: bins.map(b => b.index), yAxisID: 'y',
              backgroundColor: bins.map(b => b.index >= 100 ? 'rgba(56,189,248,0.75)' : 'rgba(245,158,11,0.75)') },
            { type: 'line', label: '% snapshots with reporter > 6000 km', data: bins.map(b => b.pct_dx), yAxisID: 'y2',
              borderColor: '#4ade80', backgroundColor: '#4ade80', borderWidth: 2, pointRadius: 3, tension: 0.25 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                tooltip: { callbacks: { afterBody: items => {
                    const b = bins[items[0].dataIndex];
                    return `${b.count.toLocaleString()} snapshots · avg ${b.avg_n} reporters · avg farthest ${b.avg_max.toLocaleString()} km`;
                } } },
            },
            scales: {
                x: { ticks: { color: col.text, font: { size: 10 } }, grid: { display: false },
                     title: { display: true, text: xTitle, color: col.text, font: { size: 10 } } },
                y: { beginAtZero: true, ticks: { color: col.text, font: { size: 10 } }, grid: { color: col.grid },
                     title: { display: true, text: 'index (100 = typical)', color: col.text, font: { size: 10 } } },
                y2: { position: 'right', beginAtZero: true, grid: { display: false },
                      ticks: { color: col.text, font: { size: 10 } },
                      title: { display: true, text: '% > 6000 km', color: col.text, font: { size: 10 } } },
            }
        }
    });
}

window.addEventListener('resize', () => {
    if (_anData && document.getElementById('analysis-view').classList.contains('active')) drawHeatmap();
});

