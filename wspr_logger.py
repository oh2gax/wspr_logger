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
import shutil
import xml.etree.ElementTree as ET
from html import unescape
from datetime import datetime, timedelta

from flask import Flask, abort, jsonify, make_response, render_template, request, send_from_directory

from core import analysis, changelog, db, greyline, guides, outlook, replay_db, wprs

try:
    from api_keys import CARTO_API_KEY
except ImportError:
    CARTO_API_KEY = ""
    print("[WARN] api_keys.py not found — CARTO maps will show a watermark. "
          "Copy api_keys.py.example to api_keys.py and add your key.")

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.ini")

# config.ini is a local file (not in git). A fresh checkout only has config.ini.example:
# copy it on the first start so the program runs with sensible defaults.
if not os.path.exists(CONFIG_FILE) and os.path.exists(CONFIG_FILE + ".example"):
    try:
        shutil.copyfile(CONFIG_FILE + ".example", CONFIG_FILE)
        print("[Config] config.ini was missing - created from config.ini.example (edit it and restart)")
    except OSError as e:
        print(f"[Config] could not create config.ini: {e}")

def load_config():
    cfg = configparser.ConfigParser(inline_comment_prefixes=(";",))      # "key = value   ; comment" works
    cfg.read(CONFIG_FILE)
    return cfg

cfg = load_config()

CALLSIGN     = cfg.get("station",  "callsign",     fallback="OH2GAX").strip()
if not re.fullmatch(r"[A-Za-z0-9/]{3,12}", CALLSIGN):      # it is put into the wspr.live queries
    raise SystemExit(f"config.ini: [station] callsign {CALLSIGN!r} is not a valid callsign (letters, digits and / only)")
DEFAULT_BAND = cfg.getint("station", "default_band", fallback=14)
HOST         = cfg.get("server",   "host",          fallback="0.0.0.0")
PORT         = cfg.getint("server", "port",          fallback=5008)
DEBUG        = cfg.getboolean("server", "debug",     fallback=False)
DB_PATH          = cfg.get("database", "path",          fallback="data/wspr_data.db")
MAP_DEFAULT_LAT  = cfg.getfloat("map", "default_lat", fallback=60.0)
MAP_DEFAULT_LON  = cfg.getfloat("map", "default_lon", fallback=24.0)
MAP_DEFAULT_ZOOM = cfg.getint("map",   "default_zoom", fallback=6)
REPLAY_ENABLED   = cfg.getboolean("replay", "enabled", fallback=True)
REPLAY_DB_PATH   = cfg.get("replay",   "path",          fallback="data/wspr_replay.db")

# Make DB paths relative to the script directory if not absolute
_script_dir = os.path.dirname(os.path.abspath(__file__))


def _db_file(path: str) -> str:
    """Absolute path of a database file. The databases live in data/. Installations from before
    that folder existed keep them next to this script: when the file is not in data/ but is found
    there, use it (and say so), so that an update never silently starts an empty database.
    `bash update.sh --migrate-data` moves the files."""
    p = path if os.path.isabs(path) else os.path.join(_script_dir, path)
    legacy = os.path.join(_script_dir, os.path.basename(p))
    if (not os.path.exists(p) and os.path.dirname(p) == os.path.join(_script_dir, "data")
            and os.path.exists(legacy)):
        print(f"[Config] {os.path.basename(p)} is not in data/ - using the old location {legacy}. "
              "Move it with:  bash update.sh --migrate-data")
        return legacy
    return p


DB_PATH = _db_file(DB_PATH)
REPLAY_DB_PATH = _db_file(REPLAY_DB_PATH)

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
_wspr_live_down       = False  # True when wspr.live queries are failing

# Solar data cache (refreshed on demand, TTL = 60 s)
_solar_cache      = {}
_solar_cache_time = None
_SOLAR_TTL        = 60     # seconds
_cached_fof2      = None   # Latest foF2 value from GIRO (MHz)


# ---------------------------------------------------------------------------
# Helper: Maidenhead → lat/lon
# ---------------------------------------------------------------------------

_LOCATOR6 = re.compile(r"[A-R]{2}[0-9]{2}[A-X]{2}")


def maidenhead_to_latlon(grid: str):
    """Centre of a six-character Maidenhead subsquare; (None, None) for anything that is not a valid
    locator (field letters A-R, digits, subsquare letters A-X), so a garbled locator never becomes a fix."""
    g = (grid or "")[:6].upper()
    if not _LOCATOR6.fullmatch(g):
        return None, None
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
    global _wspr_live_down
    url = "https://db1.wspr.live/?query=" + urllib.parse.quote_plus(sql + " FORMAT JSON")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))["data"]
        return result
    except Exception as e:
        print(f"[WSPR.live] Query failed: {e}")
        _wspr_live_down = True
        return None


def check_wsprlive_health():
    """Run a global recent-spot count against wspr.live to verify the DB is alive.
    Sets _wspr_live_down True when the DB is unreachable OR returning no data at all.
    This is the authoritative source for the flag — called once per poll cycle.
    """
    global _wspr_live_down
    rows = wsprlive_query(
        "SELECT count() AS cnt FROM wspr.rx WHERE time > subtractMinutes(now(), 5)"
    )
    if rows is None:
        # Exception path — _wspr_live_down already set True by wsprlive_query
        print("[WSPR.live] Health check: unreachable")
        return
    cnt = int(rows[0].get("cnt", 0)) if rows else 0
    _wspr_live_down = (cnt == 0)
    if _wspr_live_down:
        print("[WSPR.live] Health check: DB alive but returning no recent data")
    else:
        print(f"[WSPR.live] Health check OK — {cnt} spots in last 5 min globally")

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


# ---------------------------------------------------------------------------
# Grid-based geographic lookup (used for non-standard callsigns)
# ---------------------------------------------------------------------------

