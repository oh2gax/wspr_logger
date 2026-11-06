# Changelog

All notable changes to WSPR Logger are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [2026-11-06]

### Added
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
- README: new "Updating on a Server" section; `update.sh` added to the project
  structure.

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
