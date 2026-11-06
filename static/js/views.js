// Sidebar, view switching, today / 1 h statistics, History and Statistics pages.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, info, wprs, main.

'use strict';

// ── Sidebar collapse ───────────────────────────────────────────────────────
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('collapsed');
    // Let the CSS transition finish before telling Leaflet to resize
    setTimeout(() => { liveMap && liveMap.invalidateSize(); }, 270);
    setTimeout(() => { histMap && histMap.invalidateSize(); }, 270);
    setTimeout(() => { wprsMap && wprsMap.invalidateSize(); }, 270);
}

// ── Trail / Home toggles ───────────────────────────────────────────────────
function toggleTrail() {
    showTrail = !showTrail;
    document.getElementById('swTrail').className = 'sw' + (showTrail ? ' on' : '');
    if (showTrail) { refreshTrail(); }
    else if (liveTrail) { liveMap.removeLayer(liveTrail); liveTrail = null; }
    saveLayerPrefs();
}

// ── View switching ─────────────────────────────────────────────────────────
function showView(name) {
    if (name !== 'map') replayPause();
    if (name !== 'wprs') wprsPause();
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.getElementById(name+'-view').classList.add('active');
    document.getElementById('nav-'+name).classList.add('active');

    if (name === 'map') {
        setTimeout(() => liveMap && liveMap.invalidateSize(), 60);
    } else if (name === 'history') {
        if (!histMap) initHistMap();
        setTimeout(() => histMap && histMap.invalidateSize(), 60);
        setHistDate(0); loadHistory();
    } else if (name === 'stats') {
        setStatsDate(0); loadStats();
    } else if (name === 'analysis') {
        loadAnalysis();
    } else if (name === 'wprs') {
        if (!wprsMap) initWprsMap();
        setTimeout(() => wprsMap && wprsMap.invalidateSize(), 60);
        loadWprs();
    }
    // The address bar follows the page, so a copied link opens the same view
    // (history and statistics add their date when they load, WPRS its drive).
    if (name === 'map') setHash('');
    else if (name === 'wprs') setHash(wprsSel ? wprsHash() : 'wprs');
    else if (name === 'analysis') setHash('analysis');
}

// ── Stats window toggle ────────────────────────────────────────────────────
function setStatsWindow(w) {
    statsWindow = w;
    document.getElementById('tabToday').classList.toggle('active', w === 'today');
    document.getElementById('tab1h').classList.toggle('active',    w === '1h');
    document.getElementById('miniStatsTitle').textContent = w === '1h' ? 'Last 1h' : 'Today';
    fetchTodayStats();
    saveLayerPrefs();
}

// ── Today / 1h stats sidebar ───────────────────────────────────────────────
async function fetchTodayStats() {
    try {
        let spotCount, maxDX, maxReporters;

        if (statsWindow === '1h') {
            // Fetch positions from the last hour and aggregate client-side
            const now = new Date();
            const ago = new Date(now - 3600 * 1000);
            const fmt = d => d.toISOString().replace('T', ' ').slice(0, 19);
            const r     = await fetch(
                `/api/positions?from=${encodeURIComponent(fmt(ago))}&to=${encodeURIComponent(fmt(now))}&band=${currentBand}`
            );
            const spots = await r.json();
            spotCount   = spots.length;
            maxDX       = spots.reduce((m, s) => Math.max(m, s.max_distance   || 0), 0);
            maxReporters= spots.reduce((m, s) => Math.max(m, s.reporter_count || 0), 0);
        } else {
            const r  = await fetch(`/api/stats?date=${todayStr()}&band=${currentBand}`);
            const data = await r.json();
            const s  = data.stats || {};
            spotCount    = s.spot_count    || 0;
            maxDX        = s.max_distance  || 0;
            maxReporters = s.max_reporters || 0;
        }

        document.getElementById('todaySpots').textContent     = spotCount;
        document.getElementById('todayDX').textContent        = maxDX       ? maxDX + ' km' : '—';
        document.getElementById('todayReporters').textContent = maxReporters || '—';
        document.getElementById('todayBand').textContent      = BAND_NAMES[currentBand] || currentBand+'MHz';
    } catch(e) { /* silent */ }
}

// ── History ────────────────────────────────────────────────────────────────
function setHistDate(offset) {
    const d = new Date(); d.setDate(d.getDate() + offset);
    document.getElementById('histDate').value = d.toISOString().split('T')[0];
}

async function loadHistory() {
    const date = document.getElementById('histDate').value;
    if (!date) return;
    setHash('history=' + date);
    try {
        const r     = await fetch(`/api/positions?date=${date}&band=${currentBand}`);
        const spots = await r.json();
        renderHistTable(spots);
        renderHistMap(spots);
    } catch(e) { showToast('Failed to load history', 'err'); }
}

