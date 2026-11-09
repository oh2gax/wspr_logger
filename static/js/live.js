// Live map: latest spot, propagation condition, status bar and reporter countries.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, analysis-more, info, wprs, main.

'use strict';

// ── Fetch latest spot and update live map ──────────────────────────────────
async function fetchLatest() {
    try {
        const r    = await fetch(`/api/latest?band=${currentBand}`);
        const data = await r.json();
        if (_replayActive) return;   // replay owns the panels until the user leaves it

        // Used by the Propagation card whatever layers are on (before, "& DX" needed a reporter layer
        // and HIGH MUF the Solar panel, because only those fetched the data).
        _liveDx6   = data.dx6 || 0;
        _latestMuf = data.muf || 0;
        _latestProp = data.prop || null;
        if (data.spot) {
            latestSpot = data.spot;
            updateLiveDisplay(data.spot);
            setStatus(data.spot.timestamp, true);
        } else {
            setStatus(null, false);
        }
        // Override propagation display if wspr.live is unreachable
        if (data.wspr_down) updatePropagation(0, false, true);
        updatePropRel(data.wspr_down ? null : _latestProp);
        updatePropUnusual(data.wspr_down ? null : _latestProp);
        fetchTodayStats();

        // Determine staleness here so all panels react consistently
        const isStale = !data.spot ||
            (Date.now() - new Date(data.spot.timestamp.replace(' ', 'T') + 'Z')) > 3600000;

        if (showCountries) updateCountryOverlay(isStale ? [] : (data.countries || []));
        if (showMuf)       fetchMufData();
        if (showTyp)       fetchTypData();
        if (showReporterList || showReporterPlot || showHistogram) {
            if (isStale) {
                _reporterListData = [];
                if (showReporterList) renderReporterList();
                if (showHistogram)    renderHistogram();
                if (showReporterPlot) clearReporterPlot();
            } else {
                fetchReporterList();
            }
        }
    } catch(e) {
        setStatus(null, false, 'Connection error');
    }
}

function updateLiveDisplay(spot) {
    const stale = Date.now() - new Date(spot.timestamp.replace(' ', 'T') + 'Z') > 3600000;   // > 1 hour
    showPosition(spot, stale);
    if (!liveMarker.getTooltip()) {
        liveMarker.bindTooltip('', { permanent: true, direction: 'right', offset: [12, 0], className: 'fixage', interactive: false });
    }
    updateFixAge();

    // Propagation
    updatePropagation(spot.reporter_count, stale);

    // Trail
    if (showTrail) refreshTrail();
}

// The position card of the left pane, the Current Position box on the map and the car marker: the
// latest spot when live, the replayed spot in the History Player (history-player.js, from 2026-11-07).
// stale: shown red (live: nothing heard for an hour; replay: no spot within 25 min of the snapshot).
function showPosition(spot, stale) {
    const { lat, lon, tx_loc, timestamp, reporter_count, max_distance } = spot;
    _txLat = lat; _txLon = lon;   // used by reporter plot
    const dotColor = stale ? '#ef4444' : '#4ade80';       // red or green

    // Sidebar info panel
    const locEl = document.getElementById('infoLocator');
    locEl.textContent  = tx_loc;
    locEl.style.color  = stale ? '#ef4444' : '';          // red when stale, default accent otherwise
    document.getElementById('infoReporters').textContent = stale ? '—' : reporter_count;
    document.getElementById('infoMaxDist').textContent   = (!stale && max_distance) ? max_distance + ' km' : '—';
    document.getElementById('infoReporters').style.color = stale ? '#ef4444' : '';
    document.getElementById('infoMaxDist').style.color   = stale ? '#ef4444' : '';
    document.getElementById('infoTime').textContent      = timestamp.slice(0, 16);      // minutes are enough here

    // Map overlay
    const ovLoc = document.getElementById('ovLocator');
    ovLoc.textContent = tx_loc;
    ovLoc.style.color = stale ? '#ef4444' : '';
    document.getElementById('ovTime').textContent      = timestamp + ' UTC';
    document.getElementById('ovReporters').textContent = stale ? '—' : reporter_count;
    document.getElementById('ovDX').textContent        = (!stale && max_distance) ? max_distance + ' km' : '—';
    document.getElementById('ovBand').textContent      = BAND_NAMES[currentBand] || currentBand + 'MHz';
    const staleColor = stale ? '#ef4444' : '';
    document.getElementById('ovReporters').style.color = staleColor;
    document.getElementById('ovDX').style.color        = staleColor;
    document.getElementById('ovBand').style.color      = staleColor;

    // Beacon marker
    const popup = `<strong>${escHtml(CALLSIGN)}</strong><br>
        Locator: ${escHtml(tx_loc)}<br>
        Time: ${timestamp}<br>
        Reporters: ${reporter_count}<br>
        Max DX: ${max_distance} km`;

    if (liveMarker) {
        liveMarker.setLatLng([lat, lon])
                  .setStyle({ fillColor: dotColor, color: dotColor, opacity: 1, fillOpacity: 1 })
                  .setPopupContent(popup);
    } else {
        liveMarker = L.circleMarker([lat, lon], {
            radius: 8,
            color: dotColor,
            fillColor: dotColor,
            fillOpacity: 1,
            weight: 0
        }).addTo(liveMap).bindPopup(popup);
        liveMap.panTo([lat, lon]);
    }
}

