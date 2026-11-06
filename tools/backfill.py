#!/usr/bin/env python3
"""
backfill.py -- fill the databases with the beacon's older seasons from wspr.live.

The live logger only knows what it has seen since it was started. wspr.live (the public WSPR
spot database) holds every reception of your beacon, so earlier summers can be loaded afterwards:

  * wspr_data.db     one `spots` record per heard transmission (locator, reporters, farthest km)
  * wspr_replay.db   the reporter snapshots (every 10 minutes: who heard you in the last 60
                     minutes), built the same way as the live poll builds them

What it does NOT fill: the solar and ionosonde values (SFI, K, A, MUF, foF2). Those were only
recorded live, so the backfilled seasons appear in the heatmaps, typical day, geography, DX windows,
grey line and the WPRS page, but not in the space-weather charts.

It is a one-off tool. It is polite to wspr.live: one query at a time, small chunks (default 7 days),
a pause between queries, retries with a back-off. Safe to run again: spots are only raised, never
lowered, and a snapshot is skipped when the replay database already has one within 5 minutes.

Usage (from the project folder, with the same Python / venv as the logger):

    python3 tools/backfill.py --test 2025-07-15          # one day, nothing written: check it works
    python3 tools/backfill.py --from 2025-04-01 --to 2025-11-30
    python3 tools/backfill.py --from 2024-04-01 --to 2024-11-30 --yes

--to defaults to the day before the oldest snapshot already in the replay database.
Stop the logger service first if you like (not required: SQLite waits for the other writer).
"""
import argparse
import bisect
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WSPR_LIVE = "https://db1.wspr.live/"
FMT = "%Y-%m-%d %H:%M:%S"
WINDOW_MIN = 60            # a snapshot lists the stations heard in the preceding 60 minutes
SKIP_NEAR_MIN = 5          # an existing snapshot this close makes a backfilled one redundant


# ---------------------------------------------------------------------------
# wspr.live
# ---------------------------------------------------------------------------

def fetch_chunk(callsign, band, start, end, timeout=300, retries=3):
    """All receptions of `callsign` on `band` with start <= time < end, as a list of
    (time str, tx_loc, rx_sign, rx_loc, snr int, distance int)."""
    if not re.fullmatch(r"[A-Z0-9/]{3,12}", callsign):
        raise ValueError(f"unexpected callsign: {callsign!r}")
    sql = (f"SELECT time, tx_loc, rx_sign, rx_loc, snr, distance FROM wspr.rx "
           f"WHERE tx_sign = '{callsign}' AND band = {int(band)} "
           f"AND time >= '{start.strftime(FMT)}' AND time < '{end.strftime(FMT)}' "
           f"ORDER BY time FORMAT TabSeparated")
    url = WSPR_LIVE + "?query=" + urllib.parse.quote_plus(sql)
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "wspr-logger-backfill"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return parse_tsv(resp.read().decode("utf-8", "replace"))
        except Exception as e:                    # network error, timeout, HTTP error
            last = e
            wait = 20 * attempt
            print(f"    query failed ({e}); retry {attempt}/{retries} in {wait} s")
            time.sleep(wait)
    raise RuntimeError(f"wspr.live did not answer: {last}")


def parse_tsv(text):
    rows = []
    for line in text.splitlines():
        p = line.split("\t")
        if len(p) < 6:
            continue
        try:
            rows.append((p[0], p[1], p[2], p[3], int(p[4]), int(p[5])))
        except ValueError:
            continue
    return rows


# ---------------------------------------------------------------------------
# Building spots and snapshots (pure functions)
# ---------------------------------------------------------------------------

