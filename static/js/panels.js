// Map panels: stacking, movable (and resizable) panels, the MUF graph and the Typical day graph.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, analysis-more, info, wprs, main.

'use strict';

// ── Solar panel positioning ────────────────────────────────────────────────
// Panels the user has moved (pinned) take no part in the automatic stacking.
function updateSolarPosition() {
    const solar = document.getElementById('solarPanel');
    if (!solar || solar.style.display === 'none') {
        updateReporterListPosition();
        return;
    }
    if (!isPinned('solarPanel')) {
        if (showMuf && !isPinned('mufPanel')) {
            const muf = document.getElementById('mufPanel');
            solar.style.top = (muf.offsetTop + muf.offsetHeight + 8) + 'px';
        } else {
            solar.style.top = '12px';
        }
    }
    // Chain: reporter list goes below solar
    updateReporterListPosition();
}

function updateReporterListPosition() {
    const panel = document.getElementById('reporterListPanel');
    if (!panel || panel.style.display === 'none') {
        updateHistogramPosition();
        return;
    }
    if (!isPinned('reporterListPanel')) {
        if (showSolar && !isPinned('solarPanel')) {
            const solar = document.getElementById('solarPanel');
            panel.style.top = (solar.offsetTop + solar.offsetHeight + 8) + 'px';
        } else if (showMuf && !isPinned('mufPanel')) {
            const muf = document.getElementById('mufPanel');
            panel.style.top = (muf.offsetTop + muf.offsetHeight + 8) + 'px';
        } else {
            panel.style.top = '12px';
        }
    }
    updateHistogramPosition();
}

function updateHistogramPosition() {
    const panel = document.getElementById('hgramPanel');
    if (!panel || panel.style.display === 'none' || isPinned('hgramPanel')) return;
    if (showReporterList && !isPinned('reporterListPanel')) {
        const rl = document.getElementById('reporterListPanel');
        panel.style.top = (rl.offsetTop + rl.offsetHeight + 8) + 'px';
    } else if (showSolar && !isPinned('solarPanel')) {
        const solar = document.getElementById('solarPanel');
        panel.style.top = (solar.offsetTop + solar.offsetHeight + 8) + 'px';
    } else if (showMuf && !isPinned('mufPanel')) {
        const muf = document.getElementById('mufPanel');
        panel.style.top = (muf.offsetTop + muf.offsetHeight + 8) + 'px';
    } else {
        panel.style.top = '12px';
    }
}

// ── Movable map panels ─────────────────────────────────────────────────────
// Drag a panel by its title; the place is remembered per browser. Double-click the
// title (or "Reset panel positions" in the sidebar) puts it back. The date / time
// card, the Propagation overlay under it and the MUF graph stay where they are.
// A panel with a .panel-grip (the Typical day panel) can also be resized from its corner.
const PANEL_HANDLES = {
    solarPanel: '.ov-lbl', reporterListPanel: '.rl-title',
    hgramPanel: '.hgram-title', countryOverlay: '.ov-lbl', typPanel: '.typ-title',
};
const PANEL_POS_KEY = 'wspr_panel_pos';
let _panelPos = {};              // id -> {x, y, w, h}: px from the top-left of the map view (h: resized panels only)
let _panelZ = 500;
const _panelHome = {};           // id -> comment node marking the original place of a reparented overlay

function isPinned(id) { return !!_panelPos[id]; }
function panelSavePos() { try { localStorage.setItem(PANEL_POS_KEY, JSON.stringify(_panelPos)); } catch(e) {} }

function panelApply(el, p) {
    const mv = document.getElementById('map-view');
    if (el.parentNode !== mv) {              // the overlays sit in a flex column: move them out of it
        const ph = document.createComment('panel-home');
        el.parentNode.insertBefore(ph, el);
        _panelHome[el.id] = ph;
        mv.appendChild(el);
    }
    el.classList.add('pinned');
    el.style.right = 'auto'; el.style.bottom = 'auto';
    el.style.left = p.x + 'px'; el.style.top = p.y + 'px';
    if (p.w) el.style.width = p.w + 'px';
    if (p.h) el.style.height = p.h + 'px';
    el.classList.toggle('sized', !!p.h || !!_panelSize[el.id]);     // a chosen height: the list inside scrolls (CSS)
}

