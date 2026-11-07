// Toast, utilities and the start-up code.
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, analysis-more, info, wprs, main.

'use strict';

// ── Toast ──────────────────────────────────────────────────────────────────
let _toastTimer = null;
function showToast(msg, type='') {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = type;
    t.style.display = 'block';
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => t.style.display = 'none', 3800);
}

// ── Utilities ──────────────────────────────────────────────────────────────
function todayStr() {
    return new Date().toISOString().split('T')[0];
}

// ── Bootstrap ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    loadWhatsNew();
    setHistDate(0);
    setStatsDate(0);
    initLiveMap();
    setInterval(updateFixAge, 30_000);
    initMovablePanels();    // before the layer prefs, so the automatic stacking knows which panels are pinned
    restoreLayerPrefs();    // after the map exists (Day/Night needs it), before the first fetch
    fetchLatest();
    setInterval(fetchLatest, 60_000);
    applyHash();            // open the view a shared link points to

    // UTC clock — updates every second
    function tickUtcClock() {
        const now = new Date();
        const pad = n => String(n).padStart(2, '0');
        document.getElementById('utcDate').textContent =
            `${now.getUTCFullYear()}-${pad(now.getUTCMonth()+1)}-${pad(now.getUTCDate())}`;
        document.getElementById('utcTime').textContent =
            `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())} UTC`;
    }
    tickUtcClock();
    setInterval(tickUtcClock, 1000);
});
