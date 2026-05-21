import json
import time
import urllib.request
import urllib.parse
from datetime import datetime
from flask import Flask, send_from_directory, jsonify
import folium
import threading
import csv
import os

app = Flask(__name__)

positions = []
MAX_POSITIONS = 4320
update_thread_started = False
update_thread_lock = threading.Lock()
logged_timestamps = set()

# Convert Maidenhead to lat/lon (center of 6-digit grid)
def maidenhead_to_latlon(grid):
    if len(grid) != 6:
        return None, None
    grid = grid.upper()
    lon = (ord(grid[0]) - ord('A')) * 20 - 180
    lat = (ord(grid[1]) - ord('A')) * 10 - 90
    lon += (ord(grid[2]) - ord('0')) * 2
    lat += (ord(grid[3]) - ord('0')) * 1
    lon += (ord(grid[4]) - ord('A')) * (2.0 / 24.0)
    lat += (ord(grid[5]) - ord('A')) * (1.0 / 24.0)
    lon += (2.0 / 24.0) / 2
    lat += (1.0 / 24.0) / 2
    return round(lat, 4), round(lon, 4)

# Query WSPR.live
def wsprlive_get(query):
    url = "https://db1.wspr.live/?query=" + urllib.parse.quote_plus(query + " FORMAT JSON")
    try:
        contents = urllib.request.urlopen(url, timeout=10).read()
        return json.loads(contents.decode("UTF-8"))['data']
    except:
        return None

# Log to CSV
def log_to_csv(tx_loc, lat, lon, timestamp):
    date_str = datetime.now().strftime("%d%m%Y")
    filename = f"{date_str}_wspr_location.csv"
    row = [timestamp.strftime("%H:%M"), tx_loc, lat, lon]
    print(f"[DEBUG] Writing to CSV: {filename} → {row}")
    try:
        with open(filename, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(row)
    except Exception as e:
        print(f"[Error] Could not write to CSV: {e}")

# Update positions
def update_positions():
    global update_thread_started
    with update_thread_lock:
        if update_thread_started:
            print("[DEBUG] Update thread already running.")
            return
        update_thread_started = True

    print("[DEBUG] Update thread started.")

    while True:
        now = datetime.utcnow()
        minute = now.minute
        print(f"[DEBUG] Current UTC time: {now.strftime('%H:%M:%S')}")

        if minute % 10 == 8:
            print("[DEBUG] This is a scheduled download minute. Checking WSPR.live...")
            query = """
            SELECT
                tx_loc,
                time
            FROM
                wspr.rx
            WHERE
                time > subtractHours(now(), 1)
                AND tx_sign = 'OH2GAX'
                AND band = 14
            ORDER BY
                time DESC
            LIMIT 1
            """
            data = wsprlive_get(query)

            if data:
                print(f"[DEBUG] Query returned data: {data}")
                tx_loc = data[0]["tx_loc"]
                timestamp_str = data[0]["time"]
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                if timestamp.minute % 10 == 2:
                    lat, lon = maidenhead_to_latlon(tx_loc)
                    if lat is not None and lon is not None:
                        if timestamp_str not in logged_timestamps:
                            print(f"[DEBUG] Accepting locator {tx_loc} at {timestamp_str}, logging and updating map.")
                            positions.append({
                                "tx_loc": tx_loc,
                                "lat": lat,
                                "lon": lon,
                                "time": timestamp_str
                            })
                            log_to_csv(tx_loc, lat, lon, timestamp)
                            logged_timestamps.add(timestamp_str)
                            if len(positions) > MAX_POSITIONS:
                                positions[:] = positions[-MAX_POSITIONS:]
                        else:
                            print(f"[DEBUG] Skipping duplicate entry for {timestamp_str}")
                else:
                    print(f"[DEBUG] Ignored: timestamp minute = {timestamp.minute}, not 02,12,...")
            else:
                print("[DEBUG] Query returned no data.")
        else:
            print("[DEBUG] Not a download minute. Waiting...")

        time.sleep(60)

@app.route('/')
def index():
    if not os.path.exists('templates'):
        os.makedirs('templates')

    if positions:
        latest = positions[-1]
        map_center = [latest["lat"], latest["lon"]]
    else:
        map_center = [0, 0]

    map = folium.Map(location=map_center, zoom_start=11)

    if positions:
        latest = positions[-1]
        folium.Marker(
            location=[latest["lat"], latest["lon"]],
            popup=f"<strong>Station: OH2GAX-9</strong><br>{latest['tx_loc']}<br>{latest['time']}",
            tooltip="OH2GAX-9"
        ).add_to(map)

    map.save("templates/map.html")

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv=\"refresh\" content=\"60\">
        <title>WSPR Map</title>
        <style>
            body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; }
            iframe { width: 100%; height: 100%; border: none; }
        </style>
    </head>
    <body>
        <iframe src=\"/map\"></iframe>
    </body>
    </html>
    """

    with open("templates/index.html", "w") as f:
        f.write(html_content)

    return send_from_directory("templates", "index.html")

@app.route('/map')
def serve_map():
    return send_from_directory("templates", "map.html")

@app.route('/data')
def data():
    return jsonify(list(reversed(positions)))

if __name__ == "__main__":
    threading.Thread(target=update_positions, daemon=True).start()
    app.run(debug=True, host='172.26.1.162', port=5008)
