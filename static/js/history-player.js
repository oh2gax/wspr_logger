// The History Player (replay of the stored snapshots).
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, analysis-more, info, wprs, main.

'use strict';

// ── History player (replay) ────────────────────────────────────────────────
// Steps through the snapshots stored in wspr_replay.db (one per poll, ~10 min).
// The normal layer toggles keep working: while replay is active the reporter
// list / histogram / plot / countries / solar panels show the replayed moment.
let _replayActive = false;
let _replayFrames = [];
let _replaySpots  = [];
let _replayDates  = [];     // dates with data, newest first
let _replayIdx    = 0;
let _replayTimer  = null;
let _replayFps    = 4;

// The History Player card of the left pane: idle — a day and ▶ Replay; playing — the replayed moment,
// play / pause, day steps and Live ✕ (the bar at the bottom of the map has the full controls).
function syncReplayCard() {
    const card = document.getElementById('replayCard');
    card.classList.toggle('on', _replayActive);
    document.getElementById('rcIdle').style.display = _replayActive ? 'none' : '';
    document.getElementById('rcActive').style.display = _replayActive ? '' : 'none';
    const f = _replayActive ? _replayFrames[_replayIdx] : null;
    document.getElementById('rcFrame').textContent = f ? `· ${_replayIdx + 1}/${_replayFrames.length}` : '';
    document.getElementById('rcNow').textContent = f
        ? `${f.ts.slice(0, 16)} UTC`
        : (_replayActive ? `${document.getElementById('replayDate').value || ''} — no data` : '');
    document.getElementById('rcPlay').innerHTML = _replayTimer ? '&#10074;&#10074;' : '&#9654;';
    const d = document.getElementById('rcDate');
    if (!d.value) d.value = todayStr();
    d.max = todayStr();
}

function replayFromCard() {
    const d = document.getElementById('rcDate').value;
    return enterReplay(d || undefined);
}

async function toggleReplay() {
    if (_replayActive) exitReplay(); else await enterReplay();
}

async function enterReplay(date, ts) {
    try {
        const r = await fetch(`/api/replay/dates?band=${currentBand}`);
        const d = await r.json();
        if (!d.enabled)       { showToast('Replay database is disabled in config.ini', 'err'); return; }
        if (!d.dates.length)  { showToast('No replay data stored yet', 'err'); return; }
        _replayDates = d.dates;
    } catch(e) { showToast('Could not load replay data', 'err'); return; }

    _replayActive = true;
    document.getElementById('ovLbl').textContent = 'Replay position';
    updateFixAge();                              // hides the live "last fix … ago" label at the marker
    updatePropRel(null);                         // "compared with usual" is live only
    updatePropUnusual(null);
    syncReplayCard();
    document.getElementById('replayBar').style.display = 'flex';
    const di = document.getElementById('replayDate');
    di.min = _replayDates[_replayDates.length - 1];
    di.max = _replayDates[0];
    // a day without stored data: the nearest earlier day that has some (the dates are newest first)
    const start = !date ? _replayDates[0]
        : _replayDates.includes(date) ? date
        : (_replayDates.find(d => d < date) || _replayDates[_replayDates.length - 1]);
    if (date && start !== date) showToast('No replay data for ' + date + ' — showing ' + start, 'err');
    await replayLoadDate(start, start === date ? ts : null);
}

function exitReplay() {
    replayPause();
    _replayActive = false;
    _replayFrames = [];
    _replaySpots  = [];
    document.getElementById('ovLbl').textContent = 'Current Position';
    updateClock();                               // the live UTC clock again (the position follows with fetchLatest)
    syncReplayCard();
    document.getElementById('replayBar').style.display = 'none';
    // Clear replayed data, then let the normal live refresh repaint everything
    _reporterListData = [];
    if (showReporterList) renderReporterList();
    if (showHistogram)    renderHistogram();
    if (showReporterPlot) clearReporterPlot();
    fetchLatest();
    if (showSolar) fetchSolarData();
    if (showDayNight) renderDayNight();          // back to the present terminator
}

