// m-shim.js — the full page's globals that analysis.js and analysis-more.js use, for the phone view /app
// (from 2026-11-07).  The phone loads: m-shim, map-layers (only its pure helpers are used), analysis,
// analysis-more, m-app.  These are classic scripts sharing one scope, as on the full page; m-app.js
// keeps isDark up to date and answers the "open in the History Player" links through window.MApp.

'use strict';

/* eslint-disable no-unused-vars */
var currentBand = (window.WSPR_CONFIG && WSPR_CONFIG.defaultBand) || 14;
var isDark = !document.documentElement.classList.contains('light');
var _replayActive = false;           // the phone's Replay is its own view: the Analysis links always "enter" it

function escHtml(t) {
    return String(t).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

let _toastTimer = null;
function showToast(msg, type = '') {
    const t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg;
    t.className = type;
    t.style.display = 'block';
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { t.style.display = 'none'; }, 3800);
}

function todayStr() {
    return new Date().toISOString().split('T')[0];
}

// analysis.js openReplayAt(ts): showView('map'), then enterReplay(date, ts) — on the phone: the Replay view
function showView(_name) { /* the view is switched by enterReplay */ }
function enterReplay(date, ts) { return window.MApp ? window.MApp.openReplay(date, ts) : Promise.resolve(); }
function replayLoadDate(date, ts) { return enterReplay(date, ts); }
