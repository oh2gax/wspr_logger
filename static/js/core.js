// Constants, state, tile layers, map initialisation, theme and the remembered map-layer settings.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, info, wprs, main.

'use strict';

// ── Constants (injected by Flask) ──────────────────────────────────────────
const CALLSIGN      = WSPR_CONFIG.callsign;
const MAP_LAT       = WSPR_CONFIG.mapLat;
const MAP_LON       = WSPR_CONFIG.mapLon;
const MAP_ZOOM      = WSPR_CONFIG.mapZoom;
const CARTO_API_KEY = WSPR_CONFIG.cartoApiKey;

const BAND_NAMES = {3:'80m',7:'40m',10:'30m',14:'20m',18:'17m',21:'15m',24:'12m',28:'10m'};

// ── State ──────────────────────────────────────────────────────────────────
let currentBand  = WSPR_CONFIG.defaultBand;
let showTrail    = true;
let isDark       = true;
let statsWindow  = 'today';   // 'today' | '1h'
let showFixAge       = true;     // the "last fix N min ago" label next to the car marker
let showCountries    = false;
let showMuf          = false;
let showSolar        = false;
let showReporterList = false;
let showHistogram    = false;
let showReporterPlot = false;
let showDayNight     = false;
// Every string that comes from outside (callsigns, grids, country names) must go through this before it is put into HTML.
function escHtml(t) {
    return String(t).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

let _reporterListData = [];
let _latestMuf        = 0;    // most recent J-MUF value in MHz (0 = unknown)
let _liveDx6          = 0;    // current reporters beyond 6000 km, from /api/latest (the "& DX" mark)
let _rlSortKey        = 'snr';   // 'snr' | 'dist'
let _hgramMode        = 'snr';   // 'snr' | 'dist'
let hgramChart        = null;
let _solarTimer   = null;
let mufChart      = null;
let mufDays       = 2;

// Live map objects
let liveMap            = null;
let liveTileLayer      = null;
let liveMarker         = null;
let liveTrail          = null;
let reporterPlotLayer  = null;
let dayNightLayer      = null;
let _dayNightTimer     = null;
let _txLat             = null;
let _txLon             = null;

// Latest spot cache
let latestSpot    = null;

// History map objects
let histMap       = null;
let histTileLayer = null;
let histTrail     = null;
let histMarkers   = [];

// ── Tile layers ────────────────────────────────────────────────────────────
function makeTiles(dark) {
    const key = CARTO_API_KEY ? `?key=${CARTO_API_KEY}` : '';
    return dark
        ? L.tileLayer(`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png${key}`,
            { attribution: '© OpenStreetMap © CARTO', maxZoom: 19, subdomains: 'abcd' })
        : L.tileLayer(`https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png${key}`,
            { attribution: '© OpenStreetMap © CARTO', maxZoom: 19, subdomains: 'abcd' });
}

function swapTiles(map, oldLayer) {
    if (oldLayer) map.removeLayer(oldLayer);
    const newLayer = makeTiles(isDark);
    newLayer.addTo(map);
    return newLayer;
}

// ── Init live map ──────────────────────────────────────────────────────────
function initLiveMap() {
    const savedZoom = parseInt(localStorage.getItem('wspr_zoom')) || MAP_ZOOM;
    liveMap = L.map('map', { center:[MAP_LAT, MAP_LON], zoom:savedZoom });
    liveTileLayer = makeTiles(isDark);
    liveTileLayer.addTo(liveMap);
    liveMap.on('zoomend', () => {
        localStorage.setItem('wspr_zoom', liveMap.getZoom());
    });

    // Custom pane for the day/night overlay — sits between the tile layer
    // (z-index 200) and the default overlay pane (z-index 400) so it is
    // always rendered below Reporter Plot lines and markers.
    liveMap.createPane('dayNightPane');
    liveMap.getPane('dayNightPane').style.zIndex = 300;
    liveMap.getPane('dayNightPane').style.pointerEvents = 'none';
}

// ── Init history map ───────────────────────────────────────────────────────
function initHistMap() {
    histMap = L.map('history-map', { center:[MAP_LAT, MAP_LON], zoom:MAP_ZOOM - 1 });
    histTileLayer = makeTiles(isDark);
    histTileLayer.addTo(histMap);
}

// ── Theme: Auto (follow the system) / Dark / Light ─────────────────────────
// The button in the sidebar header cycles Auto → Dark → Light. The choice is remembered;
// in Auto mode the page follows the system setting, also while it is open.
// New key: choices made with the old Dark / Light toggle (key 'wspr_theme') are not carried over, so every
// browser starts in Auto and keeps whatever it picks from now on.
const THEME_KEY   = 'wspr_theme_mode';
const THEME_ICON  = { auto: '🌓', dark: '🌙', light: '☀️' };
const THEME_LABEL = { auto: 'Auto (follows the system)', dark: 'Dark', light: 'Light' };
let themeMode = 'auto';
const _sysLight = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

function themeIsDark() {
    if (themeMode === 'dark') return true;
    if (themeMode === 'light') return false;
    return !(_sysLight && _sysLight.matches);
}

function applyTheme() {
    const was = isDark;
    isDark = themeIsDark();
    document.documentElement.classList.toggle('light', !isDark);
    const b = document.getElementById('themeBtn');
    if (b) {
        b.textContent = THEME_ICON[themeMode];
        b.title = 'Theme: ' + THEME_LABEL[themeMode] + ' — click to change';
    }
    if (isDark === was) return;                  // e.g. Auto → Dark on a dark system: nothing to redraw
    if (liveMap && liveTileLayer) liveTileLayer = swapTiles(liveMap, liveTileLayer);
    if (histMap && histTileLayer) histTileLayer = swapTiles(histMap, histTileLayer);
    if (wprsMap && wprsTile) wprsTile = swapTiles(wprsMap, wprsTile);
    if (_anData && document.getElementById('analysis-view').classList.contains('active')) renderAnalysis();
    if (document.getElementById('stats-view').classList.contains('active')) renderStatsCharts();
}

function cycleTheme() {
    themeMode = themeMode === 'auto' ? 'dark' : themeMode === 'dark' ? 'light' : 'auto';
    try { localStorage.setItem(THEME_KEY, themeMode); } catch (e) {}
    applyTheme();
    showToast('Theme: ' + THEME_LABEL[themeMode]);
}

function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem(THEME_KEY); } catch (e) {}
    themeMode = (saved === 'dark' || saved === 'light') ? saved : 'auto';
    isDark = themeIsDark();                      // the maps are built next, with the right tiles
    document.documentElement.classList.toggle('light', !isDark);
    applyTheme();
    if (_sysLight) {
        const onSys = () => { if (themeMode === 'auto') applyTheme(); };
        if (_sysLight.addEventListener) _sysLight.addEventListener('change', onSys);
        else if (_sysLight.addListener) _sysLight.addListener(onSys);
    }
}

