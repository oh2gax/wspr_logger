"""analysis_more.py — the second set of Analysis page cards (endpoint /api/analysis/more).

Pure functions on rows read by replay_db / db; no Flask and no database access here.

  geography()      stations by direction and distance from home (polar chart)
  distance_hist()  how the stations spread over distance
  loyal()          the stations that hear the beacon most often
  monthly()        stations heard and new stations per month
  snr()            SNR by UTC hour and by distance
  open_close()     first and last UTC time of the day with a well-heard transmission, with sunrise / sunset
  unusual_days()   the best and worst days against what is typical for that time of year and hour
  seasons()        the same months of different years side by side
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date

from . import sun

RINGS_KM = [0, 1000, 2000, 3000, 6000, 10000, 20100]      # distance rings of the polar chart
SECTORS = 16                                                # 22.5 degrees each, sector 0 centred on north
DIST_STEP = 500                                             # km per bar of the distance distribution
OPEN_MIN_REPORTERS = 3                                      # a transmission heard by this many stations "opens" the band
DAY_HOURS = range(6, 18)                                    # UTC hours used to judge a whole day
MIN_DAY_SNAPSHOTS = 36                                      # at least half of those hours' snapshots
SEASON_HOURS = range(8, 17)                                 # daytime used for the season comparison
MIN_MONTH_SNAPSHOTS = 50

_LOC = re.compile(r"[A-R]{2}[0-9]{2}([A-X]{2})?")


def grid_center(grid: str):
    """(lat, lon) of the centre of a 4- or 6-character Maidenhead locator, or None."""
    g = (grid or "")[:6].upper()
    if len(g) == 5:
        g = g[:4]
    if not _LOC.fullmatch(g):
        return None
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) == 6:
        lon += (ord(g[4]) - 65) * 2 / 24 + 1 / 24
        lat += (ord(g[5]) - 65) / 24 + 1 / 48
    else:
        lon += 1.0
        lat += 0.5
    return lat, lon


def _hav(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, a)))


def _bearing(la1, lo1, la2, lo2):
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _wpct(pairs, p):
    """Percentile p (0..100) of weighted values [(value, weight), ...] sorted by value."""
    total = sum(w for _, w in pairs)
    if not total:
        return None
    target, acc = total * p / 100.0, 0
    for v, w in pairs:
        acc += w
        if acc >= target:
            return v
    return pairs[-1][0]


def _r(v, nd=1):
    return None if v is None else round(v, nd)


def _place(stations, home):
    """Stations with their bearing and great-circle distance from home (from their own locator)."""
    out = []
    for s in stations:
        c = grid_center(s.get("grid"))
        if c is None or not home:
            continue
        d = _hav(home["lat"], home["lon"], c[0], c[1])
        out.append(dict(s, lat=c[0], lon=c[1], km=d, brg=_bearing(home["lat"], home["lon"], c[0], c[1])))
    return out


def geography(stations, home):
    """Stations and reports per (distance ring, 22.5-degree sector), plus totals per sector."""
    placed = _place(stations, home)
    nr = len(RINGS_KM) - 1
    st = [[0] * SECTORS for _ in range(nr)]
    rep = [[0] * SECTORS for _ in range(nr)]
    for s in placed:
        sec = int(((s["brg"] + 360 / SECTORS / 2) % 360) // (360 / SECTORS))
        ring = next((i for i in range(nr) if s["km"] < RINGS_KM[i + 1]), nr - 1)
        st[ring][sec] += 1
        rep[ring][sec] += s["n"]
    tot_st = sum(map(sum, st)) or 1
    tot_rep = sum(map(sum, rep)) or 1
    sector_share = [_r(100.0 * sum(st[r][k] for r in range(nr)) / tot_st) for k in range(SECTORS)]
    return {"rings": RINGS_KM, "sectors": SECTORS, "stations": st, "reports": rep,
            "stations_total": sum(map(sum, st)), "reports_total": sum(map(sum, rep)),
            "sector_share": sector_share,
            "ring_share": [_r(100.0 * sum(st[r]) / tot_st) for r in range(nr)],
            "ring_report_share": [_r(100.0 * sum(rep[r]) / tot_rep) for r in range(nr)]}


def distance_hist(stations, home):
    """Stations per DIST_STEP km and the share of all reports in each step (distance from home)."""
    placed = _place(stations, home)
    nb = int(math.ceil(20000 / DIST_STEP))
    st, rep = [0] * nb, [0] * nb
    for s in placed:
        b = min(int(s["km"] // DIST_STEP), nb - 1)
        st[b] += 1
        rep[b] += s["n"]
    while nb > 1 and st[nb - 1] == 0:
        nb -= 1
    tot = sum(rep) or 1
    km = sorted(s["km"] for s in placed)
    return {"step": DIST_STEP, "stations": st[:nb], "report_share": [_r(100.0 * x / tot) for x in rep[:nb]],
            "median_km": round(km[len(km) // 2]) if km else None,
            "beyond6000": sum(1 for x in km if x > 6000), "beyond10000": sum(1 for x in km if x > 10000),
            "total": len(km)}


def loyal(stations, snapshots, country_of, limit=15):
    """The stations heard in the most snapshots of the period (one row per callsign and locator)."""
    rows = sorted(stations, key=lambda s: -s["n"])[:limit]
    return [{"callsign": s["callsign"], "grid": s["grid"], "country": country_of(s["callsign"] or "??", s["grid"] or ""),
             "share": _r(100.0 * s["n"] / snapshots) if snapshots else None, "snapshots": s["n"],
             "dist": round(s["dist"]) if s["dist"] else None, "snr": _r(s["snr"]), "snr_max": s["snr_max"],
             "first": (s["first"] or "")[:10]} for s in rows]


def monthly(month_stations, first_month=None):
    """Stations heard in each month and how many of them had never been heard before (whole history
    decides "new"); months before first_month ('YYYY-MM') are left out of the result."""
    first_seen, per = {}, defaultdict(set)
    for m, call in month_stations:
        per[m].add(call)
        if call not in first_seen or m < first_seen[call]:
            first_seen[call] = m
    out = []
    for m in sorted(per):
        if first_month and m < first_month:
            continue
        out.append({"month": m, "stations": len(per[m]), "new": sum(1 for c in per[m] if first_seen[c] == m)})
    return out


def snr(table):
    """SNR quartiles (weighted by reports) per UTC hour and per 1000 km of distance."""
    by_h, by_b = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
    for h, b, v, c in table:
        by_h[h][v] += c
        by_b[min(b, 19)][v] += c

    def summary(d):
        pairs = sorted(d.items())
        n = sum(w for _, w in pairs)
        return {"p25": _wpct(pairs, 25), "median": _wpct(pairs, 50), "p75": _wpct(pairs, 75),
                "mean": _r(sum(v * w for v, w in pairs) / n) if n else None, "reports": n}
    return {"hour": [summary(by_h[h]) if h in by_h else None for h in range(24)],
            "dist": [dict(summary(by_b[b]), lo=b * 1000) for b in sorted(by_b) if sum(by_b[b].values()) >= 20]}


def open_close(spots, home, since=None):
    """Per UTC day: the first and the last transmission heard by OPEN_MIN_REPORTERS or more stations
    (hours as decimals), with sunrise and sunset at home.  spots: dicts with timestamp, reporter_count."""
    days = defaultdict(list)
    for s in spots:
        ts = s["timestamp"]
        if since and ts < since:
            continue
        if (s.get("reporter_count") or 0) >= OPEN_MIN_REPORTERS:
            days[ts[:10]].append(int(ts[11:13]) + int(ts[14:16]) / 60.0)
    out = []
    for d in sorted(days):
        t = days[d]
        rise = sset = None
        if home:
            rise, sset = sun.sunrise_sunset(home["lat"], home["lon"], date.fromisoformat(d))
        out.append({"date": d, "open": round(min(t), 2), "close": round(max(t), 2), "slots": len(t),
                    "rise": _r(rise, 2), "set": _r(sset, 2)})
    opens = sorted(x["open"] for x in out)
    closes = sorted(x["close"] for x in out)
    return {"threshold": OPEN_MIN_REPORTERS, "days": out,
            "median_open": opens[len(opens) // 2] if opens else None,
            "median_close": closes[len(closes) // 2] if closes else None}


def _typical(rows_all):
    """Mean stations heard per (month of the year, UTC hour) over the whole history."""
    acc = defaultdict(list)
    for r in rows_all:
        acc[(int(r[0][5:7]), int(r[0][11:13]))].append(r[1])
    return {k: sum(v) / len(v) for k, v in acc.items()}


def unusual_days(rows, rows_all, limit=8):
    """Best and worst days of the period: daytime (06-17 UTC) stations heard against what is typical for
    that month of the year and hour (100 = typical).  Days with too few daytime snapshots are skipped.
    rows / rows_all: snapshot rows (ts, n, max_dist, dx6, kindex, muf, sfi) of the period / whole history."""
    typ = _typical(rows_all)
    per = defaultdict(list)
    for r in rows:
        if int(r[0][11:13]) in DAY_HOURS:
            per[r[0][:10]].append(r)
    days = []
    for d, g in per.items():
        if len(g) < MIN_DAY_SNAPSHOTS:
            continue
        exp = sum(typ.get((int(r[0][5:7]), int(r[0][11:13])), 0) for r in g)
        if exp <= 0:
            continue
        peak = max(g, key=lambda r: r[1])
        ks = [r[4] for r in g if r[4] is not None]
        days.append({"date": d, "index": round(100.0 * sum(r[1] for r in g) / exp),
                     "avg_n": _r(sum(r[1] for r in g) / len(g)), "peak_n": peak[1], "peak_ts": peak[0],
                     "max_km": max(r[2] for r in g), "dx": sum(1 for r in g if r[3] > 0),
                     "k_max": max(ks) if ks else None, "snapshots": len(g)})
    days.sort(key=lambda x: x["index"])
    return {"worst": days[:limit], "best": days[::-1][:limit], "days_rated": len(days)}


def seasons(rows_all):
    """The same calendar months of different years side by side: median daytime (08-16 UTC) stations heard
    per snapshot and the share of snapshots with a station beyond 6000 km."""
    per = defaultdict(list)
    for r in rows_all:
        per[(int(r[0][:4]), int(r[0][5:7]))].append(r)
    years = sorted({y for y, _ in per})
    months = sorted({m for _, m in per})
    med, dx, days = {}, {}, {}
    for y in years:
        med[y], dx[y], days[y] = [], [], []
        for m in months:
            g = per.get((y, m), [])
            day = sorted(r[1] for r in g if int(r[0][11:13]) in SEASON_HOURS)
            if len(day) < MIN_MONTH_SNAPSHOTS:
                med[y].append(None); dx[y].append(None); days[y].append(len({r[0][:10] for r in g}))
                continue
            med[y].append(day[len(day) // 2])
            dx[y].append(_r(100.0 * sum(1 for r in g if r[3] > 0) / len(g)))
            days[y].append(len({r[0][:10] for r in g}))
    return {"years": years, "months": months, "median": med, "dx": dx, "days": days}
