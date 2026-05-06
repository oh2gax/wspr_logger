"""
wspr_logger.py — WSPR Beacon Location Logger
Refactored Flask app: client-side Leaflet map, SQLite storage, REST API.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import configparser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

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
_state_lock           = threading.Lock()
_last_update_utc      = None   # ISO string of last successful fetch
_update_error         = None   # Last error message, if any
_cached_countries     = []     # Reporter countries from last poll
_cached_reporter_list = []     # Individual reporter details from last poll

# Solar data cache (refreshed on demand, TTL = 60 s)
_solar_cache      = {}
_solar_cache_time = None
_SOLAR_TTL        = 60     # seconds
_cached_fof2      = None   # Latest foF2 value from GIRO (MHz)


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
    # ── 3-char prefixes (checked first) ─────────────────────────────────────
    'EA8':'Canary Is.',   'EA9':'Ceuta/Melilla',
    'HB0':'Liechtenstein',
    'KH6':'Hawaii',       'KL7':'Alaska',       'KP4':'Puerto Rico',
    'KP2':'US Virgin Is.','KH0':'N. Mariana Is.',
    '3DA':'Eswatini',
    # ── UK & Ireland ────────────────────────────────────────────────────────
    'GM':'Scotland',  'GW':'Wales',     'GI':'N. Ireland', 'GD':'Isle of Man',
    'GJ':'Jersey',    'GU':'Guernsey',  'G':'UK',          'M':'UK',
    '2E':'UK',        '2M':'UK',        '2W':'UK',         '2I':'UK',
    'EI':'Ireland',
    # ── Scandinavia ─────────────────────────────────────────────────────────
    'OH':'Finland',   'OF':'Finland',   'OG':'Finland',
    'OI':'Finland',   'OJ':'Finland',
    'SM':'Sweden',    'SA':'Sweden',    'SK':'Sweden',
    'SL':'Sweden',    'SJ':'Sweden',
    'LA':'Norway',    'LB':'Norway',    'LC':'Norway',
    'OZ':'Denmark',   'OU':'Denmark',   'OV':'Denmark',
    'OY':'Faroe Is.', 'OX':'Greenland', 'TF':'Iceland',
    # ── Western Europe ──────────────────────────────────────────────────────
    'DA':'Germany',   'DB':'Germany',   'DC':'Germany',   'DD':'Germany',
    'DF':'Germany',   'DG':'Germany',   'DH':'Germany',   'DJ':'Germany',
    'DK':'Germany',   'DL':'Germany',   'DM':'Germany',   'DN':'Germany',
    'DO':'Germany',   'DP':'Germany',   'DQ':'Germany',   'DR':'Germany',
    'F':'France',     'TM':'France',
    'PA':'Netherlands','PB':'Netherlands','PC':'Netherlands','PD':'Netherlands',
    'PE':'Netherlands','PF':'Netherlands','PG':'Netherlands','PH':'Netherlands',
    'PI':'Netherlands','PL':'Netherlands',
    'ON':'Belgium',   'OO':'Belgium',   'OP':'Belgium',   'OQ':'Belgium',
    'OR':'Belgium',   'OS':'Belgium',   'OT':'Belgium',
    'HB':'Switzerland',
    'OE':'Austria',
    'LX':'Luxembourg',
    'I':'Italy',      'IK':'Italy',     'IN':'Italy',     'IO':'Italy',
    'IP':'Italy',     'IQ':'Italy',     'IR':'Italy',     'IS':'Italy',
    'IU':'Italy',     'IW':'Italy',     'IZ':'Italy',
    'EA':'Spain',     'EB':'Spain',     'EC':'Spain',     'ED':'Spain',
    'EE':'Spain',     'EF':'Spain',     'EG':'Spain',     'EH':'Spain',
    'CT':'Portugal',  'CS':'Portugal',  'CQ':'Portugal',  'CR':'Portugal',
    # ── Balkans ─────────────────────────────────────────────────────────────
    '9A':'Croatia',
    'S5':'Slovenia',
    'YU':'Serbia',    '4N':'Serbia',
    'E7':'Bosnia',    'T9':'Bosnia',
    'Z3':'N. Macedonia',
    '4O':'Montenegro',
    'ZA':'Albania',
    'Z6':'Kosovo',
    # ── Central & Eastern Europe ────────────────────────────────────────────
    'SP':'Poland',    'SN':'Poland',    'SO':'Poland',
    'SQ':'Poland',    'SR':'Poland',    '3Z':'Poland',
    'OK':'Czechia',   'OL':'Czechia',
    'OM':'Slovakia',
    'HA':'Hungary',   'HG':'Hungary',
    'YO':'Romania',   'YP':'Romania',   'YQ':'Romania',   'YR':'Romania',
    'LZ':'Bulgaria',
    'SV':'Greece',    'SW':'Greece',    'SX':'Greece',
    'SY':'Greece',    'J4':'Greece',
    'TA':'Turkey',    'TB':'Turkey',    'TC':'Turkey',    'YM':'Turkey',
    'ER':'Moldova',
    # ── Baltic & Belarus ────────────────────────────────────────────────────
    'ES':'Estonia',   'YL':'Latvia',    'LY':'Lithuania', 'EW':'Belarus',
    # ── Ukraine ─────────────────────────────────────────────────────────────
    'EM':'Ukraine',   'EN':'Ukraine',   'EO':'Ukraine',
    'UR':'Ukraine',   'US':'Ukraine',   'UT':'Ukraine',
    'UX':'Ukraine',   'UY':'Ukraine',   'UZ':'Ukraine',
    # ── Russia ──────────────────────────────────────────────────────────────
    'R':'Russia',
    'RA':'Russia',    'RB':'Russia',    'RC':'Russia',    'RD':'Russia',
    'RE':'Russia',    'RF':'Russia',    'RG':'Russia',    'RJ':'Russia',
    'RK':'Russia',    'RL':'Russia',    'RM':'Russia',    'RN':'Russia',
    'RO':'Russia',    'RP':'Russia',    'RQ':'Russia',    'RT':'Russia',
    'RU':'Russia',    'RV':'Russia',    'RW':'Russia',    'RX':'Russia',
    'RY':'Russia',    'RZ':'Russia',
    'UA':'Russia',    'UB':'Russia',    'UC':'Russia',    'UD':'Russia',
    'UE':'Russia',    'UF':'Russia',    'UG':'Russia',
    # ── Caucasus & Central Asia ─────────────────────────────────────────────
    '4J':'Azerbaijan','4K':'Azerbaijan',
    '4L':'Georgia',
    'EK':'Armenia',
    'UN':'Kazakhstan','UP':'Kazakhstan','UQ':'Kazakhstan',
    'EX':'Kyrgyzstan','EY':'Tajikistan','EZ':'Turkmenistan',
    'UK':'Uzbekistan',
    # ── Americas ────────────────────────────────────────────────────────────
    'AA':'USA',  'AB':'USA',  'AC':'USA',  'AD':'USA',  'AE':'USA',
    'AF':'USA',  'AG':'USA',  'AI':'USA',  'AK':'USA',  'AL':'USA',
    'K':'USA',   'W':'USA',   'N':'USA',
    'VE':'Canada',   'VA':'Canada',   'VO':'Canada',   'VY':'Canada',
    'XE':'Mexico',   'XF':'Mexico',
    'TI':'Costa Rica',
    'HI':'Dom. Rep.','CO':'Cuba',     'CM':'Cuba',
    'PY':'Brazil',   'PP':'Brazil',   'PT':'Brazil',   'PU':'Brazil',
    'PV':'Brazil',   'PW':'Brazil',   'PX':'Brazil',
    'LU':'Argentina','AY':'Argentina','AZ':'Argentina',
    'CE':'Chile',    'XQ':'Chile',    'CA':'Chile',
    'HK':'Colombia', 'OA':'Peru',     'CP':'Bolivia',
    'CX':'Uruguay',  'ZP':'Paraguay', 'HC':'Ecuador',
    'YV':'Venezuela','YW':'Venezuela','4M':'Venezuela',
    '9Y':'Trinidad', '8P':'Barbados',
    # ── Asia / Pacific ──────────────────────────────────────────────────────
    'JA':'Japan',    'JE':'Japan',    'JF':'Japan',    'JG':'Japan',
    'JH':'Japan',    'JI':'Japan',    'JJ':'Japan',    'JK':'Japan',
    'JL':'Japan',    'JM':'Japan',    'JN':'Japan',    'JO':'Japan',
    'JP':'Japan',    'JQ':'Japan',    'JR':'Japan',    'JS':'Japan',
    'VK':'Australia',
    'ZL':'New Zealand','ZM':'New Zealand',
    'HL':'S. Korea', 'DS':'S. Korea', '6K':'S. Korea',
    '6L':'S. Korea', 'DT':'S. Korea',
    'BY':'China',    'BG':'China',    'BA':'China',    'BH':'China',
    'BI':'China',    'BJ':'China',    'BK':'China',    'BL':'China',
    'BM':'China',    'BN':'China',    'BO':'China',    'BP':'China',
    'BQ':'China',    'BR':'China',    'BS':'China',    'BT':'China',
    'BU':'China',    'BV':'Taiwan',
    'VU':'India',    'AT':'India',    'AU':'India',    'AV':'India',
    'HS':'Thailand', 'E2':'Thailand',
    'VR':'Hong Kong',
    '9V':'Singapore',
    '9W':'Malaysia',
    'YB':'Indonesia','YC':'Indonesia','YD':'Indonesia','YE':'Indonesia',
    'YF':'Indonesia','YG':'Indonesia','YH':'Indonesia',
    'DU':'Philippines','4D':'Philippines','4E':'Philippines',
    'XV':'Vietnam',  'XU':'Cambodia', 'XW':'Laos',
    '9N':'Nepal',    'S2':'Bangladesh','AP':'Pakistan',
    '4S':'Sri Lanka',
    'JT':'Mongolia', 'JU':'Mongolia',
    # ── Middle East ─────────────────────────────────────────────────────────
    '4X':'Israel',   '4Z':'Israel',
    'A4':'Oman',     'A6':'UAE',      'A7':'Qatar',    'A9':'Bahrain',
    '9K':'Kuwait',   'HZ':'Saudi Arabia','7Z':'Saudi Arabia',
    'YK':'Syria',    'OD':'Lebanon',  'YI':'Iraq',
    'EP':'Iran',     'EQ':'Iran',
    # ── Africa ──────────────────────────────────────────────────────────────
    'ZS':'S. Africa','ZR':'S. Africa','ZT':'S. Africa','ZU':'S. Africa',
    '5B':'Cyprus',
    'CN':'Morocco',  '7X':'Algeria',  'TS':'Tunisia',
    '5A':'Libya',    'SU':'Egypt',    'ST':'Sudan',
    '5Z':'Kenya',    '5H':'Tanzania', '9J':'Zambia',
    'Z2':'Zimbabwe',
    '7Q':'Malawi',   'V5':'Namibia',  'A2':'Botswana',
    '9X':'Rwanda',   '9U':'Burundi',  '5R':'Madagascar',
    'TZ':'Mali',     '5N':'Nigeria',  '5O':'Guinea',
    '6W':'Senegal',  'TL':'C. African Rep.',
    'TR':'Gabon',    'TJ':'Cameroon', '9Q':'DR Congo',
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


_BAND_LABELS_SHORT = {
    3:'80m', 7:'40m', 10:'30m', 14:'20m',
    18:'17m', 21:'15m', 24:'12m', 28:'10m',
}


def fetch_reporter_list(callsign: str, band: int) -> list:
    """
    Return [{band, callsign, grid, snr, distance}, …] for individual reporters
    heard in the past 60 minutes.  One row per unique (rx_sign, rx_loc) pair,
    keeping the best (highest) SNR and the corresponding distance.
    """
    sql = f"""
        SELECT
            rx_sign,
            rx_loc,
            max(snr)      AS snr,
            max(distance) AS distance
        FROM wspr.rx
        WHERE tx_sign = '{callsign}'
          AND band    = {band}
          AND time > subtractMinutes(now(), 60)
        GROUP BY rx_sign, rx_loc
        ORDER BY snr DESC
    """
    rows = wsprlive_query(sql)
    if not rows:
        return []
    band_label = _BAND_LABELS_SHORT.get(band, f"{band}MHz")
    result = []
    for r in rows:
        try:
            snr  = int(r.get("snr", 0))
            dist = int(r.get("distance", 0))
        except (TypeError, ValueError):
            snr, dist = 0, 0
        result.append({
            "band":     band_label,
            "callsign": r.get("rx_sign", "?"),
            "grid":     (r.get("rx_loc") or "?")[:6],
            "snr":      snr,
            "distance": dist,
        })
    return result


def fetch_giro_mufd() -> float | None:
    """
    Fetch the latest MUF(D=3000 km) directly from Juliusruh (JR055) via
    the GIRO DIDBase MUFD endpoint.  MUFD is the measured propagation MUF
    for a 3000 km path — same data that was previously scraped from the HTML
    page but sourced from the authoritative ionosonde database (~5 min lag).
    Returns MUF in MHz, or None if unavailable.
    """
    now     = datetime.utcnow()
    from_dt = (now - timedelta(hours=24)).strftime("%Y/%m/%d %H:%M:%S")
    to_dt   = now.strftime("%Y/%m/%d %H:%M:%S")
    params  = urllib.parse.urlencode({
        "ursiCode": "JR055",
        "charName": "MUFD",
        "DMUF":     "3000",
        "fromDate": from_dt,
        "toDate":   to_dt,
    })
    url = f"https://lgdc.uml.edu/common/DIDBGetValues?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        val = _parse_giro_latest(text)
        if val is not None:
            print(f"[GIRO] MUFD = {val:.3f} MHz")
        else:
            print("[GIRO] MUFD: no valid data in response")
        return val
    except Exception as e:
        print(f"[GIRO] MUFD fetch failed: {e}")
        return None


def _parse_giro_latest(text: str) -> float | None:
    """
    Return the most recent valid numeric value from a GIRO DIDBGetValues response.

    Actual line format returned by the endpoint:
      ISO-timestamp  quality(int)  value(float)  qualifier
      e.g.: 2026-05-04T23:58:16.000Z  80  3.700 //

    Quality scores are plain integers; actual measurements always have a
    decimal point.  We therefore require '.' in the token to accept it as
    a measurement value.  The last accepted value wins (chronological order).
    """
    latest = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        for token in parts:
            if '.' not in token:
                continue          # skip integers (quality flags, year fields, etc.)
            try:
                val = float(token)
                if 0.1 < val < 100.0:   # plausible ionospheric range (MHz or M-factor)
                    latest = val
                    break               # one value per line; move to next line
            except ValueError:
                pass
    return latest


def fetch_giro_fof2() -> float | None:
    """
    Fetch the latest foF2 from Juliusruh (JR055) via GIRO DIDBase.
    Uses a 24-hour rolling window with the correct GIRO date format
    (YYYY/MM/DD HH:MM:SS) which returns near-real-time data (~5 min lag).
    Returns foF2 in MHz, or None if unavailable.
    """
    now     = datetime.utcnow()
    from_dt = (now - timedelta(hours=24)).strftime("%Y/%m/%d %H:%M:%S")
    to_dt   = now.strftime("%Y/%m/%d %H:%M:%S")
    params  = urllib.parse.urlencode({
        "ursiCode": "JR055",
        "charName": "foF2",
        "DMUF":     "3000",
        "fromDate": from_dt,
        "toDate":   to_dt,
    })
    url = f"https://lgdc.uml.edu/common/DIDBGetValues?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        val = _parse_giro_latest(text)
        if val is not None:
            print(f"[GIRO] foF2 = {val:.3f} MHz")
        else:
            print("[GIRO] foF2: no valid data in response")
        return val
    except Exception as e:
        print(f"[GIRO] foF2 fetch failed: {e}")
        return None


def fetch_solar_data() -> dict:
    """
    Fetch solar indices from hamqsl.com.
    Returns cached data if fresher than _SOLAR_TTL seconds.
    """
    global _solar_cache, _solar_cache_time
    now = datetime.utcnow()
    if _solar_cache_time and (now - _solar_cache_time).total_seconds() < _SOLAR_TTL:
        return _solar_cache
    try:
        url = "https://www.hamqsl.com/solarxml.php"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        sd   = root.find(".//solardata")
        result = {
            "sfi":        sd.findtext("solarflux",    "—"),
            "kindex":     sd.findtext("kindex",        "—"),
            "aindex":     sd.findtext("aindex",        "—"),
            "xray":       sd.findtext("xray",          "—"),
            "bz":         sd.findtext("magneticfield", "—"),
            "solarwind":  sd.findtext("solarwind",     "—"),
            "aurora":     sd.findtext("aurora",        "—"),
            "protonflux": sd.findtext("protonflux",    "—"),
            "updated":    sd.findtext("updated",       "—"),
        }
        _solar_cache      = result
        _solar_cache_time = now
        print(f"[Solar] SFI={result['sfi']} K={result['kindex']} "
              f"A={result['aindex']} X={result['xray']} Bz={result['bz']}")
        return result
    except Exception as e:
        print(f"[Solar] Fetch failed: {e}")
        return _solar_cache   # return stale cache on error


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
    global _last_update_utc, _update_error, _cached_countries, _cached_reporter_list, _cached_fof2
    print(f"[INFO] Update thread started — tracking {CALLSIGN} on {DEFAULT_BAND} MHz")

    # Populate caches immediately on startup so the UI has data before the
    # first scheduled poll cycle (minutes ending in :08).
    print(f"[INFO] Initial fetch on startup...")
    initial_spot = fetch_latest_spot(CALLSIGN, DEFAULT_BAND)
    if initial_spot:
        ts = initial_spot.get("time", "")
        try:
            ts_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            if ts_dt.minute % 10 == 2:
                lat, lon = maidenhead_to_latlon(initial_spot["tx_loc"])
                if lat is not None:
                    db.insert_spot(ts, initial_spot["tx_loc"], lat, lon,
                                   DEFAULT_BAND,
                                   int(initial_spot.get("reporter_count") or 0),
                                   int(initial_spot.get("max_distance")   or 0))
        except ValueError:
            pass
    with _state_lock:
        _cached_countries     = fetch_reporter_countries(CALLSIGN, DEFAULT_BAND)
        _cached_reporter_list = fetch_reporter_list(CALLSIGN, DEFAULT_BAND)
    muf_init = fetch_giro_mufd()
    if muf_init:
        db.insert_muf(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), muf_init)
    fof2_init = fetch_giro_fof2()
    with _state_lock:
        _cached_fof2 = fof2_init
    print(f"[INFO] Initial fetch complete — {len(_cached_countries)} countries cached, "
          f"{len(_cached_reporter_list)} reporters, "
          f"MUF={muf_init} MHz, foF2={fof2_init} MHz")

    while True:
        now = datetime.utcnow()

        # Act at minute :08, :18, :28, :38, :48, :58
        # (6 minutes after each 10-min WSPR TX cycle boundary so data is settled)
        if now.minute % 10 == 8:
            print(f"[INFO] Polling WSPR.live at {now.strftime('%H:%M:%S')} UTC")

            row           = fetch_latest_spot(CALLSIGN, DEFAULT_BAND)
            countries     = fetch_reporter_countries(CALLSIGN, DEFAULT_BAND)
            reporter_list = fetch_reporter_list(CALLSIGN, DEFAULT_BAND)
            with _state_lock:
                _cached_countries     = countries
                _cached_reporter_list = reporter_list

            # MUF and foF2 both from GIRO DIDBase (JR055, ~5 min lag)
            muf = fetch_giro_mufd()
            if muf:
                db.insert_muf(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), muf)
                print(f"[INFO] MUF D=3000: {muf} MHz")
            fof2 = fetch_giro_fof2()
            with _state_lock:
                _cached_fof2 = fof2

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
        lu        = _last_update_utc
        err       = _update_error
        countries = _cached_countries
    return jsonify({
        "spot":        spot,
        "last_update": lu,
        "error":       err,
        "callsign":    CALLSIGN,
        "countries":   countries,
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


@app.route("/api/muf")
def api_muf():
    band      = request.args.get("band", type=int, default=DEFAULT_BAND)
    days      = request.args.get("days", type=int, default=1)
    days      = max(1, min(days, 7))
    muf_rows  = db.get_muf_last_24h(days)
    spot_rows = db.get_spots_last_24h(band, days)
    return jsonify({"muf": muf_rows, "spots": spot_rows})


@app.route("/api/solar")
def api_solar():
    data = fetch_solar_data()
    muf_rows = db.get_muf_last_24h()
    data = dict(data)
    data["muf"] = muf_rows[-1]["muf"] if muf_rows else None
    with _state_lock:
        data["fof2"] = _cached_fof2
    return jsonify(data)


@app.route("/api/reporters")
def api_reporters():
    with _state_lock:
        countries = _cached_countries
    return jsonify({"countries": countries})


@app.route("/api/reporter_list")
def api_reporter_list():
    with _state_lock:
        reporters = _cached_reporter_list
    return jsonify({"reporters": reporters})




# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.init(DB_PATH)
    threading.Thread(target=update_thread, daemon=True).start()
    app.run(debug=DEBUG, host=HOST, port=PORT, use_reloader=False)
