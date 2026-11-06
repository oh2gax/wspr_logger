# What's new in WSPR Logger

Short notes for users of the web page, newest first. Each version is one day of development
(v.DDMMYYYY). The full technical history is in CHANGELOG.md. The newest heading gives the
version shown under the page title.

## v.06112026 — The WPRS page and trips, three seasons of history, grey line and DX outlook in Analysis, movable windows, an Auto / Dark / Light button, and an easier installation

- **WPRS page — where the car has been** — a new page that turns the logged positions into a track. A list shows the days on which the car moved (how many squares, how far, how far from home), a map draws the squares, the track line and every fix, and a replay bar plays a drive back. Switch between *Days* and *Trips*: consecutive days away from home become one trip card with its dates, length and farthest point. *Copy link* gives an address that opens the same day and fix.
- **Three summers of history** — the Analysis page now covers 2024, 2025 and 2026. The two earlier seasons were rebuilt from wspr.live, so they have no solar or MUF data and appear in the heatmap and the DX statistics but not in the space-weather charts.
- **Two scientific papers under Guides** — a study of 20 m propagation as seen by a 200 mW beacon, and a paper on position reporting with WSPR (WPRS), both written from this station's own data and updated for all three seasons. *Guides* and *What's new* share one window.
- **Analysis: grey line and DX outlook** — the grey-line card tests whether long-distance reports cluster around sunrise and sunset, at either end of the path. The DX outlook card gives, for the next 12 hours, the chance of a report beyond 6000 km, from this station's own history; the MUF and K-index adjustment is used only when a back-test showed that it helps, and the card says so.
- **Analysis: odd reporters left out** — a station whose distance contradicts its own locator by more than 500 km is no longer counted in the analysis and the records, and is listed under *Excluded reports*.
- **Analysis: more to look at** — a *Right now* comparison with what is usual for this hour, DX windows by hour and month, the farthest reporters with a replay button, a day view of the Juliusruh MUF against your reporters, and a storm-day table.
- **Move the windows yourself** — the History / reporter list, the histogram and the country list can be dragged by their titles; the place is remembered and a double-click on the title puts a window back. The date and time card, the Propagation card and the MUF graph stay where they are.
- **How old is the position?** — the car marker says *last fix 9 min ago* (green, amber after 25 minutes, red after an hour), and the left pane shows the same line under the time of the last spot, which now shows minutes only. The *Last Fix Label* switch in Map Layers hides the label on the map.
- **Auto / Dark / Light** — one icon button next to the page title cycles Auto (follow the system), Dark and Light. Auto is the default, and the page no longer flashes the wrong colours while it loads.
- **Share a view** — the address of the page follows what you look at, so a day, a moment in the History Player or a WPRS fix can be sent to someone else.
- **Settings are remembered** — the Map Layers switches, the MUF period, the histogram tab and the reporter-list sorting are kept in your browser.
- **A redesigned Statistics page, the History Player on the live map, and the What's new / About windows** — the day at a glance, all-time records with their dates, and a replay of stored snapshots on the live map.
- **Fixes** — the Reporter Countries window no longer disappears after a reload, the MUF graph no longer slides under the date and time card, the histogram shows when it is the only layer switched on, and the records and logged dates of the Statistics page work again.
- **Fixed: Best DX too low** — distant stations upload to wspr.live later than the nearby ones; the page now keeps refreshing the last 45 minutes and raises the stored value when late reports arrive.
- **For whoever runs the server** — one command, `bash update.sh`, updates from GitHub with a backup and a health check; the databases live in a `data/` folder, `config.ini` is a local file that updates never touch, and the code is split into a `core/` package and the page into separate style and script files. `bash update.sh --migrate-data` moves an older installation's databases into `data/`.

## v.06092026 — Map tiles with your own CARTO key

- **CARTO Basemaps key** — put your key into `api_keys.py` and the map tiles lose the "API key required" watermark. Without a key the page works as before.

## v.23052026 — A warning when wspr.live is not answering

- **DB Timeout!** — the Propagation card shows *DB Timeout!* in amber when wspr.live does not answer or returns no spots at all, so a silent map is not mistaken for a transmitter that has stopped. It clears by itself when the data is back.

## v.21052026 — Repairs: the page, the map, the country list and late reports

- **Fixed: the page and the map** — the page returned *Not Found* and, after that, no map was shown; both are repaired.
- **Fixed: Reporter Countries** — the list showed "No data" even when stations were being heard.
- **Better Best DX** — a later poll that finds a farther reporter for an earlier transmission now updates it, so today's Best DX in the sidebar is no longer too low.
