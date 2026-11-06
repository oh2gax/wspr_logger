// Map panels: stacking, movable panels and the MUF graph.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, info, wprs, main.

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
const PANEL_HANDLES = {
    solarPanel: '.ov-lbl', reporterListPanel: '.rl-title',
    hgramPanel: '.hgram-title', countryOverlay: '.ov-lbl',
};
const PANEL_POS_KEY = 'wspr_panel_pos';
let _panelPos = {};              // id -> {x, y, w}: px from the top-left of the map view
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
}

function panelClamp(id) {
    const el = document.getElementById(id), p = _panelPos[id], mv = document.getElementById('map-view');
    if (!el || !p || !mv.clientWidth) return;        // map view hidden: leave positions alone
    const w = el.offsetWidth || p.w || 200, h = el.offsetHeight || 40;
    const x = Math.min(Math.max(p.x, 4), Math.max(4, mv.clientWidth - w - 4));
    const y = Math.min(Math.max(p.y, 4), Math.max(4, mv.clientHeight - Math.min(h, 60) - 4));   // keep the title reachable
    if (x !== p.x || y !== p.y) { p.x = x; p.y = y; el.style.left = x + 'px'; el.style.top = y + 'px'; }
}

function panelDown(e, el) {
    if (e.button !== undefined && e.button !== 0) return;
    const mv = document.getElementById('map-view');
    const x0 = e.clientX, y0 = e.clientY;
    let moved = false, base = null;
    const move = ev => {
        const dx = ev.clientX - x0, dy = ev.clientY - y0;
        if (!moved) {
            if (Math.abs(dx) + Math.abs(dy) < 4) return;       // a click, not a drag
            moved = true;
            const r = el.getBoundingClientRect(), m = mv.getBoundingClientRect();
            base = { x: r.left - m.left, y: r.top - m.top };
            _panelPos[el.id] = { x: base.x, y: base.y, w: Math.round(r.width) };
            panelApply(el, _panelPos[el.id]);
            _panelZ = Math.min(_panelZ + 1, 590);
            el.style.zIndex = _panelZ;                          // the panel you move comes to the front
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
    el.classList.remove('pinned');
    ['left', 'top', 'right', 'bottom', 'width', 'zIndex'].forEach(k => { el.style[k] = ''; });
    const ph = _panelHome[id];
    if (ph && ph.parentNode) { ph.parentNode.insertBefore(el, ph); ph.remove(); }
    delete _panelHome[id];
    updateSolarPosition();
}

function resetAllPanels() { Object.keys(PANEL_HANDLES).forEach(panelReset); showToast('Panel positions reset'); }

function initMovablePanels() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(PANEL_POS_KEY)) || {}; } catch(e) {}
    for (const [id, sel] of Object.entries(PANEL_HANDLES)) {
        const el = document.getElementById(id), handle = el && el.querySelector(sel);
        if (!handle) continue;
        handle.classList.add('drag-handle');
        handle.title = 'Drag to move · double-click to reset';
        const q = saved[id];
        if (q && Number.isFinite(q.x) && Number.isFinite(q.y)) {
            _panelPos[id] = { x: q.x, y: q.y, w: Number.isFinite(q.w) ? q.w : 0 };
            panelApply(el, _panelPos[id]);
        }
        handle.addEventListener('pointerdown', e => panelDown(e, el));
        handle.addEventListener('dblclick', () => panelReset(id));
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
    // Update panel title
    const labels = {1:'Last 24 h', 2:'Last 2 Days', 3:'Last 3 Days', 7:'Last 7 Days'};
    document.getElementById('mufPanelTitle').textContent =
        `MUF D=3000 km (MHz) & Reporter Count — ${labels[d]}`;
    // Destroy chart so it's rebuilt with correct label format
    if (mufChart) { mufChart.destroy(); mufChart = null; }
    fetchMufData();
    saveLayerPrefs();
}

async function fetchMufData() {
    if (!showMuf) return;
    try {
        const r    = await fetch(`/api/muf?band=${currentBand}&days=${mufDays}`);
        const data = await r.json();
        renderMufChart(data.muf || [], data.spots || []);
    } catch(e) { /* silent */ }
}

function renderMufChart(mufRows, spotRows) {
    // Key maps by full timestamp to preserve chronological uniqueness
    const mufMap  = {};
    mufRows.forEach(r  => { mufMap[r.timestamp]  = r.muf; });
    const spotMap = {};
    spotRows.forEach(s => {
        const key = s.timestamp;
        spotMap[key] = Math.max(spotMap[key] || 0, s.reporter_count);
    });

    // Merge full timestamps and sort chronologically
    const allTimes = [...new Set([
        ...mufRows.map(r  => r.timestamp),
        ...spotRows.map(s => s.timestamp)
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

    const darkMode  = isDark;
    const gridColor = darkMode ? '#374151' : '#cbd5e1';
    const textColor = darkMode ? '#9ca3af' : '#475569';
    // Aim for ~24 visible ticks regardless of range
    const maxTicks  = 24;

    if (mufChart) {
        mufChart.data.labels                          = chartLabels;
        mufChart.data.datasets[0].data                = mufVals;
        mufChart.data.datasets[1].data                = spotVals;
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
                }
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
                    title: { display: true, text: 'MUF (MHz)', color: '#38bdf8', font: { size: 9 } },
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