# Ordered list of geographic bounding boxes: (name, lon_min, lon_max, lat_min, lat_max).
# More specific regions are listed before broader ones so the first match wins.
_GEO_BOXES = [
    ("UK/Ireland",        -11,   2,   49,  62),
    ("Iceland",           -25, -13,   62,  67),
    ("Faroe Islands",      -8,  -6,   61,  63),
    ("Azores",            -32, -25,   36,  40),
    ("Canary Islands",    -18, -13,   27,  30),
    ("Scandinavia",         4,  32,   55,  72),
    ("Finland",            20,  32,   59,  70),
    ("W. Europe",         -10,  15,   36,  55),
    ("C. Europe",           6,  20,   46,  56),
    ("E. Europe",          14,  40,   44,  60),
    ("Russia",             28, 180,   50,  78),
    ("Japan",             129, 146,   30,  46),
    ("Australia",         112, 155,  -44, -10),
    ("New Zealand",       165, 180,  -47, -34),
    ("Hawaii",           -163,-154,   18,  23),
    ("Alaska",           -170,-130,   54,  72),
    ("W. USA",           -130, -100,  31,  50),
    ("C. USA",           -100,  -81,  29,  50),
    ("E. USA",            -82,  -65,  24,  47),
    ("Canada",           -145,  -52,  45,  72),
    ("Caribbean",         -90,  -60,  10,  26),
    ("Mexico",           -120,  -86,  14,  33),
    ("N. Africa",         -18,   55,  14,  38),
    ("S. Africa",          12,   40, -35, -10),
    ("Middle East",        25,   65,  14,  42),
    ("India",              68,   97,   6,  37),
    ("SE Asia",            95,  135,  -5,  28),
    ("China",              73,  135,  18,  54),
    ("N. America",       -170,  -34,   5,  85),
    ("S. America",        -85,  -34, -60,  15),
    ("Europe",            -25,   45,  35,  72),
    ("Africa",            -20,   55, -35,  38),
    ("Asia",               25,  180,   5,  78),
]


def _grid_to_latlon(grid: str) -> tuple:
    """Convert a Maidenhead grid square to approximate (lat, lon) centre."""
    if not grid or len(grid) < 2:
        return None, None
    g = grid.upper()
    try:
        lon = (ord(g[0]) - ord('A')) * 20 - 180
        lat = (ord(g[1]) - ord('A')) * 10 - 90
        if len(g) >= 4 and g[2].isdigit() and g[3].isdigit():
            lon += int(g[2]) * 2 + 1   # centre of 2°×1° subsquare
            lat += int(g[3]) + 0.5
        else:
            lon += 10   # centre of 20°×10° field
            lat += 5
        return lat, lon
    except Exception:
        return None, None


def _latlon_to_region(lat: float, lon: float) -> str:
    """Return the most specific named region for the given coordinates."""
    for name, lon_min, lon_max, lat_min, lat_max in _GEO_BOXES:
        if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
            return name
    return "Unknown"


# Known placeholder / invalid callsigns that should be located by grid
# rather than prefix (they look like real calls but are not).
_FAKE_CALLSIGNS = {
    "N0CALL", "NOCALL", "N0ONE", "UNKNWN", "INVALID",
}

# Continent/zone for each country in _COUNTRY_MAP.
# Countries that genuinely span multiple zones (Russia, Turkey, Kazakhstan)
# are set to None to skip the cross-check and avoid false positives.
_COUNTRY_ZONE = {
    # North America
    'USA':'n_america',       'Canada':'n_america',    'Mexico':'n_america',
    'Alaska':'n_america',    'Hawaii':'pacific',       'Puerto Rico':'n_america',
    'US Virgin Is.':'n_america', 'N. Mariana Is.':'pacific',
    'Costa Rica':'n_america','Dom. Rep.':'n_america',  'Cuba':'n_america',
    'Trinidad':'n_america',  'Barbados':'n_america',
    # South America
    'Brazil':'s_america',    'Argentina':'s_america',  'Chile':'s_america',
    'Colombia':'s_america',  'Peru':'s_america',       'Bolivia':'s_america',
    'Uruguay':'s_america',   'Paraguay':'s_america',   'Ecuador':'s_america',
    'Venezuela':'s_america',
    # Europe
    'Finland':'europe',      'Sweden':'europe',        'Norway':'europe',
    'Denmark':'europe',      'Faroe Is.':'europe',     'Iceland':'europe',
    'Greenland':'n_america',
    'UK':'europe',           'Scotland':'europe',      'Wales':'europe',
    'N. Ireland':'europe',   'Isle of Man':'europe',   'Jersey':'europe',
    'Guernsey':'europe',     'Ireland':'europe',
    'Germany':'europe',      'France':'europe',        'Netherlands':'europe',
    'Belgium':'europe',      'Switzerland':'europe',   'Austria':'europe',
    'Luxembourg':'europe',   'Liechtenstein':'europe',
    'Italy':'europe',        'Spain':'europe',         'Portugal':'europe',
    'Canary Is.':'africa',   'Ceuta/Melilla':'africa',
    'Croatia':'europe',      'Slovenia':'europe',      'Serbia':'europe',
    'Bosnia':'europe',       'N. Macedonia':'europe',  'Montenegro':'europe',
    'Albania':'europe',      'Kosovo':'europe',
    'Poland':'europe',       'Czechia':'europe',       'Slovakia':'europe',
    'Hungary':'europe',      'Romania':'europe',       'Bulgaria':'europe',
    'Greece':'europe',       'Moldova':'europe',
    'Estonia':'europe',      'Latvia':'europe',        'Lithuania':'europe',
    'Belarus':'europe',      'Ukraine':'europe',       'Cyprus':'europe',
    'Turkey':None,           # straddles Europe/Asia
    'Russia':None,           # spans Europe and Asia
    # Asia / Pacific
    'Japan':'asia',          'China':'asia',           'S. Korea':'asia',
    'Taiwan':'asia',         'Australia':'pacific',    'New Zealand':'pacific',
    'India':'asia',          'Thailand':'asia',        'Vietnam':'asia',
    'Indonesia':'asia',      'Philippines':'asia',     'Malaysia':'asia',
    'Singapore':'asia',      'Hong Kong':'asia',       'Mongolia':'asia',
    'Nepal':'asia',          'Bangladesh':'asia',      'Pakistan':'asia',
    'Sri Lanka':'asia',      'Cambodia':'asia',        'Laos':'asia',
    'Kazakhstan':None,       'Kyrgyzstan':'asia',      'Tajikistan':'asia',
    'Turkmenistan':'asia',   'Uzbekistan':'asia',
    'Azerbaijan':'asia',     'Georgia':'asia',         'Armenia':'asia',
    'Israel':'asia',         'Oman':'asia',            'UAE':'asia',
    'Qatar':'asia',          'Bahrain':'asia',         'Kuwait':'asia',
    'Saudi Arabia':'asia',   'Syria':'asia',           'Lebanon':'asia',
    'Iraq':'asia',           'Iran':'asia',
    # Africa
    'S. Africa':'africa',    'Morocco':'africa',       'Algeria':'africa',
    'Tunisia':'africa',      'Libya':'africa',         'Egypt':'africa',
    'Sudan':'africa',        'Kenya':'africa',         'Tanzania':'africa',
    'Zambia':'africa',       'Zimbabwe':'africa',      'Malawi':'africa',
    'Namibia':'africa',      'Botswana':'africa',      'Rwanda':'africa',
    'Burundi':'africa',      'Madagascar':'africa',    'Mali':'africa',
    'Nigeria':'africa',      'Guinea':'africa',        'Senegal':'africa',
    'C. African Rep.':'africa','Gabon':'africa',       'Cameroon':'africa',
    'DR Congo':'africa',     'Eswatini':'africa',
}

