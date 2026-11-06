// What's new / User guides / About window (three tabs of one window).
// Part of the WSPR Logger page. The scripts in templates/index.html are loaded in this order and share one scope,
// so keep the order: core, live, panels, map-layers, history-player, views, analysis, info, wprs, main.

'use strict';

// ── What's new / About ─────────────────────────────────────────────────────
let _wnData = null;

function escHtml(t) {
    return String(t).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function openModal(title, html) {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalBody').innerHTML = html;
    document.getElementById('modalBack').style.display = 'flex';
    document.querySelector('#modalBack .modal-card').classList.remove('fixed');
}

function closeModal() {
    document.getElementById('modalBack').style.display = 'none';
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

async function loadWhatsNew() {
    try {
        const r = await fetch('/api/whatsnew');
        _wnData = await r.json();
    } catch(e) { return; }
    const badge = document.getElementById('navVersion');
    if (!_wnData.version) { badge.textContent = ''; return; }
    badge.textContent = _wnData.version;
    let seen = null;
    try { seen = localStorage.getItem('wspr_seen_version'); } catch(e) {}
    badge.classList.toggle('new', seen !== _wnData.version);
}

// What's new, User guides and About share one window with three tabs (as on the Mode-S Wind page)
let _infoTab = 'whatsnew';

// **bold**, *italic* and `code` of the notes; everything else is shown as plain text
function inlineMd(t) {
    return escHtml(t)
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

function whatsNewHtml() {
    const d = _wnData || { entries: [] };
    if (!d.entries.length) return '<div class="wn-ver">No notes are available.</div>';
    let html = '<div class="wn-ver">Short notes for users, newest first. Each version is one day of development.</div>';
    for (const e of d.entries) {
        const nice = new Date(e.date + 'T00:00:00Z').toLocaleDateString('en-GB',
            { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
        html += `<div class="wn-version"><span class="wn-vnum">${escHtml(e.version)}</span>` +
                `<span class="wn-vdate">${nice}</span></div>`;
        if (e.headline) html += `<div class="wn-headline">${inlineMd(e.headline)}</div>`;
        html += '<ul class="wn-notes">' + e.items.map(i =>
            '<li>' + (i.lead ? `<b>${inlineMd(i.lead)}</b>` + (i.text ? ' &mdash; ' : '') : '') + inlineMd(i.text) + '</li>'
        ).join('') + '</ul>';
    }
    html += '<div class="wn-foot">The technical history is in CHANGELOG.md in the ' +
            '<a href="https://github.com/oh2gax/wspr_logger" target="_blank" rel="noopener">GitHub repository</a>.</div>';
    return html;
}

async function guidesHtml() {
    let list = [];
    try {
        const r = await fetch('/api/guides');
        list = (await r.json()).guides || [];
    } catch(e) { return '<div class="wn-ver">The guides could not be loaded.</div>'; }
    if (!list.length) return '<div class="wn-ver">No guides yet. PDF documents placed in the doc folder appear here.</div>';
    let html = '<div class="wn-ver">Technical notes and studies written about this station and its data</div>';
    for (const g of list) {
        const url = '/doc/' + encodeURIComponent(g.file);
        const meta = [g.date, 'PDF', g.size_kb + ' kB'].filter(Boolean).join(' · ');
        html += `<div class="gd-item"><div class="gd-title">${escHtml(g.title)}</div>` +
                (g.description ? `<div class="gd-desc">${escHtml(g.description)}</div>` : '') +
                `<div class="gd-meta">${escHtml(meta)}</div>` +
                `<div class="gd-links" style="margin-top:6px"><a href="${url}" target="_blank" rel="noopener">Open</a>` +
                `<a href="${url}" download>Download</a></div></div>`;
    }
    return html;
}

function aboutHtml() {
    const ver = (_wnData && _wnData.version) ? escHtml(_wnData.version) : '';
    return `
        <div class="about-row"><div class="about-lbl">Operator</div><div>Otso Laakso / OH2GAX</div></div>
        <div class="about-row"><div class="about-lbl">Transmitter</div><div>WSPR transmitter based on the
            <a href="https://www.zachtek.com/1012" target="_blank" rel="noopener">ZachTek desktop transmitter</a>,
            200&nbsp;mW (23&nbsp;dBm) transmit power</div></div>
        <div class="about-row"><div class="about-lbl">Antenna</div><div>Diamond monoband antenna for 14&nbsp;MHz (20&nbsp;m),
            mounted on a VW Touran car</div></div>
        <div class="about-row"><div class="about-lbl">Home locator</div><div>KP20JG<div class="about-note">The actual location
            changes as the car moves &mdash; the map and the Locator field always show the latest reported position.</div></div></div>
        <div class="about-row"><div class="about-lbl">Software</div><div>WSPR Logger ${ver}<div class="about-note">
            Data from wspr.live, GIRO / Juliusruh ionosonde and hamqsl.com</div></div></div>
        <div class="about-row"><div class="about-lbl">Source code</div><div>Public repository on GitHub:
            <a href="https://github.com/oh2gax/wspr_logger" target="_blank" rel="noopener">https://github.com/oh2gax/wspr_logger</a></div></div>`;
}

async function renderInfo() {
    const TABS = [['whatsnew', "What's new"], ['guides', 'User guides'], ['about', 'About']];
    const tabs = '<div class="info-tabs">' + TABS.map(([k, t]) =>
        `<button class="info-tab${_infoTab === k ? ' on' : ''}" onclick="switchInfo('${k}')">${t}</button>`).join('') + '</div>';
    document.getElementById('modalBody').innerHTML = tabs + '<div class="wn-ver">Loading&hellip;</div>';
    const tab = _infoTab;
    const body = tab === 'whatsnew' ? whatsNewHtml() : tab === 'guides' ? await guidesHtml() : aboutHtml();
    if (tab !== _infoTab) return;              // the user switched tab while loading
    document.getElementById('modalBody').innerHTML = tabs + body;
    if (tab === 'whatsnew' && _wnData && _wnData.version) {
        try { localStorage.setItem('wspr_seen_version', _wnData.version); } catch(e) {}
        document.getElementById('navVersion').classList.remove('new');
    }
}

function infoTitle(tab) {
    return tab === 'whatsnew' ? "What's new" : tab === 'guides' ? 'User guides' : 'About ' + CALLSIGN;
}

function switchInfo(tab) {
    _infoTab = tab;
    document.getElementById('modalTitle').textContent = infoTitle(tab);
    renderInfo();
}

async function openInfo(tab) {
    if (!_wnData) await loadWhatsNew();
    openModal(infoTitle(tab), '');
    // What's new and User guides are tabs of one window: fixed size, so switching tabs never moves it
    document.querySelector('#modalBack .modal-card').classList.add('fixed');
    _infoTab = tab;
    renderInfo();
}
function openWhatsNew() { return openInfo('whatsnew'); }
function openGuides()   { return openInfo('guides'); }
function openAbout()    { return openInfo('about'); }

