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


# ---------------------------------------------------------------------------
# Callsign prefix → Country mapping (ITU allocations)
# ---------------------------------------------------------------------------

_COUNTRY_MAP = {
    # UK & Ireland
    'GM':'Scotland',  'GW':'Wales',     'GI':'N. Ireland', 'GD':'Isle of Man',
    'GJ':'Jersey',    'GU':'Guernsey',  'G':'UK',          'M':'UK',
    'EI':'Ireland',
    # Scandinavia
    'OH':'Finland',   'OF':'Finland',   'OG':'Finland',
    'SM':'Sweden',    'SA':'Sweden',    'SK':'Sweden',      'SL':'Sweden',
    'LA':'Norway',    'LB':'Norway',
    'OZ':'Denmark',   'OU':'Denmark',   'OV':'Denmark',
    'OY':'Faroe Is.', 'OX':'Greenland', 'TF':'Iceland',
    # Western Europe
    'DL':'Germany',   'DA':'Germany',   'DC':'Germany',     'DD':'Germany',
    'DF':'Germany',   'DG':'Germany',   'DH':'Germany',     'DJ':'Germany',
    'DK':'Germany',   'DM':'Germany',   'DO':'Germany',
    'F':'France',
    'PA':'Netherlands','PB':'Netherlands','PC':'Netherlands','PD':'Netherlands',
    'PE':'Netherlands','PH':'Netherlands','PI':'Netherlands',
    'ON':'Belgium',   'OO':'Belgium',   'OP':'Belgium',
    'HB':'Switzerland','OE':'Austria',
    'IK':'Italy',     'IW':'Italy',     'IZ':'Italy',       'I':'Italy',
    'EA':'Spain',     'EB':'Spain',     'EC':'Spain',
    'CT':'Portugal',  'CS':'Portugal',
    # Central & Eastern Europe
    'SP':'Poland',    'SQ':'Poland',    'SR':'Poland',      'SO':'Poland',
    'OK':'Czechia',   'OL':'Czechia',   'OM':'Slovakia',
    'HA':'Hungary',   'HG':'Hungary',
    'YO':'Romania',   'YP':'Romania',
    'LZ':'Bulgaria',
    'SV':'Greece',    'SW':'Greece',    'SX':'Greece',
    'TA':'Turkey',
    # Baltic & Belarus
    'ES':'Estonia',   'YL':'Latvia',    'LY':'Lithuania',   'EW':'Belarus',
    # Ukraine
    'UR':'Ukraine',   'US':'Ukraine',   'UT':'Ukraine',     'UX':'Ukraine',
    'UY':'Ukraine',   'UZ':'Ukraine',   'EM':'Ukraine',     'EN':'Ukraine',
    # Russia
    'UA':'Russia',    'RA':'Russia',    'RK':'Russia',      'RL':'Russia',
    'RN':'Russia',    'RT':'Russia',    'RU':'Russia',      'RV':'Russia',
    'RW':'Russia',    'RX':'Russia',    'RZ':'Russia',      'R':'Russia',
    # Americas
    'AA':'USA',  'AB':'USA',  'AC':'USA',  'AD':'USA',  'AE':'USA',
    'AF':'USA',  'AG':'USA',  'AI':'USA',  'AK':'USA',  'AL':'USA',
    'K':'USA',   'W':'USA',   'N':'USA',
    'VE':'Canada',    'VA':'Canada',
    'PY':'Brazil',    'PP':'Brazil',    'PT':'Brazil',      'PU':'Brazil',
    'LU':'Argentina', 'CE':'Chile',     'XE':'Mexico',      'HK':'Colombia',
    # Asia / Pacific
    'JA':'Japan',     'JE':'Japan',     'JF':'Japan',       'JG':'Japan',
    'JH':'Japan',     'JI':'Japan',     'JJ':'Japan',       'JL':'Japan',
    'JR':'Japan',     'JS':'Japan',
    'VK':'Australia', 'ZL':'New Zealand',
    'HL':'S. Korea',  'DS':'S. Korea',
    'BY':'China',     'BG':'China',     'BA':'China',
    'VU':'India',     'HS':'Thailand',
    # Africa & Middle East
    'ZS':'S. Africa', '4X':'Israel',    '4Z':'Israel',
    '5B':'Cyprus',    'A4':'Oman',      'A6':'UAE',
    'EA8':'Canary Is.',
}


def callsign_to_country(sign: str) -> str:
    """Return a country name for a given amateur callsign."""
    base = sign.upper().strip().split('/')[0]   # strip /P /M suffixes
    for length in (3, 2, 1):
        if len(base) >= length:
            country = _COUNTRY_MAP.get(base[:length])
            if country:
                return country
    return base[:2] if len(base) >= 2 else base  # fallback: show prefix


def fetch_reporter_countries(callsign: str, band: int) -> list:
    """
    Return [{country, count}, …] for the most recent transmission,
    sorted by count descending.
    """
    sql = f"""
        SELECT DISTINCT rx_sign
        FROM wspr.rx
        WHERE tx_sign = '{callsign}'
          AND band    = {band}
          AND time > subtractMinutes(now(), 60)
    """
    rows = wsprlive_query(sql)
    if not rows:
        return []

    counts: dict = {}
    for row in rows:
        country = callsign_to_country(row.get("rx_sign", "??"))
        counts[country] = counts.get(country, 0) + 1

    return sorted(
        [{"country": c, "count": n} for c, n in counts.items()],
        key=lambda x: -x["count"]
    )


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

_BAND_LABELS = {
    3:'80m — 3.5 MHz', 7:'40m — 7 MHz', 10:'30m — 10 MHz',
    14:'20m — 14 MHz', 18:'17m — 18 MHz', 21:'15m — 21 MHz',
    24:'12m — 24 MHz', 28:'10m — 28 MHz',
}

@app.route("/")
def index():
    return render_template(
        "index.html",
        callsign=CALLSIGN,
        default_band=DEFAULT_BAND,
        band_label=_BAND_LABELS.get(DEFAULT_BAND, f"{DEFAULT_BAND} MHz"),
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


@app.route("/api/reporters")
def api_reporters():
    band = request.args.get("band", type=int, default=DEFAULT_BAND)
    countries = fetch_reporter_countries(CALLSIGN, band)
    return jsonify({"countries": countries})




# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.init(DB_PATH)
    threading.Thread(target=update_thread, daemon=True).start()
    app.run(debug=DEBUG, host=HOST, port=PORT, use_reloader=False)
