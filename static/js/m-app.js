/**
 * m-app.js — the WSPR Logger phone view /app (from 2026-11-07).
 *
 * The user interface of the MODE-S Wind phone view: a slim top bar (☰, the view's title, the UTC
 * clock, the theme button, the beacon's status dot), one view at a time filling the screen, and
 * every choice in the ☰ menu — the views as tiles, each view's options in a folding section (the
 * shown view's opens by itself), the selects marked data-chips shown as tap buttons.
 *
 *   Live map    /api/latest every minute: the beacon, the last fix's age, the trail of the day
 *               (/api/positions), the reporters' great-circle arcs (/api/reporter_list), day / night
 *   Now         propagation, position, today or the last hour, solar conditions (/api/solar) and the
 *               Analysis page's Right now card (/api/analysis?days=90)
 *   Reporters   the stations of the last 60 minutes: list with search, countries, SNR / distance
 *   MUF graph   /api/muf: Juliusruh MUF and the reporter counts
 *   Replay      /api/replay/day + /api/positions: the stored snapshots of a day on the map
 *   History     one day's spots (/api/stats, /api/positions); a tap opens Replay at that moment
 *   Statistics  the all-time records and the day-by-day chart (/api/daily_summary)
 *   Analysis    the full page's analysis.js and analysis-more.js on the same markup (_analysis_body.html)
 *   WPRS        /api/wprs/days and /api/wprs/track: days, trips and a track with a fix slider
 *
 * Only the shown view is refreshed, and nothing while the page is hidden (screen off, another app).
 * Back on the page after more than an hour, or when the server has a newer build (a deploy,
 * /api/app/build), the page reloads itself; the view and the options are kept in localStorage.
 * The theme is the full page's setting (wspr_theme_mode), What's new its seen version (wspr_seen_version).
 */
