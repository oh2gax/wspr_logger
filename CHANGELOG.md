# Changelog

All notable changes to WSPR Logger are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [2026-11-06]

### Added
- **WPRS page — the car's movements** — new sidebar page **WPRS** (Whisper Position
  Reporting System). Every transmission carries the locator the transmitter computed from
  its GPS fix, so the logged spots are a position track. A *drive detector* lists the days
  on which the car moved: per day the squares used, the largest distance between two squares
  (moved), the path length and the farthest distance from the home square (the most
  frequent locator), so days parked far from home are caught too. A filter (any change of
  square, 5, 10 — the default —, 25 or 100 km) and a 1 / 2 / 3 / 5-day span select what is
  shown. The map draws the visited Maidenhead squares (shaded by number of fixes), the
  track line with a dot per fix (hover for time, locator, reporters and best DX), start,
  end and home. A *drive replay* bar plays the fixes in order (1–16 fixes per second, slider,
  to start) with the trail so far, and **History Player** opens the shown moment in the
  History Player on the live map. New module `wprs.py`, endpoints `/api/wprs/days` and
  `/api/wprs/track?from=&to=` (up to 7 days), `db.get_all_spots()`.
- **Guides — PDF documents on the page** — new sidebar entry **Guides** opens a window
  that lists the PDF files of the new `doc/` folder with *Open* and *Download* links.
  Titles, descriptions and dates come from `doc/guides.json` (a PDF without an entry is
  listed under its file name). New module `guides.py`, endpoints `/api/guides` and
  `/doc/<file>` (only plain `*.pdf` names inside `doc/` are served). *What's new* and
  *User guides* are two tabs of one window, as on the Mode-S Wind page: both sidebar
  entries open it, on the tab of the entry.
- **Movable map panels** — the History / reporter list, the histogram and the country
  overlay can be dragged by their title bar anywhere on the map (kept inside the map; the
  position is remembered, double-click the title to reset). The date/time card, the
  Propagation overlay and the MUF D=3000 graph stay where they were.
- **Fix age on the live map** — a label beside the car marker and a line in the Current
  Position card say how old the latest fix is (for example "last fix 38 min ago"), so a stale
  position is not mistaken for the present one. The new **Last Fix Label** switch in Map Layers
  hides the label on the map (remembered; the line in the card stays).
- **Share links** — the address of the page follows the view: a day, a moment in the
  History Player or a WPRS day and fix can be copied and opened by someone else
  (`#...` links; WPRS has a *Copy link* button).
- **WPRS trip summary cards** — consecutive days away from home (gap of at most 36 h, at
  least 25 km from home) are grouped into trips with dates, duration, squares, path length
  and farthest point. A *Days / Trips* switch in the list; selecting a trip draws it on the
  map and replays it. `wprs.build_trips()`, `trips` in `/api/wprs/days`.
- **Analysis: outlier filter** — a reporter whose distance contradicts its own locator by
  more than 500 km (a mistyped or stale grid) is dropped from the analysis and the records,
  and listed in a collapsible *Excluded reports* card. `excluded` in `/api/analysis`.
- **Analysis: grey-line card** — whether long-distance reports cluster around the sunrise
  and sunset at the far end or at home, with the hour of the day held fixed, compared with
  the share expected by chance (z score). New modules `sun.py` and `greyline.py`;
  `greyline` in `/api/analysis`.
- **Analysis: DX outlook card** — for the next 12 hours the chance of a report beyond
  6000 km, from the hour-of-day history with shrinkage towards the average, adjusted for the
  present MUF and K only if that adjustment beat the hour of the day alone in a
  chronological back-test (otherwise the card says so). New module `outlook.py`;
  `outlook`, `outlook_model` in `/api/analysis`. Always fitted on the whole history.
- **History backfill from wspr.live** — `tools/backfill.py` fills the replay database with
  the snapshots of earlier seasons by reconstructing, from the spots wspr.live holds for
  the callsign, what the :08 poll would have listed. Run it on the server:
  `venv/bin/python tools/backfill.py --test 2025-08-15`, then for example
  `venv/bin/python tools/backfill.py --from 2024-07-01`. Existing snapshots are
  never overwritten; solar and MUF data are not backfilled. `--compare DATE` checks rebuilt snapshots against the live ones of the same days. See README.