def build_spots(rows):
    """One entry per transmission slot: {time, tx_loc, reporter_count, max_distance}.
    Only slots that start at a minute ending in 2 are WSPR cycle slots of this beacon."""
    by_time = {}
    for t, tx_loc, _rs, _rl, _snr, dist in rows:
        by_time.setdefault(t, []).append((tx_loc, dist))
    out = []
    for t, items in sorted(by_time.items()):
        if int(t[14:16]) % 10 != 2:
            continue
        loc = Counter(i[0] for i in items).most_common(1)[0][0]
        out.append({"time": t, "tx_loc": loc, "reporter_count": len(items),
                    "max_distance": max(i[1] for i in items)})
    return out


def snapshot_times(start, end):
    """The poll times :08, :18, ... :58 with start <= T < end."""
    t = start.replace(minute=0, second=0, microsecond=0)
    out = []
    while t < end:
        for m in range(8, 60, 10):
            c = t.replace(minute=m)
            if start <= c < end:
                out.append(c)
        t += timedelta(hours=1)
    return out


def build_snapshots(rows, start, end):
    """[(timestamp str, [reporter dicts])] for the poll times in [start, end).
    Each snapshot lists one entry per (rx_sign, 6-char rx_loc) heard in the previous 60 minutes
    with its best SNR and largest distance, as the live poll does."""
    parsed = [(datetime.strptime(r[0], FMT), r) for r in rows]
    parsed.sort(key=lambda x: x[0])
    times = [p[0] for p in parsed]
    out = []
    for T in snapshot_times(start, end):
        lo = bisect.bisect_right(times, T - timedelta(minutes=WINDOW_MIN))
        hi = bisect.bisect_right(times, T)
        best = {}
        for _t, (_ts, _txl, rx_sign, rx_loc, snr, dist) in parsed[lo:hi]:
            key = (rx_sign, (rx_loc or "?")[:6])
            cur = best.get(key)
            if cur is None:
                best[key] = [snr, dist]
            else:
                cur[0] = max(cur[0], snr)
                cur[1] = max(cur[1], dist)
        if best:
            out.append((T.strftime(FMT), [{"callsign": k[0], "grid": k[1], "snr": v[0], "distance": v[1]}
                                          for k, v in best.items()]))
    return out


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def existing_snapshot_times(replay_db, start, end):
    """Sorted datetimes of replay snapshots between start - 5 min and end + 5 min."""
    lo = (start - timedelta(minutes=SKIP_NEAR_MIN)).strftime(FMT)
    hi = (end + timedelta(minutes=SKIP_NEAR_MIN)).strftime(FMT)
    with replay_db._connect() as conn:
        rows = conn.execute("SELECT DISTINCT timestamp FROM reporters_log WHERE timestamp >= ? AND timestamp < ?",
                            (lo, hi)).fetchall()
    return sorted(datetime.strptime(r[0], FMT) for r in rows)


def write_chunk(db, replay_db, maidenhead_to_latlon, band, spots, snapshots, existing):
    """Returns (spots written, snapshots written, snapshots skipped)."""
    n_spots = 0
    for s in spots:
        lat, lon = maidenhead_to_latlon(s["tx_loc"])
        if lat is None:
            continue
        if db.insert_spot(s["time"], s["tx_loc"], lat, lon, band, s["reporter_count"], s["max_distance"]):
            n_spots += 1
    n_snap = n_skip = 0
    for ts, reporters in snapshots:
        T = datetime.strptime(ts, FMT)
        i = bisect.bisect_left(existing, T - timedelta(minutes=SKIP_NEAR_MIN))
        if i < len(existing) and existing[i] <= T + timedelta(minutes=SKIP_NEAR_MIN):
            n_skip += 1
            continue
        replay_db.insert_reporters(ts, reporters, band)
        n_snap += 1
    return n_spots, n_snap, n_skip