# Zone for each region name returned by _latlon_to_region().
_REGION_ZONE = {
    'UK/Ireland':'europe',   'Iceland':'europe',       'Faroe Islands':'europe',
    'Azores':'europe',       'Canary Islands':'africa',
    'Scandinavia':'europe',  'Finland':'europe',
    'W. Europe':'europe',    'C. Europe':'europe',     'E. Europe':'europe',
    'Russia':'europe',
    'Japan':'asia',          'Australia':'pacific',    'New Zealand':'pacific',
    'Hawaii':'pacific',      'Alaska':'n_america',
    'W. USA':'n_america',    'C. USA':'n_america',     'E. USA':'n_america',
    'Canada':'n_america',    'Caribbean':'n_america',  'Mexico':'n_america',
    'N. Africa':'africa',    'S. Africa':'africa',
    'Middle East':'asia',    'India':'asia',            'SE Asia':'asia',
    'China':'asia',
    'N. America':'n_america','S. America':'s_america',
    'Europe':'europe',       'Africa':'africa',         'Asia':'asia',
}

def callsign_to_country(sign: str, grid: str = "") -> str:
    """Return a country/region name for a given callsign.

    Non-standard callsigns (those containing no digit), known placeholder
    callsigns, and callsigns whose prefix country is geographically
    incompatible with their grid locator all fall back to grid-based lookup.
    """
    base = sign.upper().strip().split('/')[0]   # strip /P /M suffixes
    # Validate: real amateur callsigns always contain at least one digit,
    # and must not be a known placeholder.
    if not any(c.isdigit() for c in base) or base in _FAKE_CALLSIGNS:
        lat, lon = _grid_to_latlon(grid)
        if lat is not None:
            return _latlon_to_region(lat, lon)
        return "Special Station"
    for length in (3, 2, 1):
        if len(base) >= length:
            country = _COUNTRY_MAP.get(base[:length])
            if country:
                # Cross-check: verify the country zone matches the grid zone.
                # Skip check when either zone is undefined (large/spanning countries).
                if grid:
                    lat, lon = _grid_to_latlon(grid)
                    if lat is not None:
                        grid_region  = _latlon_to_region(lat, lon)
                        grid_zone    = _REGION_ZONE.get(grid_region)
                        country_zone = _COUNTRY_ZONE.get(country)
                        if (grid_zone and country_zone
                                and grid_zone != country_zone):
                            return grid_region  # mismatch — trust the grid
                return country
    return base[:2] if len(base) >= 2 else base  # fallback: show prefix


def countries_of(reporters: list) -> list:
    """
    [{country, count}, …] of the stations in a reporter list (fetch_reporter_list(), one entry per
    callsign and grid heard in the past 60 minutes), sorted by count descending.  Worked out here
    instead of with a second wspr.live query: the list holds exactly the same (callsign, grid) pairs.
    """
    counts: dict = {}
    for r in reporters:
        country = callsign_to_country(r.get("callsign") or "??", r.get("grid") or "")
        counts[country] = counts.get(country, 0) + 1

    return sorted(
        [{"country": c, "count": n} for c, n in counts.items()],
        key=lambda x: -x["count"]
    )


_BAND_LABELS_SHORT = {
    3:'80m', 7:'40m', 10:'30m', 14:'20m',
    18:'17m', 21:'15m', 24:'12m', 28:'10m',
}

# Bands the API accepts: the WSPR bands above plus the configured one.  Anything else is a 400, so a
# crafted ?band= can neither fail inside SQLite nor create new cache entries.
ALLOWED_BANDS = frozenset(_BAND_LABELS_SHORT) | {DEFAULT_BAND}


def _band_arg() -> int:
    """The ?band= query parameter (default: the configured band); 400 when it is not a known band."""
    band = request.args.get('band', DEFAULT_BAND, type=int)
    if band not in ALLOWED_BANDS:
        abort(make_response(jsonify({"error": "unknown band"}), 400))
    return band


def _cache_put(cache: dict, key, value, limit: int = 16) -> None:
    """Store a cache entry; the oldest entries are dropped beyond `limit` so a cache cannot grow without bound."""
    cache[key] = value
    while len(cache) > limit:
        cache.pop(min(cache, key=lambda k: cache[k][0]))


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


