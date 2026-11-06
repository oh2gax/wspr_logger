"""Grey-line analysis: are long-distance windows tied to twilight at either end of the path?

For every region that produced DX reports (beyond 6000 km) it gives
  * the share of days with a DX report from that region in each UTC hour,
  * sunrise and sunset (median and quartiles over the period) at home and at the region's
    far end (median position of its reporters),
  * how many DX hours had twilight (sun within +-TWILIGHT_DEG of the horizon) at home or at the
    far end, against what the same UTC hour gives on the other days of the period.
The comparison keeps the hour of the day fixed, so it asks "given the hour, is DX more likely
on days when the terminator happens to be there?" and does not just restate the day profile.
"""
import math
from datetime import date, datetime

from . import sun

TWILIGHT_DEG = 6.0
MIN_EVENT_DAYS = 10
ZONE_NAMES = {"n_america": "North America", "africa": "Africa", "pacific": "Oceania",
              "s_america": "South America", "asia": "Asia"}


def _median(v):
    v = sorted(v)
    n = len(v)
    return None if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


def _quart(v, q):
    v = sorted(v)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _circ(values):
    """(q1, median, q3) of hours of the day, robust to wrapping past midnight."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    ref = values[0]
    adj = [((v - ref + 12) % 24) - 12 + ref for v in values]
    return [round(_quart(adj, .25) % 24, 2), round(_median(adj) % 24, 2), round(_quart(adj, .75) % 24, 2)]


def _sun_times(lat, lon, days):
    rises, sets = [], []
    for d in days:
        r, s = sun.sunrise_sunset(lat, lon, date.fromisoformat(d))
        rises.append(r); sets.append(s)
    return {"rise": _circ(rises), "set": _circ(sets)}


def _twilight(lat, lon, day, hour):
    t = datetime.fromisoformat(day) .replace(hour=hour, minute=30)
    return abs(sun.solar_elevation(lat, lon, t)) <= TWILIGHT_DEG


def build(events, hour_days, home):
    """
    events:    iterable of (day 'YYYY-MM-DD', hour 0-23, zone, lat, lon): one per DX reporter and hour.
    hour_days: {hour: set of days that have snapshots in that hour}.
    home:      {'lat', 'lon', 'loc'}.
    """
    if not home or not hour_days:
        return {"zones": []}
    all_days = sorted(set().union(*hour_days.values()))
    per_zone = {}
    for day, hour, zone, la, lo in events:
        z = per_zone.setdefault(zone, {"hits": set(), "lat": [], "lon": [], "reports": 0})
        z["hits"].add((day, hour)); z["lat"].append(la); z["lon"].append(lo); z["reports"] += 1
    out = []
    home_sun = _sun_times(home["lat"], home["lon"], all_days)
    for zone, z in per_zone.items():
        ev_days = {d for d, _ in z["hits"]}
        if len(ev_days) < MIN_EVENT_DAYS:
            continue
        flat, flon = _median(z["lat"]), _median(z["lon"])
        by_hour = [round(100.0 * len({d for d, h in z["hits"] if h == hh}) / len(hour_days[hh]), 1)
                   if hour_days.get(hh) else None for hh in range(24)]
        # twilight table for this region: tw[hour] = days on which either end is in twilight
        tw = {}
        for hh in range(24):
            tw[hh] = {d for d in hour_days.get(hh, ()) if _twilight(home["lat"], home["lon"], d, hh)
                      or _twilight(flat, flon, d, hh)}
        e_hour = {hh: (len(tw[hh]) / len(hour_days[hh]) if hour_days.get(hh) else 0.0) for hh in range(24)}
        obs = sum(1 for d, h in z["hits"] if d in tw[h])
        exp = sum(e_hour[h] for _, h in z["hits"])
        var = sum(e_hour[h] * (1 - e_hour[h]) for _, h in z["hits"])
        n = len(z["hits"])
        out.append({
            "zone": zone, "name": ZONE_NAMES.get(zone, zone), "lat": round(flat, 1), "lon": round(flon, 1),
            "days": len(ev_days), "events": n, "by_hour": by_hour,
            "far": _sun_times(flat, flon, all_days),
            "tw_obs_pct": round(100.0 * obs / n, 1), "tw_exp_pct": round(100.0 * exp / n, 1),
            "ratio": round(obs / exp, 2) if exp > 0 else None,
            "z": round((obs - exp) / math.sqrt(var), 1) if var > 0 else None,
        })
    out.sort(key=lambda r: -r["days"])
    return {"twilight_deg": TWILIGHT_DEG, "home": dict(home_sun, lat=home["lat"], lon=home["lon"], loc=home["loc"]),
            "days_in_period": len(all_days), "zones": out}
