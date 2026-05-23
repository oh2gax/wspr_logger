# Changelog

All notable changes to WSPR Logger are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- **wspr.live timeout detection** — `wsprlive_query()` now tracks whether the last
  query to wspr.live succeeded or failed via a `_wspr_live_down` boolean flag.
- **"DB Timeout!" propagation indicator** — when wspr.live is unreachable the
  Propagation overlay shows **DB Timeout!** in amber with a "wspr.live unreachable"
  subtitle instead of "No propagation or TX Fail", making it clear the silence is
  caused by an external database outage rather than a transmission problem.
- `/api/latest` response now includes a `wspr_down` boolean field so the frontend
  can react to backend connectivity state without extra API calls.

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