def fetch_muf_fallback() -> float | None:
    """
    Fallback MUF source: scrape the current MUF(D=3000 km) from the
    Juliusruh ionosonde page.  Used automatically when GIRO DIDBase is
    unavailable.  Lower resolution than GIRO (~hourly update) but stable.
    """
    url = "https://www.ionosonde.iap-kborn.de/actuellz.htm"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        m = re.search(
            r'<td>\s*3000\s*</td>\s*<td>\s*(\d{1,2}\.?\d*)\s*</td>',
            html, re.IGNORECASE
        )
        if m:
            val = float(m.group(1))
            if 1.0 < val < 50.0:
                print(f"[MUF-fallback] {val} MHz (from Juliusruh HTML page)")
                return val
        print("[MUF-fallback] Could not parse MUF from page")
        return None
    except Exception as e:
        print(f"[MUF-fallback] Fetch failed: {e}")
        return None


def fetch_giro_mufd() -> float | None:
    """
    Fetch the latest MUF(D=3000 km) from Juliusruh (JR055) via GIRO DIDBase.
    If GIRO is unavailable or returns no valid data, automatically falls back
    to scraping the Juliusruh ionosonde HTML page.
    Returns MUF in MHz, or None if both sources fail.
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
            return val
        print("[GIRO] MUFD: no valid data — trying fallback")
    except Exception as e:
        print(f"[GIRO] MUFD fetch failed: {e} — trying fallback")
    return fetch_muf_fallback()


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


def _parse_juliusruh_fof2(html: str) -> float | None:
    """
    Parse the latest autoscaled foF2 (MHz) from the Juliusruh Space Weather
    Monitor page.  The "ION" row reads: yesterday's foF2 vs. prediction (%),
    latest foF2 (MHz), latest vs. prediction (%), quality letter, e.g.
        ION | 100% | 9.8 | 113% | F
    The HTML is reduced to plain text first so the match does not depend on the
    exact table markup.  Returns None when the row is missing or has no value.
    """
    text = re.sub(r'<[^>]+>', ' ', html)
    text = unescape(text).replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text)
    m = re.search(r'\bION\b[\s|]*\d+\s*%[\s|]*(\d{1,2}\.\d+)[\s|]*\d+\s*%', text)
    if m:
        val = float(m.group(1))
        if 0.5 < val < 20.0:
            return val
    return None


def fetch_fof2_juliusruh() -> float | None:
    """foF2 from the Juliusruh Space Weather Monitor page (updated every 15 min)."""
    url = "https://www.ionosonde.iap-kborn.de/actuellz.htm"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        val = _parse_juliusruh_fof2(html)
        if val is not None:
            print(f"[foF2] {val:.1f} MHz (Juliusruh monitor page)")
        else:
            print("[foF2] Juliusruh page: no foF2 value found")
        return val
    except Exception as e:
        print(f"[foF2] Juliusruh page fetch failed: {e}")
        return None


def fetch_fof2() -> float | None:
    """
    Latest foF2 in MHz.  The Juliusruh monitor page is tried first because it
    answers reliably; GIRO DIDBase (which often returns nothing) is only the
    second choice.  Returns None if both fail.
    """
    val = fetch_fof2_juliusruh()
    if val is None:
        val = fetch_giro_fof2()
    return val


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


# How far back each poll looks for transmission slots.  Distant reporters
# (USA, Asia, Pacific) upload to wspr.live minutes after the nearby ones, so
# one poll 6 minutes after a slot sees only part of its final reporter list.
# Re-reading the last few slots on every poll (still ONE query) lets later
# polls complete the earlier slots; db.insert_spot() keeps the maximum values.
SPOT_LOOKBACK_MIN = 45
SPOT_LOOKBACK_ROWS = 5


def fetch_recent_spots(callsign: str, band: int) -> list:
    """
    Fetch the most recent WSPR transmission slots (newest first) for
    callsign/band from the last SPOT_LOOKBACK_MIN minutes.
    Each row is {tx_loc, time, reporter_count, max_distance}; groups by
    (tx_loc, time) so each unique TX is one row with aggregated stats.
    """
    sql = f"""
        SELECT
            tx_loc,
            time,
            count()       AS reporter_count,
            max(distance) AS max_distance
        FROM wspr.rx
        WHERE time > subtractMinutes(now(), {SPOT_LOOKBACK_MIN})
          AND tx_sign = '{callsign}'
          AND band    = {band}
        GROUP BY tx_loc, time
        ORDER BY time DESC
        LIMIT {SPOT_LOOKBACK_ROWS}
    """
    return wsprlive_query(sql) or []


def store_spots(rows: list) -> int:
    """
    Store/refresh every valid TX slot in rows.  New slots are inserted;
    existing slots are raised to the larger reporter_count / max_distance.
    Returns the number of slots that were added or improved.
    """
    changed = 0
    for row in rows:
        timestamp_str = row.get("time", "")
        try:
            ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print(f"[WARN] Unparseable timestamp: {timestamp_str}")
            continue
        # Only accept WSPR cycle timestamps (minute ends in :02, :12, :22, ...)
        if ts.minute % 10 != 2:
            continue
        tx_loc = row.get("tx_loc", "")
        lat, lon = maidenhead_to_latlon(tx_loc)
        if lat is None:
            print(f"[WARN] Could not convert locator: {tx_loc}")
            continue
        reporter_count = int(row.get("reporter_count") or 0)
        max_distance   = int(row.get("max_distance")   or 0)

        old = db.get_spot_at(timestamp_str)
        if not db.insert_spot(timestamp_str, tx_loc, lat, lon, DEFAULT_BAND,
                              reporter_count, max_distance):
            continue
        if old is None:
            changed += 1
            print(f"[INFO] Logged: {tx_loc} @ {timestamp_str}  reporters={reporter_count}  max_dx={max_distance} km")
        elif (max_distance > old["max_distance"]
              or reporter_count > old["reporter_count"]):
            changed += 1
            print(f"[INFO] Updated: {timestamp_str}  reporters {old['reporter_count']}->"
                  f"{max(reporter_count, old['reporter_count'])}  max_dx {old['max_distance']}->"
                  f"{max(max_distance, old['max_distance'])} km")
    return changed


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

def _asset_version() -> int:
    """Newest modification time of the files in static/: part of their URLs, so a browser
    fetches the new CSS / JavaScript after an update instead of using its cached copy."""
    newest = 0
    for root, _dirs, files in os.walk(os.path.join(_script_dir, "static")):
        for f in files:
            try:
                newest = max(newest, int(os.path.getmtime(os.path.join(root, f))))
            except OSError:
                pass
    return newest


@app.route('/')
def index():
    return render_template(
        'index.html',
        asset_v=_asset_version(),
        callsign=CALLSIGN,
        default_band=DEFAULT_BAND,
        map_lat=MAP_DEFAULT_LAT,
        map_lon=MAP_DEFAULT_LON,
        map_zoom=MAP_DEFAULT_ZOOM,
        carto_api_key=CARTO_API_KEY,
    )


MUF_MAX_AGE = timedelta(hours=3)     # an older MUF reading is not shown as the present one


def _latest_muf() -> float | None:
    """The newest stored Juliusruh MUF, or None when there is none from the last MUF_MAX_AGE
    (GIRO and the Juliusruh page both stalled): a stale value must not look like the present one."""
    rows = db.get_muf_last_24h(1)
    if not rows:
        return None
    try:
        if datetime.utcnow() - datetime.strptime(rows[-1]["timestamp"], "%Y-%m-%d %H:%M:%S") > MUF_MAX_AGE:
            return None
    except ValueError:
        return None
    return rows[-1]["muf"]


@app.route('/api/latest')
def api_latest():
    """Latest spot, cached reporter countries, the number of current reporters beyond 6000 km
    (for the "& DX" mark of the Propagation card) and the present MUF (for "HIGH MUF")."""
    band = _band_arg()
    spot = db.get_latest_spot(band)
    with _state_lock:
        countries = list(_cached_countries)
        dx6 = sum(1 for r in _cached_reporter_list if (r.get("distance") or 0) > 6000)
    wspr_down = _wspr_live_down
    spot_out = None
    if spot:
        spot_out = {
            "timestamp":      spot["timestamp"],
            "tx_loc":         spot["tx_loc"],
            "lat":            spot["lat"],
            "lon":            spot["lon"],
            "band":           spot["band"],
            "reporter_count": spot["reporter_count"],
            "max_distance":   spot["max_distance"],
        }
    return jsonify({"spot": spot_out, "countries": countries, "wspr_down": wspr_down,
                    "dx6": dx6, "muf": _latest_muf()})


@app.route('/api/positions')
def api_positions():
    """Spot positions for map trail and history view.

    Query params:
      date=YYYY-MM-DD          – all spots for that day
      from=YYYY-MM-DD HH:MM:SS – range start (used with to=)
      to=YYYY-MM-DD HH:MM:SS   – range end
      band=<int>               – band filter (default: DEFAULT_BAND)
    """
    band     = _band_arg()
    date_str = request.args.get('date')
    from_dt  = request.args.get('from')
    to_dt    = request.args.get('to')
    if from_dt and to_dt:
        rows = db.get_spots_range(from_dt, to_dt, band)
    elif date_str:
        rows = db.get_spots_by_date(date_str, band)
    else:
        rows = db.get_spots_by_date(datetime.utcnow().strftime("%Y-%m-%d"), band)
    return jsonify(rows)


@app.route('/api/reporters')
def api_reporters():
    """Cached reporter countries list."""
    with _state_lock:
        countries = list(_cached_countries)
    return jsonify({"countries": countries})


@app.route('/api/reporter_list')
def api_reporter_list():
    """Cached per-reporter details (callsign, grid, snr, distance)."""
    with _state_lock:
        reporters = list(_cached_reporter_list)
    return jsonify({"reporters": reporters})


@app.route('/api/muf')
def api_muf():
    """MUF history + reporter-count overlay for chart."""
    days = request.args.get('days', 1, type=int)
    band = _band_arg()
    muf_rows  = db.get_muf_last_24h(days)
    spot_rows = db.get_spots_last_24h(band, days)
    return jsonify({"muf": muf_rows, "spots": spot_rows})


@app.route('/api/solar')
def api_solar():
    """Solar indices + foF2 + latest MUF."""
    solar = fetch_solar_data()
    with _state_lock:
        fof2 = _cached_fof2
    result      = dict(solar)
    result["fof2"] = fof2
    result["muf"]  = _latest_muf()          # None (shown as —) when the newest reading is over 3 h old
    return jsonify(result)


def _tidy_solar(s: dict | None) -> dict | None:
    """Replay solar rows hold floats; show whole numbers without '.0'."""
    if not s:
        return None
    out = dict(s)
    for k in ("sfi", "kindex", "aindex", "solarwind", "aurora"):
        v = out.get(k)
        if isinstance(v, float) and v.is_integer():
            out[k] = int(v)
    return out


@app.route('/api/replay/dates')
def api_replay_dates():
    """UTC dates that have replay snapshots (newest first)."""
    band = _band_arg()
    return jsonify({
        "enabled": replay_db.is_enabled(),
        "dates":   replay_db.get_available_dates(band),
    })


@app.route('/api/replay/day')
def api_replay_day():
    """All replay frames of one UTC day for the history player.

    Query params: date=YYYY-MM-DD (required), band=<int>.
    Frame: {ts, r: [[callsign, grid, snr, dist], ...],
            c: [{country, count}, ...], s: {solar indices} | null}
    """
    date_str = request.args.get('date', '')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_str):
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400
    band   = _band_arg()
    frames = []
    for f in replay_db.get_day_frames(date_str, band):
        counts: dict = {}
        for call, grid, _snr, _dist in f["reporters"]:
            c = callsign_to_country(call or "??", grid or "")
            counts[c] = counts.get(c, 0) + 1
        frames.append({
            "ts": f["ts"],
            "r":  [list(x) for x in f["reporters"]],
            "c":  sorted(({"country": c, "count": n} for c, n in counts.items()),
                         key=lambda x: -x["count"]),
            "s":  _tidy_solar(f["solar"]),
        })
    return jsonify({"date": date_str, "frames": frames})


@app.route('/api/whatsnew')
def api_whatsnew():
    """Version label and the newest notes, read from doc/whats_new.md."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doc", "whats_new.md")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    return jsonify(changelog.whats_new(text, limit=10))