function renderHistTable(spots) {
    const tbody = document.getElementById('histTbody');
    if (!spots.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="no-data">No data for this date</td></tr>';
        return;
    }
    tbody.innerHTML = [...spots].reverse().map(s =>
        `<tr>
            <td>${s.timestamp.split(' ')[1]}</td>
            <td class="mono">${escHtml(s.tx_loc)}</td>
            <td>${s.reporter_count}</td>
            <td>${s.max_distance || '—'}</td>
        </tr>`
    ).join('');
}

function renderHistMap(spots) {
    if (!histMap) return;
    if (histTrail) { histMap.removeLayer(histTrail); histTrail = null; }
    histMarkers.forEach(m => histMap.removeLayer(m));
    histMarkers = [];
    if (!spots.length) return;

    const pts = spots.map(s => [s.lat, s.lon]);

    if (pts.length > 1) {
        histTrail = L.polyline(pts, {
            color:'#38bdf8', weight:2.5, opacity:.7
        }).addTo(histMap);
    }

    spots.forEach((s, i) => {
        const last   = i === spots.length - 1;
        const first  = i === 0;
        const color  = last ? '#38bdf8' : first ? '#4ade80' : '#94a3b8';
        const radius = last ? 8 : 5;
        const m = L.circleMarker([s.lat, s.lon], {
            radius, color, fillColor:color, fillOpacity:.85, weight:2
        }).addTo(histMap).bindPopup(
            `<strong>${s.tx_loc}</strong><br>
             ${s.timestamp}<br>
             Reporters: ${s.reporter_count}<br>
             Max DX: ${s.max_distance} km`
        );
        histMarkers.push(m);
    });

    histMap.fitBounds(L.latLngBounds(pts), { padding:[40,40] });
}

// ── Statistics ─────────────────────────────────────────────────────────────
function setStatsDate(offset) {
    const d = new Date(); d.setDate(d.getDate() + offset);
    document.getElementById('statsDate').value = d.toISOString().split('T')[0];
}

let _stDaily = [];
let _stDay   = [];
let _stRange = 90;
let _stAllBest = 0;

function shiftStatsDate(dir) {
    const el = document.getElementById('statsDate');
    const d  = new Date((el.value || todayStr()) + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() + dir);
    el.value = d.toISOString().slice(0, 10);
    loadStats();
}

function setStatsRange(n) {
    _stRange = n;
    [[30,'stR30'],[90,'stR90'],[0,'stR0']].forEach(([v,id]) =>
        document.getElementById(id).classList.toggle('active', v === n));
    drawStatsHistChart();
}

async function loadStats() {
    const date = document.getElementById('statsDate').value;
    if (!date) return;
    setHash('stats=' + date);
    try {
        const [data, pos, daily] = await Promise.all([
            fetch(`/api/stats?date=${date}&band=${currentBand}`).then(r => r.json()),
            fetch(`/api/positions?date=${date}&band=${currentBand}`).then(r => r.json()),
            fetch(`/api/daily_summary?band=${currentBand}`).then(r => r.json()),
        ]);
        const s  = data.stats || {};
        const at = data.all_time || {};
        _stDay   = Array.isArray(pos) ? pos : [];
        _stDaily = Array.isArray(daily) ? daily : [];
        _stAllBest = at.best_dx || 0;

        document.getElementById('stDayLabel').textContent =
            new Date(date + 'T00:00:00Z').toLocaleDateString('en-GB',
                { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });

        document.getElementById('stSpots').textContent   = s.spot_count    || 0;
        document.getElementById('stMaxRprt').textContent = s.max_reporters || '—';
        const dayDX = s.max_distance || 0;
        const dxEl  = document.getElementById('stMaxDX');
        dxEl.textContent = dayDX ? dayDX.toLocaleString() : '—';
        const isRecord = dayDX > 0 && dayDX >= _stAllBest;
        dxEl.classList.toggle('hit', isRecord);
        document.getElementById('stMaxDXSub').textContent = isRecord ? '🏆 all-time best'
            : (dayDX && _stAllBest ? `km · ${Math.round(100 * dayDX / _stAllBest)} % of record` : 'km');
        const avg = _stDay.length ? _stDay.reduce((a, x) => a + (x.reporter_count || 0), 0) / _stDay.length : null;
        document.getElementById('stAvgRprt').textContent = avg === null ? '—' : avg.toFixed(1);
        document.getElementById('stFirst').textContent   = s.first_spot ? s.first_spot.split(' ')[1] : '—';
        document.getElementById('stLast').textContent    = s.last_spot  ? s.last_spot.split(' ')[1]  : '—';

        // All-time records, with the date each record was set (from the daily summary)
        const bestDxDay  = _stDaily.find(x => x.max_dx === at.best_dx);
        const bestRepDay = _stDaily.find(x => x.max_reporters === at.best_reporters);
        document.getElementById('atSpots').textContent = at.total_spots ? at.total_spots.toLocaleString() : '—';
        document.getElementById('atDX').textContent    = at.best_dx ? at.best_dx.toLocaleString() + ' km' : '—';
        document.getElementById('atDXSub').textContent = bestDxDay ? bestDxDay.date : '';
        document.getElementById('atRprt').textContent  = at.best_reporters || '—';
        document.getElementById('atRprtSub').textContent = bestRepDay ? bestRepDay.date : '';
        document.getElementById('atDays').textContent  = at.active_days    || '—';
        document.getElementById('atFirst').textContent = at.first_ever     || '—';
        document.getElementById('atLast').textContent  = at.last_ever      || '—';

        document.getElementById('dateChips').innerHTML = (data.available_dates || []).map(d =>
            `<span class="quick-btn${d === date ? ' active-qb' : ''}"
                   onclick="document.getElementById('statsDate').value='${d}';loadStats()">${d}</span>`
        ).join('');

        renderStatsCharts();
    } catch(e) { showToast('Failed to load stats', 'err'); }
}

