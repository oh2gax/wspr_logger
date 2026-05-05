"""
db.py — SQLite database layer for WSPR Logger
"""
from __future__ import annotations

import sqlite3
import os

_db_path = "wspr_data.db"


def init(path: str):
    """Set the database path and create tables if needed."""
    global _db_path
    _db_path = path
    _create_tables()


def _connect():
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _create_tables():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS spots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL UNIQUE,
                tx_loc          TEXT    NOT NULL,
                lat             REAL    NOT NULL,
                lon             REAL    NOT NULL,
                band            INTEGER NOT NULL DEFAULT 14,
                reporter_count  INTEGER NOT NULL DEFAULT 0,
                max_distance    INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_spots_timestamp
            ON spots (timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_spots_date
            ON spots (date(timestamp))
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS muf_data (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  TEXT    NOT NULL UNIQUE,
                muf        REAL    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_muf_timestamp
            ON muf_data (timestamp)
        """)
        conn.commit()
    print(f"[DB] Initialised at: {_db_path}")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def insert_spot(timestamp: str, tx_loc: str, lat: float, lon: float,
                band: int, reporter_count: int, max_distance: int) -> bool:
    """Insert a spot. Returns True if inserted, False if duplicate/error."""
    try:
        with _connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO spots
                    (timestamp, tx_loc, lat, lon, band, reporter_count, max_distance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (timestamp, tx_loc, lat, lon, band, reporter_count, max_distance))
            conn.commit()
            return conn.execute("SELECT changes()").fetchone()[0] == 1
    except Exception as e:
        print(f"[DB Error] insert_spot: {e}")
        return False


# ---------------------------------------------------------------------------
# Read — single spot
# ---------------------------------------------------------------------------

def get_latest_spot(band: int = None) -> dict | None:
    with _connect() as conn:
        if band:
            row = conn.execute("""
                SELECT * FROM spots WHERE band = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (band,)).fetchone()
        else:
            row = conn.execute("""
                SELECT * FROM spots ORDER BY timestamp DESC LIMIT 1
            """).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Read — collections
# ---------------------------------------------------------------------------

def get_spots_by_date(date_str: str, band: int = None) -> list[dict]:
    """date_str: 'YYYY-MM-DD'"""
    with _connect() as conn:
        if band:
            rows = conn.execute("""
                SELECT * FROM spots
                WHERE date(timestamp) = ? AND band = ?
                ORDER BY timestamp ASC
            """, (date_str, band)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM spots
                WHERE date(timestamp) = ?
                ORDER BY timestamp ASC
            """, (date_str,)).fetchall()
        return [dict(r) for r in rows]


def get_spots_range(from_dt: str, to_dt: str, band: int = None) -> list[dict]:
    """from_dt / to_dt: 'YYYY-MM-DD HH:MM:SS'"""
    with _connect() as conn:
        if band:
            rows = conn.execute("""
                SELECT * FROM spots
                WHERE timestamp BETWEEN ? AND ? AND band = ?
                ORDER BY timestamp ASC
            """, (from_dt, to_dt, band)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM spots
                WHERE timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
            """, (from_dt, to_dt)).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Read — statistics
# ---------------------------------------------------------------------------

def get_stats_by_date(date_str: str, band: int = None) -> dict | None:
    with _connect() as conn:
        if band:
            row = conn.execute("""
                SELECT
                    COUNT(*)        AS spot_count,
                    MAX(reporter_count) AS max_reporters,
                    MAX(max_distance)   AS max_distance,
                    MIN(timestamp)      AS first_spot,
                    MAX(timestamp)      AS last_spot
                FROM spots
                WHERE date(timestamp) = ? AND band = ?
            """, (date_str, band)).fetchone()
        else:
            row = conn.execute("""
                SELECT
                    COUNT(*)        AS spot_count,
                    MAX(reporter_count) AS max_reporters,
                    MAX(max_distance)   AS max_distance,
                    MIN(timestamp)      AS first_spot,
                    MAX(timestamp)      AS last_spot
                FROM spots
                WHERE date(timestamp) = ?
            """, (date_str,)).fetchone()
        return dict(row) if row else None


def get_available_dates(band: int = None) -> list[str]:
    with _connect() as conn:
        if band:
            rows = conn.execute("""
                SELECT DISTINCT date(timestamp) AS d
                FROM spots WHERE band = ?
                ORDER BY d DESC
            """, (band,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT DISTINCT date(timestamp) AS d
                FROM spots ORDER BY d DESC
            """).fetchall()
        return [r["d"] for r in rows]


def insert_muf(timestamp: str, muf: float) -> bool:
    """Insert a MUF reading. Returns True if inserted, False if duplicate/error."""
    try:
        with _connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO muf_data (timestamp, muf)
                VALUES (?, ?)
            """, (timestamp, muf))
            conn.commit()
            return conn.execute("SELECT changes()").fetchone()[0] == 1
    except Exception as e:
        print(f"[DB Error] insert_muf: {e}")
        return False


def get_muf_last_24h(days: int = 1) -> list[dict]:
    """Return MUF readings from the last N days, oldest first."""
    days = max(1, min(int(days), 7))
    with _connect() as conn:
        rows = conn.execute("""
            SELECT timestamp, muf FROM muf_data
            WHERE timestamp >= datetime('now', ?)
            ORDER BY timestamp ASC
        """, (f'-{days} days',)).fetchall()
        return [dict(r) for r in rows]


def get_spots_last_24h(band: int = None, days: int = 1) -> list[dict]:
    """Return spots from the last N days for chart overlay."""
    days = max(1, min(int(days), 7))
    with _connect() as conn:
        if band:
            rows = conn.execute("""
                SELECT timestamp, reporter_count FROM spots
                WHERE timestamp >= datetime('now', ?)
                  AND band = ?
                ORDER BY timestamp ASC
            """, (f'-{days} days', band)).fetchall()
        else:
            rows = conn.execute("""
                SELECT timestamp, reporter_count FROM spots
                WHERE timestamp >= datetime('now', ?)
                ORDER BY timestamp ASC
            """, (f'-{days} days',)).fetchall()
        return [dict(r) for r in rows]


def get_all_time_stats() -> dict:
    with _connect() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)            AS total_spots,
                MAX(reporter_count) AS best_reporters,
                MAX(max_distance)   AS best_dx,
                MIN(timestamp)      AS first_ever,
                MAX(timestamp)      AS last_ever,
                COUNT(DISTINCT date(timestamp)) AS active_days
            FROM spots
        """).fetchone()
        return dict(row) if row else {}
