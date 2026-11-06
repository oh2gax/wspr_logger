"""WPRS (Whisper Position Reporting System) helpers.

Every logged WSPR transmission carries the Maidenhead locator the transmitter
computed from its GPS fix, so the spots table is a position track of the car.
This module turns those spots into

  * a list of days with their movement (the "drive detector"), and
  * the track of one or more days (fixes, visited squares, distances).

Pure functions on lists of dicts (timestamp, tx_loc, lat, lon, reporter_count,
max_distance); no database or Flask here, so it is easy to test.
"""
import math
from collections import Counter

EARTH_KM = 6371.0


def hav_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def square_half_size(loc):
    """Half height / half width in degrees of a Maidenhead square (4 or 6 characters)."""
    if len(loc or "") >= 6:
        return 1.25 / 60, 2.5 / 60          # subsquare 2.5' x 5'
    return 0.5, 1.0                         # square 1 deg x 2 deg


def home_of(spots):
    """The most frequently reported locator, taken as the home position."""
    if not spots:
        return None
    loc, _ = Counter(s["tx_loc"] for s in spots).most_common(1)[0]
    for s in spots:
        if s["tx_loc"] == loc:
            return {"loc": loc, "lat": s["lat"], "lon": s["lon"]}
    return None


def _spread_km(points):
    """Largest distance between any two of the given (lat, lon) points."""
    best = 0.0
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = hav_km(points[i][0], points[i][1], points[j][0], points[j][1])
            if d > best:
                best = d
    return best


def _path_km(spots):
    return sum(hav_km(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(spots, spots[1:]))


def _stats(spots, home):
    squares = {}
    for s in spots:
        squares[s["tx_loc"]] = (s["lat"], s["lon"])
    pts = list(squares.values())
    home_km = max((hav_km(home["lat"], home["lon"], la, lo) for la, lo in pts), default=0.0) if home else 0.0
    return {
        "fixes": len(spots),
        "squares": len(squares),
        "spread_km": round(_spread_km(pts), 1),
        "path_km": round(_path_km(spots), 1),
        "home_km": round(home_km, 1),
    }


def summarize_days(spots, home=None):
    """One entry per UTC day, newest first.

    spread_km = largest distance between two squares used that day (how far the car moved),
    path_km   = summed distance between consecutive fixes,
    home_km   = farthest distance from the home square (also catches days parked far away).
    """
    home = home or home_of(spots)
    by_day = {}
    for s in spots:
        by_day.setdefault(s["timestamp"][:10], []).append(s)
    out = []
    for date, rows in by_day.items():
        rows.sort(key=lambda r: r["timestamp"])
        st = _stats(rows, home)
        st.update({
            "date": date,
            "first": rows[0]["timestamp"][11:16],
            "last": rows[-1]["timestamp"][11:16],
            "start_loc": rows[0]["tx_loc"],
            "end_loc": rows[-1]["tx_loc"],
        })
        out.append(st)
    out.sort(key=lambda d: d["date"], reverse=True)
    return out


def build_track(spots, home=None):
    """Track of the given spots (already limited to the wanted days)."""
    spots = sorted(spots, key=lambda r: r["timestamp"])
    home = home or home_of(spots)
    fixes = []
    for s in spots:
        fixes.append({"t": s["timestamp"], "loc": s["tx_loc"], "lat": s["lat"], "lon": s["lon"],
                      "n": s.get("reporter_count", 0), "dx": s.get("max_distance", 0)})
    counts = Counter(s["tx_loc"] for s in spots)
    seen = {}
    for s in spots:
        if s["tx_loc"] not in seen:
            hl, ho = square_half_size(s["tx_loc"])
            seen[s["tx_loc"]] = {"loc": s["tx_loc"], "lat": s["lat"], "lon": s["lon"], "hlat": hl, "hlon": ho,
                                 "n": counts[s["tx_loc"]], "first": s["timestamp"]}
    stats = _stats(spots, home)
    return {"home": home, "fixes": fixes, "squares": list(seen.values()), "stats": stats}
