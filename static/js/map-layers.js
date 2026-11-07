// Map layers: reporter plot, day / night overlay, solar conditions, reporter list and histogram.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, info, wprs, main.

'use strict';

// ── Great-circle path helper ─────────────────────────────────────────────────
/**
 * Return an array of [lat, lon] waypoints following the great-circle arc
 * between two points, split at the antimeridian so Leaflet doesn't wrap
 * across the map incorrectly.  Uses spherical SLERP interpolation.
 */
function greatCirclePoints(lat1, lon1, lat2, lon2, steps) {
    steps = steps || 60;
    const toRad = d => d * Math.PI / 180;
    const toDeg = r => r * 180 / Math.PI;

    // Convert to unit-sphere Cartesian
    function toXYZ(lat, lon) {
        const φ = toRad(lat), λ = toRad(lon);
        return [Math.cos(φ)*Math.cos(λ), Math.cos(φ)*Math.sin(λ), Math.sin(φ)];
    }
    function fromXYZ(v) {
        const lat = toDeg(Math.asin(v[2]));
        const lon = toDeg(Math.atan2(v[1], v[0]));
        return [lat, lon];
    }
    function dot(a, b) { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
    function scale(v, s) { return [v[0]*s, v[1]*s, v[2]*s]; }
    function add(a, b) { return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]; }

    const A = toXYZ(lat1, lon1);
    const B = toXYZ(lat2, lon2);
    const cosΩ = Math.max(-1, Math.min(1, dot(A, B)));
    const Ω    = Math.acos(cosΩ);

    const pts = [];
    for (let i = 0; i <= steps; i++) {
        const t = i / steps;
        let v;
        if (Ω < 1e-10) {
            v = A;
        } else {
            const sA = Math.sin((1-t)*Ω) / Math.sin(Ω);
            const sB = Math.sin(   t *Ω) / Math.sin(Ω);
            v = add(scale(A, sA), scale(B, sB));
        }
        pts.push(fromXYZ(v));
    }

    // Split at antimeridian crossings into separate polyline segments
    const segments = [[]];
    for (let i = 0; i < pts.length; i++) {
        segments[segments.length - 1].push(pts[i]);
        if (i < pts.length - 1) {
            const dLon = pts[i+1][1] - pts[i][1];
            if (Math.abs(dLon) > 180) {
                segments.push([]);  // start new segment after wrap
            }
        }
    }
    return segments;   // array of arrays of [lat, lon]
}

// ── Reporter Plot ────────────────────────────────────────────────────────────
function maidenheadToLatLon(grid) {
    if (!grid || grid.length < 4) return null;
    const g = grid.toUpperCase();
    try {
        let lon = (g.charCodeAt(0) - 65) * 20 - 180;
        let lat = (g.charCodeAt(1) - 65) * 10 - 90;
        lon += (g.charCodeAt(2) - 48) * 2;
        lat += (g.charCodeAt(3) - 48) * 1;
        if (g.length >= 6 && /^[A-X]{2}$/.test(g.slice(4, 6))) {
            lon += (g.charCodeAt(4) - 65) * (2.0 / 24.0) + (2.0 / 24.0) / 2;     // centre of the subsquare
            lat += (g.charCodeAt(5) - 65) * (1.0 / 24.0) + (1.0 / 24.0) / 2;
        } else {
            lon += 1.0;                                                        // centre of the 2° x 1° square
            lat += 0.5;
        }
        if (!(lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180)) return null;
        return [lat, lon];
    } catch(e) { return null; }
}

function toggleReporterPlot() {
    showReporterPlot = !showReporterPlot;
    document.getElementById('swReporterPlot').className = 'sw' + (showReporterPlot ? ' on' : '');
    if (!showReporterPlot) {
        clearReporterPlot();
    } else {
        fetchReporterList();   // fetches & renders; guard inside handles dual-use
    }
    saveLayerPrefs();
}

function clearReporterPlot() {
    if (reporterPlotLayer) reporterPlotLayer.clearLayers();
}