function renderStatsCharts() {
    drawStatsDayChart();
    drawStatsHistChart();
}

function drawStatsDayChart() {
    const col = anColors(), has = _stDay.length > 0;
    document.getElementById('stDayEmpty').style.display = has ? 'none' : 'block';
    document.getElementById('stDayChart').parentElement.style.display = has ? 'block' : 'none';
    if (!has) { if (_anCharts.stDayChart) { _anCharts.stDayChart.destroy(); delete _anCharts.stDayChart; } return; }
    anChart('stDayChart', {
        type: 'bar',
        data: { labels: _stDay.map(x => x.timestamp.slice(11, 16)), datasets: [
            { type: 'bar', label: 'Reporters', data: _stDay.map(x => x.reporter_count), yAxisID: 'y',
              backgroundColor: 'rgba(56,189,248,0.65)' },
            { type: 'line', label: 'Farthest (km)', data: _stDay.map(x => x.max_distance), yAxisID: 'y2',
              borderColor: '#4ade80', backgroundColor: '#4ade80', borderWidth: 2, pointRadius: 2, tension: 0.2 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } } },
            scales: {
                x:  { ticks: { color: col.text, font: { size: 10 }, maxTicksLimit: 24, maxRotation: 0 }, grid: { display: false } },
                y:  { beginAtZero: true, ticks: { color: col.text, font: { size: 10 }, precision: 0 }, grid: { color: col.grid },
                      title: { display: true, text: 'reporters', color: col.text, font: { size: 10 } } },
                y2: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { color: col.text, font: { size: 10 } },
                      title: { display: true, text: 'km', color: col.text, font: { size: 10 } } },
            }
        }
    });
}

function drawStatsHistChart() {
    const col = anColors();
    const sel = document.getElementById('statsDate').value;
    let rows = _stDaily;
    if (_stRange > 0 && rows.length) {
        const cut = new Date(); cut.setUTCDate(cut.getUTCDate() - _stRange);
        const cutS = cut.toISOString().slice(0, 10);
        rows = rows.filter(x => x.date >= cutS);
    }
    anChart('stHistChart', {
        type: 'bar',
        data: { labels: rows.map(x => x.date.slice(5)), datasets: [
            { type: 'bar', label: 'Best DX (km)', data: rows.map(x => x.max_dx), yAxisID: 'y',
              backgroundColor: rows.map(x => x.date === sel ? '#f59e0b' : 'rgba(56,189,248,0.65)') },
            { type: 'line', label: 'Max reporters', data: rows.map(x => x.max_reporters), yAxisID: 'y2',
              borderColor: '#4ade80', backgroundColor: '#4ade80', borderWidth: 1.5, pointRadius: 2, tension: 0.2 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false,
            onClick: (e, els) => {
                if (els.length) {
                    document.getElementById('statsDate').value = rows[els[0].index].date;
                    loadStats();
                }
            },
            onHover: (e, els) => { e.native.target.style.cursor = els.length ? 'pointer' : 'default'; },
            plugins: {
                legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                tooltip: { callbacks: { title: items => rows[items[0].dataIndex].date,
                                        afterBody: items => `${rows[items[0].dataIndex].spots} transmissions logged` } },
            },
            scales: {
                x:  { ticks: { color: col.text, font: { size: 10 }, maxTicksLimit: 20, maxRotation: 0 }, grid: { display: false } },
                y:  { beginAtZero: true, ticks: { color: col.text, font: { size: 10 } }, grid: { color: col.grid },
                      title: { display: true, text: 'km', color: col.text, font: { size: 10 } } },
                y2: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { color: col.text, font: { size: 10 }, precision: 0 },
                      title: { display: true, text: 'reporters', color: col.text, font: { size: 10 } } },
            }
        }
    });
}

