"""
replay_db.py — SQLite storage for the WSPR Logger replay feature.

Stores two types of historical snapshots at each 10-minute poll cycle:

  reporters_log — individual reporter records (callsign, grid, SNR, distance)
                  for the 60-minute window visible at each poll time.
                  Multiple polls will overlap (the same reporter may appear
                  in up to 6 consecutive polls) — this is intentional, since
                  it faithfully records the "current reporter window" at every
                  point in time, which is exactly what the replay UI will show.

  solar_log     — one row per poll with all solar/geomagnetic indices plus
                  foF2 and MUF, giving a complete picture of space-weather
                  conditions at any past moment.

This database is completely independent of wspr_data.db.  It can be deleted
at any time to reclaim disk space or start fresh without affecting live
logging.  The replay feature simply becomes unavailable until new data
accumulates.

Estimated storage: ~50–80 MB per year of continuous operation.
"""
from __future__ import annotations

import os
import sqlite3

_db_path: str | None = None
_enabled: bool = False


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def init(path: str, enabled: bool = True) -> None:
    """Initialise the replay database.  Safe to call even if disabled."""
    global _db_path, _enabled
    _enabled = enabled
    if not enabled:
        print("[ReplayDB] Disabled in config — skipping initialisation")
        return
    _db_path = path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    _create_tables()


def is_enabled() -> bool:
    return _enabled


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _create_tables() -> None:
    with _connect() as conn:
        # Individual reporters heard in the 60-min window at each poll cycle.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reporters_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                callsign    TEXT    NOT NULL,
                grid        TEXT    NOT NULL,
                snr         INTEGER NOT NULL DEFAULT 0,
                distance    INTEGER NOT NULL DEFAULT 0,
                band        INTEGER NOT NULL DEFAULT 14,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_rep_timestamp
            ON reporters_log (timestamp)
        """)

        # Solar / geomagnetic / ionospheric snapshot per poll cycle.
        # xray is kept as TEXT because it carries a letter prefix (e.g. "B5.3").
        # All numeric fields use REAL to accommodate non-integer inputs from
        # hamqsl.com; NULL is stored when the source returns "—" or is absent.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS solar_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL UNIQUE,
                sfi         REAL,
                kindex      REAL,
                aindex      REAL,
                xray        TEXT,
                bz          REAL,
                solarwind   REAL,
                aurora      REAL,
                protonflux  REAL,
                fof2        REAL,
                muf         REAL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_solar_timestamp
            ON solar_log (timestamp)
        """)
        conn.commit()
    print(f"[ReplayDB] Initialised at: {_db_path}")


def _to_float(val) -> float | None:
    """Convert a value to float, returning None for missing / dash values."""
    if val is None or val == "—" or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Write — reporters
# ---------------------------------------------------------------------------