function renderReporterPlot() {
    if (!showReporterPlot || !liveMap) return;
    if (!reporterPlotLayer) {
        reporterPlotLayer = L.layerGroup().addTo(liveMap);
    }
    reporterPlotLayer.clearLayers();
    if (_txLat === null || !_reporterListData.length) return;

    // Normalise SNR to opacity and line weight
    const snrs    = _reporterListData.map(r => r.snr);
    const minSnr  = Math.min(...snrs);
    const maxSnr  = Math.max(...snrs);
    const snrSpan = maxSnr - minSnr || 1;

    const accent = '#38bdf8';

    _reporterListData.forEach(r => {
        const pos = maidenheadToLatLon(r.grid);
        if (!pos) return;
        const norm    = (r.snr - minSnr) / snrSpan;   // 0 = weakest, 1 = strongest
        const opacity = 0.18 + norm * 0.72;            // 0.18 → 0.90
        const weight  = 1 + norm * 2.5;                // 1 px → 3.5 px

        // Great-circle line: TX → reporter (split at antimeridian if needed)
        const gcSegs = greatCirclePoints(_txLat, _txLon, pos[0], pos[1], 60);
        gcSegs.forEach(seg => {
            if (seg.length > 1) {
                L.polyline(seg, { color: accent, weight, opacity })
                 .addTo(reporterPlotLayer);
            }
        });

        // Reporter circle
        L.circleMarker(pos, {
            radius: 5,
            color: accent,
            fillColor: accent,
            fillOpacity: opacity,
            weight: 1.5,
        }).bindPopup(
            `<strong>${escHtml(r.callsign)}</strong><br>` +
            `Grid: ${escHtml(r.grid)}<br>` +
            `SNR: ${r.snr} dB<br>` +
            `Dist: ${r.distance} km`
        ).addTo(reporterPlotLayer);
    });
}

// ── Day / Night / Grayline overlay ──────────────────────────────────────────
/**
 * Compute the subsolar point (lat, lon) for a given UTC Date.
 * Uses a simplified low-accuracy solar position model.
 */
function sunPosition(date) {
    const toRad = d => d * Math.PI / 180;
    const toDeg = r => r * 180 / Math.PI;

    const JD = date / 86400000 + 2440587.5;
    const n  = JD - 2451545.0;   // days since J2000.0

    // Mean longitude and mean anomaly (degrees, kept positive)
    const L0 = ((280.46646 + 0.9856474 * n) % 360 + 360) % 360;
    const M  = toRad(((357.52911 + 0.9856003 * n) % 360 + 360) % 360);

    // Equation of centre → Sun's true longitude
    const C   = 1.9146 * Math.sin(M) + 0.0200 * Math.sin(2*M) + 0.0003 * Math.sin(3*M);
    const lam = toRad(L0 + C);

    // Obliquity, right ascension, declination
    const eps = toRad(23.439 - 0.0000004 * n);
    const RA  = Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam));
    const dec = Math.asin(Math.sin(eps) * Math.sin(lam));

    // Greenwich Mean Sidereal Time — correct formula with J2000.0 epoch offset.
    // The old approach (UTC_hours × 15) is off by ~135° today; this is exact.
    const GMST = ((280.46061837 + 360.98564724 * n) % 360 + 360) % 360;

    // Greenwich Hour Angle → subsolar longitude
    const GHA = ((GMST - toDeg(RA)) % 360 + 360) % 360;
    let lon = -GHA;
    if (lon < -180) lon += 360;
    if (lon >  180) lon -= 360;

    return { lat: toDeg(dec), lon };
}

/**
 * Compute the terminator latitude at a given longitude.
 *
 * The terminator satisfies:
 *   sin(φs)·sin(φ) + cos(φs)·cos(φ)·cos(λ−λs) = 0
 * Rearranging:
 *   tan(φ) = −cos(λ−λs) / tan(φs)
 *   φ = atan(−cos(Δλ) / tan(φs))
 *
 * sunLat/sunLon in degrees, lon in degrees, returns lat in degrees.
 * The optional offsetDeg shifts the boundary (positive = toward night side).
 */