@app.route('/api/wprs/days')
def api_wprs_days():
    """Home square and one movement summary per logged UTC day (newest first)."""
    band = _band_arg()
    spots = db.get_all_spots(band)
    home = wprs.home_of(spots)
    return jsonify({"home": home, "days": wprs.summarize_days(spots, home), "trips": wprs.build_trips(spots, home)})


@app.route('/api/wprs/track')
def api_wprs_track():
    """Position track for a range of UTC days: ?from=YYYY-MM-DD&to=YYYY-MM-DD (inclusive, max 7 days)."""
    band = _band_arg()
    d_from = request.args.get('from', '')
    d_to = request.args.get('to', d_from)
    try:
        a = datetime.strptime(d_from, "%Y-%m-%d")
        b = datetime.strptime(d_to, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "from/to must be YYYY-MM-DD"}), 400
    if b < a or (b - a).days > 6:
        return jsonify({"error": "range must be 1 to 7 days"}), 400
    home = wprs.home_of(db.get_all_spots(band))
    rows = db.get_spots_range(a.strftime("%Y-%m-%d 00:00:00"), b.strftime("%Y-%m-%d 23:59:59"), band)
    return jsonify(wprs.build_track(rows, home))


DOC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doc")


@app.route('/api/guides')
def api_guides():
    """The PDF documents in doc/ (titles and descriptions from doc/guides.json)."""
    return jsonify({"guides": guides.list_guides(DOC_DIR)})