- **Two scientific PDF notes in `doc/`** — *Twenty-metre WSPR propagation study*
  (three seasons, 2024–2026, 495 days with data, the first two rebuilt from wspr.live: diurnal and seasonal patterns, season comparison, geography, DX windows,
  space-weather effects, a storm case study) and *WPRS – Whisper Position Reporting
  System* (position beaconing over HF with the 200 mW GPS transmitter and the
  car-roof antenna: locator resolution, fix availability, tracks, power reach, battery
  budget). Every figure, table and number is generated from the databases by
  `doc/src/analyze.py` and `doc/src/analyze_wprs.py`; the LaTeX sources are in `doc/src/`.
- **Propagation Analysis page** — new sidebar page **Analysis**, computed from the
  replay database (no wspr.live queries, cached 10 minutes). A *band-open heatmap*
  (UTC hour by date, coloured by average reporters or farthest distance, with
  hover details), a *typical day* chart (median and 25–75 % range per UTC hour with
  the latest day on top), reporters versus Juliusruh *MUF*, *K-index* and *SFI*, and
  a table of *geomagnetic storm days* (K ≥ 5). Period buttons 30 d / 90 d / All.
  The bin charts show an index (100 = typical number of reporters for that UTC
  hour) so the day/night rhythm does not masquerade as a space-weather effect;
  solar readings of 0 (feed glitches) are ignored. New module `analysis.py`,
  endpoint `/api/analysis?days=&band=`, `replay_db.get_snapshot_rows()`.
- **Analysis: "Right now" comparison** — the live number of stations heard is shown
  next to what is usual for this UTC hour (median and 25–75 % range) and, when
  there is enough history, for a similar Juliusruh MUF (same 2 MHz bin), with a
  verdict: better than usual / typical / below usual. A MUF reading older than
  3 hours is ignored, and no verdict is given while wspr.live is down.
- **Analysis: DX windows** — share of snapshots with a reporter beyond 6000 km and
  the average farthest reporter by UTC hour, plus a month-by-month chart of average
  stations heard and DX share (tooltips show days, snapshots and average SFI).
- **Analysis: farthest reporters and replay links** — table of the ten farthest
  stations of the period (one row per station, with country and grid), and a ▶ button
  on every row of it and of the storm-day table that opens that exact moment in the
  History Player. `replay_db.get_top_distances()`; the player now accepts a start
  moment (`openReplayAt()`).
- **Analysis: Ionosonde day view** — pick any day and see Juliusruh MUF (and foF2,
  for days where it was collected) as lines over the stations heard through that
  day; foF2 history builds up from the day the new foF2 source went live.
- **History player on the live map** — new sidebar switch **History Player** opens
  a player bar at the bottom of the map: play/pause, time slider, date picker with
  previous/next day that has data, 1/2/4/8/16 frames per second, and **Live ✕** to
  return to live data. One frame per stored poll snapshot (~every 10 minutes).
  While replaying, the normal layer switches decide what is shown: Reporter List,
  SNR / Dist Histogram, Reporter Plot (great-circle arcs from the beacon position
  logged at that time), Reporter Countries, and the Solar Conditions panel
  (SFI, K, A, X-ray, Bz, wind, aurora, proton flux, foF2, MUF). The Propagation
  overlay uses the spot logged at that time, or "No propagation" if none was
  logged within 25 minutes. Live refreshes are paused during replay and the page
  repaints from live data on exit. New endpoints `/api/replay/dates` and
  `/api/replay/day?date=YYYY-MM-DD` (a whole day in one ~300 KB response);
  `replay_db.get_day_frames()`; solar panel rendering split into `renderSolar()`.
- **Map Layer toggles are remembered per browser** — the sidebar switches and their
  sub-settings (MUF period, histogram SNR/Dist tab, reporter-list sort, 1h/Today tab)
  are saved to `localStorage` (key `wspr_layers`) on every change and restored on
  page load through the normal toggle functions. Missing or corrupt storage falls
  back to the defaults.
- **What's new and About** — two new entries in the sidebar. *What's new* lists the
  changes of the last 10 days (read from this CHANGELOG by `changelog.py`, endpoint
  `/api/whatsnew`) and shows the version as `v.DDMMYYYY` (date of the newest
  entry), with a NEW marker until it has been opened. *About* shows the station:
  operator, transmitter (200 mW), antenna, home locator and a link to the public
  GitHub repository.