function terminatorLatAt(lon, sunLat, sunLon, offsetDeg) {
    const toRad = d => d * Math.PI / 180;
    const toDeg = r => r * 180 / Math.PI;
    offsetDeg = offsetDeg || 0;
    const dLon   = toRad(lon - sunLon);
    const tanSun = Math.tan(toRad(sunLat));
    // Handle near-equinox edge case (terminator is a meridian)
    if (Math.abs(tanSun) < 1e-9) {
        return Math.cos(dLon) >= 0 ? -(90 - offsetDeg) : (90 - offsetDeg);
    }
    // Basic terminator lat at this longitude
    const lat = toDeg(Math.atan(-Math.cos(dLon) / tanSun));
    // Shift toward night by offsetDeg along the meridian
    // (positive offset pushes boundary into the night side)
    return lat - offsetDeg * Math.sign(sunLat) * Math.sign(Math.cos(dLon + Math.PI / 2));
}

/**
 * Build the night-hemisphere polygon and a pair of terminator line arrays.
 * Returns { nightPoly, termLine, grayLine }.
 *
 * The polygon is constructed as:
 *   terminator points (lon −180 → 180) + night-pole corners to close it.
 *
 * Night pole = south pole when sun is in northern hemisphere, and vice versa.
 * This is the same approach used by the Leaflet.terminator plugin.
 */
function buildNightPolygon(sunLat, sunLon) {
    const termLine = [];
    for (let lon = -180; lon <= 180; lon++) {
        termLine.push([terminatorLatAt(lon, sunLat, sunLon, 0), lon]);
    }
    // The night pole is the pole NOT illuminated
    const nightPole = sunLat >= 0 ? -90 : 90;
    // Close the polygon by adding the two corners of the night pole strip
    const nightPoly = termLine.concat([
        [nightPole, 180],
        [nightPole, -180]
    ]);
    return { nightPoly, termLine };
}

function renderDayNight() {
    if (!showDayNight || !liveMap) return;
    if (!dayNightLayer) {
        dayNightLayer = L.layerGroup().addTo(liveMap);
    }
    dayNightLayer.clearLayers();

    const now = new Date();
    const sun = sunPosition(now);
    const { nightPoly, termLine } = buildNightPolygon(sun.lat, sun.lon);

    // Night fill — rendered in the custom dayNightPane (z-index 300) so it
    // always sits below Reporter Plot lines (default overlayPane, z-index 400),
    // preventing brightness flicker when the polygon is cleared and redrawn.
    L.polygon(nightPoly, {
        color: 'none',
        fillColor: '#1a3a5c',
        fillOpacity: 0.40,
        stroke: false,
        interactive: false,
        pane: 'dayNightPane',
    }).addTo(dayNightLayer);

    // Terminator — single dashed amber line, split at large lat jumps (polar wrap)
    const segs = [[]];
    for (let i = 0; i < termLine.length; i++) {
        segs[segs.length - 1].push(termLine[i]);
        if (i < termLine.length - 1 &&
            Math.abs(termLine[i+1][0] - termLine[i][0]) > 60) {
            segs.push([]);
        }
    }
    segs.forEach(seg => {
        if (seg.length > 1) {
            L.polyline(seg, {
                color: '#fbbf24', weight: 1.5, opacity: 0.80,
                dashArray: '6 5', interactive: false,
                pane: 'dayNightPane',
            }).addTo(dayNightLayer);
        }
    });
}

function clearDayNight() {
    if (dayNightLayer) dayNightLayer.clearLayers();
}

function toggleDayNight() {
    showDayNight = !showDayNight;
    document.getElementById('swDayNight').className = 'sw' + (showDayNight ? ' on' : '');
    if (showDayNight) {
        renderDayNight();
        _dayNightTimer = setInterval(renderDayNight, 60000);
    } else {
        clearInterval(_dayNightTimer);
        _dayNightTimer = null;
        clearDayNight();
    }
    saveLayerPrefs();
}

// ── Solar conditions ────────────────────────────────────────────────────────
function toggleSolar() {
    showSolar = !showSolar;
    document.getElementById('swSolar').className        = 'sw' + (showSolar ? ' on' : '');
    document.getElementById('solarPanel').style.display = showSolar ? 'block' : 'none';
    if (showSolar) {
        updateSolarPosition();      // also chains → updateReporterListPosition
        fetchSolarData();
        _solarTimer = setInterval(fetchSolarData, 60000);
    } else {
        clearInterval(_solarTimer);
        _solarTimer = null;
        updateReporterListPosition();   // re-stack without solar
    }
    saveLayerPrefs();
}

