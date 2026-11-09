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
from datetime import datetime, timedelta

# Snapshot row layout: (ts, n, max_dist, dx6, kindex, muf, sfi)
MIN_BIN_SNAPSHOTS = 15      # bins with fewer snapshots are dropped
STORM_K = 5                 # a day with K >= this counts as a storm day
MIN_EXPECT_SAMPLES = 8      # smallest sample used for an hour+MUF expectation
MUF_BIN_TOP = 24            # MUF bins of 2 MHz; 24 MHz and above are one bin: on 20 m the number of
                            # stations stops growing at about 22 MHz (the gain goes to the higher
                            # bands), so the upper bins share their samples
TX_USUAL_MIN = 4            # an hour is "busy" when the polls that hear someone usually hear at least
TX_QUIET_SHARE = 0.4        # this many stations and fewer than this share of its polls hear nobody,
TX_SURE_MIN = 20            # or when they usually hear at least this many (then a real silence is
                            # impossible: the band does not close at such an hour); an empty poll at a
                            # busy hour means the transmitter was off.  Autumn nights on 20 m are
                            # really closed: few stations and mostly empty polls, so not busy.
TX_RAMP_MIN = 60            # minutes after the transmitter comes back during which the 60-minute
                            # station count is still building up


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


def _stats(vals: list) -> dict:
    """count / mean / quartiles (and the 10 and 90 % levels) of a list of numbers."""
    v = sorted(vals)
    return {"count": len(v), "mean": _r(_mean(v)), "p10": _r(_pct(v, 10)), "p25": _r(_pct(v, 25)),
            "median": _r(_pct(v, 50)), "p75": _r(_pct(v, 75)), "p90": _r(_pct(v, 90))}


def muf_bin(muf: float) -> int:
    """The 2 MHz MUF bin of the expectation tables (24 = 24 MHz and above)."""
    return min(math.floor(muf / 2) * 2, MUF_BIN_TOP)


def busy_hours(rows: list) -> list:
    """For each UTC hour whether it is "busy" (see TX_USUAL_MIN): an empty poll then means the
    transmitter was off.  rows: every poll, with the empty ones; days with no reception are left out."""
    day_sum = defaultdict(int)
    for r in rows:
        day_sum[r[0][:10]] += r[1]
    heard, empty = defaultdict(list), defaultdict(int)
    for r in rows:
        if day_sum[r[0][:10]] == 0:
            continue
        h = int(r[0][11:13])
        if r[1] > 0:
            heard[h].append(r[1])
        else:
            empty[h] += 1
    out = []
    for h in range(24):
        n = len(heard[h]) + empty[h]
        med = _pct(sorted(heard[h]), 50) if heard[h] else 0
        share = empty[h] / n if n else 1.0
        out.append(bool(med >= TX_SURE_MIN or (med >= TX_USUAL_MIN and share < TX_QUIET_SHARE)))
    return out


def tx_on(rows: list) -> list:
    """
    The snapshots taken while the transmitter was on (from 2026-11-09).  rows: (ts, n, ...) of every
    poll, including the polls that heard nobody (n = 0).  Left out:
      - every poll of a day with no reception at all (battery not swapped, the winter season);
      - an empty poll at a busy hour (busy_hours()): the transmitter was off (antenna removed for a
        garage, an empty battery); empty polls at quiet hours (autumn nights) stay in, as real silence;
      - the polls of the TX_RAMP_MIN minutes after such an off period, or after a gap of over 25
        minutes between polls at a busy hour, while the 60-minute count is still building up.
    """
    rows = sorted(rows, key=lambda r: r[0])
    if not rows:
        return []
    day_sum = defaultdict(int)
    for r in rows:
        day_sum[r[0][:10]] += r[1]
    busy = busy_hours(rows)
    out, off_until, prev = [], None, None
    for r in rows:
        t = datetime.strptime(r[0][:19], "%Y-%m-%d %H:%M:%S")
        off = day_sum[r[0][:10]] == 0 or (r[1] == 0 and busy[t.hour])
        if prev is not None and busy[t.hour] and (t - prev).total_seconds() > 25 * 60:
            off_until = t + timedelta(minutes=TX_RAMP_MIN)      # a gap: the count starts again from zero
        prev = t
        if off:
            off_until = t + timedelta(minutes=TX_RAMP_MIN)
            continue
        if off_until is not None and t < off_until:
            continue
        out.append(r)
    return out