- **Statistics page redesign** — day navigation with previous/next arrows and a
  weekday label, an *average reporters* card, a *Longest DX* card that shows the
  percentage of the all-time record (or a trophy on a record day), a *Through the
  day* chart (reporters per transmission and farthest distance), a *Best DX per
  day* chart (30 d / 90 d / All; click a bar to open that day), all-time records
  with the date each was set, and a clickable list of logged dates. New endpoint
  `/api/daily_summary`.
- **`update.sh` — one-command server update** — pulls the latest version from
  GitHub on a git-clone installation (such as the AWS server), restarts the
  systemd service, and verifies that the web page answers with HTTP 200 again.
  It shows the new commits and changed files first and asks for confirmation
  (`-y` skips the question). `bash update.sh --rollback` returns to the version
  that ran before the last update.
- **Safety checks in `update.sh`** — only fast-forwards (`git merge --ff-only`)
  and never runs `git reset`, `stash`, or `checkout`, so server-local files
  (`config.ini` with `host = 127.0.0.1`, `api_keys.py`, the databases) are never
  overwritten; if GitHub changes a file that is also modified locally, the script
  stops and explains what to do. Changed `.py` files and templates are
  syntax-checked straight from git before anything is touched, so a broken or
  truncated push cannot take the running service down. Both SQLite databases are
  copied to `<install folder>_backups/` with SQLite's online backup before every
  update (the 7 newest copies are kept), and `pip install -r requirements.txt`
  runs only when `requirements.txt` changed.
- **README: Updating on a Server** — a step-by-step recipe for converting a folder
  that was copied rather than cloned into a git checkout without touching
  `config.ini`, `api_keys.py`, the databases or `venv/`; `update.sh` added to the
  project structure.

### Changed
- **Databases in a `data/` folder** — `wspr_data.db` and `wspr_replay.db` now live in
  `data/` (created automatically; the folder is gitignored). Installations that still have
  the files next to `wspr_logger.py` keep working: the program finds them there and logs a
  note. `bash update.sh --migrate-data` moves them in one step (backup first, service
  stopped for a moment, `config.ini` paths updated, automatic undo if the service does not
  come back). The analysis scripts in `doc/src` look in `data/` first.
- **`config.ini` is a local file** — it is no longer in git; the repository has
  `config.ini.example` and the program creates `config.ini` from it when it is missing.
  Updates therefore never conflict with server settings such as `host = 127.0.0.1`, and
  `update.sh --rollback` keeps the local `config.ini`. Inline `; comments` after a value are
  now accepted. The one update that introduces this needs a short manual step, described
  in the README.
- **Theme selector: Auto / Dark / Light** — the *Dark Mode / Light Mode* entry of the
  left menu is replaced by one icon button (🌓 / 🌙 / ☀️) beside the sidebar title, next to the
  collapse arrow. Each click cycles Auto, Dark and Light. *Auto* follows the system setting and
  switches live when it changes; it is also the default for browsers that have not chosen yet
  (earlier explicit choices are kept). The page no longer flashes the wrong theme while loading.
- **More reliable foF2 source** — foF2 is now read first from the Juliusruh Space
  Weather Monitor page (`ionosonde.iap-kborn.de/actuellz.htm`, "ION" row, updated
  every 15 minutes, 10 s timeout) and GIRO DIDBase is only tried if that fails,
  because GIRO frequently returned nothing. The HTML is reduced to plain text before
  matching, so the parser does not depend on the table markup. The MUF source is
  unchanged (GIRO first, Juliusruh page as fallback).
- **Empty "Band" block removed from the sidebar** — it never showed a value (the
  template variable was never supplied); the band is still shown in the 1h / Today
  card.
- **`.gitignore` updated** — it now ignores `wspr_replay.db*` (large, server-local), and its line
  endings were normalised.

### Fixed
- **Reporter Countries window hidden after a reload** — a window that had been moved lost
  its stacking order when its saved place was restored and went behind the map. Moved
  windows now always stay above the map.
- **MUF graph under the Date/Time card** — the "last fix … ago" text had widened the card on
  the right; it now has its own line and the right-hand column keeps a fixed width.