function panelClamp(id) {
    const el = document.getElementById(id), p = _panelPos[id], mv = document.getElementById('map-view');
    if (!el || !p || !mv.clientWidth) return;        // map view hidden: leave positions alone
    const w = el.offsetWidth || p.w || 200, h = el.offsetHeight || 40;
    const x = Math.min(Math.max(p.x, 4), Math.max(4, mv.clientWidth - w - 4));
    const y = Math.min(Math.max(p.y, 4), Math.max(4, mv.clientHeight - Math.min(h, 60) - 4));   // keep the title reachable
    if (x !== p.x || y !== p.y) { p.x = x; p.y = y; el.style.left = x + 'px'; el.style.top = y + 'px'; }
}

// Start a move: the panel is taken out of the automatic stacking at its present place.
function panelPin(el) {
    const mv = document.getElementById('map-view');
    const r = el.getBoundingClientRect(), m = mv.getBoundingClientRect();
    const old = _panelPos[el.id];
    _panelPos[el.id] = { x: r.left - m.left, y: r.top - m.top, w: Math.round(r.width), h: old && old.h ? old.h : 0 };
    panelApply(el, _panelPos[el.id]);
    _panelZ = Math.min(_panelZ + 1, 590);
    el.style.zIndex = _panelZ;                          // the panel you move comes to the front
    return _panelPos[el.id];
}

// Resize from the corner grip: width and height are remembered with the place.  data-grip="h" on the
// panel: the height only (Reporter Countries keeps the width of the right-hand column);
// data-min-w / data-min-h: the smallest size (default 300 x 170).  data-size-only: resizing does not
// take the panel out of its place in the automatic stacking (the size is kept in PANEL_SIZE_KEY);
// otherwise (the Typical day graph, anchored at the bottom) it is pinned where it is first.
const PANEL_SIZE_KEY = 'wspr_panel_size';
let _panelSize = {};             // id -> {w, h} of the data-size-only panels
function panelSaveSize() { try { localStorage.setItem(PANEL_SIZE_KEY, JSON.stringify(_panelSize)); } catch(e) {} }
function panelApplySize(el, s) {
    if (s.w && el.dataset.grip !== 'h') el.style.width = s.w + 'px';
    el.style.height = s.h + 'px';
    el.classList.add('sized');
}

function panelGripDown(e, el) {
    if (e.button !== undefined && e.button !== 0) return;
    e.stopPropagation();
    const mv = document.getElementById('map-view');
    const x0 = e.clientX, y0 = e.clientY;
    const r0 = el.getBoundingClientRect();
    const sizeOnly = !!el.dataset.sizeOnly;
    let p = null;
    const move = ev => {
        if (!p) {
            p = sizeOnly ? (_panelSize[el.id] = { w: 0, h: 0 }) : panelPin(el);
            el.classList.add('sized'); document.body.classList.add('panel-resizing');
        }
        const r = el.getBoundingClientRect(), m = mv.getBoundingClientRect();
        const maxW = m.right - r.left - 4, maxH = m.bottom - r.top - 4;
        const minW = +el.dataset.minW || 300, minH = +el.dataset.minH || 170;
        if (el.dataset.grip !== 'h') {
            p.w = Math.round(Math.max(minW, Math.min(maxW, r0.width + ev.clientX - x0)));
            el.style.width = p.w + 'px';
        }
        p.h = Math.round(Math.max(minH, Math.min(maxH, r0.height + ev.clientY - y0)));
        el.style.height = p.h + 'px';
        if (sizeOnly) updateSolarPosition();             // the panels stacked below move with it
    };
    const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        document.body.classList.remove('panel-resizing');
        if (p) { if (sizeOnly) panelSaveSize(); else panelSavePos(); }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    e.preventDefault();
}

function panelDown(e, el) {
    if (e.button !== undefined && e.button !== 0) return;
    const x0 = e.clientX, y0 = e.clientY;
    let moved = false, base = null;
    const move = ev => {
        const dx = ev.clientX - x0, dy = ev.clientY - y0;
        if (!moved) {
            if (Math.abs(dx) + Math.abs(dy) < 4) return;       // a click, not a drag
            moved = true;
            const q = panelPin(el);
            base = { x: q.x, y: q.y };
            document.body.classList.add('panel-dragging');
        }
        const p = _panelPos[el.id];
        p.x = base.x + dx; p.y = base.y + dy;
        el.style.left = p.x + 'px'; el.style.top = p.y + 'px';
        panelClamp(el.id);
    };
    const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        document.body.classList.remove('panel-dragging');
        if (moved) { panelSavePos(); updateSolarPosition(); }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    e.preventDefault();
}

