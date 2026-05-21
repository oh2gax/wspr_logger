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