- **Best DX / reporter count under-reported long-distance spots** — each poll only
  queried the single newest transmission slot, six minutes after it was sent.
  Distant reporters (USA, Asia, Pacific) upload to wspr.live later, and by the next
  poll the newest slot was a different one, so the earlier slot was never refreshed;
  the `ON CONFLICT` update added earlier only helped after a backend restart.
  Comparing the databases showed that on 67 of 163 days the farthest reporter in the
  replay data was farther than the stored Best DX (e.g. 15,614 km vs 4,553 km on
  2026-10-07). The poll query now covers the last 45 minutes / 5 slots (still one
  query per cycle, no extra wspr.live load), and every poll raises the stored
  `max_distance` / `reporter_count` of the recent slots (values are never lowered).
  New helpers: `fetch_recent_spots()`, `store_spots()`, `db.get_spot_at()`; the
  log shows `Updated: <slot> reporters a->b max_dx x->y km` when a slot improves.
  Days already stored are not corrected retroactively.
- **Statistics: All-Time Records and Logged Dates were always empty** — the
  `/api/stats` route returned only the day's numbers while the page also expected
  `all_time` and `available_dates`; both are now included.
- **SNR / Dist Histogram was empty when it was the only layer switched on** — the
  reporter data was only fetched when the Reporter List or Reporter Plot was
  enabled. The histogram now triggers the fetch itself.
- **MUF panel title said "Last 24 h" at start-up** although the default period is
  2 days; the title now matches the active period button.

---

## [2026-09-06]

### Added
- **CARTO Basemaps API key support** — CARTO now requires a free API key on its
  raster tile service to remove the "API key required" watermark. The key is
  loaded from a local, gitignored `api_keys.py` file (`CARTO_API_KEY = "..."`)
  following the same local-secrets pattern used in other projects:
  `api_keys.py` holds the real key and is excluded via `.gitignore`;
  `api_keys.py.example` is the committed template with an empty placeholder.
  `wspr_logger.py` imports the key with a graceful fallback (empty string plus
  a console warning) so the server still starts on a machine where the file
  hasn't been configured yet — the map just keeps the watermark until it is.
  The key is passed through `render_template()` to the frontend and appended
  as a `?key=` query parameter on both the dark and light CARTO tile URLs in
  `makeTiles()`.

---

## [2026-05-23]

### Added
- **wspr.live health check** — a dedicated `check_wsprlive_health()` function runs
  `SELECT count() AS cnt FROM wspr.rx WHERE time > subtractMinutes(now(), 5)` once
  per poll cycle (and immediately on startup). Because there are always thousands of
  WSPR spots globally every few minutes, a count of zero reliably indicates that the
  ClickHouse database is broken or lagging, even when the HTTP connection itself
  succeeds. The `_wspr_live_down` flag is set `True` on either a network failure
  (exception) or an empty count, and cleared only when the health check confirms live
  data is present.
- **"DB Timeout!" propagation indicator** — when `_wspr_live_down` is `True` the
  Propagation overlay shows **DB Timeout!** in amber with a "wspr.live unreachable"
  subtitle, distinguishing a data source outage from "No propagation or TX Fail" and
  making it immediately clear the silence is external rather than a transmission
  problem. The indicator clears automatically on the next successful health check.
- `/api/latest` response now includes a `wspr_down` boolean field so the frontend
  can react to backend connectivity state without any extra API calls.

---

## [2026-05-21]

### Fixed
- **Page returned "Not Found"** — the entire Flask routes section
  (`/`, `/api/latest`, `/api/positions`, `/api/reporters`, `/api/reporter_list`,
  `/api/muf`, `/api/solar`, `/api/stats`) was missing from `wspr_logger.py` and
  was reconstructed in full.
- **Map not displayed after page load** — `render_template()` was passing
  `band=DEFAULT_BAND` but the Jinja2 template referenced `{{ default_band }}`.
  Parameter renamed to `default_band=DEFAULT_BAND`.
- **Reporter Countries panel showed "No data"** — `/api/reporters` was returning
  a raw JSON array (`jsonify(countries)`) but the frontend `toggleCountries()`
  handler expected `data.countries`. Response changed to
  `jsonify({"countries": countries})`.
- **Duplicate `if __name__ == "__main__":` block** — the entry point was
  duplicated at the end of `wspr_logger.py`, causing `db.init()` and the update
  thread to be started twice on launch. The redundant block was removed.

### Changed
- **`db.insert_spot()` — late-arriving WSPR data now updates stored distance** —
  `INSERT OR IGNORE` replaced with
  `INSERT … ON CONFLICT(timestamp) DO UPDATE SET` so that if a subsequent poll
  finds a higher `max_distance` or `reporter_count` for an already-stored
  transmission slot (because distant reporters upload to wspr.live with a delay),
  the local database record is updated rather than silently ignored. This fixes
  "Today Best DX" underreporting in the statistics sidebar.