async function fetchSolarData() {
    if (!showSolar) return;
    if (_replayActive) { applyReplayFrame(); return; }
    try {
        const r    = await fetch('/api/solar');
        renderSolar(await r.json());
    } catch(e) { /* silent */ }
}

// Fill the Solar Conditions panel from a dict with the /api/solar keys
// (used for live data and for replay frames).
function renderSolar(data) {
    try {
        document.getElementById('solSFI').textContent  = data.sfi      ?? '—';
        // A-index colour coding (NOAA scale)
        const aEl  = document.getElementById('solA');
        const aVal = parseInt(data.aindex) || 0;
        aEl.textContent = data.aindex ?? '—';
        aEl.style.color = aVal >= 100 ? '#9333ea'   // Severe storm — purple
                        : aVal >= 50  ? '#ef4444'   // Major storm  — red
                        : aVal >= 30  ? '#f97316'   // Minor storm  — orange
                        : aVal >= 16  ? '#facc15'   // Active       — yellow
                        : aVal >= 8   ? '#a3e635'   // Unsettled    — yellow-green
                        : '';                        // Quiet        — default accent
        // Bz colour coding (nT, diverging scale)
        const bzEl  = document.getElementById('solBz');
        const bzVal = parseFloat(data.bz) || 0;
        bzEl.textContent = data.bz ?? '—';
        bzEl.style.color = bzVal < -20  ? '#9333ea'   // Severe          — purple
                         : bzVal < -15  ? '#ef4444'   // Strong storm    — red
                         : bzVal < -10  ? '#f97316'   // Storm coupling  — orange
                         : bzVal < -5   ? '#facc15'   // Geoeffective    — yellow
                         : bzVal < -2   ? '#a3e635'   // Mildly geoeff.  — lime
                         : bzVal < 0    ? '#4ade80'   // Slightly south  — green
                         : '';                         // Northward (≥ 0) — default accent
        // foF2 — default accent colour only
        document.getElementById('solFoF2').textContent = data.fof2 ? data.fof2.toFixed(2) : '—';
        // J-MUF colour coding (MHz, band-open scale)
        const mufEl  = document.getElementById('solMUF');
        const mufVal = parseFloat(data.muf) || 0;
        _latestMuf = mufVal;
        mufEl.textContent = data.muf ? data.muf.toFixed(1) : '—';
        mufEl.style.color = mufVal >= 35 ? '#9333ea'   // Exceptional    — purple
                          : mufVal >= 30 ? '#ef4444'   // Outstanding    — red
                          : mufVal >= 25 ? '#f97316'   // Excellent      — orange
                          : mufVal >= 22 ? '#facc15'   // Very good      — yellow
                          : mufVal >= 18 ? '#84cc16'   // Good           — yellow-green
                          : mufVal >= 15 ? '#a3e635'   // Decent         — lime
                          : mufVal >= 12 ? '#4ade80'   // Modest         — green
                          : mufVal >= 8  ? ''          // Low            — default accent
                          : '#6b7280';                 // Very poor      — gray
        // Solar wind colour coding (km/s)
        const swEl  = document.getElementById('solSW');
        const swVal = parseFloat(data.solarwind) || 0;
        swEl.textContent = data.solarwind ?? '—';
        swEl.style.color = swVal >= 1000 ? '#9333ea'   // Extreme        — purple
                         : swVal >= 800  ? '#ef4444'   // Very fast/CME  — red
                         : swVal >= 650  ? '#f97316'   // Fast stream    — orange
                         : swVal >= 550  ? '#facc15'   // Elevated       — yellow
                         : swVal >= 450  ? '#a3e635'   // Slightly elev. — yellow-green
                         : '';                          // Slow / quiet   — default accent
        // Aurora colour coding (0–9 Kp-like scale)
        const auEl  = document.getElementById('solAU');
        const auVal = parseInt(data.aurora) || 0;
        auEl.textContent = data.aurora ?? '—';
        auEl.style.color = auVal >= 9   ? '#9333ea'   // Extreme storm   — purple
                         : auVal >= 7   ? '#ef4444'   // Strong/severe   — red
                         : auVal >= 6   ? '#f43f5e'   // Moderate storm  — red-orange
                         : auVal >= 5   ? '#f97316'   // Minor storm     — orange
                         : auVal >= 4   ? '#facc15'   // Active          — yellow
                         : auVal >= 3   ? '#a3e635'   // Background      — lime
                         : '';                         // Very quiet 0–2  — default accent
        // Proton flux colour coding (pfu, NOAA S-scale)
        const pfEl  = document.getElementById('solPF');
        const pfVal = parseFloat(data.protonflux) || 0;
        pfEl.textContent = data.protonflux ?? '—';
        pfEl.style.color = pfVal >= 100000 ? '#9333ea'   // S5 Extreme     — purple
                         : pfVal >= 10000  ? '#b91c1c'   // S4 Severe      — dark red
                         : pfVal >= 1000   ? '#ef4444'   // S3 Strong      — red
                         : pfVal >= 100    ? '#f97316'   // S2 Moderate    — orange
                         : pfVal >= 50     ? '#facc15'   // S1 Minor       — yellow
                         : '';                            // < 50 pfu       — default accent
        document.getElementById('solarUpdated').textContent = data.updated ? 'Updated: ' + data.updated : '';

        // K-index: green 0–1 (very quiet), default 2–3, orange 4–5, red 6+
        const kEl = document.getElementById('solK');
        const kVal = parseInt(data.kindex) || 0;
        kEl.textContent  = data.kindex ?? '—';
        kEl.style.color  = kVal >= 6 ? '#ef4444'
                         : kVal >= 4 ? '#f97316'
                         : kVal <= 1 ? '#22c55e' : '';

        // X-ray: yellow for C-class, orange for M-class, red for X-class
        const xEl  = document.getElementById('solX');
        const xray = (data.xray || '').toUpperCase();
        xEl.textContent = data.xray ?? '—';
        xEl.style.color = xray.startsWith('X') ? '#ef4444'
                        : xray.startsWith('M') ? '#f97316'
                        : xray.startsWith('C') ? '#facc15' : '';
    } catch(e) { /* silent */ }
}