function panelReset(id) {
    const el = document.getElementById(id);
    if (!el) return;
    delete _panelPos[id];
    panelSavePos();
    if (_panelSize[id]) { delete _panelSize[id]; panelSaveSize(); }
    el.classList.remove('pinned', 'sized');
    ['left', 'top', 'right', 'bottom', 'width', 'height', 'zIndex'].forEach(k => { el.style[k] = ''; });
    const ph = _panelHome[id];
    if (ph && ph.parentNode) { ph.parentNode.insertBefore(el, ph); ph.remove(); }
    delete _panelHome[id];
    updateSolarPosition();
}

function resetAllPanels() { Object.keys(PANEL_HANDLES).forEach(panelReset); showToast('Panel positions reset'); }

function initMovablePanels() {
    let saved = {}, sizes = {};
    try { saved = JSON.parse(localStorage.getItem(PANEL_POS_KEY)) || {}; } catch(e) {}
    try { sizes = JSON.parse(localStorage.getItem(PANEL_SIZE_KEY)) || {}; } catch(e) {}
    for (const [id, sel] of Object.entries(PANEL_HANDLES)) {
        const el = document.getElementById(id), handle = el && el.querySelector(sel);
        if (!handle) continue;
        handle.classList.add('drag-handle');
        handle.title = 'Drag to move · double-click to reset';
        const q = saved[id];
        if (q && Number.isFinite(q.x) && Number.isFinite(q.y)) {
            _panelPos[id] = { x: q.x, y: q.y, w: Number.isFinite(q.w) ? q.w : 0, h: Number.isFinite(q.h) ? q.h : 0 };
            panelApply(el, _panelPos[id]);
        }
        const z = sizes[id];
        if (el.dataset.sizeOnly && z && Number.isFinite(z.h) && z.h > 0) {
            _panelSize[id] = { w: Number.isFinite(z.w) ? z.w : 0, h: z.h };
            panelApplySize(el, _panelSize[id]);
        }
        handle.addEventListener('pointerdown', e => panelDown(e, el));
        handle.addEventListener('dblclick', () => panelReset(id));
        const grip = el.querySelector('.panel-grip');
        if (grip) grip.addEventListener('pointerdown', e => panelGripDown(e, el));
        if (window.ResizeObserver) new ResizeObserver(() => panelClamp(id)).observe(el);
    }
    window.addEventListener('resize', () => Object.keys(_panelPos).forEach(panelClamp));
}

// ── MUF graph ──────────────────────────────────────────────────────────────
function toggleMuf() {
    showMuf = !showMuf;
    document.getElementById('swMuf').className        = 'sw' + (showMuf ? ' on' : '');
    document.getElementById('mufPanel').style.display = showMuf ? 'block' : 'none';
    if (showMuf) fetchMufData();
    updateSolarPosition();          // also chains → updateReporterListPosition
    saveLayerPrefs();
}

function setMufDays(d) {
    mufDays = d;
    // Update button states
    [1,2,3,7].forEach(n => {
        const id = n === 7 ? 'mufBtn7d' : `mufBtn${n}d`;
        document.getElementById(id).classList.toggle('active', n === d);
    });
    mufTitle();
    // Destroy chart so it's rebuilt with correct label format
    if (mufChart) { mufChart.destroy(); mufChart = null; }
    fetchMufData();
    saveLayerPrefs();
}

function mufTitle() {
    const labels = {1:'Last 24 h', 2:'Last 2 Days', 3:'Last 3 Days', 7:'Last 7 Days'};
    document.getElementById('mufPanelTitle').textContent =
        `MUF D=3000 km${mufFof2 ? ' & foF2' : ''} (MHz) & Reporter Count — ${labels[mufDays]}`;
}

// foF2 button: a third line (amber) on the MUF scale, from the foF2 readings of each poll
function toggleMufFof2() {
    mufFof2 = !mufFof2;
    document.getElementById('mufBtnFof2').classList.toggle('active', mufFof2);
    mufTitle();
    if (mufChart) { mufChart.destroy(); mufChart = null; }
    fetchMufData();
    saveLayerPrefs();
}

let _mufSeq = 0;
async function fetchMufData() {
    if (!showMuf) return;
    const seq = ++_mufSeq;
    try {
        const r    = await fetch(`/api/muf?band=${currentBand}&days=${mufDays}${mufFof2 ? '&fof2=1' : ''}`);
        const data = await r.json();
        if (seq !== _mufSeq) return;            // a newer request (another period, foF2 on / off) is on its way
        renderMufChart(data.muf || [], data.spots || [], mufFof2 ? (data.fof2 || []) : null);
    } catch(e) { /* silent */ }
}

