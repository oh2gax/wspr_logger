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

// ── The date and time at the top of the Current Position box ───────────────
// The UTC clock, every second; in the History Player the replayed moment instead, in amber with a
// REPLAY tag (from 2026-11-07), so the box never shows the present time over a replayed map.
function updateClock() {
    const f = _replayActive ? _replayFrames[_replayIdx] : null;
    document.getElementById('utcClock').classList.toggle('replay', !!f);
    let date, time;
    if (f) {
        date = f.ts.slice(0, 10);
        time = f.ts.slice(11, 19) + ' UTC';
    } else {
        const now = new Date();
        const pad = n => String(n).padStart(2, '0');
        date = `${now.getUTCFullYear()}-${pad(now.getUTCMonth()+1)}-${pad(now.getUTCDate())}`;
        time = `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())} UTC`;
    }
    document.getElementById('utcDate').textContent = date;
    document.getElementById('utcTime').textContent = time;
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
    syncReplayCard();       // the History Player card: today's date ready to replay
    applyHash();            // open the view a shared link points to

    // UTC clock (or the replayed moment) — updates every second
    updateClock();
    setInterval(updateClock, 1000);
});