async function replayLoadDate(date, ts) {
    if (!date || !_replayActive) return;
    replayPause();
    try {
        const [fr, sp] = await Promise.all([
            fetch(`/api/replay/day?date=${date}&band=${currentBand}`).then(r => r.json()),
            fetch(`/api/positions?date=${date}&band=${currentBand}`).then(r => r.json()),
        ]);
        if (!_replayActive) return;          // left replay while loading
        _replayFrames = fr.frames || [];
        _replaySpots  = Array.isArray(sp) ? sp : [];
    } catch(e) { showToast('Failed to load replay day', 'err'); return; }

    document.getElementById('replayDate').value = date;
    document.getElementById('replaySlider').max = Math.max(_replayFrames.length - 1, 0);
    if (!_replayFrames.length) showToast('No replay data for ' + date, 'err');
    let idx = 0;
    if (ts) {   // jump to the first snapshot at or after the requested moment
        const k = _replayFrames.findIndex(f => f.ts >= ts);
        idx = k < 0 ? Math.max(_replayFrames.length - 1, 0) : k;
    }
    replaySeek(idx);
}

function replaySeek(i) {
    _replayIdx = Math.max(0, Math.min(parseInt(i) || 0, _replayFrames.length - 1));
    applyReplayFrame();
}

function applyReplayFrame() {
    if (!_replayActive) return;
    const f = _replayFrames[_replayIdx];
    const band = BAND_NAMES[currentBand] || '';
    _reporterListData = f
        ? f.r.map(a => ({ band, callsign: a[0], grid: a[1], snr: a[2], distance: a[3] }))
        : [];
    document.getElementById('replaySlider').value = _replayIdx;
    document.getElementById('replayTime').textContent = f
        ? `${f.ts.slice(0, 16)} UTC  (${_replayIdx + 1}/${_replayFrames.length})`
        : `${document.getElementById('replayDate').value} — no data`;

    if (f) {
        // Beacon position = latest logged spot at or before this moment
        let sp = null;
        for (const s of _replaySpots) { if (s.timestamp <= f.ts) sp = s; else break; }
        if (!sp) sp = _replaySpots[0] || null;
        const ageMs = sp ? Date.parse(f.ts.replace(' ', 'T') + 'Z') - Date.parse(sp.timestamp.replace(' ', 'T') + 'Z') : Infinity;
        const fresh = sp && ageMs >= 0 && ageMs <= 25 * 60000;
        if (sp) {                                // the box on the map, the left pane and the marker follow the replay
            showPosition(sp, !fresh);
            const min = Math.round(ageMs / 60000);     // the fix's age at the replayed moment
            showFixAgeLines(min >= 0 ? `last fix ${min} min before` : `no fix yet this day (first at ${sp.timestamp.slice(11, 16)})`,
                            min >= 0 ? min : 999);
        } else showNoPosition();
        updatePropagation(fresh ? sp.reporter_count : 0, !fresh);
    } else {
        showNoPosition();
    }
    updateClock();                               // the box's date and time: the replayed moment
    syncReplayCard();
    if (showReporterList) renderReporterList();
    if (showHistogram)    renderHistogram();
    if (showReporterPlot) renderReporterPlot();
    if (showCountries)    updateCountryOverlay(f ? f.c : []);
    if (showSolar && f && f.s) renderSolar(f.s);
    if (showDayNight)     renderDayNight();      // the terminator of the replayed moment
}

function replayTogglePlay() {
    if (_replayTimer) replayPause(); else replayPlay();
}

function replayPlay() {
    if (!_replayActive || !_replayFrames.length) return;
    if (_replayIdx >= _replayFrames.length - 1) replaySeek(0);
    document.getElementById('replayPlayBtn').innerHTML = '&#10074;&#10074;';
    _replayTimer = setInterval(() => {
        if (_replayIdx >= _replayFrames.length - 1) { replayPause(); return; }
        replaySeek(_replayIdx + 1);
    }, 1000 / _replayFps);
    syncReplayCard();
}

function replayPause() {
    if (_replayTimer) { clearInterval(_replayTimer); _replayTimer = null; }
    const b = document.getElementById('replayPlayBtn');
    if (b) b.innerHTML = '&#9654;';
    if (document.getElementById('rcPlay')) syncReplayCard();
}

function replaySetSpeed(v) {
    _replayFps = parseInt(v) || 4;
    if (_replayTimer) { replayPause(); replayPlay(); }
}

// dir = -1 → previous day that has data, +1 → next day that has data
function replayShiftDay(dir) {
    const cur = document.getElementById('replayDate').value;
    const asc = [..._replayDates].reverse();
    const target = dir < 0 ? [...asc].reverse().find(d => d < cur) : asc.find(d => d > cur);
    return target ? replayLoadDate(target) : Promise.resolve();
}

