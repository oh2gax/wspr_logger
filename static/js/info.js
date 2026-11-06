// What's new / User guides / About window.
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

// What's new and User guides share one window with two tabs (as on the Mode-S Wind page)
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

async function renderInfo() {
    const tabs = '<div class="info-tabs">' +
        `<button class="info-tab${_infoTab === 'whatsnew' ? ' on' : ''}" onclick="switchInfo('whatsnew')">What's new</button>` +
        `<button class="info-tab${_infoTab === 'guides' ? ' on' : ''}" onclick="switchInfo('guides')">User guides</button></div>`;
    document.getElementById('modalBody').innerHTML = tabs + '<div class="wn-ver">Loading&hellip;</div>';
    const tab = _infoTab;
    const body = tab === 'whatsnew' ? whatsNewHtml() : await guidesHtml();
    if (tab !== _infoTab) return;              // the user switched tab while loading
    document.getElementById('modalBody').innerHTML = tabs + body;
    if (tab === 'whatsnew' && _wnData && _wnData.version) {
        try { localStorage.setItem('wspr_seen_version', _wnData.version); } catch(e) {}
        document.getElementById('navVersion').classList.remove('new');
    }
}

function switchInfo(tab) {
    _infoTab = tab;
    document.getElementById('modalTitle').textContent = tab === 'whatsnew' ? "What's new" : 'User guides';
    renderInfo();
}

async function openInfo(tab) {
    if (!_wnData) await loadWhatsNew();
    openModal(tab === 'whatsnew' ? "What's new" : 'User guides', '');
    _infoTab = tab;
    renderInfo();
}
function openWhatsNew() { return openInfo('whatsnew'); }
function openGuides()   { return openInfo('guides'); }

