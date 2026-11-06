// WPRS page (drive detector, track map, replay) and share links.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, info, wprs, main.

'use strict';

// ── WPRS page: drive detector, track map and replay ────────────────────────
let wprsMap = null, wprsTile = null, wprsLayers = null;
let wprsData = null;             // /api/wprs/days
let wprsSel = null;              // first UTC date of the shown range
let wprsTrack = null;            // /api/wprs/track
let wprsIdx = 0, wprsTimer = null, wprsPlayed = null, wprsCursor = null;
let wprsTab_ = 'days';
let wprsPendingFix = null;       // fix index asked for by a shared link, applied when the track has loaded

function initWprsMap() {
    wprsMap = L.map('wprs-map', { center: [MAP_LAT, MAP_LON], zoom: MAP_ZOOM - 2 });
    wprsTile = makeTiles(isDark);
    wprsTile.addTo(wprsMap);
    wprsLayers = L.layerGroup().addTo(wprsMap);
}

function wprsDayPasses(d, min) {
    return min <= 0 ? d.squares > 1 : Math.max(d.spread_km, d.home_km) >= min;
}

async function loadWprs() {
    const sel = document.getElementById('wprsMin');
    try {
        const v = localStorage.getItem('wspr_wprs_min');
        if (v !== null && [...sel.options].some(o => o.value === v)) sel.value = v;
    } catch(e) {}
    try {
        const r = await fetch(`/api/wprs/days?band=${currentBand}`);
        wprsData = await r.json();
    } catch(e) {
        document.getElementById('wprsList').innerHTML = '<div class="an-empty">Could not load the position history.</div>';
        return;
    }
    if (wprsSel && !wprsData.days.some(d => d.date === wprsSel && wprsDayPasses(d, +sel.value))) {
        sel.value = '0';             // a linked day that the filter would hide: show everything
    }
    renderWprsList();
    if (wprsTab_ === 'trips') renderWprsTrips();
    if (!wprsSel) {
        const first = wprsData.days.find(d => wprsDayPasses(d, +sel.value));
        if (first) wprsSelect(first.date);
    }
}

function wprsTab(which) {
    wprsTab_ = which;
    document.getElementById('wprsTabDays').classList.toggle('on', which === 'days');
    document.getElementById('wprsTabTrips').classList.toggle('on', which === 'trips');
    document.getElementById('wprsFilter').style.display = which === 'days' ? '' : 'none';
    document.getElementById('wprsList').style.display = which === 'days' ? '' : 'none';
    document.getElementById('wprsTrips').style.display = which === 'trips' ? '' : 'none';
    if (which === 'trips') renderWprsTrips();
}

function wprsDur(h) {
    if (h < 1) return '< 1 h';
    const th = Math.round(h), d = Math.floor(th / 24), r = th % 24;
    return d ? `${d} d ${r} h` : `${th} h`;
}