// A replayed day without any logged position (e.g. the transmitter off, only solar data stored):
// dashes in the box and the left pane, the marker hidden — never the live position under a replayed clock.
function showNoPosition() {
    for (const id of ['infoLocator', 'ovLocator']) { const el = document.getElementById(id); el.textContent = '——'; el.style.color = ''; }
    for (const id of ['infoReporters', 'infoMaxDist', 'ovReporters', 'ovDX']) {
        const el = document.getElementById(id); el.textContent = '—'; el.style.color = '';
    }
    document.getElementById('infoTime').textContent = 'no position this day';
    document.getElementById('ovTime').textContent = 'no position this day';
    showFixAgeLines('', 0);
    if (liveMarker) liveMarker.setStyle({ opacity: 0, fillOpacity: 0 });
}

// How old the latest fix is: a label at the marker ("15 min ago") and a line in the position card ("last fix 15 min ago").
// Green up to 25 min (a transmission every 10 min plus the upload delay), amber to 60 min, red beyond.
function updateFixAge() {
    if (!liveMarker || !latestSpot) return;
    const min = Math.max(0, Math.round((Date.now() - new Date(latestSpot.timestamp.replace(' ', 'T') + 'Z')) / 60000));
    const txt = min < 60 ? `${min} min ago`
              : min < 2880 ? `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, '0')} min ago`
              : `${Math.floor(min / 1440)} days ago`;
    const tt = liveMarker.getTooltip();
    if (tt) {
        tt.setContent(txt);                                  // the label just says "15 min ago" (from 2026-11-09)
        const el = tt.getElement();
        if (el) {
            el.classList.toggle('warn', min > 25 && min <= 60);
            el.classList.toggle('old', min > 60);
            el.style.display = (_replayActive || !showFixAge) ? 'none' : '';
        }
    }
    if (_replayActive) return;                               // the History Player writes the age lines itself
    showFixAgeLines('last fix ' + txt, min);
}

// The age line in the Current Position box and under "Last Spot (UTC)" in the left pane.
function showFixAgeLines(text, min) {
    document.getElementById('ovAge').textContent = text;
    const ia = document.getElementById('infoAge');
    ia.textContent = text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
    ia.classList.toggle('warn', min > 25 && min <= 60);
    ia.classList.toggle('old', min > 60);
}

function toggleFixAge() {
    showFixAge = !showFixAge;
    document.getElementById('swFixAge').className = 'sw' + (showFixAge ? ' on' : '');
    updateFixAge();
    saveLayerPrefs();
}

async function refreshTrail() {
    try {
        const today = todayStr();
        const r     = await fetch(`/api/positions?date=${today}&band=${currentBand}`);
        const spots = await r.json();

        if (liveTrail) { liveMap.removeLayer(liveTrail); liveTrail = null; }

        if (spots.length > 1) {
            liveTrail = L.polyline(spots.map(s => [s.lat, s.lon]), {
                color:'#38bdf8', weight:2, opacity:.55, dashArray:'6 4'
            }).addTo(liveMap);
        }
    } catch(e) { /* silent */ }
}

// ── Propagation condition ──────────────────────────────────────────────────
function getPropCondition(n) {
    if (n <= 5)   return { text: 'Very low',        color: '#ef4444', pct:  8 };
    if (n <= 10)  return { text: 'Low',            color: '#f97316', pct: 20 };
    if (n <= 20)  return { text: 'Normal',         color: '#eab308', pct: 40 };
    if (n <= 40)  return { text: 'Good',           color: '#84cc16', pct: 60 };
    if (n <= 60)  return { text: 'Very good',      color: '#22c55e', pct: 75 };
    if (n <= 100) return { text: 'Extremely good', color: '#4ade80', pct: 88 };
    return              { text: 'Exceptional',     color: '#a855f7', pct: 100 };
}