def build_expect(rows: list) -> dict:
    """Expectation tables: per UTC hour the statistics of all snapshots and per MUF bin (muf_bin)."""
    expect = {}
    for h in range(24):
        hrows = [r for r in rows if int(r[0][11:13]) == h]
        per_muf = defaultdict(list)
        for r in hrows:
            if r[5] is not None:
                per_muf[muf_bin(r[5])].append(r[1])
        expect[str(h)] = {
            "all": _stats([r[1] for r in hrows]),
            "muf": {str(lo): _stats(v) for lo, v in per_muf.items() if len(v) >= MIN_EXPECT_SAMPLES},
        }
    return expect


VERDICTS = ("much_below", "below", "typical", "above", "exceptional")


def prop_verdict(expect: dict, hour: int, muf, live_n) -> dict | None:
    """
    The live station count (heard in the last 60 minutes) against history at this UTC hour and a
    similar MUF (else the hour alone): much_below < p10 < below < p25 <= typical <= p75 < above
    <= p90 < exceptional.  A difference smaller than max(2, sqrt(median)) stays "typical" (small
    numbers at night).  None without enough history.
    """
    tab = expect.get(str(hour)) or {}
    allh = tab.get("all") or {}
    ref, basis = allh, "hour"
    if muf is not None and muf > 0:
        m = (tab.get("muf") or {}).get(str(muf_bin(muf)))
        if m:
            ref, basis = m, "muf"
    if live_n is None or not ref or ref.get("count", 0) < MIN_EXPECT_SAMPLES or ref.get("p25") is None:
        return None
    med = ref["median"]
    if live_n < ref["p10"]:
        v = "much_below"
    elif live_n < ref["p25"]:
        v = "below"
    elif live_n <= ref["p75"]:
        v = "typical"
    elif live_n <= ref["p90"]:
        v = "above"
    else:
        v = "exceptional"
    if v != "typical" and abs(live_n - med) < max(2.0, math.sqrt(max(med, 1.0))):
        v = "typical"
    return {"verdict": v, "basis": basis, "hour": hour, "live_n": live_n,
            "muf_bin": muf_bin(muf) if basis == "muf" else None,
            "p10": ref["p10"], "p25": ref["p25"], "median": med, "p75": ref["p75"], "p90": ref["p90"],
            "count": ref["count"], "usual_hour": allh.get("median")}


def expectation(expect: dict, hour: int, muf, live_n: int) -> dict:
    """
    Compare the live reporter count with history for this UTC hour: first with
    all snapshots of the hour, then (if enough samples) with those at a similar
    MUF (same 2 MHz bin).  verdict: 'above' / 'typical' / 'below' relative to
    the quartiles of the best available comparison.
    """
    tab = expect.get(str(hour)) or {}
    allh = tab.get("all") or {}
    at_muf = None
    if muf is not None and muf > 0:
        at_muf = (tab.get("muf") or {}).get(str(muf_bin(muf)))
    ref = at_muf or allh
    verdict = None
    if live_n is not None and ref and ref.get("p25") is not None:
        verdict = "above" if live_n > ref["p75"] else "below" if live_n < ref["p25"] else "typical"
    return {"hour": hour, "muf": muf, "live_n": live_n, "typical": allh or None,
            "typical_muf": at_muf, "verdict": verdict,
            "verdict_basis": "muf" if at_muf else "hour"}


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

    # --- DX windows: share of snapshots with a reporter beyond 6000 km ----
    dx_hour = []
    for h in range(24):
        g = [r for r in rows if int(r[0][11:13]) == h]
        dx_hour.append({"hour": h, "count": len(g),
                        "pct_dx": _r(100.0 * sum(1 for r in g if r[3] > 0) / len(g), 1) if g else None,
                        "avg_max": _r(_mean([r[2] for r in g]), 0) if g else None})
    by_month = defaultdict(list)
    for r in rows:
        by_month[r[0][:7]].append(r)
    dx_month = []
    for m in sorted(by_month):
        g = by_month[m]
        sfi = [r[6] for r in g if r[6] is not None]
        dx_month.append({"month": m, "count": len(g),
                         "avg_n": _r(_mean([r[1] for r in g])),
                         "pct_dx": _r(100.0 * sum(1 for r in g if r[3] > 0) / len(g), 1),
                         "avg_sfi": _r(_mean(sfi), 0) if sfi else None,
                         "days": len({r[0][:10] for r in g})})

    # --- expectation tables for "right now": per UTC hour, overall and per MUF bin
    expect = build_expect(rows)

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
            "bins": bins, "storms": storms[:15],
            "dx_hour": dx_hour, "dx_month": dx_month, "expect": expect}
