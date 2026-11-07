# What's new in WSPR Logger

Short notes for users of the web page, newest first. Each version is one day of development
(v.DDMMYYYY). The full technical history is in CHANGELOG.md. The newest heading gives the
version shown under the page title.

## v.07112026 — A phone app, user guides, seven new Analysis cards, longer analysis periods, a cleaner full-screen map and WPRS in two pages

- **WSPR Logger on your phone** — open *wspr.oh2gax.org/app* (or tap *📱 Phone app* under *What's new*): one view at a time filling the screen and every choice in the ☰ menu, as in the Mode-S Wind phone view. Nine views — Live map, Now, Reporters, MUF graph, Replay, History, Statistics, the whole Analysis page and WPRS. A tap on a day's transmission, on ▶ in an Analysis table or on *Replay* in WPRS opens that very moment in Replay. Add it to the home screen and it opens like an app; it keeps itself up to date.
- **Analysis opens at once** — the server now prepares the default 90-day analysis in the background every ten minutes, so the Analysis page (on the full page and in the phone app) no longer keeps you waiting. The other periods are still computed when you choose them; meanwhile the page says what it is doing — a message with the seconds waited on the first opening, and *Loading …* beside the period buttons, with the old cards dimmed, when you switch periods.
- **When is there data?** — *About* (on the full page and in the phone app) now says that data comes only while the car's WSPR transmitter is running: it runs on 30 000 mAh batteries and can sometimes be off, and typically it runs around the clock in the summer season (March–November) and is off in the winter.
- **A user guide for the phone** — *Guides* now has the *Mobile app user guide* right after the user guide: how to open the app, the menu and every view.
- **WPRS in two pages** — *Guides* now also has a two-page summary of the WPRS paper: how the car reports its position over HF and the key results of three seasons, for a quick read.
- **WPRS: only the long trips** — the day filter on the WPRS page now also has *150 km* and *200 km*.
- **A user guide** — *Guides* now starts with a 25-page user guide: how WSPR and the logger work, every part of the live map, the History Player, the History and Statistics pages, and above all how to read each chart of the Analysis page, with examples from this station's own data.
- **Seven new things to look at on the Analysis page** — a compass chart of *where* you are heard (direction and distance), how the stations spread over distance, when the band opens and closes each day next to sunrise and sunset, the seasons side by side month by month, how many stations (and how many new ones) hear you each month, signal strength by hour and by distance, the most unusual days with a button to replay them, and the stations that hear you most faithfully.
- **Analysis in a new order** — *Right now* is followed by the Ionosonde view, the band-open heatmap and the DX outlook, so the present conditions and the ionosphere come first.
- **Ionosonde view over any period** — the MUF and foF2 chart on the Analysis page can now show one day, the last 30 days, 90 days, 6 months, a year, all history or any range of days you choose. Longer periods are shown as averages, and the night-time MUF is no longer missing on the day view.
- **Day and night in the History Player** — with the *Day / Night* layer on, the History Player now shows where the terminator was at the replayed moment, so you can watch the grey line move across the map. The player bar also fits on one line again.
- **Analysis over 6 months or a year** — next to 30 d, 90 d and All, the Propagation Analysis page now has *6 m* and *1 yr* buttons.
- **Fixes from a code review** — *& DX* and ⚡ *HIGH MUF* on the Propagation card now work whatever layers are switched on; an old MUF reading is no longer shown as the present one; the History Player no longer skips the hours when nobody heard the car; reporters with a four-character locator appear at the right place on the Reporter Plot; and the logger asks wspr.live one question less every ten minutes.
- **Fixed: Analysis missed many stations** — a few hours of reports with an unknown distance in May 2025 made 42 ordinary European stations look implausible, and the Analysis page left them out of everything. They are counted again, so the averages are now higher and correct; only three genuinely inconsistent stations stay excluded. The *Farthest reporters* table now sits at the bottom of the page, full width.
- **Reporter Countries the same width as Propagation** — a Reporter Countries window that had been moved could be wider than the cards above it; it now always matches them.
- **Hide the menu completely** — the ◀ button at the top of the menu now hides the whole menu, so the map gets the full window. A large ▶ handle on the left edge of the page opens it again.

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