function updatePropagation(reporter_count, stale = false, wspr_down = false) {
    const el        = document.getElementById('propCondition');
    const highMufEl = document.getElementById('propHighMuf');
    highMufEl.style.display = (_latestMuf > 28) ? 'block' : 'none';
    if (wspr_down) {
        el.textContent  = 'DB Timeout!';
        el.style.color  = '#f59e0b';
        document.getElementById('propBarFill').style.width      = '5%';
        document.getElementById('propBarFill').style.background = '#f59e0b';
        document.getElementById('propReporters').textContent    = 'wspr.live unreachable';
        return;
    }
    if (stale) {
        // Silence at an hour when the band is usually open is suspicious — flag TX Fail.  The server knows
        // the usual hours (prop.busy_now, from the last 30 days); without it, 20 m in daytime (06–15 UTC).
        const utcHour = new Date().getUTCHours();
        const p = _replayActive ? null : _latestProp;
        const suspect = p ? (p.tx_suspect || p.busy_now)
                          : (currentBand === 14) && (utcHour >= 6 && utcHour < 15);
        el.textContent  = suspect ? 'No propagation or TX Fail' : 'No propagation';
        el.style.color  = '#ef4444';
        document.getElementById('propBarFill').style.width      = '0%';
        document.getElementById('propBarFill').style.background = '#ef4444';
        document.getElementById('propReporters').textContent    = '0 reporters heard';
        return;
    }
    const n = reporter_count || 0;
    const c = getPropCondition(n);

    // Append "& DX" at any level when 2 or more reporters are beyond 6000 km
    // (live: counted by the server; replay: from the replayed reporter list)
    const dxCount = _replayActive ? _reporterListData.filter(r => r.distance > 6000).length : _liveDx6;
    const hasDX   = dxCount >= 2;

    el.innerHTML = hasDX
        ? `<span style="color:${c.color}">${c.text}</span> <span style="color:#4ade80">& DX</span>`
        : `<span style="color:${c.color}">${c.text}</span>`;
    el.style.color = '';
    document.getElementById('propBarFill').style.width      = c.pct + '%';
    document.getElementById('propBarFill').style.background = c.color;
    document.getElementById('propReporters').textContent    =
        n + ' reporter' + (n === 1 ? '' : 's') + ' heard' +
        (hasDX ? ', ' + dxCount + ' over 6000 km' : '');
}

// ── Compared with usual (from 2026-11-09) ──────────────────────────────────
// prop (from /api/latest): the stations heard in the last 60 minutes against the 30 days before today at
// this UTC hour and a similar MUF (verdict), the "transmitter off?" warning (tx_suspect) and the first hour
// after the transmitter came back (warming, no comparison yet).  Live only: hidden in the History Player.
const PROP_REL = {
    much_below:  { text: '▼▼ Much below usual',          color: '#ef4444' },
    below:       { text: '▼ Below usual',                color: '#f97316' },
    typical:     { text: '● Typical for this hour',      color: 'var(--text-secondary)' },
    above:       { text: '▲ Above usual',                color: '#84cc16' },
    exceptional: { text: '▲▲ Exceptional for this hour', color: '#a855f7' },
};
function updatePropRel(p) {
    const box = document.getElementById('propRel');
    if (_replayActive || !p || (!p.verdict && !p.tx_suspect && !p.warming)) { box.style.display = 'none'; return; }
    box.style.display = 'block';
    box.classList.toggle('tx-warn', !!p.tx_suspect);
    const txt = document.getElementById('propRelText'), sub = document.getElementById('propRelSub');
    const nums = document.getElementById('propRelNums'), gauge = document.getElementById('propGauge');
    if (p.tx_suspect) {
        txt.textContent = '⚠ No reports for 20 min';
        txt.style.color = '';
        sub.textContent = '';
        nums.textContent = `Transmitter off? Check the battery — usually ${Math.round(p.usual_now)} stations at this hour.`;
        gauge.style.display = 'none';
        return;
    }
    if (p.warming) {
        txt.textContent = 'Transmitter back on';
        txt.style.color = 'var(--text-secondary)';
        sub.textContent = '';
        nums.textContent = 'Compared with usual after an hour, when the 60-minute count is complete.';
        gauge.style.display = 'none';
        return;
    }
    const v = p.verdict, c = PROP_REL[v.verdict];
    txt.textContent = c.text;
    txt.style.color = c.color;
    sub.textContent = `vs. ${p.base_days} days at ${String(v.hour).padStart(2, '0')} UTC` +
        (v.basis === 'muf' ? `, MUF ${v.muf_bin >= 24 ? '24+' : v.muf_bin + '–' + (v.muf_bin + 2)} MHz` : '');
    sub.title = `Compared with the ${p.base_days} days before today at this hour` +
        (v.basis === 'muf' ? ' and a similar MUF' : '') + ` (${v.count} polls)`;
    // the gauge: 0 … the larger of the 90 % level and the live count; band = the middle half, line = median
    const max = Math.max(v.p90, v.live_n, 1) * 1.12, pc = x => (100 * x / max).toFixed(1) + '%';
    gauge.style.display = 'block';
    Object.assign(document.getElementById('pgWide').style, { left: pc(v.p10), width: pc(v.p90 - v.p10) });
    Object.assign(document.getElementById('pgBand').style, { left: pc(v.p25), width: pc(v.p75 - v.p25) });
    document.getElementById('pgMed').style.left = pc(v.median);
    Object.assign(document.getElementById('pgDot').style, { left: pc(v.live_n), background: c.color === 'var(--text-secondary)' ? '#38bdf8' : c.color });
    nums.textContent = `${v.live_n} heard in 60 min · usually ${Math.round(v.p25)}–${Math.round(v.p75)}`;
}