@app.route('/doc/<name>')
def serve_doc(name):
    """Serve one PDF from doc/ (plain *.pdf file names only)."""
    if not guides.is_safe_name(name):
        abort(404)
    return send_from_directory(DOC_DIR, name, mimetype='application/pdf')


_analysis_cache: dict = {}          # (days, band) -> (monotonic time, payload)
_ANALYSIS_TTL = 600                 # seconds
_ANALYSIS_DAYS = (30, 90, 180, 365) # periods of the Analysis page buttons (30 d, 90 d, 6 m, 1 yr); other ?days= values round up to one of them

# Reporters whose reported distance contradicts their own grid (a wrong grid or a decoding error)
# would otherwise show up as the farthest "reporter" or as a long-distance window.
OUTLIER_TOL_KM = 500
_outlier_cache: dict = {}           # band -> (monotonic time, [outlier dicts])
_OUTLIER_TTL = 3600                 # seconds; the scan reads every reporter once, so it is cached longer


def find_outliers(band: int) -> list:
    """(callsign, grid) pairs whose distances differ by more than OUTLIER_TOL_KM from the
    distance computed from the grid (4 or more characters) to the home square.  The tolerance
    covers the size of a 4-character square and the car's trips from home (up to ~200 km)."""
    hit = _outlier_cache.get(band)
    if hit and time.monotonic() - hit[0] < _OUTLIER_TTL:
        return hit[1]
    out = []
    home = wprs.home_of(db.get_all_spots(band))
    if home:
        for p in replay_db.get_reporter_pairs(band):
            grid = p["grid"] or ""
            if len(grid) < 4:
                continue
            la, lo = _grid_to_latlon(grid)
            if la is None:
                continue
            gd = wprs.hav_km(home["lat"], home["lon"], la, lo)
            d_far = abs(gd - p["dmax"]) >= abs(gd - p["dmin"])
            if max(abs(gd - p["dmax"]), abs(gd - p["dmin"])) > OUTLIER_TOL_KM:
                out.append({"callsign": p["callsign"], "grid": grid, "reports": p["n"],
                            "reported_km": p["dmax"] if d_far else p["dmin"], "grid_km": round(gd)})
    _cache_put(_outlier_cache, band, (time.monotonic(), out))
    return out


def _outlier_keys(outliers: list) -> set:
    return {f"{o['callsign']}|{o['grid']}" for o in outliers}


def _dx_events(dx_rows: list) -> list:
    """(day, hour, region, lat, lon) for DX reports from outside Europe."""
    cache, events = {}, []
    for day, hour, _call, grid, _dist in dx_rows:
        if grid not in cache:
            la, lo = _grid_to_latlon(grid or "")
            zone = _REGION_ZONE.get(_latlon_to_region(la, lo), "other") if la is not None else "other"
            cache[grid] = (zone, la, lo)
        zone, la, lo = cache[grid]
        if zone not in ("other", "europe"):
            events.append((day, hour, zone, la, lo))
    return events


_outlook_cache: dict = {}           # band -> (monotonic time, {"model", "last_k"})


def outlook_state(band: int) -> dict:
    """The DX outlook model, always fitted on the whole history (the Analysis period buttons do not
    change it: more days make the hour-of-day tables and the back-test more reliable)."""
    hit = _outlook_cache.get(band)
    if hit and time.monotonic() - hit[0] < _ANALYSIS_TTL:
        return hit[1]
    excl = _outlier_keys(find_outliers(band))
    rows = replay_db.get_snapshot_rows(0, band, exclude=excl)
    events = _dx_events(replay_db.get_dx_reports(0, band, exclude=excl))
    state = {"model": outlook.fit([(d, h, z) for d, h, z, _la, _lo in events], rows) if rows else None,
             "last_k": next(((r[0], r[4]) for r in reversed(rows) if r[4] is not None), None)}
    _cache_put(_outlook_cache, band, (time.monotonic(), state))
    return state


