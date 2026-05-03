"""
wspr_logger.py — WSPR Beacon Location Logger
Refactored Flask app: client-side Leaflet map, SQLite storage, REST API.
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request
import configparser
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import db

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.ini")

def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE)
    return cfg

cfg = load_config()

CALLSIGN     = cfg.get("station",  "callsign",     fallback="OH2GAX")
DEFAULT_BAND = cfg.getint("station", "default_band", fallback=14)
HOST         = cfg.get("server",   "host",          fallback="0.0.0.0")
PORT         = cfg.getint("server", "port",          fallback=5008)
DEBUG        = cfg.getboolean("server", "debug",     fallback=False)
DB_PATH          = cfg.get("database", "path",          fallback="wspr_data.db")
MAP_DEFAULT_LAT  = cfg.getfloat("map", "default_lat", fallback=60.0)
MAP_DEFAULT_LON  = cfg.getfloat("map", "default_lon", fallback=24.0)
MAP_DEFAULT_ZOOM = cfg.getint("map",   "default_zoom", fallback=6)

# Make DB_PATH relative to the script directory if not absolute
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_PATH)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))

# Thread-safe state
_state_lock = threading.Lock()
_last_update_utc = None      # ISO string of last successful fetch
_update_error    = None      # Last error message, if any


# ---------------------------------------------------------------------------
# Helper: Maidenhead → lat/lon
# ---------------------------------------------------------------------------

def maidenhead_to_latlon(grid: str):
    if len(grid) < 6:
        return None, None
    g = grid.upper()
    try:
        lon = (ord(g[0]) - ord('A')) * 20 - 180
        lat = (ord(g[1]) - ord('A')) * 10 - 90
        lon += (ord(g[2]) - ord('0')) * 2
        lat += (ord(g[3]) - ord('0')) * 1
        lon += (ord(g[4]) - ord('A')) * (2.0 / 24.0)
        lat += (ord(g[5]) - ord('A')) * (1.0 / 24.0)
        lon += (2.0 / 24.0) / 2
        lat += (1.0 / 24.0) / 2
        return round(lat, 4), round(lon, 4)
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# WSPR.live query
# ---------------------------------------------------------------------------

def wsprlive_query(sql: str):
    url = "https://db1.wspr.live/?query=" + urllib.parse.quote_plus(sql + " FORMAT JSON")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))["data"]
    except Exception as e:
        print(f"[WSPR.live] Query failed: {e}")
        return None


def fetch_latest_spot(callsign: str, band: int):
    """
    Fetch the most recent WSPR transmission for callsign/band.
    Returns a dict with tx_loc, time, reporter_count, max_distance — or None.
    Groups by (tx_loc, time) so each unique TX is one row with aggregated stats.
    """
    sql = f"""
        SELECT
            tx_loc,
            time,
            count()       AS reporter_count,
            max(distance) AS max_distance
        FROM wspr.rx
        WHERE time > subtractMinutes(now(), 20)
          AND tx_sign = '{callsign}'
          AND band    = {band}
        GROUP BY tx_loc, time
        ORDER BY time DESC
        LIMIT 1
    """
    data = wsprlive_query(sql)
    return data[0] if data else None


# ---------------------------------------------------------------------------
# Background update thread
# ---------------------------------------------------------------------------

def update_thread():
    global _last_update_utc, _update_error
    print(f"[INFO] Update thread started — tracking {CALLSIGN} on {DEFAULT_BAND} MHz")

    while True:
        now = datetime.utcnow()

        # Act at minute :08, :18, :28, :38, :48, :58
        # (6 minutes after each 10-min WSPR TX cycle boundary so data is settled)
        if now.minute % 10 == 8:
            print(f"[INFO] Polling WSPR.live at {now.strftime('%H:%M:%S')} UTC")

            row = fetch_latest_spot(CALLSIGN, DEFAULT_BAND)

            if row:
                tx_loc         = row["tx_loc"]
                timestamp_str  = row["time"]
                reporter_count = int(row.get("reporter_count") or 0)
                max_distance   = int(row.get("max_distance")   or 0)

                try:
                    ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    print(f"[WARN] Unparseable timestamp: {timestamp_str}")
                    time.sleep(60)
                    continue

                # Only accept WSPR cycle timestamps (minute ends in :02, :12, :22, ...)
                if ts.minute % 10 != 2:
                    print(f"[INFO] Skipping — timestamp minute {ts.minute} not a TX slot")
                else:
                    lat, lon = maidenhead_to_latlon(tx_loc)
                    if lat is not None:
                        inserted = db.insert_spot(
                            timestamp_str, tx_loc, lat, lon,
                            DEFAULT_BAND, reporter_count, max_distance
                        )
                        if inserted:
                            with _state_lock:
                                _last_update_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                                _update_error    = None
                            print(f"[INFO] Logged: {tx_loc} @ {timestamp_str}  "
                                  f"reporters={reporter_count}  max_dx={max_distance} km")
                        else:
                            print(f"[INFO] Duplicate, skipped: {timestamp_str}")
                    else:
                        print(f"[WARN] Could not convert locator: {tx_loc}")
            else:
                print("[INFO] No data returned from WSPR.live")
                with _state_lock:
                    _update_error = "No data from WSPR.live"

        time.sleep(60)


# ---------------------------------------------------------------------------
# Flask routes — pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template(
        "index.html",
        callsign=CALLSIGN,
        default_band=DEFAULT_BAND,
        map_lat=MAP_DEFAULT_LAT,
        map_lon=MAP_DEFAULT_LON,
        map_zoom=MAP_DEFAULT_ZOOM,
    )


# ---------------------------------------------------------------------------
# Flask routes — REST API
# ---------------------------------------------------------------------------

@app.route("/api/latest")
def api_latest():
    band = request.args.get("band", type=int)
    spot = db.get_latest_spot(band)
    with _state_lock:
        lu = _last_update_utc
        err = _update_error
    return jsonify({
        "spot":        spot,
        "last_update": lu,
        "error":       err,
        "callsign":    CALLSIGN,
    })


@app.route("/api/positions")
def api_positions():
    band    = request.args.get("band",  type=int)
    date    = request.args.get("date")
    from_dt = request.args.get("from")
    to_dt   = request.args.get("to")

    if date:
        spots = db.get_spots_by_date(date, band)
    elif from_dt and to_dt:
        spots = db.get_spots_range(from_dt, to_dt, band)
    else:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        spots = db.get_spots_by_date(today, band)

    return jsonify(spots)


@app.route("/api/stats")
def api_stats():
    band    = request.args.get("band",  type=int)
    date    = request.args.get("date",  default=datetime.utcnow().strftime("%Y-%m-%d"))
    stats   = db.get_stats_by_date(date, band)
    dates   = db.get_available_dates(band)
    alltime = db.get_all_time_stats()
    return jsonify({
        "stats":           stats,
        "available_dates": dates,
        "all_time":        alltime,
    })


@app.route("/api/config", methods=["GET"])
def api_config_get():
    return jsonify({
        "callsign":     CALLSIGN,
        "default_band": DEFAULT_BAND,
        "host":         HOST,
        "port":         PORT,
        "map_lat":      MAP_DEFAULT_LAT,
        "map_lon":      MAP_DEFAULT_LON,
        "map_zoom":     MAP_DEFAULT_ZOOM,
        "db_path":      DB_PATH,
    })


@app.route("/api/config", methods=["POST"])
def api_config_set():
    data = request.get_json(silent=True) or {}
    try:
        new_cfg = configparser.ConfigParser()
        new_cfg.read(CONFIG_FILE)

        # Ensure all sections exist
        for section in ("station", "server", "database", "map"):
            if not new_cfg.has_section(section):
                new_cfg.add_section(section)

        mapping = {
            "callsign":     ("station",  "callsign"),
            "default_band": ("station",  "default_band"),
            "host":         ("server",   "host"),
            "port":         ("server",   "port"),
            "db_path":      ("database", "path"),
            "map_lat":      ("map",      "default_lat"),
            "map_lon":      ("map",      "default_lon"),
            "map_zoom":     ("map",      "default_zoom"),
        }
        for key, (section, option) in mapping.items():
            if key in data:
                new_cfg.set(section, option, str(data[key]))

        with open(CONFIG_FILE, "w") as f:
            new_cfg.write(f)

        return jsonify({"success": True,
                        "message": "Settings saved. Restart the server to apply all changes."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.init(DB_PATH)
    threading.Thread(target=update_thread, daemon=True).start()
    app.run(debug=DEBUG, host=HOST, port=PORT, use_reloader=False)