// Unusual DX openings now (prop.unusual): a region beyond 6000 km heard at an hour when it is seldom heard at
// this time of year ("opening"), or by many more stations than usual ("strong").  Live only.
const UNUSUAL_COLORS = { opening: '#a855f7', strong: '#4ade80' };
function unusualLines(e) {
    const hh = String(e.hour).padStart(2, '0');
    return e.kind === 'opening'
        ? { hd: `★ Unusual opening: ${e.name}`,
            sub: `${e.stations} station${e.stations === 1 ? '' : 's'} · heard on ${e.p} % of days at ${hh} UTC at this time of year` }
        : { hd: `▲ Unusually strong: ${e.name}`,
            sub: `${e.stations} stations · usually ${e.median == null ? '—' : Math.round(e.median)} at ${hh} UTC` };
}
function updatePropUnusual(p) {
    const box = document.getElementById('propUnusual');
    const ev = (!_replayActive && p && p.unusual) || [];
    box.style.display = ev.length ? 'block' : 'none';
    box.innerHTML = ev.map(e => {
        const l = unusualLines(e);
        return `<div class="pu-row" title="${escHtml(e.calls.join(', '))}"><div class="pu-hd" style="color:${UNUSUAL_COLORS[e.kind]}">${escHtml(l.hd)}</div>` +
               `<div class="pu-sub">${escHtml(l.sub)}</div></div>`;
    }).join('');
    if (showReporterPlot) renderReporterPlot();       // their arcs in the same colour
}
// The colour of a reporter's arc when it belongs to an unusual opening now, else null
function unusualColorOf(call) {
    if (_replayActive || !_latestProp || !_latestProp.unusual) return null;
    const base = String(call || '').toUpperCase().split('-')[0].split('/')[0];
    const e = _latestProp.unusual.find(x => x.calls.includes(base));
    return e ? UNUSUAL_COLORS[e.kind] : null;
}

// ── Status bar ─────────────────────────────────────────────────────────────
function setStatus(timestamp, ok, msg) {
    const dot  = document.getElementById('statusDot');
    const text = document.getElementById('statusText');
    if (!ok) {
        dot.className    = 'dot dead';
        text.textContent = msg || 'No data';
        return;
    }
    const diffMin = (Date.now() - new Date(timestamp.replace(' ','T')+'Z')) / 60000;
    if (diffMin < 20) {
        dot.className    = 'dot';
        text.textContent = `Live · ${Math.round(diffMin)} min ago`;
    } else if (diffMin < 120) {
        dot.className    = 'dot stale';
        text.textContent = `Stale · ${Math.round(diffMin)} min ago`;
    } else {
        dot.className    = 'dot dead';
        text.textContent = `Last: ${timestamp.split(' ')[1]} UTC`;
    }
}


// ── Reporter countries ─────────────────────────────────────────────────────
function toggleCountries() {
    showCountries = !showCountries;
    document.getElementById('swCountries').className = 'sw' + (showCountries ? ' on' : '');
    document.getElementById('countryOverlay').style.display = showCountries ? 'flex' : 'none';
    if (showCountries && _replayActive) {
        applyReplayFrame();
    } else if (showCountries) {
        fetch('/api/reporters')
            .then(r => r.json())
            .then(data => updateCountryOverlay(data.countries || []))
            .catch(() => {});
    }
    saveLayerPrefs();
}

function updateCountryOverlay(list) {
    const el = document.getElementById('countryList');
    document.getElementById('countryCount').textContent = list.length ? list.length : '';
    if (!list.length) {
        el.innerHTML = '<div style="color:var(--text-muted);font-size:11px;">No data</div>';
        return;
    }
    const maxCount = list[0].count;
    el.innerHTML = list.map(c => `
        <div class="country-row">
            <span class="country-name">${escHtml(c.country)}</span>
            <div class="country-bar-wrap">
                <div class="country-bar" style="width:${Math.round(c.count / maxCount * 100)}%"></div>
            </div>
            <span class="country-count">${c.count}</span>
        </div>`).join('');
}