@app.route('/api/analysis')
def api_analysis():
    """Propagation analysis computed from the replay database.

    Query params: days=<0..365> (0 = whole history, default 90; rounded up to 30, 90, 180 or 365), band=<int>.
    Results are cached for 10 minutes; no wspr.live queries are made.
    """
    days = request.args.get('days', 90, type=int)
    days = 0 if days <= 0 else next((d for d in _ANALYSIS_DAYS if days <= d), _ANALYSIS_DAYS[-1])
    band = _band_arg()
    if not replay_db.is_enabled():
        return jsonify({"enabled": False, "empty": True})
    key = (days, band)
    hit = _analysis_cache.get(key)
    if hit and time.monotonic() - hit[0] < _ANALYSIS_TTL:
        payload = hit[1]
    else:
        outliers = find_outliers(band)
        excl = _outlier_keys(outliers)
        rows = replay_db.get_snapshot_rows(days, band, exclude=excl)
        payload = analysis.build(rows, datetime.utcnow().strftime("%Y-%m-%d"))
        payload["enabled"] = True
        payload["excluded"] = outliers
        if not payload.get("empty"):
            records = replay_db.get_top_distances(days, band, limit=10, exclude=excl)
            for rec in records:
                rec["country"] = callsign_to_country(rec["callsign"] or "??", rec["grid"] or "")
            payload["records"] = records
            events = _dx_events(replay_db.get_dx_reports(days, band, exclude=excl))
            hour_days = {}
            for r in rows:
                hour_days.setdefault(int(r[0][11:13]), set()).add(r[0][:10])
            home = wprs.home_of(db.get_all_spots(band))
            payload["greyline"] = greyline.build(events, hour_days, home)
        _cache_put(_analysis_cache, key, (time.monotonic(), payload))

    out = {k: v for k, v in payload.items() if not k.startswith("_")}      # "right now" is never cached
    if not out.get("empty"):
        muf = _latest_muf()               # None when the newest reading is older than 3 hours
        with _state_lock:
            live_n = len(_cached_reporter_list)
        if live_n == 0 and _wspr_live_down:
            live_n = None                 # no usable live data: do not claim "below usual"
        out["now"] = analysis.expectation(out["expect"], datetime.utcnow().hour, muf, live_n)
        state = outlook_state(band)
        model = state["model"]
        if model:
            out["outlook_model"] = outlook.public(model)
        k_now = None                      # K from the latest snapshot, if it is less than 3 hours old
        last_k = state["last_k"]
        if last_k:
            try:
                if datetime.utcnow() - datetime.strptime(last_k[0], "%Y-%m-%d %H:%M:%S") <= timedelta(hours=3):
                    k_now = float(last_k[1])
            except ValueError:
                pass
        out["outlook"] = outlook.forecast(model, datetime.utcnow(), muf, k_now)
    return jsonify(out)


_iono_cache: dict = {}              # (kind, range, band) -> (monotonic time, payload)
_IONO_BUCKETS = (10, 60, 180, 360, 720, 1440, 2880, 10080)   # minutes; the smallest that gives <= _IONO_MAX_POINTS
_IONO_MAX_POINTS = 500
_EPOCH = datetime(1970, 1, 1)


