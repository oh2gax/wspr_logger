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
        if (data.spot) {
            latestSpot = data.spot;
            updateLiveDisplay(data.spot);
            setStatus(data.spot.timestamp, true);
        } else {
            setStatus(null, false);
        }
        // Override propagation display if wspr.live is unreachable
        if (data.wspr_down) updatePropagation(0, false, true);
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
        // On 20 m during daytime (06–15 UTC) silence is suspicious — flag TX Fail
        const utcHour = new Date().getUTCHours();
        const daytime20m = (currentBand === 14) && (utcHour >= 6 && utcHour < 15);
        el.textContent  = daytime20m ? 'No propagation or TX Fail' : 'No propagation';
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
    document.getElementById('countryOverlay').style.display = showCountries ? 'block' : 'none';
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

