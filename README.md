# WSPR Logger

A lightweight web-based dashboard for tracking and logging WSPR beacon transmissions in real time. Built with Python/Flask on the backend and a single-page Leaflet.js frontend, it queries [wspr.live](https://wspr.live) every 10 minutes, stores spots in a local SQLite database, and presents live position, history, statistics, propagation conditions, ionospheric MUF data, solar indices, and reporter country breakdowns in the browser.

Originally developed to track a mobile WSPR beacon (callsign **OH2GAX**) operating on the 20 m band from a car, but fully configurable for any callsign and band.

---

## Features

- **Live map** — beacon position shown as a solid colour circle; auto-centres on first spot; zoom level remembered between sessions
- **Age-aware beacon marker** — circle is **green** when the last spot is less than 1 hour old, **red** when older, giving an instant visual indication of whether the beacon is active or the band is closed
- **Stale data indicators** — when the last spot is older than 1 hour the locator text turns red in both the sidebar and map overlay, the Propagation card switches to "No propagation / 0 reporters", helping users quickly assess band conditions
- **Position trail** — dashed polyline connecting today's logged positions on the live map
- **Propagation indicator** — estimates band conditions from the latest reporter count (Very poor → Extremely good) with a colour-coded bar; resets to "No propagation" automatically when data is stale
- **MUF / Reporter count graph** — optional 24-hour dual-axis chart (blue line = Juliusruh ionosonde MUF D=3000 km, green bars = reporter count); data logged every 10 minutes; toggle on/off from sidebar
- **Solar conditions panel** — optional top-left overlay showing SFI, K-index, A-index, X-ray flux, Bz (IMF), and Juliusruh MUF; moves down automatically when the MUF graph is also enabled; refreshes every 60 seconds from hamqsl.com; toggle on/off from sidebar
- **Reporter countries** — optional overlay listing every country that heard the beacon in the past hour, with a proportional bar and station count; loads instantly from backend cache
- **History view** — map and table of all logged spots for any selected date
- **Statistics view** — daily and all-time records (spot count, longest DX, max reporters)
- **1 h / Today stats** — toggle the sidebar mini-stats between the last 60 minutes (default) and the full day
- **Light / Dark theme** — toggle in the sidebar; preference is remembered in the browser
- **Collapsible sidebar** — fold the panel away for a full-screen map view, handy on mobile
- **Config-file driven** — all settings managed in `config.ini`; no settings UI exposed to the browser
- **SQLite storage** — one database file, WAL mode, indexed for fast date-range queries; separate table for MUF history

---

## Screenshots

![WSPR Logger — live map view](https://raw.githubusercontent.com/oh2gax/wspr_logger/main/Main_screen_1_wspr_logger.png)
*Live map (dark mode) with position overlay, propagation card, and reporter countries panel on the right; collapsible info sidebar on the left.*

---

## How It Works

1. A background thread polls **wspr.live** (a public ClickHouse database) at minutes `:08`, `:18`, `:28`, `:38`, `:48`, `:58` — six minutes after each 10-minute WSPR transmission cycle, giving reporters time to upload their data.
2. The query groups all received spots for the latest transmission by `(tx_loc, time)` and returns the Maidenhead locator, UTC timestamp, reporter count, and maximum reported distance.
3. Valid new spots are inserted into the local SQLite database; duplicates are silently ignored.
4. At each poll cycle the backend also fetches the **MUF D=3000 km** value from the [Juliusruh ionosonde](https://www.ionosonde.iap-kborn.de/actuellz.htm) and stores it in the `muf_data` table alongside the timestamp.
5. Reporter country data is derived from individual reporter callsigns, cached in memory, and bundled into every `/api/latest` response — no extra wspr.live queries are ever triggered from the browser.
6. On startup the background thread performs an immediate fetch of the latest spot, reporter countries, and MUF value so the UI has data ready the moment the page is opened.
7. The browser polls `/api/latest` every 60 seconds and updates the map, overlays, and sidebar without a page reload.
8. **Solar conditions** are fetched on demand from [hamqsl.com](https://www.hamqsl.com/solarxml.php) with a 60-second server-side cache; the frontend polls `/api/solar` every 60 seconds when the panel is visible.

---

## Requirements

| Component | Version |
|-----------|---------|
| Python    | 3.9 or newer |
| Flask     | 3.0 or newer |
| SQLite    | bundled with Python |

No other Python packages are required. The frontend loads Leaflet.js and Chart.js from CDN and needs no build step.

---

## Installation on Ubuntu

### 1 — Clone or copy the files

```bash
git clone https://github.com/your-username/wspr_logger.git
cd wspr_logger
```

Or copy the project folder to your preferred location, for example `/opt/wspr_logger`.

### 2 — Install Python dependencies

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

Create a virtual environment (recommended):

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask
```

### 3 — Edit the configuration file

Open `config.ini` and set your callsign, preferred band, and server address:

```ini
[station]
callsign = OH2GAX
default_band = 14        ; MHz — 14 = 20 m

[server]
host = 0.0.0.0           ; listen on all interfaces
port = 5008
debug = false

[database]
path = wspr_data.db      ; relative to the script directory

[map]
default_lat = 60.0
default_lon = 24.0
default_zoom = 6
```

### 4 — Test the server manually

```bash
source venv/bin/activate   # if not already active
python3 wspr_logger.py
```

Open `http://<server-ip>:5008` in a browser. You should see the dashboard. The first spot will appear at the next polling window (minutes ending in 8).

Press `Ctrl+C` to stop.

---

## Running as a Background Service (systemd)

The recommended way to keep the logger running permanently and have it restart automatically after reboots or crashes.

### 1 — Create the service file

```bash
sudo nano /etc/systemd/system/wspr_logger.service
```

Paste the following, adjusting the paths and username to match your setup:

```ini
[Unit]
Description=WSPR Logger — beacon tracking web dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu                          ; change to your Linux username
WorkingDirectory=/opt/wspr_logger    ; change to your installation path
ExecStart=/opt/wspr_logger/venv/bin/python3 wspr_logger.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 2 — Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable wspr_logger
sudo systemctl start wspr_logger
```

### 3 — Check the status

```bash
sudo systemctl status wspr_logger
```

### 4 — View live logs

```bash
sudo journalctl -u wspr_logger -f
```

### 5 — Restart after a config change

```bash
sudo systemctl restart wspr_logger
```

---

## Firewall

If the server has `ufw` enabled, allow the port:

```bash
sudo ufw allow 5008/tcp
```

---

## Frontend User Guide

### Sidebar

| Element | Description |
|---------|-------------|
| **◀ / ▶ button** | Collapse or expand the sidebar to give the map more space |
| **Status dot** | Green = live data (< 20 min old) · Amber = stale · Red = no recent data |
| **Locator** | Current 6-character Maidenhead grid square; turns red when last spot is older than 1 hour |
| **Latitude / Longitude** | Decimal coordinates derived from the locator |
| **Reporters / Max DX** | How many stations received the last transmission and the farthest one |
| **Last Spot (UTC)** | Timestamp of the most recent logged transmission |
| **Band** | Static display of the active band as configured in `config.ini` |
| **Position Trail** | Toggle the dashed trail connecting today's positions on the live map |
| **Reporter Countries** | Toggle the country breakdown overlay on the live map |
| **MUF / Reports Graph** | Toggle the 24-hour MUF and reporter count chart at the top of the map |
| **Solar Conditions** | Toggle the solar indices panel at the bottom-left of the map |
| **1h / Today tabs** | Switch the mini-stats cards between the last 60 minutes (default) and the full day |
| **🌙 / ☀️ Dark / Light Mode** | Toggle the colour theme; saved across sessions |

### Live Map

The main view opens by default. The beacon position is shown as a **solid circle** — **green** when the last spot is less than 1 hour old, **red** when older. The map auto-pans to the beacon on first load. A **dashed polyline** shows today's path. Click the circle to see a popup with full spot details.

Up to **five overlay elements** can be shown simultaneously:

**Current Position** (top-right) — locator (red when stale), timestamp, reporter count, max DX, and band.

**Propagation** (top-right, below position) — estimated band condition with a colour-coded label and fill bar:

| Reporters | Condition |
|-----------|-----------|
| ≤ 5       | Very poor |
| ≤ 10      | Poor |
| ≤ 20      | Normal |
| ≤ 40      | Good |
| ≤ 60      | Very good |
| > 60      | Extremely good |

When the last spot is older than 1 hour the card shows **No propagation** with a red bar and 0 reporters, regardless of the last recorded value.

**Reporter Countries** (top-right, below propagation) *(optional)* — unique countries from the past 60 minutes, sorted by station count, with proportional bars. Loads instantly from the backend cache; refreshes every 10 minutes with the poll cycle.

**MUF / Reports Graph** (top of map, spanning full width) *(optional)* — 24-hour dual-axis Chart.js chart. The **blue line** shows the Juliusruh ionosonde MUF D=3000 km (left axis, MHz); the **green bars** show reporter count per transmission (right axis). Both datasets are logged every 10 minutes and stored in the database. Useful for correlating band openings with ionospheric conditions.

**Solar Conditions** (top-left, below the MUF graph when that is also enabled) *(optional)* — compact panel showing current solar and geomagnetic indices:

| Field | Description |
|-------|-------------|
| SFI   | Solar Flux Index |
| K     | K-index (geomagnetic activity, 0–9) |
| A     | A-index (daily geomagnetic activity) |
| X-ray | X-ray flux class (e.g. B9.3, C2.1) |
| Bz    | Interplanetary magnetic field Z-component (nT) |
| J-MUF | Juliusruh ionosonde MUF D=3000 km (MHz) |

Data sourced from [hamqsl.com](https://www.hamqsl.com/solarxml.php), refreshed every 60 seconds while the panel is visible.

### History View

Select a date using the date picker or the **Today / Yesterday / −7 days** quick buttons. The map plots the full day's trail (green = first spot, blue = last spot, grey = intermediate), and the table on the right lists every transmission with time, locator, reporter count, and max DX.

### Statistics View

Shows aggregated data for the selected date (total spots, max reporters, longest DX, first/last spot time) alongside **all-time records**. A list of all dates with logged data appears at the bottom as clickable chips.

### Configuration

All settings are managed directly in `config.ini` on the server — there is no settings UI in the browser. This keeps the public-facing interface read-only. Edit the file and restart the service to apply any changes:

```ini
[station]
callsign = OH2GAX
default_band = 14        ; MHz — 3/7/10/14/18/21/24/28

[server]
host = 0.0.0.0
port = 5008
debug = false

[database]
path = wspr_data.db

[map]
default_lat = 60.0
default_lon = 24.0
default_zoom = 6
```

---

## Project Structure

```
wspr_logger/
├── config.ini          — station, server, map, and database settings
├── wspr_logger.py      — Flask app, background polling thread, REST API
├── db.py               — SQLite read/write layer
├── requirements.txt    — Python dependencies (flask)
├── wspr_data.db        — SQLite database (created automatically on first run)
└── templates/
    └── index.html      — single-page frontend (Leaflet.js, Chart.js, vanilla JS)
```

---

## REST API

| Endpoint | Method | Parameters | Description |
|----------|--------|------------|-------------|
| `/api/latest` | GET | `band` | Most recent spot, server status, and cached reporter countries |
| `/api/positions` | GET | `date`, or `from`+`to`, `band` | List of spots for a date or time range |
| `/api/stats` | GET | `date`, `band` | Aggregated stats for a date plus all-time records |
| `/api/reporters` | GET | — | Cached reporter countries from the past 60 minutes |
| `/api/muf` | GET | `band` | MUF D=3000 km readings and reporter counts for the last 24 hours |
| `/api/solar` | GET | — | Current solar indices (SFI, K, A, X-ray, Bz, J-MUF); cached 60 s |

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

Free to use, modify, and distribute. Attribution appreciated but not required.