@app.route('/api/iono')
def api_iono():
    """Stations heard, Juliusruh MUF and foF2 over a period, for the Ionosonde view of the Analysis page.

    Query params: from=YYYY-MM-DD&to=YYYY-MM-DD (UTC days, both included), or days=<n> (rounded up to
    30, 90, 180 or 365 like /api/analysis; 0 = the whole history), band=<int>.
    One day comes back as single snapshots (10 min); longer periods are averaged over buckets of up to
    a week so that there are at most 500 points.  Empty buckets are included (null), so gaps show.
    Cached for 10 minutes.
    """
    band = _band_arg()
    if not replay_db.is_enabled():
        return jsonify({"enabled": False, "points": []})
    now = datetime.utcnow()
    d_from, d_to = request.args.get('from'), request.args.get('to')
    if d_from or d_to:
        try:
            a = datetime.strptime(d_from or d_to, "%Y-%m-%d")
            b = datetime.strptime(d_to or d_from, "%Y-%m-%d") + timedelta(days=1)
        except (ValueError, OverflowError):
            return jsonify({"error": "from/to must be YYYY-MM-DD"}), 400
        if b <= a:
            return jsonify({"error": "to must not be before from"}), 400
        # keep the range within the data (first snapshot .. tomorrow): a range of centuries would
        # otherwise produce tens of thousands of empty points
        first = replay_db.get_first_timestamp(band)
        if first:
            a = max(a, datetime.strptime(first[:10], "%Y-%m-%d"))
        b = min(b, datetime.strptime(now.strftime("%Y-%m-%d"), "%Y-%m-%d") + timedelta(days=1))
        if b <= a:
            return jsonify({"enabled": True, "from": d_from, "to": d_to, "bucket_min": 10, "points": [],
                            "has_muf": False, "has_fof2": False})
        key = ("range", a, b, band)
    else:
        days = request.args.get('days', 30, type=int)
        days = 0 if days <= 0 else next((d for d in _ANALYSIS_DAYS if days <= d), _ANALYSIS_DAYS[-1])
        b = now
        if days:
            a = now - timedelta(days=days)
        else:
            first = replay_db.get_first_timestamp(band)
            a = datetime.strptime(first[:10], "%Y-%m-%d") if first else now - timedelta(days=1)
        key = ("days", days, band)
    hit = _iono_cache.get(key)
    if hit and time.monotonic() - hit[0] < _ANALYSIS_TTL:
        return jsonify(hit[1])

    span_min = (b - a).total_seconds() / 60
    bucket = next((m for m in _IONO_BUCKETS if span_min / m <= _IONO_MAX_POINTS), _IONO_BUCKETS[-1])
    off = 8 if bucket == 10 else 0            # single snapshots: buckets start at the poll minutes :08, :18, ...
    fmt = "%Y-%m-%d %H:%M:%S"
    rows = {r["k"]: r for r in replay_db.get_iono_series(a.strftime(fmt), b.strftime(fmt), band, bucket, off)}
    step, shift = bucket * 60, off * 60
    k0 = -int(-((a - _EPOCH).total_seconds() - shift) // step)      # first bucket that starts at or after `a`
    k1 = int(((b - _EPOCH).total_seconds() - shift - 1) // step)
    def rnd(v):
        return None if v is None else round(v, 1)
    points = []
    for k in range(k0, k1 + 1):
        r = rows.get(k)
        points.append({"t": (_EPOCH + timedelta(seconds=k * step + shift)).strftime("%Y-%m-%d %H:%M"),
                       "n": rnd(r["n"]) if r else None, "muf": rnd(r["muf"]) if r else None,
                       "fof2": rnd(r["fof2"]) if r else None, "snaps": r["snaps"] if r else 0})
    payload = {"enabled": True, "from": a.strftime("%Y-%m-%d"), "to": (b - timedelta(seconds=1)).strftime("%Y-%m-%d"),
               "bucket_min": bucket, "points": points,
               "has_muf": any(p["muf"] is not None for p in points),
               "has_fof2": any(p["fof2"] is not None for p in points)}
    _cache_put(_iono_cache, key, (time.monotonic(), payload))
    return jsonify(payload)


@app.route('/api/stats')
def api_stats():
    """Daily statistics (spot count, max DX, max reporters)."""
    date_str = request.args.get('date', datetime.utcnow().strftime("%Y-%m-%d"))
    band     = _band_arg()
    stats    = db.get_stats_by_date(date_str, band)
    return jsonify({
        "stats":           stats,
        "all_time":        db.get_all_time_stats(),
        "available_dates": db.get_available_dates(band),
    })


@app.route('/api/daily_summary')
def api_daily_summary():
    """Per-day totals (spots, best DX, max reporters) for the Statistics charts."""
    band = _band_arg()
    return jsonify(db.get_daily_summary(band))


# ---------------------------------------------------------------------------
# Background update thread
# ---------------------------------------------------------------------------

def _next_poll_time(now: datetime) -> datetime:
    """The next whole minute after `now` whose minute ends in 8 (:08, :18, ... :58)."""
    t = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while t.minute % 10 != 8:
        t += timedelta(minutes=1)
    return t


def update_thread():
    global _last_update_utc, _update_error, _cached_countries, _cached_reporter_list, _cached_fof2
    print(f"[INFO] Update thread started — tracking {CALLSIGN} on {DEFAULT_BAND} MHz")

    # Populate caches immediately on startup so the UI has data before the
    # first scheduled poll cycle (minutes ending in :08).
    try:
        print("[INFO] Initial fetch on startup...")
        store_spots(fetch_recent_spots(CALLSIGN, DEFAULT_BAND))
        init_reporters = fetch_reporter_list(CALLSIGN, DEFAULT_BAND)
        with _state_lock:
            _cached_countries     = countries_of(init_reporters)
            _cached_reporter_list = init_reporters
        check_wsprlive_health()
        muf_init = fetch_giro_mufd()
        if muf_init:
            db.insert_muf(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), muf_init)
        fof2_init = fetch_fof2()
        with _state_lock:
            _cached_fof2 = fof2_init

        # Store initial snapshot in replay DB
        _ts_init = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        n_rep = replay_db.insert_reporters(_ts_init, init_reporters, DEFAULT_BAND)
        solar_init = fetch_solar_data()
        replay_db.insert_solar(_ts_init, solar_init, fof2_init, muf_init)
        print(f"[INFO] Initial fetch complete — {len(_cached_countries)} countries cached, "
              f"{len(init_reporters)} reporters (stored {n_rep} to replay DB), "
              f"MUF={muf_init} MHz, foF2={fof2_init} MHz")

    except Exception as e:                  # the polling loop below must start whatever went wrong here
        print(f"[ERROR] Initial fetch failed: {e}")

    while True:
        # Act at minute :08, :18, :28, :38, :48, :58
        # (6 minutes after each 10-min WSPR TX cycle boundary so data is settled).
        # Sleep until that minute instead of polling the clock every 60 s: a fixed sleep drifts by the
        # time the work takes and, now and then, steps over the minute, which loses a snapshot.
        time.sleep(max(1.0, (_next_poll_time(datetime.utcnow()) - datetime.utcnow()).total_seconds()))
        now = datetime.utcnow()
        if now.minute % 10 == 8:
            print(f"[INFO] Polling WSPR.live at {now.strftime('%H:%M:%S')} UTC")
            try:
                rows          = fetch_recent_spots(CALLSIGN, DEFAULT_BAND)
                reporter_list = fetch_reporter_list(CALLSIGN, DEFAULT_BAND)
                countries     = countries_of(reporter_list)
                check_wsprlive_health()
                with _state_lock:
                    _cached_countries     = countries
                    _cached_reporter_list = reporter_list

                # MUF: GIRO DIDBase (JR055) with Juliusruh page fallback; foF2: Juliusruh page first, GIRO second
                muf = fetch_giro_mufd()
                if muf:
                    db.insert_muf(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), muf)
                    print(f"[INFO] MUF D=3000: {muf} MHz")
                fof2 = fetch_fof2()
                with _state_lock:
                    _cached_fof2 = fof2   # None when GIRO unavailable

                # Store replay snapshots
                _ts_poll = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                replay_db.insert_reporters(_ts_poll, reporter_list, DEFAULT_BAND)
                solar_poll = fetch_solar_data()
                replay_db.insert_solar(_ts_poll, solar_poll, fof2, muf)

                if rows:
                    if store_spots(rows):
                        with _state_lock:
                            _last_update_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                            _update_error    = None
                else:
                    print("[INFO] No data returned from WSPR.live")
                    with _state_lock:
                        _update_error = "No data from WSPR.live"

            except Exception as e:
                print(f"[ERROR] Poll cycle exception: {e}")
                with _state_lock:
                    _update_error = f"Poll error: {e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.init(DB_PATH)
    replay_db.init(REPLAY_DB_PATH, enabled=REPLAY_ENABLED)
    threading.Thread(target=update_thread, daemon=True).start()
    app.run(debug=DEBUG, host=HOST, port=PORT, use_reloader=False)