/* global currentBand, isDark:writable, escHtml, showToast, anColors, loadAnalysis, renderAnalysis, setAnalysisDays,
          drawHeatmap, drawPolar, _anData, _anDays, _amData, greatCirclePoints, maidenheadToLatLon,
          sunPosition, buildNightPolygon, APP_VERSION, APP_BUILD */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const lsGet = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (_) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, String(v)); } catch (_) { /* private mode */ } };
  const lsJson = (k, d) => { try { const v = JSON.parse(lsGet(k, 'null')); return v && typeof v === 'object' ? Object.assign({}, d, v) : Object.assign({}, d); } catch (_) { return Object.assign({}, d); } };
  const pad = n => String(n).padStart(2, '0');
  const esc = escHtml;
  const CFG = window.WSPR_CONFIG;
  const BAND_NAMES = { 3: '80m', 7: '40m', 10: '30m', 14: '20m', 18: '17m', 21: '15m', 24: '12m', 28: '10m' };
  const BAND = BAND_NAMES[currentBand] || currentBand + ' MHz';
  const tsMs = ts => Date.parse(String(ts).replace(' ', 'T') + 'Z');
  const isoDay = d => d.toISOString().slice(0, 10);
  const addDays = (date, n) => { const t = new Date(date + 'T00:00:00Z'); t.setUTCDate(t.getUTCDate() + n); return isoDay(t); };
  const today = () => isoDay(new Date());
  const km = v => (v || v === 0) ? Number(v).toLocaleString('en-GB') : '—';
  const niceDay = (d, wd) => new Date(d + 'T00:00:00Z').toLocaleDateString('en-GB',
    { weekday: wd || 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  async function getJson(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  const VIEWS = {
    map:    { title: 'Live map',   sec: 'map',    el: 'v-map' },
    now:    { title: 'Now',        sec: 'now',    el: 'v-now' },
    rep:    { title: 'Reporters',  sec: 'rep',    el: 'v-rep' },
    muf:    { title: 'MUF graph',  sec: 'muf',    el: 'v-muf' },
    replay: { title: 'Replay',     sec: 'replay', el: 'v-replay' },
    hist:   { title: 'History',    sec: 'hist',   el: 'v-hist' },
    stats:  { title: 'Statistics', sec: 'stats',  el: 'v-stats' },
    an:     { title: 'Analysis',   sec: 'an',     el: 'analysis-view' },
    wprs:   { title: 'WPRS',       sec: 'wprs',   el: 'v-wprs' },
  };
  let view = lsGet('wspr_app_view', 'map');
  if (!VIEWS[view]) view = 'map';
  let timer = null;

  // ── menu ─────────────────────────────────────────────────────────────────
  const drawer = $('app-drawer'), backdrop = $('app-backdrop');
  function menu(open) {
    if (open) { $('m-o-andays').value = String(_anDays); syncChips(); }   // the period may have stepped on by itself
    drawer.classList.toggle('open', open);
    backdrop.hidden = !open;
    drawer.setAttribute('aria-hidden', String(!open));
    $('app-menu-btn').setAttribute('aria-expanded', String(open));
  }
  $('app-menu-btn').addEventListener('click', () => menu(!drawer.classList.contains('open')));
  $('app-menu-close').addEventListener('click', () => menu(false));
  backdrop.addEventListener('click', () => menu(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') menu(false); });

  // chips: a select marked data-chips is shown as a row of tap buttons; the select (hidden) keeps the
  // value and gets the change event
  const chipSels = [];
  function chipify(sel) {
    const box = document.createElement('div');
    box.className = 'app-chips';
    box.setAttribute('role', 'group');
    for (const o of sel.options) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'app-chip'; b.dataset.v = o.value;
      b.textContent = o.textContent;
      b.addEventListener('click', () => {
        if (sel.value !== o.value) { sel.value = o.value; sel.dispatchEvent(new Event('change', { bubbles: true })); }
        syncChip(sel);
      });
      box.appendChild(b);
    }
    sel.hidden = true;
    sel.after(box);
    sel._chips = box;
    sel.addEventListener('change', () => syncChip(sel));
    chipSels.push(sel);
  }
  function syncChip(sel) {
    for (const b of sel._chips.children) {
      const on = b.dataset.v === sel.value;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', String(on));
    }
  }
  const syncChips = () => chipSels.forEach(syncChip);
  document.querySelectorAll('select[data-chips]').forEach(chipify);
  // a select's value from localStorage (only one of its options), and saved when changed
  function bindSel(id, key, def, onChange) {
    const sel = $(id);
    const v = lsGet(key, def);
    sel.value = [...sel.options].some(o => o.value === v) ? v : def;
    sel.addEventListener('change', () => { lsSet(key, sel.value); onChange(sel.value); });
    return sel.value;
  }
  function bindSwitch(id, obj, key, store, onChange) {
    const cb = $(id);
    cb.checked = !!obj[key];
    cb.addEventListener('change', () => { obj[key] = cb.checked; lsSet(store, JSON.stringify(obj)); onChange(cb.checked); });
  }

  // ── charts: one registry for the phone's own charts ─────────────────────
  const charts = {};
  function mkChart(id, cfg) {
    if (charts[id]) charts[id].destroy();
    cfg.options = cfg.options || {};
    cfg.options.animation = false;
    charts[id] = new Chart($(id).getContext('2d'), cfg);
    return charts[id];
  }

  // ── maps ─────────────────────────────────────────────────────────────────
  function makeTiles(dark) {
    const key = CFG.cartoApiKey ? `?key=${CFG.cartoApiKey}` : '';
    return dark
      ? L.tileLayer(`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png${key}`,
          { attribution: '© OpenStreetMap © CARTO', maxZoom: 19, subdomains: 'abcd' })
      : L.tileLayer(`https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png${key}`,
          { attribution: '© OpenStreetMap © CARTO', maxZoom: 19, subdomains: 'abcd' });
  }
  const maps = [];                   // {map, tiles}
  // a map with + / − and ⌂ (home(): the place to return to); a night pane under the overlays
  function mkMap(id, zoom, home) {
    const map = L.map(id, { center: [CFG.mapLat, CFG.mapLon], zoom, zoomControl: false, attributionControl: true });
    const m = { map, tiles: makeTiles(isDark).addTo(map) };
    L.control.zoom({ position: 'topleft' }).addTo(map);
    const Home = L.Control.extend({
      options: { position: 'topleft' },
      onAdd() {
        const bar = L.DomUtil.create('div', 'leaflet-bar');
        const a = L.DomUtil.create('a', 'm-home', bar);
        a.href = '#'; a.title = 'Back to the beacon'; a.setAttribute('role', 'button'); a.textContent = '⌂';
        L.DomEvent.disableClickPropagation(bar);
        L.DomEvent.on(a, 'click', e => { L.DomEvent.preventDefault(e); home(); });
        return bar;
      },
    });
    new Home().addTo(map);
    map.createPane('nightPane');
    map.getPane('nightPane').style.zIndex = 300;
    map.getPane('nightPane').style.pointerEvents = 'none';
    maps.push(m);
    return map;
  }
  // day / night of the moment `when` into a layer group (the full page's renderDayNight, map-layers.js helpers)
  function drawNight(group, when) {
    group.clearLayers();
    const sun = sunPosition(when);
    const { nightPoly, termLine } = buildNightPolygon(sun.lat, sun.lon);
    L.polygon(nightPoly, { stroke: false, fillColor: '#1a3a5c', fillOpacity: 0.40, interactive: false, pane: 'nightPane' }).addTo(group);
    const segs = [[]];
    for (let i = 0; i < termLine.length; i++) {
      segs[segs.length - 1].push(termLine[i]);
      if (i < termLine.length - 1 && Math.abs(termLine[i + 1][0] - termLine[i][0]) > 60) segs.push([]);
    }
    segs.forEach(s => {
      if (s.length > 1) L.polyline(s, { color: '#fbbf24', weight: 1.5, opacity: 0.8, dashArray: '6 5', interactive: false, pane: 'nightPane' }).addTo(group);
    });
  }
  // the reporters' great-circle arcs from (lat, lon): stronger signals brighter and thicker (as the full page)
  function drawArcs(group, lat, lon, reporters) {
    group.clearLayers();
    if (lat == null || !reporters.length) return;
    const snrs = reporters.map(r => r.snr);
    const lo = Math.min(...snrs), span = (Math.max(...snrs) - lo) || 1;
    const accent = '#38bdf8';
    for (const r of reporters) {
      const pos = maidenheadToLatLon(r.grid);
      if (!pos) continue;
      const k = (r.snr - lo) / span, op = 0.18 + k * 0.72, w = 1 + k * 2.5;
      greatCirclePoints(lat, lon, pos[0], pos[1], 60).forEach(seg => {
        if (seg.length > 1) L.polyline(seg, { color: accent, weight: w, opacity: op, interactive: false }).addTo(group);
      });
      L.circleMarker(pos, { radius: 6, color: accent, fillColor: accent, fillOpacity: op, weight: 1.5 })
        .bindPopup(`<strong>${esc(r.callsign)}</strong><br>Grid: ${esc(r.grid)}<br>SNR: ${r.snr} dB<br>Dist: ${km(r.distance)} km` +
                   (r.country ? `<br>${esc(r.country)}` : '')).addTo(group);
    }
  }

  // ── theme ────────────────────────────────────────────────────────────────
  // The button of the top bar: Dark, Light or Auto (follows the phone's setting, also while the page
  // is open); a tap steps Dark → Light → Auto → Dark.  The same key and values as the full page.
  const themeBtn = $('app-theme-btn');
  const themeMq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;
  const THEME_LBL = { dark: 'Dark', light: 'Light', auto: 'Auto — follows the phone' };
  let themeMode = (() => { const m = lsGet('wspr_theme_mode', 'auto'); return m === 'dark' || m === 'light' ? m : 'auto'; })();
  let themeDirty = {};               // views whose charts must be redrawn in the new colours when next shown
  function applyTheme(redraw) {
    const root = document.documentElement;
    const was = isDark;
    const light = themeMode === 'auto' ? !!(themeMq && themeMq.matches) : themeMode === 'light';
    isDark = !light;
    root.classList.toggle('light', light);
    root.dataset.themeMode = themeMode;
    const tc = document.querySelector('meta[name="theme-color"]');
    if (tc) tc.content = light ? '#f1f5f9' : '#111827';
    const lbl = `Theme: ${THEME_LBL[themeMode]}${themeMode === 'auto' ? ` (now ${light ? 'light' : 'dark'})` : ''} — tap to change`;
    themeBtn.title = lbl; themeBtn.setAttribute('aria-label', lbl);
    if (redraw && was !== isDark) {
      for (const m of maps) { m.map.removeLayer(m.tiles); m.tiles = makeTiles(isDark).addTo(m.map); }
      themeDirty = { rep: 1, muf: 1, hist: 1, stats: 1, an: 1 };
      redrawView();
    }
  }
  let themeNoteT = null;
  function themeNote(txt) {
    const n = $('app-theme-note');
    n.textContent = txt; n.hidden = false; n.classList.remove('fade');
    clearTimeout(themeNoteT);
    themeNoteT = setTimeout(() => { n.classList.add('fade'); themeNoteT = setTimeout(() => { n.hidden = true; }, 300); }, 1600);
  }
  applyTheme(false);
  themeBtn.addEventListener('click', () => {
    themeMode = { dark: 'light', light: 'auto', auto: 'dark' }[themeMode];
    lsSet('wspr_theme_mode', themeMode);
    applyTheme(true);
    themeNote(`Theme: ${THEME_LBL[themeMode]}`);
  });
  if (themeMq) {
    const onMq = () => { if (themeMode === 'auto') applyTheme(true); };
    if (themeMq.addEventListener) themeMq.addEventListener('change', onMq); else if (themeMq.addListener) themeMq.addListener(onMq);
  }

  // ══ The latest spot (all the live views) ═══════════════════════════════
  const LV = { latest: null, reporters: [], repAt: 0 };
  // the propagation condition of n stations (the full page's scale)
  function propCond(n) {
    if (n <= 5)   return { text: 'Very low',       color: '#ef4444', pct: 8 };
    if (n <= 10)  return { text: 'Low',            color: '#f97316', pct: 20 };
    if (n <= 20)  return { text: 'Normal',         color: '#eab308', pct: 40 };
    if (n <= 40)  return { text: 'Good',           color: '#84cc16', pct: 60 };
    if (n <= 60)  return { text: 'Very good',      color: '#22c55e', pct: 75 };
    if (n <= 100) return { text: 'Extremely good', color: '#4ade80', pct: 88 };
    return               { text: 'Exceptional',    color: '#a855f7', pct: 100 };
  }
  // {html, color, pct, line} for n reporters, dx of them beyond 6000 km; stale: nothing heard for an hour
  function propState(n, dx, stale, down, atHour) {
    if (down) return { html: '<span style="color:#f59e0b">DB Timeout!</span>', color: '#f59e0b', pct: 5, line: 'wspr.live unreachable' };
    if (stale) {
      const h = atHour == null ? new Date().getUTCHours() : atHour;
      const txt = currentBand === 14 && h >= 6 && h < 15 ? 'No propagation or TX Fail' : 'No propagation';
      return { html: `<span style="color:#ef4444">${txt}</span>`, color: '#ef4444', pct: 0, line: '0 reporters heard' };
    }
    const c = propCond(n || 0), hasDx = dx >= 2;
    return {
      html: `<span style="color:${c.color}">${c.text}</span>` + (hasDx ? ' <span style="color:#4ade80">&amp; DX</span>' : ''),
      color: c.color, pct: c.pct,
      line: `${n} reporter${n === 1 ? '' : 's'} heard` + (hasDx ? `, ${dx} over 6000 km` : ''),
    };
  }
  const ageMin = ts => Math.max(0, Math.round((Date.now() - tsMs(ts)) / 60000));
  const ageTxt = min => min < 60 ? `${min} min ago`
    : min < 2880 ? `${Math.floor(min / 60)} h ${pad(min % 60)} min ago` : `${Math.floor(min / 1440)} days ago`;
  const ageCls = min => min > 60 ? 'old' : min > 25 ? 'warn' : '';

  async function fetchLatest() {
    try { LV.latest = await getJson(`/api/latest?band=${currentBand}`); }
    catch (_) { setHealth(null, 'Connection error'); return null; }
    const s = LV.latest.spot;
    setHealth(s ? s.timestamp : null);
    return LV.latest;
  }
  async function fetchReporters(maxAgeMs) {
    if (Date.now() - LV.repAt < (maxAgeMs || 0)) return LV.reporters;
    try {
      const d = await getJson('/api/reporter_list');
      LV.reporters = d.reporters || [];
      LV.repAt = Date.now();
    } catch (_) { /* keep the last */ }
    return LV.reporters;
  }
  const isStale = () => !LV.latest || !LV.latest.spot || Date.now() - tsMs(LV.latest.spot.timestamp) > 3600e3;
  function liveProp() {
    const d = LV.latest || {}, s = d.spot;
    return propState(s ? s.reporter_count : 0, d.dx6 || 0, isStale(), d.wspr_down);
  }

  // the status dot of the top bar: the full page's status bar
  function setHealth(ts, err) {
    const dot = $('app-health');
    let cls = 'st-err', txt = err || 'No data';
    if (ts) {
      const m = (Date.now() - tsMs(ts)) / 60000;
      cls = m < 20 ? 'st-ok' : m < 120 ? 'st-warn' : 'st-err';
      txt = m < 20 ? `Live · ${Math.round(m)} min ago` : m < 120 ? `Stale · ${Math.round(m)} min ago` : `Last: ${ts.slice(0, 16)} UTC`;
    }
    dot.className = 'app-health ' + cls;
    dot.title = 'Beacon: ' + txt;
    $('app-health-txt').textContent = `Beacon ${CFG.callsign} on ${BAND}: ${txt}`;
  }

  // ══ Live map ═══════════════════════════════════════════════════════════
  const LM = lsJson('wspr_app_map', { trail: true, fixAge: true, arcs: false, dn: false, card: true, follow: false });
  let lmap = null, lmMarker = null, lmTrail = null, lmArcs = null, lmNight = null;
  const lmHome = () => { const s = LV.latest && LV.latest.spot; if (s) lmap.setView([s.lat, s.lon], Math.max(lmap.getZoom(), 6)); };
  function initLiveMap() {
    if (lmap) return;
    lmap = mkMap('m-map', parseInt(lsGet('wspr_app_zoom', CFG.mapZoom), 10) || CFG.mapZoom, lmHome);
    lmap.on('zoomend', () => lsSet('wspr_app_zoom', lmap.getZoom()));
    lmArcs = L.layerGroup().addTo(lmap);
    lmNight = L.layerGroup().addTo(lmap);
  }
  async function loadMap() {
    initLiveMap();
    $('m-live-card').hidden = !LM.card;
    const d = await fetchLatest();
    if (view !== 'map' || !d) return;
    drawLive();
    if (LM.trail) loadTrail(); else if (lmTrail) { lmap.removeLayer(lmTrail); lmTrail = null; }
    if (LM.arcs && !isStale()) { await fetchReporters(); if (view === 'map') drawLiveArcs(); } else lmArcs.clearLayers();
    if (LM.dn) drawNight(lmNight, new Date()); else lmNight.clearLayers();
  }
  function drawLiveArcs() {
    const s = LV.latest && LV.latest.spot;
    if (LM.arcs && s && !isStale()) drawArcs(lmArcs, s.lat, s.lon, LV.reporters); else lmArcs.clearLayers();
  }
  function drawLive() {
    const s = LV.latest && LV.latest.spot;
    const p = liveProp();
    $('m-lc-band').textContent = BAND;
    $('m-lc-prop').innerHTML = p.html;
    $('m-lc-bar').style.width = p.pct + '%'; $('m-lc-bar').style.background = p.color;
    if (!s) { $('m-lc-loc').textContent = '——'; $('m-lc-age').textContent = ''; return; }
    const stale = isStale(), col = stale ? '#ef4444' : '#4ade80', min = ageMin(s.timestamp);
    $('m-lc-loc').textContent = s.tx_loc;
    $('m-lc-loc').style.color = stale ? '#ef4444' : '';
    const age = $('m-lc-age');
    age.textContent = 'last fix ' + ageTxt(min); age.className = 'lc-age ' + ageCls(min);
    $('m-lc-rep').textContent = stale ? '—' : s.reporter_count;
    $('m-lc-dx').textContent = !stale && s.max_distance ? km(s.max_distance) + ' km' : '—';
    $('m-lc-time').textContent = s.timestamp.slice(11, 16) + ' UTC';
    $('app-sub').textContent = `${CFG.callsign} · ${s.tx_loc} · ${BAND}`;
    const popup = `<strong>${esc(CFG.callsign)}</strong><br>Locator: ${esc(s.tx_loc)}<br>Time: ${s.timestamp}<br>` +
                  `Reporters: ${s.reporter_count}<br>Max DX: ${km(s.max_distance)} km`;
    if (lmMarker) lmMarker.setLatLng([s.lat, s.lon]).setStyle({ fillColor: col, color: col }).setPopupContent(popup);
    else {
      lmMarker = L.circleMarker([s.lat, s.lon], { radius: 9, color: col, fillColor: col, fillOpacity: 1, weight: 0 }).addTo(lmap).bindPopup(popup);
      lmMarker.bindTooltip('', { permanent: true, direction: 'right', offset: [12, 0], className: 'fixage', interactive: false });
      lmap.setView([s.lat, s.lon], lmap.getZoom());
    }
    if (LM.follow) lmap.panTo([s.lat, s.lon]);
    const tt = lmMarker.getTooltip();
    tt.setContent('last fix ' + ageTxt(min));
    const el = tt.getElement();
    if (el) { el.classList.toggle('warn', min > 25 && min <= 60); el.classList.toggle('old', min > 60); el.style.display = LM.fixAge ? '' : 'none'; }
  }
  async function loadTrail() {
    try {
      const spots = await getJson(`/api/positions?date=${today()}&band=${currentBand}`);
      if (lmTrail) { lmap.removeLayer(lmTrail); lmTrail = null; }
      if (LM.trail && spots.length > 1) {
        lmTrail = L.polyline(spots.map(s => [s.lat, s.lon]), { color: '#38bdf8', weight: 2, opacity: 0.55, dashArray: '6 4' }).addTo(lmap);
      }
    } catch (_) { /* silent */ }
  }
  bindSwitch('m-o-trail', LM, 'trail', 'wspr_app_map', () => { if (lmap) loadMap(); });
  bindSwitch('m-o-fixage', LM, 'fixAge', 'wspr_app_map', () => { if (lmap) drawLive(); });
  bindSwitch('m-o-arcs', LM, 'arcs', 'wspr_app_map', () => { if (lmap) loadMap(); });
  bindSwitch('m-o-dn', LM, 'dn', 'wspr_app_map', () => { if (lmap) loadMap(); });
  bindSwitch('m-o-card', LM, 'card', 'wspr_app_map', on => { $('m-live-card').hidden = !on; });
  bindSwitch('m-o-follow', LM, 'follow', 'wspr_app_map', on => { if (on && lmap) lmHome(); });

  // ══ Now ═════════════════════════════════════════════════════════════════
  let nowWin = bindSel('m-o-win', 'wspr_app_now_win', 'today', v => { nowWin = v; loadNowStats(); });
  let rnData = null, rnAt = 0;
  async function loadNow() {
    const d = await fetchLatest();
    if (view !== 'now') return;
    if (d) drawNow();
    loadNowStats(); loadSolar(); loadRightNow();
  }
  function drawNow() {
    const d = LV.latest, s = d.spot, p = liveProp(), stale = isStale();
    $('m-now-prop').innerHTML = p.html;
    $('m-now-bar').style.width = p.pct + '%'; $('m-now-bar').style.background = p.color;
    $('m-now-rep').textContent = p.line;
    $('m-now-highmuf').hidden = !(d.muf > 28);
    if (!s) return;
    const min = ageMin(s.timestamp);
    $('m-now-loc').textContent = s.tx_loc;
    $('m-now-loc').style.color = stale ? '#ef4444' : '';
    $('m-now-lat').textContent = s.lat.toFixed(4) + '°';
    $('m-now-lon').textContent = s.lon.toFixed(4) + '°';
    $('m-now-n').textContent = stale ? '—' : s.reporter_count;
    $('m-now-dx').textContent = !stale && s.max_distance ? km(s.max_distance) + ' km' : '—';
    $('m-now-time').textContent = s.timestamp.slice(0, 16);
    const a = $('m-now-age');
    a.textContent = 'last fix ' + ageTxt(min);
    a.style.color = min > 60 ? 'var(--red)' : min > 25 ? 'var(--amber)' : 'var(--green)';
    $('app-sub').textContent = `${CFG.callsign} · ${BAND}`;
  }
  async function loadNowStats() {
    $('m-now-win-t').textContent = nowWin === '1h' ? 'Last hour' : 'Today';
    $('m-now-band').textContent = BAND;
    try {
      let spots, best, maxr;
      if (nowWin === '1h') {
        const now = new Date(), ago = new Date(now - 3600e3);
        const f = t => t.toISOString().replace('T', ' ').slice(0, 19);
        const rows = await getJson(`/api/positions?from=${encodeURIComponent(f(ago))}&to=${encodeURIComponent(f(now))}&band=${currentBand}`);
        spots = rows.length;
        best = rows.reduce((m, x) => Math.max(m, x.max_distance || 0), 0);
        maxr = rows.reduce((m, x) => Math.max(m, x.reporter_count || 0), 0);
      } else {
        const st = (await getJson(`/api/stats?date=${today()}&band=${currentBand}`)).stats || {};
        spots = st.spot_count || 0; best = st.max_distance || 0; maxr = st.max_reporters || 0;
      }
      $('m-now-spots').textContent = spots;
      $('m-now-best').textContent = best ? km(best) + ' km' : '—';
      $('m-now-maxr').textContent = maxr || '—';
    } catch (_) { /* silent */ }
  }
  // the colours of the full page's Solar panel (NOAA scales)
  const SOL = {
    a:  v => v >= 100 ? '#9333ea' : v >= 50 ? '#ef4444' : v >= 30 ? '#f97316' : v >= 16 ? '#facc15' : v >= 8 ? '#a3e635' : '',
    bz: v => v < -20 ? '#9333ea' : v < -15 ? '#ef4444' : v < -10 ? '#f97316' : v < -5 ? '#facc15' : v < -2 ? '#a3e635' : v < 0 ? '#4ade80' : '',
    muf: v => v >= 35 ? '#9333ea' : v >= 30 ? '#ef4444' : v >= 25 ? '#f97316' : v >= 22 ? '#facc15' : v >= 18 ? '#84cc16'
            : v >= 15 ? '#a3e635' : v >= 12 ? '#4ade80' : v >= 8 ? '' : '#6b7280',
    sw: v => v >= 1000 ? '#9333ea' : v >= 800 ? '#ef4444' : v >= 650 ? '#f97316' : v >= 550 ? '#facc15' : v >= 450 ? '#a3e635' : '',
    au: v => v >= 9 ? '#9333ea' : v >= 7 ? '#ef4444' : v >= 6 ? '#f43f5e' : v >= 5 ? '#f97316' : v >= 4 ? '#facc15' : v >= 3 ? '#a3e635' : '',
    pf: v => v >= 1e5 ? '#9333ea' : v >= 1e4 ? '#b91c1c' : v >= 1e3 ? '#ef4444' : v >= 100 ? '#f97316' : v >= 50 ? '#facc15' : '',
    k:  v => v >= 6 ? '#ef4444' : v >= 4 ? '#f97316' : v <= 1 ? '#22c55e' : '',
    x:  s => s.startsWith('X') ? '#ef4444' : s.startsWith('M') ? '#f97316' : s.startsWith('C') ? '#facc15' : '',
  };
  function solTile(id, txt, color) { const el = $(id); el.textContent = txt == null || txt === '' ? '—' : txt; el.style.color = color || ''; }
  async function loadSolar() {
    let d;
    try { d = await getJson('/api/solar'); } catch (_) { return; }
    solTile('m-sol-sfi', d.sfi);
    solTile('m-sol-k', d.kindex, SOL.k(parseInt(d.kindex, 10) || 0));
    solTile('m-sol-a', d.aindex, SOL.a(parseInt(d.aindex, 10) || 0));
    solTile('m-sol-x', d.xray, SOL.x(String(d.xray || '').toUpperCase()));
    solTile('m-sol-bz', d.bz, SOL.bz(parseFloat(d.bz) || 0));
    solTile('m-sol-sw', d.solarwind, SOL.sw(parseFloat(d.solarwind) || 0));
    solTile('m-sol-au', d.aurora, SOL.au(parseInt(d.aurora, 10) || 0));
    solTile('m-sol-pf', d.protonflux, SOL.pf(parseFloat(d.protonflux) || 0));
    solTile('m-sol-fof2', d.fof2 ? d.fof2.toFixed(2) : null);
    solTile('m-sol-muf', d.muf ? d.muf.toFixed(1) : null, SOL.muf(parseFloat(d.muf) || 0));
    $('m-sol-upd').textContent = d.updated ? 'updated ' + d.updated : '';
  }
  // the Analysis page's Right now card (90 days; the server caches it for 10 minutes)
  async function loadRightNow() {
    if (!rnData || Date.now() - rnAt > 600e3) {
      try { rnData = (await getJson(`/api/analysis?days=90&band=${currentBand}`)).now || null; rnAt = Date.now(); }
      catch (_) { /* keep the last */ }
    }
    const n = rnData;
    $('m-now-hist').hidden = !n;
    if (!n) return;
    const f = v => v == null ? '—' : v;
    $('m-rn-sub').textContent = `${pad(n.hour)}:00 UTC · Juliusruh MUF ${n.muf ? n.muf.toFixed(1) + ' MHz' : 'not available'} · last 90 days`;
    $('m-rn-live').textContent = f(n.live_n);
    const t = n.typical, m = n.typical_muf;
    $('m-rn-typ').textContent = t ? f(t.median) : '—';
    $('m-rn-typs').textContent = t ? `usual ${t.p25}–${t.p75}` : '';
    $('m-rn-muf').textContent = m ? f(m.median) : '—';
    $('m-rn-mufs').textContent = m ? `usual ${m.p25}–${m.p75}` : 'not enough history';
    const v = $('m-rn-v');
    v.textContent = { above: 'Better than usual', typical: 'Typical', below: 'Below usual' }[n.verdict] || '—';
    v.style.color = n.verdict === 'above' ? '#4ade80' : n.verdict === 'below' ? '#f59e0b' : '';
    $('m-rn-vb').textContent = n.verdict ? (n.verdict_basis === 'muf' ? 'vs. similar MUF at this hour' : 'vs. this hour of day') : '';
  }

  // ══ Reporters ═══════════════════════════════════════════════════════════
  const RS = lsJson('wspr_app_rep', { list: true, countries: true, hgram: true });
  let repSort = bindSel('m-o-rsort', 'wspr_app_rep_sort', 'snr', v => { repSort = v; drawRep(); });
  let repHg = bindSel('m-o-hg', 'wspr_app_rep_hg', 'snr', v => { repHg = v; drawRep(); });
  document.querySelectorAll('#m-o-rsecs input[data-sec]').forEach(cb => {
    cb.checked = !!RS[cb.dataset.sec];
    cb.addEventListener('change', () => { RS[cb.dataset.sec] = cb.checked; lsSet('wspr_app_rep', JSON.stringify(RS)); drawRep(); });
  });
  $('m-rep-q').addEventListener('input', () => drawRep());
  async function loadRep() {
    await fetchLatest();
    if (view !== 'rep') return;
    if (isStale()) { LV.reporters = []; LV.repAt = Date.now(); } else await fetchReporters();
    if (view === 'rep') drawRep();
  }
  function drawRep() {
    const all = isStale() ? [] : LV.reporters;
    const q = $('m-rep-q').value.trim().toUpperCase();
    const list = q ? all.filter(r => [r.callsign, r.grid, r.country].some(x => String(x || '').toUpperCase().includes(q))) : all.slice();
    $('m-rep-n').textContent = q ? `${list.length} / ${all.length}` : `${all.length} station${all.length === 1 ? '' : 's'}`;
    $('app-sub').textContent = `heard in the last 60 min · ${BAND}`;
    document.querySelectorAll('#m-rep-secs [data-sec]').forEach(el => { el.hidden = !RS[el.dataset.sec]; });
    // list
    const cmp = { snr: (a, b) => b.snr - a.snr, dist: (a, b) => b.distance - a.distance,
                  call: (a, b) => a.callsign.localeCompare(b.callsign), country: (a, b) => String(a.country).localeCompare(String(b.country)) || b.snr - a.snr }[repSort];
    list.sort(cmp);
    $('m-rep-sorted').textContent = { snr: 'by SNR', dist: 'by distance', call: 'by callsign', country: 'by country' }[repSort];
    $('m-rep-list').innerHTML = list.length
      ? list.map(r => `<div class="m-rrow"><span><b>${esc(r.callsign)}</b> <span class="g">${esc(r.grid)}</span></span>` +
          `<span class="snr">${r.snr > 0 ? '+' : ''}${r.snr} dB</span><span class="km${r.distance > 6000 ? ' dx' : ''}">${km(r.distance)} km</span>` +
          `<span class="c">${esc(r.country || '')}</span></div>`).join('')
      : `<div class="m-empty">${all.length ? 'No station matches the search.' : 'No stations heard in the last 60 minutes.'}</div>`;
    // countries
    const cn = {};
    for (const r of list) { const c = r.country || '?'; cn[c] = (cn[c] || 0) + 1; }
    const cl = Object.entries(cn).sort((a, b) => b[1] - a[1]);
    $('m-rep-cn').textContent = cl.length ? `${cl.length} countr${cl.length === 1 ? 'y' : 'ies'}` : '';
    $('m-rep-countries').innerHTML = cl.length
      ? cl.map(([c, n]) => `<div class="m-cbar"><span>${esc(c)}</span><span class="bw"><i style="width:${Math.round(100 * n / cl[0][1])}%"></i></span><span class="n">${n}</span></div>`).join('')
      : '<div class="m-empty">No data</div>';
    // distribution (the full page's histogram)
    if (!RS.hgram) return;
    let labels, counts;
    if (repHg === 'snr') {
      counts = new Array(15).fill(0);
      list.forEach(r => { const i = Math.floor((r.snr + 33) / 3); if (i >= 0 && i < 15) counts[i]++; });
      labels = counts.map((_, i) => { const v = -33 + i * 3; return (v >= 0 ? '+' : '') + v; });
    } else {
      const mx = Math.max(...list.map(r => r.distance), 1000), step = mx <= 5000 ? 500 : 1000, n = Math.ceil(mx / step) + 1;
      counts = new Array(n).fill(0);
      list.forEach(r => { const i = Math.floor(r.distance / step); if (i >= 0 && i < n) counts[i]++; });
      labels = counts.map((_, i) => (i * step / 1000).toFixed(i * step < 1000 ? 1 : 0) + 'k');
    }
    $('m-rep-hgt').textContent = repHg === 'snr' ? 'SNR distribution (dB)' : 'Distance distribution (km)';
    const col = anColors();
    mkChart('m-rep-hg', {
      type: 'bar',
      data: { labels, datasets: [{ data: counts, backgroundColor: 'rgba(56,189,248,0.55)', borderColor: '#38bdf8', borderWidth: 1 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false },
                   tooltip: { callbacks: { title: it => (repHg === 'snr' ? 'SNR ' : 'Distance ') + it[0].label, label: it => 'Stations: ' + it.raw } } },
        scales: { x: { ticks: { color: col.text, font: { size: 10 }, maxRotation: 0 }, grid: { display: false } },
                  y: { beginAtZero: true, ticks: { color: col.text, font: { size: 10 }, precision: 0 }, grid: { color: col.grid } } },
      },
    });
  }

  // ══ MUF graph ═══════════════════════════════════════════════════════════
  let mufDays = parseInt(bindSel('m-o-mufd', 'wspr_app_mufd', '2', v => { mufDays = parseInt(v, 10); loadMuf(); }), 10);
  let mufData = null;
  async function loadMuf() {
    const lbl = { 1: 'last 24 h', 2: 'last 2 days', 3: 'last 3 days', 7: 'last 7 days' }[mufDays];
    $('m-muf-t').textContent = `MUF D=3000 km & reporters — ${lbl}`;
    $('app-sub').textContent = `Juliusruh ionosonde · ${lbl}`;
    try { mufData = await getJson(`/api/muf?band=${currentBand}&days=${mufDays}`); } catch (_) { return; }
    if (view === 'muf') drawMuf();
  }
  function drawMuf() {
    if (!mufData) return;
    const muf = mufData.muf || [], sp = mufData.spots || [];
    const mm = {}, sm = {};
    muf.forEach(r => { mm[r.timestamp] = r.muf; });
    sp.forEach(s => { sm[s.timestamp] = Math.max(sm[s.timestamp] || 0, s.reporter_count); });
    const times = [...new Set([...muf.map(r => r.timestamp), ...sp.map(s => s.timestamp)])].sort();
    const lab = ts => mufDays <= 1 ? ts.slice(11, 16) : `${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][new Date(tsMs(ts)).getUTCDay()]} ${ts.slice(11, 16)}`;
    const col = anColors();
    const last = muf.length ? muf[muf.length - 1] : null;
    $('m-muf-note').textContent = last ? `Latest MUF ${last.muf.toFixed(1)} MHz at ${last.timestamp.slice(0, 16)} UTC.` : 'No MUF readings in this range.';
    mkChart('m-muf-c', {
      data: { labels: times.map(lab), datasets: [
        { type: 'line', label: 'MUF (MHz)', data: times.map(t => mm[t] ?? null), borderColor: '#38bdf8', backgroundColor: 'transparent',
          borderWidth: 1.5, pointRadius: 0, yAxisID: 'yM', tension: 0.4, spanGaps: true, order: 1 },
        { type: 'bar', label: 'Reporters', data: times.map(t => sm[t] || 0), backgroundColor: 'rgba(74,222,128,0.45)',
          borderColor: '#4ade80', borderWidth: 1, yAxisID: 'yR', order: 2 },
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { color: col.text, font: { size: 11 }, boxWidth: 12 } } },
        scales: {
          x: { ticks: { color: col.text, font: { size: 9 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 }, grid: { color: col.grid } },
          yM: { type: 'linear', position: 'left', ticks: { color: '#38bdf8', font: { size: 10 } }, grid: { color: col.grid },
                title: { display: true, text: 'MUF (MHz)', color: '#38bdf8', font: { size: 10 } } },
          yR: { type: 'linear', position: 'right', beginAtZero: true, ticks: { color: '#4ade80', font: { size: 10 }, precision: 0 },
                grid: { drawOnChartArea: false }, title: { display: true, text: 'reporters', color: '#4ade80', font: { size: 10 } } },
        },
      },
    });
  }

  // ══ Replay ══════════════════════════════════════════════════════════════
  const RPO = lsJson('wspr_app_replay', { arcs: true, dn: true });
  const RP = { dates: null, date: null, frames: [], spots: [], idx: 0, timer: null, fps: 4, seq: 0 };
  RP.fps = parseInt(bindSel('m-o-rp-fps', 'wspr_app_rp_fps', '4', v => { RP.fps = parseInt(v, 10); if (RP.timer) { rpPause(); rpPlay(); } }), 10);
  let rmap = null, rmMarker = null, rmTrail = null, rmArcs = null, rmNight = null;
  const rmHome = () => { if (rmMarker) rmap.setView(rmMarker.getLatLng(), Math.max(rmap.getZoom(), 5)); };
  function initReplayMap() {
    if (rmap) return;
    rmap = mkMap('m-rmap', Math.max(2, CFG.mapZoom - 3), rmHome);
    rmArcs = L.layerGroup().addTo(rmap);
    rmNight = L.layerGroup().addTo(rmap);
  }
  async function rpDates() {
    if (RP.dates) return RP.dates;
    try {
      const d = await getJson(`/api/replay/dates?band=${currentBand}`);
      if (!d.enabled) { showToast('The replay database is disabled in config.ini', 'err'); return null; }
      RP.dates = d.dates || [];
    } catch (_) { showToast('Could not load the replay dates', 'err'); return null; }
    if (RP.dates.length) { $('m-o-rp-date').min = RP.dates[RP.dates.length - 1]; $('m-o-rp-date').max = RP.dates[0]; }
    return RP.dates;
  }
  async function loadReplay() {
    initReplayMap();
    if (RP.date) { if (!RP.frames.length) await rpLoad(RP.date); else rpApply(); return; }
    const ds = await rpDates();
    if (!ds || !ds.length) { $('m-rp-time').textContent = 'No replay data stored yet'; return; }
    await rpLoad(ds[0], null, true);
  }
  // open a day (and a moment of it): ts 'YYYY-MM-DD HH:MM:SS'; toEnd: the newest snapshot
  async function rpLoad(date, ts, toEnd) {
    rpPause();
    const seq = ++RP.seq;
    const ds = await rpDates();
    if (!ds) return;
    if (!ds.includes(date)) {
      const near = ds.find(d => d <= date) || ds[ds.length - 1];
      if (!near) return;
      showToast(`No replay data for ${date} — showing ${near}`, 'err');
      date = near; ts = null;
    }
    $('m-rp-time').textContent = 'Loading…';
    try {
      const [fr, sp] = await Promise.all([
        getJson(`/api/replay/day?date=${date}&band=${currentBand}`),
        getJson(`/api/positions?date=${date}&band=${currentBand}`),
      ]);
      if (seq !== RP.seq) return;
      RP.frames = fr.frames || []; RP.spots = Array.isArray(sp) ? sp : [];
    } catch (_) { showToast('Failed to load the replay day', 'err'); return; }
    RP.date = date;
    $('m-o-rp-date').value = date;
    $('m-rp-slider').max = Math.max(RP.frames.length - 1, 0);
    if (rmTrail) { rmap.removeLayer(rmTrail); rmTrail = null; }
    if (RP.spots.length > 1) rmTrail = L.polyline(RP.spots.map(s => [s.lat, s.lon]), { color: '#94a3b8', weight: 2, opacity: 0.6, dashArray: '5 5' }).addTo(rmap);
    let idx = toEnd ? RP.frames.length - 1 : 0;
    if (ts) { const k = RP.frames.findIndex(f => f.ts >= ts); idx = k < 0 ? RP.frames.length - 1 : k; }
    rpSeek(idx, true);
  }
  function rpSeek(i, recenter) {
    RP.idx = Math.max(0, Math.min(parseInt(i, 10) || 0, RP.frames.length - 1));
    rpApply(recenter);
  }
  function rpApply(recenter) {
    const f = RP.frames[RP.idx];
    $('m-rp-slider').value = RP.idx;
    const ds = RP.dates || [];
    $('m-rp-pday').disabled = !ds.some(d => d < RP.date);
    $('m-rp-nday').disabled = !ds.some(d => d > RP.date);
    $('app-sub').textContent = RP.date ? niceDay(RP.date) : '';
    if (!f) { $('m-rp-time').textContent = `${RP.date || ''} — no data`; $('m-rp-n').textContent = ''; $('m-rp-prop').innerHTML = ''; rmArcs.clearLayers(); return; }
    $('m-rp-time').textContent = f.ts.slice(11, 16) + ' UTC';
    $('m-rp-n').textContent = `${RP.idx + 1} / ${RP.frames.length}`;
    let sp = null;
    for (const s of RP.spots) { if (s.timestamp <= f.ts) sp = s; else break; }
    if (!sp) sp = RP.spots[0] || null;
    const age = sp ? tsMs(f.ts) - tsMs(sp.timestamp) : Infinity;
    const fresh = sp && age >= 0 && age <= 25 * 60000;
    const reps = f.r.map(a => ({ callsign: a[0], grid: a[1], snr: a[2], distance: a[3] }));
    const p = propState(fresh ? sp.reporter_count : 0, reps.filter(r => r.distance > 6000).length, !fresh, false, parseInt(f.ts.slice(11, 13), 10));
    $('m-rp-prop').innerHTML = p.html + ` <span style="color:var(--text-2);font-weight:400">· ${reps.length} heard</span>`;
    if (sp) {
      const col = fresh ? '#4ade80' : '#ef4444';
      const pop = `<strong>${esc(CFG.callsign)}</strong><br>${esc(sp.tx_loc)}<br>Fix: ${sp.timestamp}<br>Reporters: ${sp.reporter_count}`;
      if (rmMarker) rmMarker.setLatLng([sp.lat, sp.lon]).setStyle({ color: col, fillColor: col }).setPopupContent(pop);
      else rmMarker = L.circleMarker([sp.lat, sp.lon], { radius: 9, color: col, fillColor: col, fillOpacity: 1, weight: 0 }).addTo(rmap).bindPopup(pop);
      if (recenter) rmap.setView([sp.lat, sp.lon], rmap.getZoom());
    }
    if (RPO.arcs && sp) drawArcs(rmArcs, sp.lat, sp.lon, reps); else rmArcs.clearLayers();
    if (RPO.dn) drawNight(rmNight, new Date(tsMs(f.ts))); else rmNight.clearLayers();
  }
  function rpPlay() {
    if (!RP.frames.length) return;
    if (RP.idx >= RP.frames.length - 1) rpSeek(0);
    $('m-rp-play').textContent = '❚❚';
    RP.timer = setInterval(() => { if (RP.idx >= RP.frames.length - 1) { rpPause(); return; } rpSeek(RP.idx + 1); }, 1000 / RP.fps);
  }
  function rpPause() {
    if (RP.timer) { clearInterval(RP.timer); RP.timer = null; }
    $('m-rp-play').textContent = '▶';
  }
  function rpDay(dir) {
    const ds = RP.dates || [];
    const t = dir < 0 ? ds.find(d => d < RP.date) : [...ds].reverse().find(d => d > RP.date);
    if (t) rpLoad(t);
  }
  $('m-rp-slider').addEventListener('input', e => { rpPause(); rpSeek(e.target.value); });
  $('m-rp-play').addEventListener('click', () => (RP.timer ? rpPause() : rpPlay()));
  $('m-rp-prev').addEventListener('click', () => { rpPause(); rpSeek(RP.idx - 1); });
  $('m-rp-next').addEventListener('click', () => { rpPause(); rpSeek(RP.idx + 1); });
  $('m-rp-pday').addEventListener('click', () => rpDay(-1));
  $('m-rp-nday').addEventListener('click', () => rpDay(1));
  $('m-o-rp-prev').addEventListener('click', () => rpDay(-1));
  $('m-o-rp-next').addEventListener('click', () => rpDay(1));
  $('m-o-rp-date').addEventListener('change', e => { if (e.target.value) rpLoad(e.target.value); });
  bindSwitch('m-o-rp-arcs', RPO, 'arcs', 'wspr_app_replay', () => { if (rmap) rpApply(); });
  bindSwitch('m-o-rp-dn', RPO, 'dn', 'wspr_app_replay', () => { if (rmap) rpApply(); });
  // the Analysis tables' ▶, History's rows and WPRS's Replay button (m-shim.js enterReplay)
  async function openReplay(date, ts) {
    setView('replay', false, true);
    initReplayMap();
    await rpLoad(date, ts);
  }

  // ══ History ═════════════════════════════════════════════════════════════
  const HO = lsJson('wspr_app_hist', { map: true, chart: true });
  const HD = { date: today(), stats: null, spots: [], seq: 0 };
  let hmap = null, hmLayer = null;
  function initHistMap() {
    if (hmap) return;
    hmap = mkMap('m-hmap', Math.max(2, CFG.mapZoom - 1), () => { if (HD.spots.length) fitHist(); });
    hmLayer = L.layerGroup().addTo(hmap);
  }
  const fitHist = () => hmap.fitBounds(L.latLngBounds(HD.spots.map(s => [s.lat, s.lon])), { padding: [30, 30], maxZoom: 12 });
  async function loadHist() {
    $('m-hd-date').value = HD.date;
    $('m-hd-date').max = today();
    $('m-hd-next').disabled = HD.date >= today();
    $('app-sub').textContent = niceDay(HD.date, 'long');
    $('m-hd-title').textContent = niceDay(HD.date, 'long');
    const seq = ++HD.seq, date = HD.date;
    try {
      const [st, pos] = await Promise.all([
        getJson(`/api/stats?date=${date}&band=${currentBand}`),
        getJson(`/api/positions?date=${date}&band=${currentBand}`),
      ]);
      if (seq !== HD.seq) return;                // a later date was chosen meanwhile
      HD.stats = st.stats || {}; HD.spots = Array.isArray(pos) ? pos : [];
    } catch (_) { if (seq === HD.seq) showToast('Failed to load history', 'err'); return; }
    if (view === 'hist') drawHist(true);
  }
  function drawHist(fit) {
    const s = HD.stats || {}, sp = HD.spots;
    $('m-hd-spots').textContent = s.spot_count || 0;
    $('m-hd-maxr').textContent = s.max_reporters || '—';
    $('m-hd-dx').textContent = s.max_distance ? km(s.max_distance) : '—';
    $('m-hd-avg').textContent = sp.length ? (sp.reduce((a, x) => a + (x.reporter_count || 0), 0) / sp.length).toFixed(1) : '—';
    $('m-hd-first').textContent = s.first_spot ? s.first_spot.slice(11, 16) : '—';
    $('m-hd-last').textContent = s.last_spot ? s.last_spot.slice(11, 16) : '—';
    // map
    $('m-hmap').closest('.m-card').hidden = !HO.map;
    if (HO.map) {
      initHistMap();
      hmap.invalidateSize();
      hmLayer.clearLayers();
      if (sp.length > 1) L.polyline(sp.map(x => [x.lat, x.lon]), { color: '#38bdf8', weight: 2.5, opacity: 0.7 }).addTo(hmLayer);
      sp.forEach((x, i) => {
        const last = i === sp.length - 1, first = i === 0;
        const c = last ? '#38bdf8' : first ? '#4ade80' : '#94a3b8';
        L.circleMarker([x.lat, x.lon], { radius: last ? 8 : 5, color: c, fillColor: c, fillOpacity: 0.85, weight: 2 })
          .bindPopup(`<strong>${esc(x.tx_loc)}</strong><br>${x.timestamp}<br>Reporters: ${x.reporter_count}<br>Max DX: ${km(x.max_distance)} km`).addTo(hmLayer);
      });
      if (fit && sp.length) fitHist();
    }
    // chart
    $('m-hd-chartcard').hidden = !HO.chart || !sp.length;
    if (HO.chart && sp.length) {
      const col = anColors();
      mkChart('m-hd-c', {
        type: 'bar',
        data: { labels: sp.map(x => x.timestamp.slice(11, 16)), datasets: [
          { type: 'bar', label: 'Reporters', data: sp.map(x => x.reporter_count), yAxisID: 'y', backgroundColor: 'rgba(56,189,248,0.65)' },
          { type: 'line', label: 'Farthest (km)', data: sp.map(x => x.max_distance), yAxisID: 'y2', borderColor: '#4ade80',
            backgroundColor: '#4ade80', borderWidth: 1.5, pointRadius: 1.5, tension: 0.2 },
        ] },
        options: {
          responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
          plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } } },
          scales: {
            x: { ticks: { color: col.text, font: { size: 9 }, maxTicksLimit: 8, maxRotation: 0 }, grid: { display: false } },
            y: { beginAtZero: true, ticks: { color: col.text, font: { size: 10 }, precision: 0 }, grid: { color: col.grid } },
            y2: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { color: col.text, font: { size: 10 } } },
          },
        },
      });
    }
    // rows, newest first
    $('m-hd-list').innerHTML = sp.length
      ? [...sp].reverse().map(x => `<div class="app-card row"><button type="button" class="hd" data-ts="${esc(x.timestamp)}">` +
          `<span>${x.timestamp.slice(11, 16)}</span><span class="loc">${esc(x.tx_loc)}</span>` +
          `<span class="r">${x.reporter_count}</span><span class="r">${x.max_distance ? km(x.max_distance) : '—'}</span></button></div>`).join('')
      : '<div class="m-empty">No data for this date.</div>';
  }
  $('m-hd-list').addEventListener('click', e => {
    const b = e.target.closest('button[data-ts]');
    if (b) openReplay(b.dataset.ts.slice(0, 10), b.dataset.ts);
  });
  const histGo = d => { HD.date = d > today() ? today() : d; loadHist(); };
  $('m-hd-prev').addEventListener('click', () => histGo(addDays(HD.date, -1)));
  $('m-hd-next').addEventListener('click', () => histGo(addDays(HD.date, 1)));
  $('m-hd-today').addEventListener('click', () => histGo(today()));
  $('m-hd-date').addEventListener('change', e => { if (e.target.value) histGo(e.target.value); });
  bindSwitch('m-o-hmap', HO, 'map', 'wspr_app_hist', () => { if (view === 'hist') drawHist(true); });
  bindSwitch('m-o-hchart', HO, 'chart', 'wspr_app_hist', () => { if (view === 'hist') drawHist(false); });

  // ══ Statistics ══════════════════════════════════════════════════════════
  let stRange = parseInt(bindSel('m-o-strange', 'wspr_app_st_range', '90', v => { stRange = parseInt(v, 10); drawStats(); }), 10);
  const ST = { at: null, daily: [] };
  async function loadStats() {
    $('app-sub').textContent = `${CFG.callsign} · ${BAND}`;
    try {
      const [st, daily] = await Promise.all([
        getJson(`/api/stats?date=${today()}&band=${currentBand}`),
        getJson(`/api/daily_summary?band=${currentBand}`),
      ]);
      ST.at = st.all_time || {}; ST.daily = Array.isArray(daily) ? daily : [];
    } catch (_) { showToast('Failed to load stats', 'err'); return; }
    if (view === 'stats') drawStats();
  }
  function drawStats() {
    if (!ST.at) return;
    const at = ST.at, daily = ST.daily;
    const dxDay = daily.find(x => x.max_dx === at.best_dx), repDay = daily.find(x => x.max_reporters === at.best_reporters);
    $('m-at-spots').textContent = at.total_spots ? km(at.total_spots) : '—';
    $('m-at-days').textContent = at.active_days || '—';
    $('m-at-dx').textContent = at.best_dx ? km(at.best_dx) + ' km' : '—';
    $('m-at-dxd').textContent = dxDay ? dxDay.date : '';
    $('m-at-rep').textContent = at.best_reporters || '—';
    $('m-at-repd').textContent = repDay ? repDay.date : '';
    $('m-at-first').textContent = at.first_ever ? String(at.first_ever).slice(0, 16) : '—';
    $('m-at-last').textContent = at.last_ever ? String(at.last_ever).slice(0, 16) : '—';
    let rows = daily;
    if (stRange > 0) { const cut = addDays(today(), -stRange); rows = rows.filter(x => x.date >= cut); }
    $('m-st-range-t').textContent = stRange ? `last ${stRange} days` : 'all days';
    const col = anColors();
    mkChart('m-st-c', {
      type: 'bar',
      data: { labels: rows.map(x => x.date.slice(5)), datasets: [
        { type: 'bar', label: 'Best DX (km)', data: rows.map(x => x.max_dx), yAxisID: 'y', backgroundColor: 'rgba(56,189,248,0.65)' },
        { type: 'line', label: 'Max reporters', data: rows.map(x => x.max_reporters), yAxisID: 'y2', borderColor: '#4ade80',
          backgroundColor: '#4ade80', borderWidth: 1.5, pointRadius: 1.5, tension: 0.2 },
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        onClick: (e, els) => { if (els.length) { HD.date = rows[els[0].index].date; setView('hist'); } },
        plugins: { legend: { labels: { color: col.text, boxWidth: 12, font: { size: 10 } } },
                   tooltip: { callbacks: { title: it => rows[it[0].dataIndex].date, afterBody: it => `${rows[it[0].dataIndex].spots} transmissions logged` } } },
        scales: {
          x: { ticks: { color: col.text, font: { size: 9 }, maxTicksLimit: 7, maxRotation: 0 }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { color: col.text, font: { size: 10 } }, grid: { color: col.grid } },
          y2: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { color: col.text, font: { size: 10 }, precision: 0 } },
        },
      },
    });
  }

  // ══ Analysis (analysis.js and analysis-more.js on the same markup) ═════
  const anView = $('analysis-view');
  $('m-o-andays').addEventListener('change', e => setAnalysisDays(parseInt(e.target.value, 10)));
  function showAnalysis() {
    $('m-o-andays').value = String(_anDays);
    syncChip($('m-o-andays'));
    $('app-sub').textContent = 'propagation analysis · ' + BAND;
    if (!_anData) { loadAnalysis(); return; }
    if (themeDirty.an) { renderAnalysis(); return; }
    // drawn while another view was shown (or the phone turned): the canvases follow the width again
    drawHeatmap();
    if (_amData && !_amData.empty) drawPolar();
  }
  // the period buttons at the top of the view: keep the menu's chips in step
  anView.addEventListener('click', e => {
    if (e.target.closest('[id^="anP"]')) setTimeout(() => { $('m-o-andays').value = String(_anDays); syncChip($('m-o-andays')); }, 0);
  });

  // ══ WPRS ════════════════════════════════════════════════════════════════
  const W = { data: null, sel: null, track: null, idx: 0, timer: null, pending: null };
  let wTab = bindSel('m-o-wtab', 'wspr_app_wprs_tab', 'days', v => { wTab = v; drawWprsList(); });
  let wMin = parseInt(bindSel('m-o-wmin', 'wspr_wprs_min', '10', v => { wMin = parseInt(v, 10); drawWprsList(); }), 10);
  let wSpan = parseInt(bindSel('m-o-wspan', 'wspr_app_wprs_span', '1', v => { wSpan = parseInt(v, 10); if (W.sel) wprsSelect(W.sel); }), 10);
  let wFps = parseInt(bindSel('m-o-wfps', 'wspr_app_wprs_fps', '4', v => { wFps = parseInt(v, 10); if (W.timer) { wPause(); wPlay(); } }), 10);
  let wmap = null, wLayer = null, wPlayed = null, wCursor = null;
  function initWprsMap() {
    if (wmap) return;
    wmap = mkMap('m-wmap', Math.max(2, CFG.mapZoom - 2), () => { if (W.track && W.track.fixes.length) wFit(); });
    wLayer = L.layerGroup().addTo(wmap);
  }
  const passes = d => wMin <= 0 ? d.squares > 1 : Math.max(d.spread_km, d.home_km) >= wMin;
  const wDur = h => { if (h < 1) return '< 1 h'; const t = Math.round(h), d = Math.floor(t / 24); return d ? `${d} d ${t % 24} h` : `${t} h`; };
  async function loadWprs() {
    initWprsMap();
    $('app-sub').textContent = 'position history · ' + BAND;
    try { W.data = await getJson(`/api/wprs/days?band=${currentBand}`); }
    catch (_) { $('m-wp-list').innerHTML = '<div class="m-empty">Could not load the position history.</div>'; return; }
    if (view !== 'wprs') return;
    drawWprsList();
    if (!W.sel) { const first = W.data.days.find(passes); if (first) wprsSelect(first.date); }
    else if (W.track) { wmap.invalidateSize(); }
  }
  function drawWprsList() {
    if (!W.data) return;
    const box = $('m-wp-list'), home = W.data.home ? W.data.home.loc : '?';
    if (wTab === 'trips') {
      const trips = W.data.trips || [];
      $('m-wp-count').textContent = `${trips.length} trip${trips.length === 1 ? '' : 's'} beyond 25 km from home (${home})`;
      const f = d => new Date(d + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
      box.innerHTML = trips.length ? trips.map((t, i) => {
        const range = t.date_from === t.date_to ? `${f(t.date_from)} ${t.date_from.slice(0, 4)}` : `${f(t.date_from)} – ${f(t.date_to)} ${t.date_from.slice(0, 4)}`;
        return `<div class="app-card${t.date_from === W.sel ? ' sel' : ''}"><button type="button" class="hd" data-trip="${i}">` +
          `<span class="l1"><b>${range}</b><span class="chs"><span class="ch">${wDur(t.hours)}</span></span></span>` +
          `<span class="l2">farthest <b>${t.far_km.toFixed(0)} km</b> (${esc(t.far_loc)}) · path ${t.path_km.toFixed(0)} km · ${t.squares} squares · best DX ${t.best_dx ? km(t.best_dx) + ' km' : '—'}</span>` +
          `<span class="l2">mostly in ${esc(t.top_loc)} · ${t.fixes} fixes · ${t.start.slice(11, 16)}–${t.end.slice(11, 16)} UTC</span></button></div>`;
      }).join('') : '<div class="m-empty">No trips beyond 25 km from home have been logged.</div>';
      return;
    }
    const days = W.data.days.filter(passes);
    $('m-wp-count').textContent = `${days.length} of ${W.data.days.length} logged days · home square ${home}`;
    const mx = Math.max(1, ...days.map(d => Math.max(d.spread_km, d.home_km)));
    box.innerHTML = days.length ? days.map(d => {
      const w = Math.max(3, Math.round(100 * Math.max(d.spread_km, d.home_km) / mx));
      const away = d.home_km >= 25 ? ` · <span class="away">${d.home_km.toFixed(0)} km from home</span>` : '';
      return `<div class="app-card${d.date === W.sel ? ' sel' : ''}"><button type="button" class="hd" data-date="${d.date}">` +
        `<span class="l1"><b>${niceDay(d.date)}</b><span class="chs"><span class="ch">${d.squares} sq · ${d.fixes} fixes</span></span></span>` +
        `<span class="mini"><i style="width:${w}%"></i></span>` +
        `<span class="l2">moved ${d.spread_km.toFixed(1)} km · path ${d.path_km.toFixed(0)} km · ${d.first}–${d.last} UTC${away}</span></button></div>`;
    }).join('') : '<div class="m-empty">No day moves that far.</div>';
  }
  $('m-wp-list').addEventListener('click', e => {
    const b = e.target.closest('button.hd');
    if (!b) return;
    if (b.dataset.trip != null) {
      const t = W.data.trips[+b.dataset.trip];
      const want = Math.min(t.days, 7), sel = $('m-o-wspan');
      const opt = [...sel.options].map(o => +o.value).find(v => v >= want) || 7;
      sel.value = String(opt); wSpan = opt; syncChip(sel);
      wprsSelect(t.date_from);
    } else wprsSelect(b.dataset.date);
    $('v-wprs').scrollTo({ top: 0, behavior: 'smooth' });
  });
  async function wprsSelect(date) {
    wPause();
    W.sel = date;
    drawWprsList();
    const to = addDays(date, wSpan - 1);
    try {
      W.track = await getJson(`/api/wprs/track?from=${date}&to=${to}&band=${currentBand}`);
      if (W.track.error || !W.track.fixes) throw new Error(W.track.error || 'no track');
    } catch (_) { W.track = null; $('m-wp-sum').textContent = 'Could not load this track.'; return; }
    drawWprsTrack(date, to);
  }
  function wFit() {
    const t = W.track, pts = t.fixes.map(f => [f.lat, f.lon]);
    if (t.stats.squares === 1) wmap.setView(pts[0], 12); else wmap.fitBounds(L.latLngBounds(pts), { padding: [30, 30], maxZoom: 13 });
  }
  function drawWprsTrack(from, to) {
    wLayer.clearLayers();
    const t = W.track, range = from === to ? niceDay(from) : `${from} → ${to}`;
    if (!t.fixes.length) { $('m-wp-sum').textContent = `${range}: no fixes logged`; $('m-wp-slider').max = 0; $('m-wp-time').textContent = '—'; return; }
    const st = t.stats, acc = anColors().accent;
    $('m-wp-sum').innerHTML = `<b>${range}</b> · ${st.fixes} fixes · ${st.squares} square${st.squares === 1 ? '' : 's'} · moved ${st.spread_km} km · ` +
      `path ${st.path_km} km · farthest from home ${st.home_km} km`;
    const maxN = Math.max(...t.squares.map(q => q.n));
    for (const q of t.squares) {
      L.rectangle([[q.lat - q.hlat, q.lon - q.hlon], [q.lat + q.hlat, q.lon + q.hlon]],
        { color: acc, weight: 1, fillColor: acc, fillOpacity: 0.12 + 0.45 * Math.log(q.n + 1) / Math.log(maxN + 1) })
        .bindPopup(`${esc(q.loc)} · ${q.n} fix${q.n === 1 ? '' : 'es'} · first ${q.first.slice(5, 16)} UTC`).addTo(wLayer);
    }
    const pts = t.fixes.map(f => [f.lat, f.lon]);
    L.polyline(pts, { color: '#94a3b8', weight: 2, opacity: 0.8, dashArray: '4 5', interactive: false }).addTo(wLayer);
    if (t.home) L.circleMarker([t.home.lat, t.home.lon], { radius: 9, color: '#f87171', weight: 2, fillOpacity: 0 }).bindPopup(`Home square ${esc(t.home.loc)}`).addTo(wLayer);
    const a = t.fixes[0], z = t.fixes[t.fixes.length - 1];
    L.circleMarker([a.lat, a.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#4ade80', fillOpacity: 1 }).bindPopup(`Start ${a.t.slice(5, 16)} UTC · ${esc(a.loc)}`).addTo(wLayer);
    L.circleMarker([z.lat, z.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#f87171', fillOpacity: 1 }).bindPopup(`End ${z.t.slice(5, 16)} UTC · ${esc(z.loc)}`).addTo(wLayer);
    wPlayed = L.polyline([], { color: '#f59e0b', weight: 4, interactive: false }).addTo(wLayer);
    wCursor = L.circleMarker([a.lat, a.lon], { radius: 10, color: '#f59e0b', weight: 3, fillColor: '#ffffff', fillOpacity: 1, interactive: false }).addTo(wLayer);
    wmap.invalidateSize();
    wFit();
    $('m-wp-slider').max = t.fixes.length - 1;
    wShow(W.pending != null ? W.pending : 0);
    W.pending = null;
  }
  function wShow(i) {
    const t = W.track;
    if (!t || !t.fixes.length) return;
    W.idx = Math.max(0, Math.min(i, t.fixes.length - 1));
    const f = t.fixes[W.idx];
    $('m-wp-slider').value = W.idx;
    $('m-wp-time').textContent = `${f.t.slice(5, 16)} UTC · ${f.loc} · ${f.n} rptr${f.n === 1 ? '' : 's'} · ${W.idx + 1}/${t.fixes.length}`;
    wPlayed.setLatLngs(t.fixes.slice(0, W.idx + 1).map(x => [x.lat, x.lon]));
    wCursor.setLatLng([f.lat, f.lon]);
    if (!wmap.getBounds().pad(-0.1).contains([f.lat, f.lon])) wmap.panTo([f.lat, f.lon]);
  }
  function wPlay() {
    if (!W.track || !W.track.fixes.length) return;
    if (W.idx >= W.track.fixes.length - 1) wShow(0);
    $('m-wp-play').textContent = '❚❚';
    W.timer = setInterval(() => { if (W.idx >= W.track.fixes.length - 1) { wPause(); return; } wShow(W.idx + 1); }, 1000 / wFps);
  }
  function wPause() {
    if (W.timer) { clearInterval(W.timer); W.timer = null; }
    $('m-wp-play').textContent = '▶';
  }
  $('m-wp-slider').addEventListener('input', e => { wPause(); wShow(+e.target.value); });
  $('m-wp-play').addEventListener('click', () => (W.timer ? wPause() : wPlay()));
  $('m-wp-start').addEventListener('click', () => { wPause(); wShow(0); });
  $('m-wp-prev').addEventListener('click', () => { wPause(); wShow(W.idx - 1); });
  $('m-wp-next').addEventListener('click', () => { wPause(); wShow(W.idx + 1); });
  $('m-wp-replay').addEventListener('click', () => {
    if (W.track && W.track.fixes.length) { const f = W.track.fixes[W.idx]; openReplay(f.t.slice(0, 10), f.t); }
  });

  // ══ Views ═══════════════════════════════════════════════════════════════
  const LOADERS = { map: loadMap, now: loadNow, rep: loadRep, muf: loadMuf, replay: loadReplay, hist: loadHist,
                    stats: loadStats, an: showAnalysis, wprs: loadWprs };
  // the shown view's data again (every minute for the live views, on return to the page)
  function refresh() {
    if (document.hidden) return;
    if (view === 'map') loadMap();
    else if (view === 'now') loadNow();
    else if (view === 'rep') loadRep();
    else if (view === 'muf') loadMuf();
    else fetchLatest();                          // the status dot
  }
  // after a theme change: the shown view's charts in the new colours (the others when next shown)
  function redrawView() {
    if (view === 'rep' && themeDirty.rep) { drawRep(); delete themeDirty.rep; }
    else if (view === 'muf' && themeDirty.muf) { drawMuf(); delete themeDirty.muf; }
    else if (view === 'hist' && themeDirty.hist) { drawHist(false); delete themeDirty.hist; }
    else if (view === 'stats' && themeDirty.stats) { drawStats(); delete themeDirty.stats; }
    else if (view === 'an' && themeDirty.an) { if (_anData) renderAnalysis(); delete themeDirty.an; }
  }
  function startTimer() {
    clearInterval(timer);
    const every = { map: 60e3, now: 60e3, rep: 60e3, muf: 600e3 }[view] || 120e3;
    timer = setInterval(refresh, every);
  }
  // noLoad: the caller loads the view itself (openReplay)
  function setView(v, fromMenu, noLoad) {
    if (view === 'replay' && v !== 'replay') rpPause();
    if (view === 'wprs' && v !== 'wprs') wPause();
    view = VIEWS[v] ? v : 'map';
    lsSet('wspr_app_view', view);
    const cfg = VIEWS[view];
    for (const k of Object.keys(VIEWS)) $(VIEWS[k].el).hidden = VIEWS[k].el !== cfg.el;
    anView.classList.toggle('active', view === 'an');   // analysis*.js redraw only while it is shown
    document.querySelectorAll('.app-sec[data-for]').forEach(s => {
      const cur = s.dataset.for === cfg.sec;
      s.open = cur; s.classList.toggle('cur', cur);
    });
    document.querySelectorAll('.app-tile').forEach(t => {
      const on = t.dataset.view === view;
      t.classList.toggle('on', on); t.setAttribute('aria-pressed', String(on));
    });
    $('app-title').textContent = cfg.title;
    $('app-sub').textContent = '';
    // a map made while hidden, or the screen turned meanwhile: Leaflet measures again
    setTimeout(() => {
      for (const m of [lmap, rmap, hmap, wmap]) if (m && m.getContainer().offsetParent) m.invalidateSize();
    }, 60);
    if (!noLoad) {
      LOADERS[view]();                           // also draws in the present theme's colours
      delete themeDirty[view];
    }
    startTimer();
    if (fromMenu) setTimeout(() => menu(false), 150);
  }
  document.querySelectorAll('.app-tile').forEach(t => t.addEventListener('click', () => setView(t.dataset.view, true)));
  window.MApp = { openReplay, setView: v => setView(v) };

  let rt = null;
  window.addEventListener('resize', () => {
    clearTimeout(rt);
    rt = setTimeout(() => {
      for (const m of [lmap, rmap, hmap, wmap]) if (m && m.getContainer().offsetParent) m.invalidateSize();
      if (view === 'an' && _amData && !_amData.empty) drawPolar();   // analysis.js redraws the heatmap itself
    }, 150);
  });
  // the fix-age label ages between the minute refreshes too
  setInterval(() => { if (!document.hidden && view === 'map' && lmMarker) drawLive(); }, 30e3);
  // the night side moves: redrawn every minute on the live map
  setInterval(() => { if (!document.hidden && view === 'map' && lmap && LM.dn) drawNight(lmNight, new Date()); }, 60e3);

  // ── Back on the page ─────────────────────────────────────────────────────
  // Away (hidden) for over an hour, or the server has a newer build of the phone view (a deploy):
  // the page reloads itself — the view and all options are kept in localStorage.  Otherwise the
  // shown view's data is refreshed.
  const RELOAD_AFTER_MS = 3600e3;
  let hiddenAt = document.hidden ? Date.now() : 0, reloading = false;
  async function newBuild() {
    if (!APP_BUILD) return false;
    try { const d = await getJson('/api/app/build'); return !!d.build && d.build !== APP_BUILD; }
    catch (_) { return false; }
  }
  async function wake() {
    if (reloading) return;
    const away = hiddenAt ? Date.now() - hiddenAt : 0;
    hiddenAt = 0;
    if (away > RELOAD_AFTER_MS || await newBuild()) { reloading = true; location.reload(); return; }
    tickUtc();
    refresh();
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { if (!hiddenAt) hiddenAt = Date.now(); }
    else wake();
  });
  window.addEventListener('pagehide', () => { if (!hiddenAt) hiddenAt = Date.now(); });
  window.addEventListener('pageshow', e => { if (e.persisted) wake(); });

  // ══ UTC clock of the top bar ════════════════════════════════════════════
  function tickUtc() { const d = new Date(); $('app-utc-t').textContent = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; }
  function scheduleUtc() { tickUtc(); setTimeout(scheduleUtc, 60000 - (Date.now() % 60000) + 50); }
  scheduleUtc();

  // ══ What's new, User guides and About ═══════════════════════════════════
  // A full-screen sheet over the view; × / Esc / the phone's Back closes it (a history entry is pushed
  // while it is open).  What's new: doc/whats_new.md, as the full page's window; a red dot on ☰ and the
  // buttons until the current version has been opened (wspr_seen_version, shared with the full page).
  const sheet = $('app-sheet');
  let sheetHist = false, guidesLoaded = false, newsLoaded = false;
  function newsDots() {
    const unseen = !!APP_VERSION && lsGet('wspr_seen_version', null) !== APP_VERSION;
    $('app-menu-dot').hidden = !unseen; $('app-news-dot').hidden = !unseen; $('app-news-dot2').hidden = !unseen;
  }
  newsDots();
  const inlineMd = t => esc(t).replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\*([^*]+)\*/g, '<i>$1</i>');
  async function loadNews() {
    const el = $('app-sheet-news');
    try {
      const es = (await getJson('/api/whatsnew')).entries || [];
      el.innerHTML = es.length
        ? '<p class="app-small">Short notes for users, newest first. Each version is one day of development.</p>' +
          es.map((e, i) => {
            const head = `<span class="app-news-ver">${esc(e.version)}</span><span class="app-news-date">${niceDay(e.date, 'long')}</span>` +
                         (e.version === APP_VERSION ? '<span class="app-news-cur">current</span>' : '');
            const body = (e.headline ? `<div class="app-news-title">${inlineMd(e.headline)}</div>` : '') +
              '<ul>' + (e.items || []).map(it => '<li>' + (it.lead ? `<b>${inlineMd(it.lead)}</b>` + (it.text ? ' — ' : '') : '') + inlineMd(it.text || '') + '</li>').join('') + '</ul>';
            return i === 0 ? `<section class="app-news-entry"><h3>${head}</h3>${body}</section>`
                           : `<details class="app-news-entry"><summary><h3>${head}</h3></summary>${body}</details>`;
          }).join('') +
          '<p class="app-small">Older versions are folded — tap to open. The technical history: CHANGELOG.md in the ' +
          '<a href="https://github.com/oh2gax/wspr_logger" target="_blank" rel="noopener">GitHub repository</a>.</p>'
        : '<p class="app-small">No notes are available.</p>';
      newsLoaded = true;
    } catch (_) { el.innerHTML = '<p class="app-small">Could not load the notes.</p>'; }
  }
  async function loadGuides() {
    const el = $('app-sheet-guides');
    try {
      const gs = (await getJson('/api/guides')).guides || [];
      el.innerHTML = gs.length
        ? '<p class="app-small">The guides open as PDF.</p>' + gs.map(g => {
            const url = '/doc/' + encodeURIComponent(g.file);
            const meta = [g.date, 'PDF', g.size_kb + ' kB'].filter(Boolean).join(' · ');
            return `<section class="app-guide"><h3>${esc(g.title)}</h3>` +
              (g.description ? `<div class="app-guide-desc">${esc(g.description)}</div>` : '') +
              `<div class="app-guide-meta">${esc(meta)}</div>` +
              `<div class="app-guide-btns"><a class="app-btn app-btn-primary" href="${url}" target="_blank" rel="noopener">Open PDF</a>` +
              `<a class="app-btn" href="${url}" download>Download</a></div></section>`;
          }).join('')
        : '<p class="app-small">No guides yet.</p>';
      guidesLoaded = true;
    } catch (_) { el.innerHTML = '<p class="app-small">Could not load the guides.</p>'; }
  }
  function openSheet(kind) {
    const NAME = { news: "What's new", guides: 'User guides', about: 'About' };
    $('app-sheet-title').textContent = NAME[kind];
    $('app-sheet-about').hidden = kind !== 'about';
    $('app-sheet-guides').hidden = kind !== 'guides';
    $('app-sheet-news').hidden = kind !== 'news';
    const others = { news: ['guides', 'about'], guides: ['news', 'about'], about: ['news', 'guides'] }[kind];
    const SHORT = { news: "What's new", guides: 'User guides', about: 'About' };
    ['app-sheet-alt', 'app-sheet-alt2'].forEach((id, k) => {
      const b = $(id), o = others[k];
      b.hidden = !o;
      if (o) { b.textContent = SHORT[o]; b.dataset.kind = o; }
    });
    if (kind === 'guides' && !guidesLoaded) { $('app-sheet-guides').innerHTML = '<p class="app-small">Loading…</p>'; loadGuides(); }
    if (kind === 'news') {
      if (!newsLoaded) { $('app-sheet-news').innerHTML = '<p class="app-small">Loading…</p>'; loadNews(); }
      if (APP_VERSION) lsSet('wspr_seen_version', APP_VERSION);
      newsDots();
    }
    sheet.hidden = false;
    $('app-sheet-body').scrollTop = 0;
    menu(false);
    if (!sheetHist) { try { history.pushState({ appSheet: kind }, ''); sheetHist = true; } catch (_) { /* */ } }
  }
  function closeSheet(fromPop) {
    if (sheet.hidden) return;
    sheet.hidden = true;
    if (sheetHist && !fromPop) { sheetHist = false; try { history.back(); } catch (_) { /* */ } }
    sheetHist = false;
  }
  $('app-news-btn').addEventListener('click', () => openSheet('news'));
  $('app-news-btn2').addEventListener('click', () => openSheet('news'));
  $('app-about-btn').addEventListener('click', () => openSheet('about'));
  $('app-guides-btn').addEventListener('click', () => openSheet('guides'));
  $('app-sheet-close').addEventListener('click', () => closeSheet(false));
  $('app-sheet-alt').addEventListener('click', e => openSheet(e.currentTarget.dataset.kind));
  $('app-sheet-alt2').addEventListener('click', e => openSheet(e.currentTarget.dataset.kind));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(false); });
  window.addEventListener('popstate', () => closeSheet(true));

  if (view !== 'map' && view !== 'now' && view !== 'rep') fetchLatest();   // the status dot (those views fetch it themselves)
  setView(view);
})();