def insert_reporters(timestamp: str, reporters: list[dict], band: int) -> int:
    """
    Insert a batch of reporter records for the given poll timestamp.
    Returns the number of rows inserted, or 0 if disabled / empty.

    timestamp : 'YYYY-MM-DD HH:MM:SS' UTC — the time of the poll cycle
    reporters : list of dicts with keys callsign, grid, snr, distance
    band      : integer band in MHz (e.g. 14 for 20 m)
    """
    if not _enabled or not reporters:
        return 0
    rows = [
        (timestamp, r["callsign"], r["grid"],
         int(r.get("snr", 0)), int(r.get("distance", 0)), band)
        for r in reporters
    ]
    try:
        with _connect() as conn:
            conn.executemany("""
                INSERT INTO reporters_log
                    (timestamp, callsign, grid, snr, distance, band)
                VALUES (?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
        return len(rows)
    except Exception as e:
        print(f"[ReplayDB Error] insert_reporters: {e}")
        return 0


# ---------------------------------------------------------------------------
# Write — solar
# ---------------------------------------------------------------------------

def insert_solar(timestamp: str, solar: dict,
                 fof2: float | None, muf: float | None) -> bool:
    """
    Insert a solar conditions snapshot.  Silently ignores duplicate timestamps
    (INSERT OR IGNORE) so it is safe to call on every poll cycle.

    timestamp : 'YYYY-MM-DD HH:MM:SS' UTC
    solar     : dict returned by fetch_solar_data() — keys sfi, kindex, aindex,
                xray, bz, solarwind, aurora, protonflux
    fof2      : foF2 in MHz from GIRO DIDBase, or None
    muf       : MUF D=3000 km in MHz from GIRO DIDBase, or None
    """
    if not _enabled:
        return False
    try:
        with _connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO solar_log
                    (timestamp, sfi, kindex, aindex, xray, bz,
                     solarwind, aurora, protonflux, fof2, muf)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                _to_float(solar.get("sfi")),
                _to_float(solar.get("kindex")),
                _to_float(solar.get("aindex")),
                solar.get("xray"),              # kept as TEXT
                _to_float(solar.get("bz")),
                _to_float(solar.get("solarwind")),
                _to_float(solar.get("aurora")),
                _to_float(solar.get("protonflux")),
                fof2,
                muf,
            ))
            conn.commit()
            inserted = conn.execute("SELECT changes()").fetchone()[0] == 1
        if inserted:
            print(f"[ReplayDB] Solar snapshot stored @ {timestamp}")
        return inserted
    except Exception as e:
        print(f"[ReplayDB Error] insert_solar: {e}")
        return False


# ---------------------------------------------------------------------------
# Read helpers (for future replay UI queries)
# ---------------------------------------------------------------------------

def get_reporters_at(timestamp: str, band: int = 14,
                     window_minutes: int = 5) -> list[dict]:
    """
    Return reporters for the poll cycle nearest to *timestamp* (within
    window_minutes).  Useful for the replay UI to populate the reporter
    list / plot for any selected moment.
    """
    if not _enabled:
        return []
    with _connect() as conn:
        rows = conn.execute("""
            SELECT callsign, grid, snr, distance, band, timestamp
            FROM reporters_log
            WHERE band = ?
              AND timestamp BETWEEN
                  datetime(?, ?)
                  AND datetime(?, ?)
            ORDER BY timestamp DESC, snr DESC
        """, (
            band,
            timestamp, f"-{window_minutes} minutes",
            timestamp, f"+{window_minutes} minutes",
        )).fetchall()
    return [dict(r) for r in rows]


def get_solar_nearest(timestamp: str) -> dict | None:
    """
    Return the solar snapshot closest in time to *timestamp*.
    Looks within ±15 minutes; returns None if no record is found.
    """
    if not _enabled:
        return None
    with _connect() as conn:
        row = conn.execute("""
            SELECT * FROM solar_log
            WHERE timestamp BETWEEN
                datetime(?, '-15 minutes')
                AND datetime(?, '+15 minutes')
            ORDER BY ABS(strftime('%s', timestamp) - strftime('%s', ?))
            LIMIT 1
        """, (timestamp, timestamp, timestamp)).fetchone()
    return dict(row) if row else None


def get_available_dates(band: int = 14) -> list[str]:
    """Return distinct UTC dates that have reporter data, newest first."""
    if not _enabled:
        return []
    with _connect() as conn:
        rows = conn.execute("""
            SELECT DISTINCT date(timestamp) AS d
            FROM reporters_log WHERE band = ?
            ORDER BY d DESC
        """, (band,)).fetchall()
    return [r["d"] for r in rows]


def get_day_frames(date_str: str, band: int = 14) -> list[dict]:
    """
    Return every stored snapshot of one UTC day (oldest first) for the
    replay player, including polls that heard nobody (no reporters, solar row only).  Each frame is
        {"ts": "YYYY-MM-DD HH:MM:SS",
         "reporters": [(callsign, grid, snr, distance), ...],
         "solar": {sfi, kindex, aindex, xray, bz, solarwind, aurora,
                   protonflux, fof2, muf} or None}
    Reporter rows and the solar row of one poll share the same timestamp.
    date_str must be 'YYYY-MM-DD' (the caller validates it).
    """
    if not _enabled:
        return []
    with _connect() as conn:
        rep = conn.execute("""
            SELECT timestamp, callsign, grid, snr, distance
            FROM reporters_log
            WHERE band = ?
              AND timestamp >= ? AND timestamp < datetime(?, '+1 day')
            ORDER BY timestamp, snr DESC
        """, (band, date_str, date_str)).fetchall()
        sol = conn.execute("""
            SELECT timestamp, sfi, kindex, aindex, xray, bz, solarwind,
                   aurora, protonflux, fof2, muf
            FROM solar_log
            WHERE timestamp >= ? AND timestamp < datetime(?, '+1 day')
        """, (date_str, date_str)).fetchall()

    solar_by_ts = {}
    for r in sol:
        s = dict(r)
        solar_by_ts[s.pop("timestamp")] = s
    # A poll that heard nobody stores only its solar row; it is still a frame (with no reporters), so the
    # player does not jump over the night and the Solar panel shows the conditions of those hours too.
    frames: dict[str, dict] = {ts: {"ts": ts, "reporters": [], "solar": s} for ts, s in solar_by_ts.items()}
    for r in rep:
        f = frames.get(r["timestamp"])
        if f is None:
            f = frames[r["timestamp"]] = {"ts": r["timestamp"], "reporters": [], "solar": None}
        f["reporters"].append((r["callsign"], r["grid"], r["snr"], r["distance"]))
    return [frames[ts] for ts in sorted(frames)]


def _exclusion(exclude) -> tuple:
    """SQL fragment and arguments that leave out the given 'CALLSIGN|GRID' keys."""
    if not exclude:
        return "", []
    keys = sorted(exclude)
    return f" AND (callsign || '|' || grid) NOT IN ({','.join('?' for _ in keys)})", keys


def get_reporter_pairs(band: int = 14) -> list[dict]:
    """Every (callsign, grid) pair with its smallest and largest reported distance.
    A distance of 0 means "not known", not "0 km": wspr.live delivered 0 for every report of a few
    hours (7 May 2025), and taking it as a distance made ordinary stations look implausible and
    dropped them from the whole analysis.  Such rows are left out of this check."""
    if not _enabled:
        return []
    with _connect() as conn:
        rows = conn.execute("""
            SELECT callsign, grid, MIN(distance) AS dmin, MAX(distance) AS dmax, COUNT(*) AS n
            FROM reporters_log WHERE band = ? AND distance > 0 GROUP BY callsign, grid
        """, (band,)).fetchall()
    return [dict(r) for r in rows]


def get_pair_distances(pairs, band: int = 14) -> dict:
    """{(callsign, grid): [distinct reported distances > 0]} for the given (callsign, grid) pairs."""
    pairs = list(pairs)
    if not _enabled or not pairs:
        return {}
    out: dict = {}
    with _connect() as conn:
        for call, grid in pairs:
            out[(call, grid)] = [r[0] for r in conn.execute(
                "SELECT DISTINCT distance FROM reporters_log WHERE band = ? AND callsign = ? AND grid = ? AND distance > 0",
                (band, call, grid))]
    return out


def get_dx_reports(days: int = 90, band: int = 14, exclude=None, min_km: int = 6000) -> list[tuple]:
    """One row per (UTC day, hour, callsign, grid) with a report beyond min_km:
    (day, hour, callsign, grid, farthest distance).  days = 0 -> all."""
    if not _enabled:
        return []
    where = "WHERE band = ? AND distance > ?"
    args: list = [band, min_km]
    if days and days > 0:
        where += " AND timestamp >= datetime('now', ?)"
        args.append(f"-{int(days)} days")
    frag, extra = _exclusion(exclude)
    with _connect() as conn:
        rows = conn.execute(f"""
            SELECT substr(timestamp, 1, 10) AS day, CAST(substr(timestamp, 12, 2) AS INTEGER) AS hr,
                   callsign, grid, MAX(distance) AS dist
            FROM reporters_log {where}{frag}
            GROUP BY day, hr, callsign, grid
        """, args + extra).fetchall()
    return [tuple(r) for r in rows]


def get_snapshot_rows(days: int = 90, band: int = 14, exclude=None) -> list[tuple]:
    """
    One row per snapshot for the Analysis page:
        (timestamp, reporter_count, max_distance, reporters_over_6000km,
         kindex, muf, sfi)
    days = 0 means the whole history.  Solar fields are None when the
    snapshot has no matching solar row.  `exclude` = 'CALLSIGN|GRID' keys to leave out.
    """
    if not _enabled:
        return []
    where = "WHERE band = ?"
    args: list = [band]
    if days and days > 0:
        where += " AND timestamp >= datetime('now', ?)"
        args.append(f"-{int(days)} days")
    frag, extra = _exclusion(exclude)
    where += frag
    args += extra
    with _connect() as conn:
        rows = conn.execute(f"""
            SELECT s.ts, s.n, s.mx, s.dx6, l.kindex, l.muf, l.sfi
            FROM (SELECT timestamp AS ts, COUNT(*) AS n,
                         MAX(distance) AS mx,
                         SUM(CASE WHEN distance > 6000 THEN 1 ELSE 0 END) AS dx6
                  FROM reporters_log {where}
                  GROUP BY timestamp) AS s
            LEFT JOIN solar_log l ON l.timestamp = s.ts
            ORDER BY s.ts
        """, args).fetchall()
    return [tuple(r) for r in rows]


def get_first_timestamp(band: int = 14) -> str | None:
    """Timestamp of the oldest reporter snapshot of the band, or None."""
    if not _enabled:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT MIN(timestamp) FROM reporters_log WHERE band = ?", (band,)).fetchone()
    return row[0] if row else None


def get_iono_series(start: str, end: str, band: int = 14, bucket_min: int = 10, offset_min: int = 0) -> list[dict]:
    """
    Stations heard, Juliusruh MUF and foF2 between start and end ('YYYY-MM-DD HH:MM:SS', end
    excluded), averaged over buckets of bucket_min minutes.  Bucket k covers the epoch seconds
    [k * bucket + offset, (k + 1) * bucket + offset).  A poll whose solar row exists but that heard
    nobody counts as 0 stations (the night), so the MUF line is not lost where the band is closed.
    MUF / foF2 readings of 0 or less are feed failures and are ignored.
    Each row: {k, snaps, n (mean stations heard), muf, fof2}.
    """
    if not _enabled:
        return []
    b, off = int(bucket_min) * 60, int(offset_min) * 60
    with _connect() as conn:
        rows = conn.execute(f"""
            WITH snaps AS (
                SELECT timestamp AS ts, COUNT(*) AS n FROM reporters_log
                WHERE band = ? AND timestamp >= ? AND timestamp < ?
                GROUP BY timestamp),
            allts AS (
                SELECT ts FROM snaps
                UNION
                SELECT timestamp FROM solar_log WHERE timestamp >= ? AND timestamp < ?)
            SELECT (CAST(strftime('%s', a.ts) AS INTEGER) - {off}) / {b} AS k,
                   COUNT(*) AS snaps,
                   AVG(COALESCE(s.n, 0)) AS n,
                   AVG(CASE WHEN l.muf  > 0 THEN l.muf  END) AS muf,
                   AVG(CASE WHEN l.fof2 > 0 THEN l.fof2 END) AS fof2
            FROM allts a
            LEFT JOIN snaps s ON s.ts = a.ts
            LEFT JOIN solar_log l ON l.timestamp = a.ts
            GROUP BY k ORDER BY k
        """, (band, start, end, start, end)).fetchall()
    return [dict(r) for r in rows]


def _period_where(days: int, band: int, exclude) -> tuple:
    """WHERE clause and arguments for one band, the last `days` days (0 = all) and the exclusions."""
    where = "WHERE band = ?"
    args: list = [band]
    if days and days > 0:
        where += " AND timestamp >= datetime('now', ?)"
        args.append(f"-{int(days)} days")
    frag, extra = _exclusion(exclude)
    return where + frag, args + extra


def get_station_stats(days: int = 90, band: int = 14, exclude=None) -> list[dict]:
    """One row per (callsign, grid) heard in the period: snapshots it appears in, mean / largest
    distance, mean / best SNR and the first time it was seen in the period."""
    if not _enabled:
        return []
    where, args = _period_where(days, band, exclude)
    with _connect() as conn:
        rows = conn.execute(f"""
            SELECT callsign, grid, COUNT(*) AS n, AVG(NULLIF(distance, 0)) AS dist, MAX(distance) AS dmax,
                   AVG(snr) AS snr, MAX(snr) AS snr_max, MIN(timestamp) AS first
            FROM reporters_log {where}
            GROUP BY callsign, grid
        """, args).fetchall()
    return [dict(r) for r in rows]


def get_month_stations(band: int = 14, exclude=None) -> list[tuple]:
    """(month 'YYYY-MM', callsign) for every station heard in each month of the whole history."""
    if not _enabled:
        return []
    where, args = _period_where(0, band, exclude)
    with _connect() as conn:
        rows = conn.execute(f"""
            SELECT substr(timestamp, 1, 7) AS m, callsign FROM reporters_log {where}
            GROUP BY m, callsign ORDER BY m
        """, args).fetchall()
    return [tuple(r) for r in rows]


def get_snr_table(days: int = 90, band: int = 14, exclude=None) -> list[tuple]:
    """(UTC hour, distance // 1000 km, SNR, number of reports) for the period: enough for SNR by hour
    and SNR by distance.  Reports with an unknown distance (0) are left out."""
    if not _enabled:
        return []
    where, args = _period_where(days, band, exclude)
    with _connect() as conn:
        rows = conn.execute(f"""
            SELECT CAST(substr(timestamp, 12, 2) AS INTEGER) AS h, distance / 1000 AS b, snr, COUNT(*) AS c
            FROM reporters_log {where} AND distance > 0
            GROUP BY h, b, snr
        """, args).fetchall()
    return [tuple(r) for r in rows]


def get_top_distances(days: int = 90, band: int = 14, limit: int = 10, exclude=None) -> list[dict]:
    """
    The farthest reporters: one row per callsign (its longest distance),
    best first.  Each row: callsign, grid, distance, timestamp (the poll at
    which that distance was seen, earliest if repeated).  days = 0 -> all.
    """
    if not _enabled:
        return []
    where = "WHERE band = ?"
    args: list = [band]
    if days and days > 0:
        where += " AND timestamp >= datetime('now', ?)"
        args.append(f"-{int(days)} days")
    frag, extra = _exclusion(exclude)
    where += frag
    args += extra
    with _connect() as conn:
        rows = conn.execute(f"""
            SELECT callsign, grid, distance, timestamp
            FROM reporters_log {where}
            ORDER BY distance DESC, timestamp ASC
            LIMIT 500
        """, args).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["callsign"] in seen:
            continue
        seen.add(r["callsign"])
        out.append(dict(r))
        if len(out) >= limit:
            break
    return out