function renderMufChart(mufRows, spotRows, fof2Rows) {
    // Key maps by full timestamp to preserve chronological uniqueness
    const mufMap  = {};
    mufRows.forEach(r  => { mufMap[r.timestamp]  = r.muf; });
    const spotMap = {};
    spotRows.forEach(s => {
        const key = s.timestamp;
        spotMap[key] = Math.max(spotMap[key] || 0, s.reporter_count);
    });

    const fof2Map = {};
    (fof2Rows || []).forEach(r => { fof2Map[r.timestamp] = r.fof2; });

    // Merge full timestamps and sort chronologically
    const allTimes = [...new Set([
        ...mufRows.map(r  => r.timestamp),
        ...spotRows.map(s => s.timestamp),
        ...(fof2Rows || []).map(r => r.timestamp),
    ])].sort();

    // For multi-day views label as "Mon 14:30", for single day just "14:30"
    const fmtLabel = (ts) => {
        if (mufDays <= 1) return ts.slice(11, 16);
        const d = new Date(ts.replace(' ', 'T') + 'Z');
        const day = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getUTCDay()];
        return `${day} ${ts.slice(11, 16)}`;
    };

    const chartLabels = allTimes.map(fmtLabel);
    const mufVals     = allTimes.map(t => mufMap[t]  ?? null);
    const spotVals    = allTimes.map(t => spotMap[t] || 0);
    const fof2Vals    = allTimes.map(t => fof2Map[t] ?? null);

    const darkMode  = isDark;
    const gridColor = darkMode ? '#374151' : '#cbd5e1';
    const textColor = darkMode ? '#9ca3af' : '#475569';
    // Aim for ~24 visible ticks regardless of range
    const maxTicks  = 24;

    if (mufChart) {
        mufChart.data.labels                          = chartLabels;
        mufChart.data.datasets[0].data                = mufVals;
        mufChart.data.datasets[1].data                = spotVals;
        if (fof2Rows) mufChart.data.datasets[2].data  = fof2Vals;
        mufChart.options.scales.x.ticks.color         = textColor;
        mufChart.options.scales.x.ticks.maxTicksLimit = maxTicks;
        mufChart.options.scales.x.grid.color          = gridColor;
        mufChart.options.scales.yM.ticks.color        = '#38bdf8';
        mufChart.options.scales.yM.grid.color         = gridColor;
        mufChart.options.scales.yR.ticks.color        = '#4ade80';
        mufChart.update('none');
        return;
    }

    const ctx = document.getElementById('mufCanvas').getContext('2d');
    mufChart = new Chart(ctx, {
        data: {
            labels: chartLabels,
            datasets: [
                {
                    type: 'line',
                    label: 'MUF D=3000 (MHz)',
                    data: mufVals,
                    borderColor: '#38bdf8',
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    yAxisID: 'yM',
                    tension: 0.4,
                    spanGaps: true,
                    order: 1,
                },
                {
                    type: 'bar',
                    label: 'Reporters',
                    data: spotVals,
                    backgroundColor: 'rgba(74,222,128,0.45)',
                    borderColor: '#4ade80',
                    borderWidth: 1,
                    yAxisID: 'yR',
                    order: 2,
                },
                ...(fof2Rows ? [{
                    type: 'line',
                    label: 'foF2 (MHz)',
                    data: fof2Vals,
                    borderColor: '#f59e0b',
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    yAxisID: 'yM',
                    tension: 0.4,
                    spanGaps: true,
                    order: 1,
                }] : []),
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    labels: { color: textColor, font: { size: 10 }, boxWidth: 12 }
                },
                tooltip: { titleFont: { size: 10 }, bodyFont: { size: 10 } }
            },
            scales: {
                x: {
                    ticks: {
                        color: textColor, font: { size: 9 }, maxRotation: 45,
                        maxTicksLimit: maxTicks,
                    },
                    grid: { color: gridColor }
                },
                yM: {
                    type: 'linear', position: 'left',
                    title: { display: true, text: fof2Rows ? 'MUF · foF2 (MHz)' : 'MUF (MHz)', color: '#38bdf8', font: { size: 9 } },
                    ticks: { color: '#38bdf8', font: { size: 9 } },
                    grid:  { color: gridColor }
                },
                yR: {
                    type: 'linear', position: 'right',
                    title: { display: true, text: 'Reporters', color: '#4ade80', font: { size: 9 } },
                    ticks: { color: '#4ade80', font: { size: 9 } },
                    grid:  { drawOnChartArea: false }
                }
            }
        }
    });
}