// ── Reporter list ──────────────────────────────────────────────────────────
function toggleReporterList() {
    showReporterList = !showReporterList;
    document.getElementById('swReporterList').className          = 'sw' + (showReporterList ? ' on' : '');
    document.getElementById('reporterListPanel').style.display   = showReporterList ? 'block' : 'none';
    if (showReporterList) {
        updateReporterListPosition();
        fetchReporterList();
    } else {
        updateHistogramPosition();
    }
    saveLayerPrefs();
}

async function fetchReporterList() {
    if (_replayActive) { applyReplayFrame(); return; }
    if (!showReporterList && !showReporterPlot && !showHistogram) return;
    try {
        const r    = await fetch('/api/reporter_list');
        const data = await r.json();
        _reporterListData = data.reporters || [];
        if (showReporterList) renderReporterList();
        if (showHistogram)    renderHistogram();
        if (showReporterPlot) renderReporterPlot();
    } catch(e) { /* silent */ }
}

function sortReporterList(key) {
    _rlSortKey = key;
    // Update header indicators
    document.getElementById('thSnr').classList.toggle('sort-active',  key === 'snr');
    document.getElementById('thDist').classList.toggle('sort-active', key === 'dist');
    document.getElementById('thSnr').textContent  = 'SNR'  + (key === 'snr'  ? ' ▾' : '');
    document.getElementById('thDist').textContent = 'Dist' + (key === 'dist' ? ' ▾' : '');
    renderReporterList();
    saveLayerPrefs();
}