function renderWprsTrips() {
    const box = document.getElementById('wprsTrips');
    const trips = (wprsData && wprsData.trips) || [];
    if (!trips.length) { box.innerHTML = '<div class="an-empty">No trips beyond 25 km from home have been logged.</div>'; return; }
    const fmt = d => new Date(d + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
    box.innerHTML = `<div class="wprs-count" style="padding:8px 12px 0;font-size:11px;">${trips.length} trip${trips.length === 1 ? '' : 's'} beyond 25 km from home ${wprsData.home ? '(' + wprsData.home.loc + ')' : ''}</div>` +
        trips.map((t, i) => {
            const yr = t.date_from.slice(0, 4);
            const range = t.date_from === t.date_to ? `${fmt(t.date_from)} ${yr}` : `${fmt(t.date_from)} – ${fmt(t.date_to)} ${yr}`;
            return `<div class="wprs-trip${t.date_from === wprsSel ? ' sel' : ''}" onclick="wprsSelectTrip(${i})">` +
                `<div class="wprs-dhead"><span>${range}</span><span class="wprs-pill">${wprsDur(t.hours)}</span></div>` +
                `<div class="wprs-tstats">` +
                `<div><b>${t.far_km.toFixed(0)} km</b><span>farthest · <i style="text-transform:none;font-style:normal">${escHtml(t.far_loc)}</i></span></div>` +
                `<div><b>${t.path_km.toFixed(0)} km</b><span>path</span></div>` +
                `<div><b>${t.squares}</b><span>squares</span></div>` +
                `<div><b>${t.best_dx ? t.best_dx.toLocaleString('en-GB') : '—'}</b><span>best DX km</span></div></div>` +
                `<div class="wprs-dmeta">mostly in ${escHtml(t.top_loc)} · ${t.fixes} fixes · ${t.start.slice(11, 16)}–${t.end.slice(11, 16)} UTC first to last</div></div>`;
        }).join('');
}

function wprsSelectTrip(i) {
    const t = wprsData.trips[i];
    const span = document.getElementById('wprsSpan');
    const want = String(Math.min(t.days, 7));
    if (![...span.options].some(o => o.value === want)) span.add(new Option(want + ' days', want));
    span.value = want;
    wprsSelect(t.date_from);
}

function wprsFilterChanged() {
    try { localStorage.setItem('wspr_wprs_min', document.getElementById('wprsMin').value); } catch(e) {}
    renderWprsList();
}

function renderWprsList() {
    if (!wprsData) return;
    const min = +document.getElementById('wprsMin').value;
    const days = wprsData.days.filter(d => wprsDayPasses(d, min));
    const home = wprsData.home ? wprsData.home.loc : '?';
    document.getElementById('wprsCount').textContent =
        `${days.length} of ${wprsData.days.length} logged days · home square ${home}`;
    if (!days.length) {
        document.getElementById('wprsList').innerHTML = '<div class="an-empty">No day moves that far.</div>';
        return;
    }
    const maxv = Math.max(1, ...days.map(d => Math.max(d.spread_km, d.home_km)));
    document.getElementById('wprsList').innerHTML = days.map(d => {
        const nice = new Date(d.date + 'T00:00:00Z').toLocaleDateString('en-GB',
            { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
        const w = Math.max(3, Math.round(100 * Math.max(d.spread_km, d.home_km) / maxv));
        const away = d.home_km >= 25 ? ` · <span class="wprs-away">${d.home_km.toFixed(0)} km from home</span>` : '';
        return `<div class="wprs-day${d.date === wprsSel ? ' sel' : ''}" data-date="${d.date}" onclick="wprsSelect('${d.date}')">` +
            `<div class="wprs-dhead"><span>${nice}</span><span class="wprs-pill">${d.squares} square${d.squares === 1 ? '' : 's'} · ${d.fixes} fixes</span></div>` +
            `<div class="wprs-mini"><div style="width:${w}%"></div></div>` +
            `<div class="wprs-dmeta">moved ${d.spread_km.toFixed(1)} km · path ${d.path_km.toFixed(0)} km · ${d.first}–${d.last} UTC${away}</div></div>`;
    }).join('');
    const cur = document.querySelector('#wprsList .wprs-day.sel');
    if (cur) cur.scrollIntoView({ block: 'nearest' });
}

function wprsAddDays(date, n) {
    const t = new Date(date + 'T00:00:00Z');
    t.setUTCDate(t.getUTCDate() + n);
    return t.toISOString().slice(0, 10);
}

async function wprsSelect(date) {
    if (!date) return;
    wprsPause();
    wprsSel = date;
    setHash(wprsHash());
    document.querySelectorAll('#wprsList .wprs-day').forEach(el => el.classList.toggle('sel', el.dataset.date === date));
    if (wprsTab_ === 'trips') renderWprsTrips();
    const span = +document.getElementById('wprsSpan').value;
    const to = wprsAddDays(date, span - 1);
    try {
        const r = await fetch(`/api/wprs/track?from=${date}&to=${to}&band=${currentBand}`);
        wprsTrack = await r.json();
        if (wprsTrack.error || !wprsTrack.fixes) throw new Error(wprsTrack.error || 'no track');
    } catch(e) {
        wprsTrack = null;
        document.getElementById('wprsSum').textContent = 'Could not load this track.';
        return;
    }
    renderWprsTrack(date, to);
}

function renderWprsTrack(from, to) {
    wprsLayers.clearLayers();
    wprsPlayed = null; wprsCursor = null;
    const t = wprsTrack, slider = document.getElementById('wprsSlider');
    const range = from === to ? from : `${from} → ${to}`;
    if (!t.fixes.length) {
        document.getElementById('wprsSum').textContent = `${range}: no fixes logged`;
        slider.max = 0; document.getElementById('wprsTime').textContent = '';
        return;
    }
    const st = t.stats, accent = anColors().accent;
    document.getElementById('wprsSum').innerHTML =
        `<b>${range}</b> · ${st.fixes} fixes · ${st.squares} square${st.squares === 1 ? '' : 's'} · moved ${st.spread_km} km · ` +
        `path ${st.path_km} km · farthest from home ${st.home_km} km`;

    const maxN = Math.max(...t.squares.map(q => q.n));
    for (const q of t.squares) {
        L.rectangle([[q.lat - q.hlat, q.lon - q.hlon], [q.lat + q.hlat, q.lon + q.hlon]],
            { color: accent, weight: 1, fillColor: accent, fillOpacity: 0.12 + 0.45 * Math.log(q.n + 1) / Math.log(maxN + 1) })
            .bindTooltip(`${q.loc} · ${q.n} fix${q.n === 1 ? '' : 'es'} · first ${q.first.slice(5, 16)} UTC`).addTo(wprsLayers);
    }
    const pts = t.fixes.map(f => [f.lat, f.lon]);
    L.polyline(pts, { color: '#94a3b8', weight: 2, opacity: 0.8, dashArray: '4 5' }).addTo(wprsLayers);
    for (const f of t.fixes) {
        L.circleMarker([f.lat, f.lon], { radius: 3, color: accent, weight: 1, fillColor: accent, fillOpacity: 0.9 })
            .bindTooltip(`${f.t.slice(5, 16)} UTC · ${f.loc} · ${f.n} reporter${f.n === 1 ? '' : 's'} · best ${f.dx.toLocaleString('en-GB')} km`)
            .addTo(wprsLayers);
    }
    if (t.home) {
        L.circleMarker([t.home.lat, t.home.lon], { radius: 9, color: '#f87171', weight: 2, fillOpacity: 0 })
            .bindTooltip(`Home square ${t.home.loc}`).addTo(wprsLayers);
    }
    const a = t.fixes[0], z = t.fixes[t.fixes.length - 1];
    L.circleMarker([a.lat, a.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#4ade80', fillOpacity: 1 })
        .bindTooltip(`Start ${a.t.slice(5, 16)} UTC · ${a.loc}`).addTo(wprsLayers);
    L.circleMarker([z.lat, z.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#f87171', fillOpacity: 1 })
        .bindTooltip(`End ${z.t.slice(5, 16)} UTC · ${z.loc}`).addTo(wprsLayers);

    wprsPlayed = L.polyline([], { color: '#f59e0b', weight: 4 }).addTo(wprsLayers);
    wprsCursor = L.circleMarker([a.lat, a.lon], { radius: 10, color: '#f59e0b', weight: 3, fillColor: '#ffffff', fillOpacity: 1 }).addTo(wprsLayers);

    wprsMap.invalidateSize();
    if (st.squares === 1) wprsMap.setView([a.lat, a.lon], 12);
    else wprsMap.fitBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 13 });
    slider.max = t.fixes.length - 1;
    wprsShow(wprsPendingFix !== null ? wprsPendingFix : 0);
    wprsPendingFix = null;
}

function wprsShow(i) {
    const t = wprsTrack;
    if (!t || !t.fixes.length) return;
    wprsIdx = Math.max(0, Math.min(i, t.fixes.length - 1));
    const f = t.fixes[wprsIdx];
    document.getElementById('wprsSlider').value = wprsIdx;
    document.getElementById('wprsTime').textContent =
        `${f.t.slice(0, 16)} UTC · ${f.loc} · ${f.n} rptr${f.n === 1 ? '' : 's'} · ${wprsIdx + 1}/${t.fixes.length}`;
    wprsPlayed.setLatLngs(t.fixes.slice(0, wprsIdx + 1).map(x => [x.lat, x.lon]));
    wprsCursor.setLatLng([f.lat, f.lon]);
    if (!wprsMap.getBounds().pad(-0.1).contains([f.lat, f.lon])) wprsMap.panTo([f.lat, f.lon]);
}

function wprsToStart() { wprsPause(); wprsShow(0); }

function wprsTogglePlay() {
    if (wprsTimer) { wprsPause(); return; }
    if (!wprsTrack || !wprsTrack.fixes.length) return;
    if (wprsIdx >= wprsTrack.fixes.length - 1) wprsShow(0);
    document.getElementById('wprsPlayBtn').innerHTML = '&#9208;';
    wprsTimer = setInterval(() => {
        if (wprsIdx >= wprsTrack.fixes.length - 1) { wprsPause(); return; }
        wprsShow(wprsIdx + 1);
    }, 1000 / +document.getElementById('wprsSpeed').value);
}

function wprsPause() {
    if (wprsTimer) { clearInterval(wprsTimer); wprsTimer = null; }
    const b = document.getElementById('wprsPlayBtn');
    if (b) b.innerHTML = '&#9654;';
}

function wprsSpeedChanged() {
    if (wprsTimer) { wprsPause(); wprsTogglePlay(); }
}

// ── Share links (the part after # in the address) ─────────────────────────
//   #wprs=2026-06-19&days=2&fix=110   a drive on the WPRS page (days and fix optional)
//   #history=DATE   #stats=DATE   #analysis
function setHash(h) {
    try { history.replaceState(null, '', h ? '#' + h : location.pathname + location.search); } catch(e) {}
}

function wprsHash(withFix) {
    let h = `wprs=${wprsSel}&days=${document.getElementById('wprsSpan').value}`;
    if (withFix && wprsTrack && wprsTrack.fixes.length) h += `&fix=${wprsIdx}`;
    return h;
}

async function wprsCopyLink() {
    if (!wprsSel) { showToast('Pick a day first'); return; }
    const url = location.origin + location.pathname + '#' + wprsHash(true);
    try { await navigator.clipboard.writeText(url); showToast('Link copied'); }
    catch(e) { window.prompt('Copy this link:', url); }
}

function applyHash() {
    const raw = location.hash.replace(/^#/, '');
    if (!raw) return;
    const q = new URLSearchParams(raw);
    const isDate = d => /^\d{4}-\d{2}-\d{2}$/.test(d || '');
    if (q.has('wprs')) {
        const date = q.get('wprs');
        if (isDate(date)) {
            const span = document.getElementById('wprsSpan');
            const want = String(Math.min(Math.max(parseInt(q.get('days')) || 1, 1), 7));
            if (![...span.options].some(o => o.value === want)) span.add(new Option(want + ' days', want));
            span.value = want;
            wprsSel = date;
            const fix = parseInt(q.get('fix'));
            wprsPendingFix = Number.isFinite(fix) && fix >= 0 ? fix : null;
        }
        showView('wprs');
        if (isDate(date)) wprsSelect(date);
    } else if (q.has('history')) {
        showView('history');
        if (isDate(q.get('history'))) { document.getElementById('histDate').value = q.get('history'); loadHistory(); }
    } else if (q.has('stats')) {
        showView('stats');
        if (isDate(q.get('stats'))) { document.getElementById('statsDate').value = q.get('stats'); loadStats(); }
    } else if (q.has('analysis')) {
        showView('analysis');
    }
}
window.addEventListener('hashchange', applyHash);

function wprsOpenHistory() {
    if (wprsTrack && wprsTrack.fixes.length) openReplayAt(wprsTrack.fixes[wprsIdx].t);
}