def run(args, fetch=fetch_chunk):
    import wspr_logger as w            # reads config.ini; nothing is started on import
    import db
    import replay_db
    callsign = (args.callsign or w.CALLSIGN).upper()
    band = args.band or w.DEFAULT_BAND
    db.init(w.DB_PATH)
    replay_db.init(w.REPLAY_DB_PATH, enabled=True)

    if args.test:
        day = datetime.strptime(args.test, "%Y-%m-%d")
        print(f"Test: {callsign} {band} MHz on {args.test} (nothing is written)")
        rows = fetch(callsign, band, day - timedelta(minutes=WINDOW_MIN), day + timedelta(days=1), args.timeout)
        spots = build_spots([r for r in rows if r[0] >= day.strftime(FMT)])
        snaps = build_snapshots(rows, day, day + timedelta(days=1))
        print(f"  {len(rows)} receptions, {len(spots)} transmissions heard, {len(snaps)} snapshots")
        for r in rows[:5]:
            print("  ", r)
        if spots:
            print(f"  first transmission {spots[0]['time']} {spots[0]['tx_loc']}, farthest of the day "
                  f"{max(s['max_distance'] for s in spots)} km")
        return 0

    start = datetime.strptime(args.date_from, "%Y-%m-%d")
    if args.date_to:
        end = datetime.strptime(args.date_to, "%Y-%m-%d") + timedelta(days=1)
    else:
        with replay_db._connect() as conn:
            first = conn.execute("SELECT MIN(timestamp) FROM reporters_log").fetchone()[0]
        end = datetime.strptime(first[:10], "%Y-%m-%d") if first else datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    if end <= start:
        print("Nothing to do: the end of the range is not after its start.")
        return 1
    step = timedelta(days=args.chunk_days)
    chunks, t = [], start
    while t < end:
        chunks.append((t, min(t + step, end)))
        t += step
    est = len(chunks) * (args.pause + 10) / 60
    print(f"{callsign} on {band} MHz: {start.date()} .. {(end - timedelta(days=1)).date()}")
    print(f"{len(chunks)} queries to wspr.live, one at a time with {args.pause} s pauses (about {est:.0f} min).")
    print(f"Writes to {w.DB_PATH} and {w.REPLAY_DB_PATH}. No solar data is filled.")
    if not args.yes and input("Go ahead? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Cancelled.")
        return 1

    tot = [0, 0, 0, 0]
    for i, (a, b) in enumerate(chunks, 1):
        t0 = time.time()
        rows = fetch(callsign, band, a - timedelta(minutes=WINDOW_MIN), b, args.timeout)
        in_chunk = [r for r in rows if a.strftime(FMT) <= r[0] < b.strftime(FMT)]
        spots = build_spots(in_chunk)
        snaps = build_snapshots(rows, a, b)
        existing = existing_snapshot_times(replay_db, a, b)
        ns, nn, nk = write_chunk(db, replay_db, w.maidenhead_to_latlon, band, spots, snaps, existing)
        tot[0] += len(in_chunk); tot[1] += ns; tot[2] += nn; tot[3] += nk
        print(f"[{i}/{len(chunks)}] {a.date()} .. {(b - timedelta(days=1)).date()}: {len(in_chunk):,} receptions, "
              f"{len(spots)} transmissions, {nn} snapshots written ({nk} skipped)  {time.time() - t0:.0f} s")
        if i < len(chunks):
            time.sleep(args.pause)
    print(f"Done: {tot[0]:,} receptions read, {tot[1]} spot records added or raised, "
          f"{tot[2]} snapshots written, {tot[3]} skipped (already covered).")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backfill older seasons of the beacon from wspr.live.")
    ap.add_argument("--from", dest="date_from", help="first day, YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", help="last day (default: the day before the oldest replay snapshot)")
    ap.add_argument("--test", metavar="DATE", help="fetch just this day and print a summary; writes nothing")
    ap.add_argument("--callsign", help="default: from config.ini")
    ap.add_argument("--band", type=int, help="default: from config.ini")
    ap.add_argument("--chunk-days", type=int, default=7, help="days per wspr.live query (default 7)")
    ap.add_argument("--pause", type=int, default=5, help="seconds between queries (default 5)")
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for one query (default 300)")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args(argv)
    if not args.test and not args.date_from:
        ap.error("give --from (and optionally --to), or --test DATE")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