function renderReporterList() {
    const tbody = document.getElementById('reporterListBody');
    if (!_reporterListData.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="rl-empty">No data</td></tr>';
        return;
    }
    const sorted = [..._reporterListData].sort((a, b) =>
        _rlSortKey === 'dist' ? b.distance - a.distance : b.snr - a.snr
    );
    tbody.innerHTML = sorted.map(r => `
        <tr>
            <td>${escHtml(r.band)}</td>
            <td>${escHtml(r.callsign)}</td>
            <td>${escHtml(r.grid)}</td>
            <td class="rl-snr">${r.snr > 0 ? '+' : ''}${r.snr}</td>
            <td class="rl-dist">${r.distance.toLocaleString()}</td>
        </tr>`).join('');
}

// ── Histogram ─────────────────────────────────────────────────────────────
function toggleHistogram() {
    showHistogram = !showHistogram;
    document.getElementById('swHgram').className       = 'sw' + (showHistogram ? ' on' : '');
    document.getElementById('hgramPanel').style.display = showHistogram ? 'block' : 'none';
    if (showHistogram) {
        updateHistogramPosition();
        renderHistogram();
        fetchReporterList();   // the histogram needs the reporter data even when the list is off
    } else {
        if (hgramChart) { hgramChart.destroy(); hgramChart = null; }
    }
    saveLayerPrefs();
}

function setHgramMode(mode) {
    _hgramMode = mode;
    document.getElementById('htSnr').classList.toggle('active',  mode === 'snr');
    document.getElementById('htDist').classList.toggle('active', mode === 'dist');
    renderHistogram();
    saveLayerPrefs();
}

function renderHistogram() {
    if (!showHistogram) return;
    const darkMode  = isDark;
    const textColor = darkMode ? '#9ca3af' : '#475569';

    let labels, counts, lineColor, fillColor;

    if (_hgramMode === 'snr') {
        const MIN = -33, STEP = 3, BINS = 15;   // −33 … +9 dB
        counts = new Array(BINS).fill(0);
        _reporterListData.forEach(r => {
            const idx = Math.floor((r.snr - MIN) / STEP);
            if (idx >= 0 && idx < BINS) counts[idx]++;
        });
        labels    = counts.map((_, i) => { const v = MIN + i * STEP; return (v >= 0 ? '+' : '') + v; });
        lineColor = '#38bdf8';
        fillColor = 'rgba(56,189,248,0.18)';
    } else {
        const maxDist = Math.max(..._reporterListData.map(r => r.distance), 1000);
        const STEP    = maxDist <= 5000 ? 500 : 1000;
        const BINS    = Math.ceil(maxDist / STEP) + 1;
        counts = new Array(BINS).fill(0);
        _reporterListData.forEach(r => {
            const idx = Math.floor(r.distance / STEP);
            if (idx >= 0 && idx < BINS) counts[idx]++;
        });
        labels    = counts.map((_, i) => (i * STEP / 1000).toFixed(i * STEP < 1000 ? 1 : 0) + 'k');
        lineColor = '#38bdf8';
        fillColor = 'rgba(56,189,248,0.18)';
    }

    const ctx = document.getElementById('hgramCanvas').getContext('2d');

    if (hgramChart) {
        hgramChart.data.labels                      = labels;
        hgramChart.data.datasets[0].data            = counts;
        hgramChart.data.datasets[0].borderColor     = lineColor;
        hgramChart.data.datasets[0].backgroundColor = fillColor;
        hgramChart.options.scales.x.ticks.color = textColor;
        hgramChart.options.scales.y.ticks.color = textColor;
        hgramChart.update('none');
        return;
    }

    hgramChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data: counts,
                borderColor: lineColor,
                backgroundColor: fillColor,
                borderWidth: 1.5,
                pointRadius: 0,
                pointHoverRadius: 0,
                tension: 0.4,
                fill: true,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    titleFont: { size: 10 }, bodyFont: { size: 10 },
                    callbacks: {
                        title: items => (_hgramMode === 'snr' ? 'SNR ' : 'Dist ') + items[0].label,
                        label: item  => 'Stations: ' + item.raw,
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: textColor, font: { size: 9 }, maxRotation: 0 },
                    grid:  { display: false }
                },
                y: {
                    ticks: { color: textColor, font: { size: 9 }, stepSize: 1, precision: 0 },
                    grid:  { display: false },
                    beginAtZero: true,
                }
            }
        }
    });
}

