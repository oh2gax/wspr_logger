"""
analysis.py — propagation analysis built from the replay database.

Pure functions, no Flask and no database access: build() takes the
per-snapshot rows from replay_db.get_snapshot_rows() and returns the JSON
structure used by the Analysis page.

A "snapshot" is one poll cycle (~every 10 minutes).  Its reporter count is
the number of distinct stations heard in the 60 minutes before the poll, so
all reporter figures here are "stations heard in the last hour".

Because both reporter counts and space-weather values (MUF in particular)
follow the day/night cycle, raw averages per MUF/K/SFI bin would mostly
show the time of day.  The bin charts therefore report an *index*:
    index = 100 * sum(reporters) / sum(typical reporters for that UTC hour)
100 means "as many reporters as usually at that hour", so the effect of
the space-weather value is separated from the daily rhythm.
"""
from __future__ import annotations

import math
from collections import defaultdict

# Snapshot row layout: (ts, n, max_dist, dx6, kindex, muf, sfi)
MIN_BIN_SNAPSHOTS = 15      # bins with fewer snapshots are dropped
STORM_K = 5                 # a day with K >= this counts as a storm day


def _pct(sorted_vals: list, p: float):
    """Linear-interpolated percentile (p in 0..100) of a sorted list."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _mean(vals: list):
    return sum(vals) / len(vals) if vals else None


def _corr(a: list, b: list):
    if len(a) < 10:
        return None
    ma, mb = _mean(a), _mean(b)
    da = sum((x - ma) ** 2 for x in a)
    db_ = sum((y - mb) ** 2 for y in b)
    if da == 0 or db_ == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(da * db_)


def _r(v, nd=1):
    return None if v is None else round(v, nd)


def _bin_stats(rows, expected, key, width):
    """Group snapshots by floor(key/width)*width and summarise each group."""
    groups = defaultdict(list)
    for row in rows:
        v = key(row)
        if v is None:
            continue
        groups[math.floor(v / width) * width].append(row)
    out = []
    for lo in sorted(groups):
        g = groups[lo]
        if len(g) < MIN_BIN_SNAPSHOTS:
            continue
        exp = sum(expected[int(r[0][11:13])] for r in g)
        out.append({
            "lo": lo, "hi": lo + width, "count": len(g),
            "avg_n": _r(_mean([r[1] for r in g])),
            "index": _r(100.0 * sum(r[1] for r in g) / exp, 0) if exp else None,
            "pct_dx": _r(100.0 * sum(1 for r in g if r[3] > 0) / len(g), 0),
            "avg_max": _r(_mean([r[2] for r in g]), 0),
        })
    return out


def build(rows: list, today: str) -> dict:
    """rows: list of (ts, n, max_dist, dx6, kindex, muf, sfi), any order."""
    # A solar value of 0 means "feed delivered nothing" (hamqsl occasionally
    # does this), not a real reading, so treat MUF/SFI <= 0 as missing.
    rows = sorted(((r[0], r[1], r[2], r[3], r[4],
                    r[5] if r[5] and r[5] > 0 else None,
                    r[6] if r[6] and r[6] > 0 else None) for r in rows),
                  key=lambda r: r[0])
    if not rows:
        return {"empty": True}

    # typical reporters per UTC hour (mean over the analysed period)
    by_hour = defaultdict(list)
    for r in rows:
        by_hour[int(r[0][11:13])].append(r[1])
    expected = [(_mean(by_hour[h]) or 0.0) for h in range(24)]

    dates = sorted({r[0][:10] for r in rows})

    # --- heatmap: mean reporters / farthest distance per (hour, date) -----
    cell_n, cell_mx = defaultdict(list), defaultdict(list)
    for r in rows:
        k = (int(r[0][11:13]), r[0][:10])
        cell_n[k].append(r[1])
        cell_mx[k].append(r[2])
    heat_n  = [[_r(_mean(cell_n[(h, d)])) if (h, d) in cell_n else None for d in dates] for h in range(24)]
    heat_mx = [[max(cell_mx[(h, d)]) if (h, d) in cell_mx else None for d in dates] for h in range(24)]

    # --- typical day: percentiles per UTC hour + the latest day -----------
    profile = []
    for h in range(24):
        v = sorted(by_hour[h])
        profile.append({"p25": _r(_pct(v, 25)), "median": _r(_pct(v, 50)),
                        "p75": _r(_pct(v, 75)), "mean": _r(_mean(v))})
    latest = dates[-1]
    latest_by_hour = defaultdict(list)
    for r in rows:
        if r[0][:10] == latest:
            latest_by_hour[int(r[0][11:13])].append(r[1])
    latest_day = {"date": latest, "is_today": latest == today,
                  "n": [_r(_mean(latest_by_hour[h])) if h in latest_by_hour else None for h in range(24)]}

    # --- space weather bins ----------------------------------------------
    bins = {
        "muf": _bin_stats(rows, expected, lambda r: r[5], 2),      # MHz
        "k":   _bin_stats(rows, expected, lambda r: None if r[4] is None else math.floor(r[4]), 1),
        "sfi": _bin_stats(rows, expected, lambda r: r[6], 10),
    }

    # --- storm days -------------------------------------------------------
    per_day = defaultdict(list)
    for r in rows:
        per_day[r[0][:10]].append(r)
    storms = []
    for d, g in per_day.items():
        ks = [(r[4], r[0]) for r in g if r[4] is not None]
        if not ks:
            continue
        kmax, kts = max(ks)
        if kmax < STORM_K:
            continue
        exp = sum(expected[int(r[0][11:13])] for r in g)
        storms.append({"date": d, "k_max": kmax, "k_time": kts[11:16],
                       "avg_n": _r(_mean([r[1] for r in g])),
                       "index": _r(100.0 * sum(r[1] for r in g) / exp, 0) if exp else None,
                       "snapshots": len(g)})
    storms.sort(key=lambda s: s["date"], reverse=True)

    # --- summary ----------------------------------------------------------
    best = max(rows, key=lambda r: r[2])
    pairs_raw = [(r[1], r[5]) for r in rows if r[5] is not None]
    pairs_rel = [(r[1] / expected[int(r[0][11:13])], r[5]) for r in rows
                 if r[5] is not None and expected[int(r[0][11:13])] > 0]
    summary = {
        "snapshots": len(rows), "days": len(dates),
        "from": dates[0], "to": dates[-1],
        "avg_n": _r(_mean([r[1] for r in rows])),
        "pct_dx": _r(100.0 * sum(1 for r in rows if r[3] > 0) / len(rows), 1),
        "best_dist": best[2], "best_ts": best[0][:16],
        "corr_muf_raw": _r(_corr([p[0] for p in pairs_raw], [p[1] for p in pairs_raw]), 2),
        "corr_muf_rel": _r(_corr([p[0] for p in pairs_rel], [p[1] for p in pairs_rel]), 2),
        "storm_k": STORM_K,
    }

    return {"empty": False, "summary": summary,
            "heatmap": {"dates": dates, "n": heat_n, "mx": heat_mx},
            "profile": profile, "latest": latest_day,
            "bins": bins, "storms": storms[:15]}