// ── Typical day (UTC) ──────────────────────────────────────────────────────
// The Analysis page's "Typical day (UTC)" card as a map panel (from 2026-11-09): stations heard in the
// last 60 minutes by UTC hour, the median and 25-75 % range over 7, 14, 30 or 90 days, and today on top.
// /api/typical_day takes it from the server's cached analysis; fetched again with every poll.
let _typData = null;

function toggleTyp() {
    showTyp = !showTyp;
    document.getElementById('swTyp').className        = 'sw' + (showTyp ? ' on' : '');
    document.getElementById('typPanel').style.display = showTyp ? 'flex' : 'none';
    if (showTyp) fetchTypData();
    else if (typChart) { typChart.destroy(); typChart = null; }
    saveLayerPrefs();
}

function setTypDays(d) {
    typDays = d;
    [7, 14, 30, 90].forEach(n => document.getElementById('typBtn' + n).classList.toggle('active', n === d));
    document.getElementById('typPanelTitle').textContent = `Typical day (UTC) — ${d} days`;
    if (showTyp) {
        document.getElementById('typNote').textContent = 'Loading …';
        fetchTypData();
    }
    saveLayerPrefs();
}

let _typSeq = 0;
async function fetchTypData() {
    if (!showTyp) return;
    const seq = ++_typSeq, days = typDays;
    try {
        const r = await fetch(`/api/typical_day?band=${currentBand}&days=${days}`);
        const d = await r.json();
        if (seq !== _typSeq || days !== typDays || !showTyp) return;       // a newer request is on its way
        _typData = d;
        renderTypChart();
    } catch (e) { /* silent: the next poll tries again */ }
}

function renderTypChart() {
    const d = _typData, note = document.getElementById('typNote');
    if (!d || d.empty) {
        if (typChart) { typChart.destroy(); typChart = null; }
        note.textContent = `No data in the last ${typDays} days — the transmitter may be off; try a longer period.`;
        return;
    }
    note.textContent = `${d.n_days} days with data, ${d.from} – ${d.to}`;
    const col = anColors();
    const labels = Array.from({length: 24}, (_, h) => String(h).padStart(2, '0'));
    const todayLbl = d.latest.is_today ? `Today (${d.latest.date})` : `Latest day (${d.latest.date})`;
    const data = [d.profile.map(p => [p.p25, p.p75]), d.profile.map(p => p.median), d.latest.n];
    if (typChart) {
        data.forEach((v, i) => { typChart.data.datasets[i].data = v; });
        typChart.data.datasets[1].borderColor = typChart.data.datasets[1].backgroundColor = col.accent;
        typChart.data.datasets[2].label = todayLbl;
        const o = typChart.options;
        o.plugins.legend.labels.color = col.text;
        o.scales.x.ticks.color = o.scales.x.title.color = col.text;
        o.scales.y.ticks.color = o.scales.y.title.color = col.text;
        o.scales.y.grid.color = col.grid;
        typChart.update('none');
        return;
    }
    // The 25-75 % range as floating bars, as on the Analysis page (drawProfileChart)
    typChart = new Chart(document.getElementById('typCanvas'), {
        type: 'bar',
        data: { labels, datasets: [
            { type: 'bar', label: '25–75 % range', data: data[0], backgroundColor: 'rgba(56,189,248,0.22)', borderWidth: 0,
              barPercentage: 1.0, categoryPercentage: 1.0, order: 3 },
            { type: 'line', label: 'Median', data: data[1], borderColor: col.accent, backgroundColor: col.accent,
              borderWidth: 2, pointRadius: 2, tension: 0.3, order: 2 },
            { type: 'line', label: todayLbl, data: data[2], borderColor: '#f59e0b', backgroundColor: '#f59e0b',
              borderWidth: 2, pointRadius: 2, tension: 0.3, spanGaps: false, order: 1 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                       tooltip: { titleFont: { size: 10 }, bodyFont: { size: 10 },
                                  callbacks: { title: it => `${it[0].label}:00–${it[0].label}:59 UTC`,
                                               label: it => it.dataset.type === 'bar'
                                                   ? `25–75 %: ${it.raw[0]} – ${it.raw[1]}` : `${it.dataset.label}: ${it.formattedValue}` } } },
            scales: {
                x: { ticks: { color: col.text, font: { size: 9 } }, grid: { display: false },
                     title: { display: true, text: 'UTC hour', color: col.text, font: { size: 9 } } },
                y: { beginAtZero: true, ticks: { color: col.text, font: { size: 9 } }, grid: { color: col.grid },
                     title: { display: true, text: 'stations heard (60 min)', color: col.text, font: { size: 9 } } },
            }
        }
    });
}