// ── Remembered Map Layer settings (per browser) ────────────────────────────
const LAYER_PREFS_KEY = 'wspr_layers';
let _layerPrefsReady = false;   // stays false until restore has run, so startup never overwrites saved prefs

function saveLayerPrefs() {
    if (!_layerPrefsReady) return;
    try {
        localStorage.setItem(LAYER_PREFS_KEY, JSON.stringify({
            trail: showTrail, fixAge: showFixAge, countries: showCountries, muf: showMuf, solar: showSolar,
            reporterList: showReporterList, histogram: showHistogram,
            reporterPlot: showReporterPlot, dayNight: showDayNight,
            mufDays: mufDays, hgramMode: _hgramMode,
            rlSortKey: _rlSortKey, statsWindow: statsWindow,
        }));
    } catch(e) { /* storage unavailable (private mode / quota) — ignore */ }
}

function restoreLayerPrefs() {
    let p = null;
    try { p = JSON.parse(localStorage.getItem(LAYER_PREFS_KEY) || 'null'); } catch(e) { p = null; }
    if (!p || typeof p !== 'object') p = {};

    // Sub-settings first so panels open with the remembered view.
    // setMufDays is always called so the panel title matches the active period button.
    setMufDays([1,2,3,7].includes(p.mufDays) ? p.mufDays : mufDays);
    if (p.hgramMode === 'snr' || p.hgramMode === 'dist') setHgramMode(p.hgramMode);
    if (p.rlSortKey === 'snr' || p.rlSortKey === 'dist') sortReporterList(p.rlSortKey);
    if (p.statsWindow === '1h' || p.statsWindow === 'today') setStatsWindow(p.statsWindow);

    // Layer switches: call the normal toggle only when the saved value differs
    // from the current (default) state, so all side effects run exactly as on a click.
    const layers = [
        ['trail',        () => showTrail,        toggleTrail],
        ['fixAge',       () => showFixAge,       toggleFixAge],
        ['countries',    () => showCountries,    toggleCountries],
        ['muf',          () => showMuf,          toggleMuf],
        ['solar',        () => showSolar,        toggleSolar],
        ['reporterList', () => showReporterList, toggleReporterList],
        ['histogram',    () => showHistogram,    toggleHistogram],
        ['reporterPlot', () => showReporterPlot, toggleReporterPlot],
        ['dayNight',     () => showDayNight,     toggleDayNight],
    ];
    for (const [key, get, toggle] of layers) {
        if (typeof p[key] === 'boolean' && p[key] !== get()) toggle();
    }
    _layerPrefsReady = true;
    saveLayerPrefs();
}

