#!/usr/bin/env python3
"""
analyze.py -- data analysis and figures for the WSPR Logger propagation study.

Reads the two SQLite databases of the WSPR Logger (wspr_replay.db, wspr_data.db),
applies the quality control described in the paper and writes
    out/numbers.tex   LaTeX macros with every number quoted in the text
    out/tables.tex    the tables
    out/fig_*.pdf     the figures
    out/stats.json    the same numbers for reference

Usage:  python3 analyze.py [path-to-wspr_logger-folder]
"""
from __future__ import annotations

import collections
import re
import json
import math
import os
import statistics as st
import sqlite3
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, REPO)
import wspr_logger as w                       # grid / region helpers of the logger

REPLAY = sqlite3.connect(f"file:{os.path.join(REPO, 'wspr_replay.db')}?mode=ro&immutable=1", uri=True)
DATA = sqlite3.connect(f"file:{os.path.join(REPO, 'wspr_data.db')}?mode=ro&immutable=1", uri=True)

# ------------------------------------------------------------------ style
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 8,
    "axes.titlesize": 8.5, "axes.labelsize": 8, "legend.fontsize": 7, "xtick.labelsize": 7,
    "ytick.labelsize": 7, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5, "figure.dpi": 150,
    "savefig.bbox": "tight", "pdf.fonttype": 42,
})
BLUE, AMBER, GREEN, RED, GREY = "#2b6cb0", "#d9822b", "#2f855a", "#c53030", "#718096"
W = 6.3                                         # text width in inches

DIG = str.maketrans("0123456789", "ABCDEFGHIJ")
NUM: dict[str, str] = {}                        # LaTeX macros
STAT: dict = {}


def macro(name: str, value) -> None:
    NUM[name] = str(value)
    STAT[name] = value


def fmt(n, nd=0):
    return f"{n:,.{nd}f}".replace(",", "\\,")


# ------------------------------------------------------------------ geography helpers
HOME_LAT, HOME_LON = w.maidenhead_to_latlon("KP20jg")


def hav(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def bearing(la1, lo1, la2, lo2):
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


ZONE_NAME = {"europe": "Europe", "n_america": "North America", "africa": "Africa", "pacific": "Oceania",
             "s_america": "South America", "asia": "Asia", "other": "Other / unknown"}
_zone_cache: dict = {}


def zone_of(call, grid):
    k = (call, grid)
    if k not in _zone_cache:
        lat, lon = w._grid_to_latlon(grid or "")
        if lat is None:
            _zone_cache[k] = "other"
        else:
            _zone_cache[k] = w._REGION_ZONE.get(w._latlon_to_region(lat, lon), "other")
    return _zone_cache[k]


# ------------------------------------------------------------------ 1. quality control of reporters
QC_TOL_KM = 500
pairs_all = REPLAY.execute("SELECT callsign, grid, MAX(distance), COUNT(*) FROM reporters_log GROUP BY callsign, grid").fetchall()
flagged = []
for call, grid, dist, n in pairs_all:
    lat, lon = w._grid_to_latlon(grid or "")
    if lat is None:
        continue
    if abs(hav(HOME_LAT, HOME_LON, lat, lon) - dist) > QC_TOL_KM:
        flagged.append((call, grid, dist, n))
macro("qcFlagged", len(flagged))
macro("qcPairs", len(pairs_all))
macro("qcTol", QC_TOL_KM)
bad_keys = {f"{c}|{g}" for c, g, _, _ in flagged}
if flagged:
    c, g, d, n = flagged[0]
    macro("qcCall", c.replace("/", "/"))
    macro("qcGrid", g)
    macro("qcDist", fmt(d))
    macro("qcGridDist", fmt(round(hav(HOME_LAT, HOME_LON, *w._grid_to_latlon(g)))))
    macro("qcRows", fmt(n))
bad_sql = ",".join("?" for _ in bad_keys) or "''"
bad_args = tuple(bad_keys)
WHERE_OK = f"(callsign || '|' || grid) NOT IN ({bad_sql})"

# ------------------------------------------------------------------ 2. snapshots
rows = REPLAY.execute(f"""
    SELECT s.ts, s.n, s.mx, s.dx6, s.dx10, l.kindex, l.aindex, l.muf, l.sfi, l.fof2, l.xray
    FROM (SELECT timestamp ts, COUNT(*) n, MAX(distance) mx,
                 SUM(CASE WHEN distance > 6000 THEN 1 ELSE 0 END) dx6,
                 SUM(CASE WHEN distance > 10000 THEN 1 ELSE 0 END) dx10
          FROM reporters_log WHERE {WHERE_OK} GROUP BY timestamp) s
    LEFT JOIN solar_log l ON l.timestamp = s.ts ORDER BY s.ts""", bad_args).fetchall()
N = len(rows)
ts = [r[0] for r in rows]
day = np.array([r[0][:10] for r in rows])
hour = np.array([int(r[0][11:13]) for r in rows])
n_rep = np.array([r[1] for r in rows], float)
mx = np.array([r[2] or 0 for r in rows], float)
dx6 = np.array([r[3] for r in rows]) > 0
dx10 = np.array([r[4] for r in rows]) > 0
kidx = np.array([np.nan if r[5] is None else r[5] for r in rows], float)
aidx = np.array([np.nan if r[6] is None else r[6] for r in rows], float)
muf = np.array([np.nan if (r[7] is None or r[7] <= 0) else r[7] for r in rows], float)
sfi = np.array([np.nan if (r[8] is None or r[8] <= 0) else r[8] for r in rows], float)
fof2 = np.array([np.nan if (r[9] is None or r[9] <= 0) else r[9] for r in rows], float)
days = sorted(set(day))
D = len(days)
dix = {d: i for i, d in enumerate(days)}
didx = np.array([dix[d] for d in day])

macro("nSnap", fmt(N))
macro("nDays", D)
macro("dateFrom", days[0])
macro("dateTo", days[-1])
macro("meanRep", f"{n_rep.mean():.1f}")
macro("medRep", f"{np.median(n_rep):.0f}")
macro("shareDXsix", f"{100 * dx6.mean():.1f}")
dayDX6 = {d for d, f in zip(day, dx6) if f}
dayDX10 = {d for d, f in zip(day, dx10) if f}
macro("daysDXsix", len(dayDX6))
macro("pctDaysDXsix", f"{100 * len(dayDX6) / D:.0f}")
macro("daysDXten", len(dayDX10))
macro("pctDaysDXten", f"{100 * len(dayDX10) / D:.0f}")
macro("solarZeroSFI", int(sum(1 for r in rows if r[8] is not None and r[8] <= 0)))
macro("nFof2", fmt(int(np.isfinite(fof2).sum())))
macro("pctFof2", f"{100 * np.isfinite(fof2).mean():.0f}")

# gaps in the snapshot series
tt = [np.datetime64(t.replace(" ", "T")) for t in ts]
gaps = [(tt[i + 1] - tt[i]) / np.timedelta64(1, "m") for i in range(len(tt) - 1)]
big = [g for g in gaps if g > 30]
macro("nGaps", len(big))
macro("gapHours", f"{sum(big) / 60:.1f}")

# unique stations
macro("nStations", fmt(REPLAY.execute(f"SELECT COUNT(DISTINCT callsign) FROM reporters_log WHERE {WHERE_OK}", bad_args).fetchone()[0]))
macro("nRows", fmt(REPLAY.execute("SELECT COUNT(*) FROM reporters_log").fetchone()[0]))
sp = DATA.execute("SELECT COUNT(*), COUNT(DISTINCT date(timestamp)), MIN(timestamp), MAX(timestamp) FROM spots").fetchone()
macro("nSpots", fmt(sp[0]))
macro("nSpotDays", sp[1])
homeshare = DATA.execute("SELECT 100.0*SUM(tx_loc='KP20jg')/COUNT(*) FROM spots").fetchone()[0]
macro("homeShare", f"{homeshare:.0f}")
macro("nTxLoc", DATA.execute("SELECT COUNT(DISTINCT tx_loc) FROM spots").fetchone()[0])

# ------------------------------------------------------------------ 3. diurnal pattern
exp_hour = np.array([n_rep[hour == h].mean() for h in range(24)])
med_h = np.array([np.median(n_rep[hour == h]) for h in range(24)])
q25_h = np.array([np.percentile(n_rep[hour == h], 25) for h in range(24)])
q75_h = np.array([np.percentile(n_rep[hour == h], 75) for h in range(24)])


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


dx_h = np.array([100 * dx6[hour == h].mean() for h in range(24)])
dx_h_ci = np.array([[100 * x for x in wilson(int(dx6[hour == h].sum()), int((hour == h).sum()))] for h in range(24)])
dx3_h = np.array([100 * (mx[hour == h] > 3000).mean() for h in range(24)])
macro("busyFrom", int(np.argmax(med_h >= 50)))
macro("hourMinMed", f"{med_h.min():.0f}")
macro("hourMaxMed", f"{med_h.max():.0f}")
macro("quietMedMax", f"{med_h[1:5].max():.0f}")
macro("busyMedAvg", f"{np.mean(med_h[8:17]):.0f}")
macro("qLoMid", f"{np.mean(q25_h[8:17]):.0f}"); macro("qHiMid", f"{np.mean(q75_h[8:17]):.0f}")
macro("busyTo", int(max(h for h in range(24) if med_h[h] >= 50)))
order = np.argsort(-dx3_h)
macro("peakThreeHour", int(order[0]))
macro("peakThreePct", f"{dx3_h[order[0]]:.0f}")
macro("lowThreeHour", int(np.argmin(dx3_h)))
macro("lowThreePct", f"{dx3_h.min():.0f}")
macro("dxPeakHour", int(np.argmax(dx_h)))
macro("dxPeakPct", f"{dx_h.max():.0f}")
macro("dxLowHour", int(np.argmin(dx_h)))
macro("dxLowPct", f"{dx_h.min():.0f}")
for h in (5, 8, 12, 19):
    macro(f"dxAt{h}", f"{dx_h[h]:.0f}")
    macro(f"dxThreeAt{h}", f"{dx3_h[h]:.0f}")

# Fig 1: heatmap
grid_n = np.full((24, D), np.nan)
cnt = collections.defaultdict(list)
for i in range(N):
    cnt[(hour[i], didx[i])].append(n_rep[i])
for (h, d), v in cnt.items():
    grid_n[h, d] = np.mean(v)
fig, ax = plt.subplots(figsize=(W, 2.9))
im = ax.imshow(grid_n, aspect="auto", origin="upper", cmap="viridis", interpolation="nearest",
               vmax=np.nanpercentile(grid_n, 97))
ticks = [i for i, d in enumerate(days) if d.endswith("-01")]
ax.set_xticks(ticks)
ax.set_xticklabels([days[i][:7] for i in ticks])
ax.set_yticks(range(0, 24, 3))
ax.set_yticklabels([f"{h:02d}" for h in range(0, 24, 3)])
ax.set_ylabel("UTC hour")
ax.grid(False)
cb = fig.colorbar(im, ax=ax, pad=0.01, fraction=0.04)
cb.set_label("stations heard (mean per hour)")
ax.set_title("Band-open heatmap, 20 m, OH2GAX")
fig.savefig(os.path.join(OUT, "fig_heatmap.pdf"))
plt.close(fig)

# Fig 2: typical day + DX share
fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.5))
hrs = np.arange(24)
a1.fill_between(hrs, q25_h, q75_h, color=BLUE, alpha=0.25, label="25–75 %")
a1.plot(hrs, med_h, color=BLUE, lw=1.6, label="median")
a1.set_xlabel("UTC hour"); a1.set_ylabel("stations heard in 60 min")
a1.set_xlim(0, 23); a1.legend(frameon=False, loc="upper left"); a1.set_title("(a) Typical day")
a2.bar(hrs, dx_h, color=GREEN, alpha=0.85, label=r"$\geq$1 station $>$ 6000 km")
a2.errorbar(hrs, dx_h, yerr=[dx_h - dx_h_ci[:, 0], dx_h_ci[:, 1] - dx_h], fmt="none", ecolor="black", lw=0.6, capsize=1.2)
a2.plot(hrs, dx3_h, color=AMBER, lw=1.3, marker="o", ms=2.5, label=r"$\geq$1 station $>$ 3000 km")
a2.set_xlabel("UTC hour"); a2.set_ylabel("share of snapshots (%)"); a2.set_xlim(-0.6, 23.6)
a2.legend(frameon=False, loc="upper left", fontsize=6.3); a2.set_title("(b) Long-distance windows (95 % Wilson CI)")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_diurnal.pdf"))
plt.close(fig)

# ------------------------------------------------------------------ 4. stations: zones, bearing, SNR
pair = {}
for call, grid, dist, snr in REPLAY.execute(f"SELECT callsign, grid, distance, snr FROM reporters_log WHERE {WHERE_OK}", bad_args):
    p = pair.setdefault((call, grid), [[], []])
    p[0].append(dist); p[1].append(snr)
pairs = []
for (call, grid), (dl, sl) in pair.items():
    lat, lon = w._grid_to_latlon(grid or "")
    br = bearing(HOME_LAT, HOME_LON, lat, lon) if lat is not None else None
    pairs.append({"call": call, "grid": grid, "dist": float(np.median(dl)), "maxd": max(dl), "snr": float(np.median(sl)),
                  "bestsnr": max(sl), "n": len(dl), "bearing": br, "zone": zone_of(call, grid)})
macro("nPairs", fmt(len(pairs)))
zrows = []
tot = len(pairs)
for z in ["europe", "n_america", "africa", "pacific", "s_america", "asia", "other"]:
    g = [p for p in pairs if p["zone"] == z]
    if not g:
        continue
    zrows.append((ZONE_NAME[z], len(g), 100 * len(g) / tot, np.median([p["dist"] for p in g]),
                  max(p["maxd"] for p in g), max(p["bestsnr"] for p in g)))
    macro(f"zn{z.replace('_', '')}", len(g))
    macro(f"zp{z.replace('_', '')}", f"{100 * len(g) / tot:.1f}")
sw = sum(1 for p in pairs if p["bearing"] is not None and 180 <= p["bearing"] < 270)
macro("swPct", f"{100 * sw / tot:.0f}")
ne = sum(1 for p in pairs if p["bearing"] is not None and (p["bearing"] < 135 or p["bearing"] >= 315 and False))
sectors = collections.Counter(int(p["bearing"] // 45) for p in pairs if p["bearing"] is not None)
names8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
macro("eastPct", f"{100 * (sectors[1] + sectors[2]) / tot:.0f}")
macro("northPct", f"{100 * (sectors[0] + sectors[7]) / tot:.0f}")
macro("secSW", sectors[5]); macro("secS", sectors[4]); macro("secW", sectors[6]); macro("secSE", sectors[3])

# top-N share of reporting
tot_rows = REPLAY.execute(f"SELECT COUNT(*) FROM reporters_log WHERE {WHERE_OK}", bad_args).fetchone()[0]
top_calls = REPLAY.execute(f"SELECT callsign, COUNT(*) c FROM reporters_log WHERE {WHERE_OK} GROUP BY callsign ORDER BY c DESC", bad_args).fetchall()
cum = 0; k = 0
for c, n in top_calls:
    cum += n; k += 1
    if cum >= 0.5 * tot_rows:
        break
macro("halfStations", k)
macro("topStations", ", ".join(c for c, _ in top_calls[:3]))
macro("topStationSnaps", fmt(top_calls[0][1]))

# distance bands vs SNR
bands = [(0, 1500, "< 1\\,500"), (1500, 3000, "1\\,500--3\\,000"), (3000, 6000, "3\\,000--6\\,000"),
         (6000, 10000, "6\\,000--10\\,000"), (10000, 20100, "$>$ 10\\,000")]
brows = []
for lo, hi, lab in bands:
    g = [p for p in pairs if lo <= p["dist"] < hi]
    sn = [p["snr"] for p in g]
    brows.append((lab, len(g), np.median(sn) if sn else np.nan, np.percentile(sn, 25) if sn else np.nan,
                  np.percentile(sn, 75) if sn else np.nan, max(p["bestsnr"] for p in g) if g else np.nan))
d_s = np.array([p["dist"] for p in pairs]); s_s = np.array([p["snr"] for p in pairs])
macro("corrDistSNR", f"{np.corrcoef(np.log10(d_s + 1), s_s)[0, 1]:.2f}")
macro("snrMed", f"{np.median(s_s):.0f}")

# Fig 3: polar scatter bearing/distance
fig = plt.figure(figsize=(W, 3.1))
axp = fig.add_subplot(1, 2, 1, projection="polar")
axp.set_theta_zero_location("N"); axp.set_theta_direction(-1)
cmap = {"europe": BLUE, "n_america": AMBER, "africa": GREEN, "pacific": RED, "s_america": "#805ad5", "asia": "#319795", "other": GREY}
for z in cmap:
    g = [p for p in pairs if p["zone"] == z and p["bearing"] is not None]
    if g:
        axp.scatter([math.radians(p["bearing"]) for p in g], [p["dist"] for p in g], s=[4 + 0.12 * min(p["n"], 200) for p in g],
                    c=cmap[z], alpha=0.55, linewidths=0, label=ZONE_NAME[z])
axp.set_rlabel_position(135); axp.set_rmax(16000); axp.set_rticks([2000, 6000, 10000, 14000])
axp.set_yticklabels(["2k", "6k", "10k", "14k"], fontsize=6); axp.tick_params(labelsize=7)
axp.set_title("(a) Bearing and distance (km)", fontsize=8, pad=10)
axp.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), fontsize=5.8, frameon=False, ncol=2, columnspacing=1.2, handletextpad=0.3)
ax2 = fig.add_subplot(1, 2, 2)
ax2.set_title("(b) Station SNR by distance band", fontsize=8)
data = [[p["snr"] for p in pairs if lo <= p["dist"] < hi] for lo, hi, _ in bands]
bp = ax2.boxplot(data, vert=True, showfliers=False, patch_artist=True, medianprops=dict(color="black", lw=1))
for patch in bp["boxes"]:
    patch.set(facecolor=BLUE, alpha=0.4, linewidth=0.6)
ax2.set_xticklabels(["<1.5k", "1.5–3k", "3–6k", "6–10k", ">10k"])
ax2.set_xlabel("distance (km)"); ax2.set_ylabel("median SNR per station (dB)")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_geography.pdf"))
plt.close(fig)

# ------------------------------------------------------------------ 5. long-distance windows per zone
ev = collections.defaultdict(set)         # zone -> {(day, hour)}
evdays = collections.defaultdict(set)
ev_rows = REPLAY.execute(f"SELECT timestamp, callsign, grid, distance FROM reporters_log WHERE distance > 6000 AND {WHERE_OK}", bad_args).fetchall()
best_zone = {}
for t, call, grid, dist in ev_rows:
    z = zone_of(call, grid)
    ev[z].add((t[:10], int(t[11:13])))
    evdays[z].add(t[:10])
    if dist > best_zone.get(z, (0,))[0]:
        best_zone[z] = (dist, call, t[:16])
days_with_hour = collections.defaultdict(set)
for d, h in zip(day, hour):
    days_with_hour[h].add(d)
prob = {z: np.array([len({dd for dd, hh in ev[z] if hh == h}) / max(len(days_with_hour[h]), 1) * 100 for h in range(24)])
        for z in ("n_america", "africa", "pacific")}
macro("daysNA", len(evdays["n_america"])); macro("daysAF", len(evdays["africa"])); macro("daysPA", len(evdays["pacific"]))
macro("daysSA", len(evdays["s_america"]))
zone_peaks = {}
for z, arr in prob.items():
    # best 3-hour window
    best = max(range(24), key=lambda h: sum(arr[(h + i) % 24] for i in range(3)))
    zone_peaks[z] = (best, sum(arr[(best + i) % 24] for i in range(3)) / 3, int(np.argmax(arr)), arr.max())
    macro(f"peak{z.replace('_', '')}", f"{best:02d}--{(best + 3) % 24:02d}")
    macro(f"peakpct{z.replace('_', '')}", f"{arr.max():.0f}")
    macro(f"peakh{z.replace('_', '')}", f"{int(np.argmax(arr)):02d}")
fig, axs = plt.subplots(1, 3, figsize=(W, 2.0), sharey=True)
for ax, (z, col) in zip(axs, (("n_america", AMBER), ("africa", GREEN), ("pacific", RED))):
    ax.bar(range(24), prob[z], color=col, alpha=0.85)
    ax.set_title(ZONE_NAME[z], fontsize=8); ax.set_xlabel("UTC hour"); ax.set_xticks(range(0, 24, 6)); ax.set_xlim(-0.6, 23.6)
axs[0].set_ylabel("% of days with a station\n> 6000 km")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_zonehours.pdf"))
plt.close(fig)

# ------------------------------------------------------------------ 6. months
months = sorted({d[:7] for d in days})
mrows = []
uniq_m = dict(REPLAY.execute(f"SELECT substr(timestamp,1,7), COUNT(DISTINCT callsign) FROM reporters_log WHERE {WHERE_OK} GROUP BY 1", bad_args).fetchall())
dmask = (hour >= 8) & (hour <= 16)
mon = np.array([d[:7] for d in day])
for m in months:
    sel = mon == m
    sd = sel & dmask
    mrows.append({"m": m, "snaps": int(sel.sum()), "days": len({d for d in day[sel]}), "uniq": uniq_m.get(m, 0),
                  "medday": float(np.median(n_rep[sd])), "mufday": float(np.nanmedian(muf[sd])), "sfi": float(np.nanmean(sfi[sel])),
                  "dx": 100 * float(dx6[sel].mean())})
full = [r for r in mrows if r["days"] >= 20]
macro("monBestName", max(full, key=lambda r: r["medday"])["m"]); macro("monBest", f"{max(full, key=lambda r: r['medday'])['medday']:.0f}")
macro("monWorstName", min(full, key=lambda r: r["medday"])["m"]); macro("monWorst", f"{min(full, key=lambda r: r['medday'])['medday']:.0f}")
for r in mrows:
    macro("mon" + r["m"].replace("-", ""), f"{r['medday']:.0f}")
    macro("monuniq" + r["m"].replace("-", ""), r["uniq"])
    macro("monmuf" + r["m"].replace("-", ""), f"{r['mufday']:.1f}")
    macro("monsfi" + r["m"].replace("-", ""), f"{r['sfi']:.0f}")
sfi_m = [r["sfi"] for r in full]; med_m = [r["medday"] for r in full]; muf_m = [r["mufday"] for r in full]
macro("corrMonSFI", f"{np.corrcoef(sfi_m, med_m)[0, 1]:.2f}")
macro("corrMonMUF", f"{np.corrcoef(muf_m, med_m)[0, 1]:.2f}")
fig, ax = plt.subplots(figsize=(W, 2.5))
x = np.arange(len(mrows))
ax.bar(x, [r["medday"] for r in mrows], color=BLUE, alpha=0.75, label="median stations heard, 08–16 UTC")
ax.set_ylabel("stations heard"); ax.set_xticks(x); ax.set_xticklabels([r["m"] for r in mrows])
axr = ax.twinx(); axr.spines["right"].set_visible(True); axr.grid(False)
axr.plot(x, [r["mufday"] for r in mrows], color=AMBER, marker="o", lw=1.5, label="median Juliusruh MUF, 08–16 UTC (MHz)")
axr2 = ax.twinx(); axr2.spines["right"].set_position(("outward", 38)); axr2.spines["right"].set_visible(True); axr2.grid(False)
axr2.plot(x, [r["sfi"] for r in mrows], color=GREEN, marker="s", lw=1.2, ls="--", label="mean SFI")
axr.set_ylabel("MUF (MHz)", color=AMBER); axr2.set_ylabel("SFI", color=GREEN)
h1, l1 = ax.get_legend_handles_labels(); h2, l2 = axr.get_legend_handles_labels(); h3, l3 = axr2.get_legend_handles_labels()
ax.legend(h1 + h2 + h3, l1 + l2 + l3, loc="upper center", fontsize=6.2, frameon=False, ncol=1, bbox_to_anchor=(0.5, 1.28))
ax.set_title("November: 6 days only", fontsize=7, loc="right", color=GREY)
fig.savefig(os.path.join(OUT, "fig_monthly.pdf"))
plt.close(fig)

# ------------------------------------------------------------------ 7. space weather (index with day-block bootstrap)
rng = np.random.default_rng(20261106)
B = 2000
exp_snap = exp_hour[hour]


def day_sums(mask, *arrays):
    out = []
    for arr in arrays:
        s = np.zeros(D)
        np.add.at(s, didx[mask], arr[mask])
        out.append(s)
    return out


def binned(values, edges, labels):
    res = []
    for (lo, hi), lab in zip(zip(edges[:-1], edges[1:]), labels):
        m = np.isfinite(values) & (values >= lo) & (values < hi)
        if m.sum() < 30:
            continue
        num, den, cnt_, dxs = day_sums(m, n_rep, exp_snap, np.ones(N), dx6.astype(float))
        idx = rng.integers(0, D, (B, D))
        i_b = 100 * num[idx].sum(1) / np.maximum(den[idx].sum(1), 1e-9)
        d_b = 100 * dxs[idx].sum(1) / np.maximum(cnt_[idx].sum(1), 1)
        res.append({"lab": lab, "n": int(m.sum()), "mean": float(n_rep[m].mean()),
                    "idx": float(100 * num.sum() / den.sum()), "lo": float(np.percentile(i_b, 2.5)), "hi": float(np.percentile(i_b, 97.5)),
                    "dx": float(100 * dxs.sum() / cnt_.sum()), "dlo": float(np.percentile(d_b, 2.5)), "dhi": float(np.percentile(d_b, 97.5))})
    return res


kb = binned(np.where(np.isnan(kidx), np.nan, np.minimum(np.floor(kidx), 5)), [0, 1, 2, 3, 4, 5, 6], ["0", "1", "2", "3", "4", "5+"])
ab = binned(aidx, [0, 8, 16, 30, 1000], ["0--7", "8--15", "16--29", "$\\geq$ 30"])
mb = binned(muf, [0, 12, 16, 20, 24, 28, 100], ["$<$ 12", "12--16", "16--20", "20--24", "24--28", "$\\geq$ 28"])
for tag, res in (("K", kb), ("A", ab), ("MUF", mb)):
    for r in res:
        pass
macro("kIdxZero", f"{kb[0]['idx']:.0f}"); macro("kIdxFive", f"{kb[-1]['idx']:.0f}")
macro("kDxZero", f"{kb[0]['dx']:.0f}"); macro("kDxOne", f"{kb[1]['dx']:.0f}")
macro("kDxHi", f"{np.mean([r['dx'] for r in kb[3:]]):.0f}")
macro("aDxLow", f"{ab[0]['dx']:.0f}"); macro("aDxHigh", f"{ab[-1]['dx']:.1f}")
macro("aIdxHigh", f"{ab[-1]['idx']:.0f}"); macro("aIdxLow", f"{ab[0]['idx']:.0f}")
macro("mufIdxLow", f"{mb[0]['idx']:.0f}"); macro("mufIdxMid", f"{mb[3]['idx']:.0f}")
macro("mufDxLow", f"{mb[0]['dx']:.0f}"); macro("mufDxMid", f"{mb[3]['dx']:.0f}")


def corr_ci(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    xs, ys = x[ok], y[ok]
    dd = didx[ok]
    S = {k: np.zeros(D) for k in ("n", "x", "y", "xx", "yy", "xy")}
    for k, v in (("n", np.ones(len(xs))), ("x", xs), ("y", ys), ("xx", xs * xs), ("yy", ys * ys), ("xy", xs * ys)):
        np.add.at(S[k], dd, v)

    def pearson(sel):
        n = S["n"][sel].sum(); sx = S["x"][sel].sum(); sy = S["y"][sel].sum()
        sxx = S["xx"][sel].sum(); syy = S["yy"][sel].sum(); sxy = S["xy"][sel].sum()
        cov = sxy - sx * sy / n; vx = sxx - sx * sx / n; vy = syy - sy * sy / n
        return cov / math.sqrt(vx * vy)
    r0 = pearson(slice(None))
    bs = []
    for _ in range(1000):
        sel = rng.integers(0, D, D)
        n = S["n"][sel].sum(); sx = S["x"][sel].sum(); sy = S["y"][sel].sum()
        sxx = S["xx"][sel].sum(); syy = S["yy"][sel].sum(); sxy = S["xy"][sel].sum()
        bs.append((sxy - sx * sy / n) / math.sqrt((sxx - sx * sx / n) * (syy - sy * sy / n)))
    return r0, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


rel = n_rep / np.maximum(exp_snap, 1e-9)
r_raw = corr_ci(n_rep, muf); r_rel = corr_ci(rel, muf)
r_sfi_raw = corr_ci(n_rep, sfi); r_sfi_rel = corr_ci(rel, sfi)
r_k_rel = corr_ci(rel, kidx)
macro("rMufRaw", f"{r_raw[0]:.2f}"); macro("rMufRawLo", f"{r_raw[1]:.2f}"); macro("rMufRawHi", f"{r_raw[2]:.2f}")
macro("rMufRel", f"{r_rel[0]:.2f}"); macro("rMufRelLo", f"{r_rel[1]:.2f}"); macro("rMufRelHi", f"{r_rel[2]:.2f}")
macro("rSfiRel", f"{r_sfi_rel[0]:.2f}"); macro("rSfiRelLo", f"{r_sfi_rel[1]:.2f}"); macro("rSfiRelHi", f"{r_sfi_rel[2]:.2f}")
macro("rSfiRaw", f"{r_sfi_raw[0]:.2f}")
macro("rKRel", f"{r_k_rel[0]:.2f}"); macro("rKRelLo", f"{r_k_rel[1]:.2f}"); macro("rKRelHi", f"{r_k_rel[2]:.2f}")

fig, axs = plt.subplots(1, 3, figsize=(W, 2.5))
for ax, res, title, xl in ((axs[0], mb, "(a) Juliusruh MUF (MHz)", "MUF"), (axs[1], kb, "(b) K-index", "K"), (axs[2], ab, "(c) A-index", "A")):
    xs = np.arange(len(res))
    idxv = np.array([r["idx"] for r in res]); lo = np.array([r["lo"] for r in res]); hi = np.array([r["hi"] for r in res])
    ax.bar(xs, idxv, color=[BLUE if v >= 100 else AMBER for v in idxv], alpha=0.8)
    ax.errorbar(xs, idxv, yerr=[idxv - lo, hi - idxv], fmt="none", ecolor="black", lw=0.7, capsize=1.5)
    ax.axhline(100, color=GREY, ls="--", lw=0.8)
    ax.set_xticks(xs); ax.set_xticklabels([r["lab"].replace("$", "").replace("\\geq", "≥").replace("<", "<").replace("--", "–").replace(" ", "") for r in res], fontsize=5.8, rotation=35 if len(res) > 5 and res is mb else 0)
    ax.set_title(title); ax.set_ylabel("index (100 = typical for the hour)" if ax is axs[0] else "")
    a2 = ax.twinx(); a2.grid(False); a2.spines["right"].set_visible(True)
    a2.plot(xs, [r["dx"] for r in res], color=GREEN, marker="o", ms=3, lw=1.2)
    a2.set_ylim(0, 40)
    if ax is axs[2]:
        a2.set_ylabel("% snapshots with a station > 6000 km", color=GREEN, fontsize=6.5)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_spaceweather.pdf"))
plt.close(fig)

# ------------------------------------------------------------------ 8. case study: 24 Jun - 9 Jul
case_days = [d for d in days if "2026-06-24" <= d <= "2026-07-09"]
cs = []
case_tab = []
for d in case_days:
    m = (day == d)
    md = m & dmask
    if md.sum() < 20:
        continue
    sl = REPLAY.execute("SELECT MAX(kindex), MAX(aindex), AVG(CASE WHEN sfi>0 THEN sfi END), group_concat(xray) FROM solar_log WHERE substr(timestamp,1,10)=?", (d,)).fetchone()
    letters = [x.strip()[:1] for x in (sl[3] or "").split(",") if x.strip()]
    xcls = max(letters, key=lambda ch: "ABCMX".index(ch) if ch in "ABCMX" else -1) if letters else ""
    rep = float(n_rep[md].mean())
    cs.append({"d": d, "rep": rep, "k": float(sl[0] or 0), "a": float(sl[1] or 0), "sfi": float(sl[2] or np.nan), "dx": int(dx6[m].sum() > 0)})
    case_tab.append((d, float(sl[2] or np.nan), float(sl[0] or 0), float(sl[1] or 0), xcls, rep))
fig, ax = plt.subplots(figsize=(W, 2.6))
x = np.arange(len(cs))
ax.bar(x, [c["rep"] for c in cs], color=BLUE, alpha=0.75, label="mean stations heard, 08–16 UTC")
ax.set_xticks(x); ax.set_xticklabels([c["d"][5:] for c in cs], rotation=60, fontsize=6.5)
ax.set_ylabel("stations heard")
ar = ax.twinx(); ar.grid(False); ar.spines["right"].set_visible(True)
ar.plot(x, [c["k"] for c in cs], color=RED, marker="o", ms=3, lw=1.3, label="max K-index")
ar.set_ylabel("max K-index", color=RED); ar.set_ylim(0, 9)
ar2 = ax.twinx(); ar2.spines["right"].set_position(("outward", 36)); ar2.spines["right"].set_visible(True); ar2.grid(False)
ar2.plot(x, [c["sfi"] for c in cs], color=GREEN, marker="s", ms=2.5, lw=1.0, ls="--", label="mean SFI")
ar2.set_ylabel("SFI", color=GREEN)
h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ar.get_legend_handles_labels(); h3, l3 = ar2.get_legend_handles_labels()
ax.legend(h1 + h2 + h3, l1 + l2 + l3, loc="upper right", fontsize=6.3, frameon=False)
fig.savefig(os.path.join(OUT, "fig_case.pdf"))
plt.close(fig)
worst_case = min(cs, key=lambda c: c["rep"])
macro("caseWorstDay", worst_case["d"]); macro("caseWorstRep", f"{worst_case['rep']:.0f}")
cw = [c for c in cs if c["d"] == "2026-07-04"]
if cw:
    macro("caseJulyK", f"{cw[0]['k']:.0f}"); macro("caseJulyA", f"{cw[0]['a']:.0f}"); macro("caseJulyRep", f"{cw[0]['rep']:.0f}")
macro("caseTypRep", f"{np.median([float(np.mean(n_rep[(day == d) & dmask])) for d in days if ((day == d) & dmask).sum() > 20]):.0f}")
macro("sfiMax", f"{np.nanmax(sfi):.0f}")
macro("sfiMin", f"{np.nanmin(sfi):.0f}")
macro("covDays", f"{N * 10 / 1440:.0f}")
macro("covPct", f"{100 * N * 10 / 1440 / D:.0f}")

# ------------------------------------------------------------------ 9. records
top = {}
for call, grid, dist, t in REPLAY.execute(f"SELECT callsign, grid, distance, timestamp FROM reporters_log WHERE {WHERE_OK} ORDER BY distance DESC, timestamp ASC LIMIT 400", bad_args):
    if call not in top:
        top[call] = (grid, dist, t)
    if len(top) >= 8:
        break
rec_rows = [(c, g, w.callsign_to_country(c, g or ""), d, t[:16]) for c, (g, d, t) in top.items()]
macro("recBest", fmt(rec_rows[0][3])); macro("recBestCall", rec_rows[0][0]); macro("recBestDate", rec_rows[0][4][:10])
macro("nOceania", sum(1 for p in pairs if p["zone"] == "pacific"))

# ------------------------------------------------------------------ 10. stored Best DX vs replay data
sp_day = dict(DATA.execute("SELECT substr(timestamp,1,10), MAX(max_distance) FROM spots GROUP BY 1").fetchall())
rp_day = dict(REPLAY.execute(f"SELECT substr(timestamp,1,10), MAX(distance) FROM reporters_log WHERE {WHERE_OK} GROUP BY 1", bad_args).fetchall())
cmp_days = [d for d in sp_day if d in rp_day]
under = [d for d in cmp_days if rp_day[d] > sp_day[d]]
macro("cmpDays", len(cmp_days)); macro("underDays", len(under)); macro("underPct", f"{100 * len(under) / len(cmp_days):.0f}")
ex = max(under, key=lambda d: rp_day[d] - sp_day[d])
macro("underExDay", ex); macro("underExStored", fmt(sp_day[ex])); macro("underExReplay", fmt(rp_day[ex]))

# ------------------------------------------------------------------ tables
T = []


def tabular(cols, head, body, caption, label, widths=None, notes=None):
    s = ["\\begin{table}[htbp]\\centering\\small", f"\\caption{{{caption}}}\\label{{{label}}}", f"\\begin{{tabular}}{{{cols}}}", "\\toprule",
         " & ".join(head) + " \\\\", "\\midrule"]
    s += [" & ".join(str(c) for c in r) + " \\\\" for r in body]
    s += ["\\bottomrule", "\\end{tabular}"]
    if notes:
        s.append(f"\\\\[2pt]{{\\footnotesize {notes}}}")
    s.append("\\end{table}")
    T.append("\n".join(s))


tabular("lrrrrr", ["Region of station", "Stations", "Share (\\%)", "Median dist. (km)", "Max. dist. (km)", "Best SNR (dB)"],
        [(n, fmt(c), f"{p:.1f}", fmt(md), fmt(mx_), f"{bs:+.0f}") for n, c, p, md, mx_, bs in zrows],
        "Receiving stations by region (unique callsign--grid pairs, quality-controlled).", "tab:zones")

tabular("lrrrrr", ["Distance (km)", "Stations", "Median SNR (dB)", "Q1 (dB)", "Q3 (dB)", "Best SNR (dB)"],
        [(lab, fmt(c), f"{m:.0f}", f"{q1:.0f}", f"{q3:.0f}", f"{b:+.0f}") for lab, c, m, q1, q3, b in brows],
        "Station SNR by distance band (median over the snapshots in which a station was heard).", "tab:snr")

zl = []
for z, nm in (("n_america", "North America"), ("africa", "Africa"), ("pacific", "Oceania"), ("s_america", "South America")):
    if z in evdays and evdays[z]:
        pk = zone_peaks.get(z)
        zl.append((nm, len(evdays[z]), f"{pk[0]:02d}--{(pk[0] + 3) % 24:02d}" if pk else "--",
                   f"{pk[3]:.0f}" if pk else "--", fmt(best_zone[z][0]), f"{best_zone[z][1]}, {best_zone[z][2][:10]}"))
tabular("lrrrrl", ["Region", "Days", "Best 3-h window (UTC)", "Peak share (\\%)", "Farthest (km)", "Station, date"],
        zl, "Days with at least one station beyond 6\\,000 km, by region.", "tab:dxzones",
        notes="Share = percentage of days with data in that UTC hour on which at least one station of the region beyond 6\\,000 km was heard.")

tabular("lrrrrrr", ["Month", "Days", "Snapshots", "Stations", "Median stations 08--16 UTC", "Median MUF (MHz)", "Mean SFI"],
        [(r["m"], r["days"], fmt(r["snaps"]), r["uniq"], f"{r['medday']:.0f}", f"{r['mufday']:.1f}", f"{r['sfi']:.0f}") for r in mrows],
        "Monthly summary. Stations = distinct callsigns heard in the month.", "tab:months")


def swtab(res, name, label, cap):
    tabular("lrrrrrr", [name, "Snapshots", "Mean stations", "Index", "95 \\% CI", "DX share (\\%)", "95 \\% CI"],
            [(r["lab"], fmt(r["n"]), f"{r['mean']:.0f}", f"{r['idx']:.0f}", f"{r['lo']:.0f}--{r['hi']:.0f}", f"{r['dx']:.0f}", f"{r['dlo']:.0f}--{r['dhi']:.0f}") for r in res],
            cap, label)


swtab(mb, "MUF (MHz)", "tab:muf", "Reporting versus Juliusruh MUF. Index: stations heard relative to the typical value for the same UTC hour (100 = typical); DX share: snapshots with a station beyond 6\\,000 km. Confidence intervals by day-block bootstrap.")
swtab(kb, "K-index", "tab:k", "Reporting versus the K-index (day-block bootstrap intervals).")
swtab(ab, "A-index", "tab:a", "Reporting versus the A-index (day-block bootstrap intervals).")

tabular("lrrrrl", ["Date", "SFI", "Max K", "Max A", "Max X-ray", "Stations 08--16 UTC"],
        [(d, f"{s_:.0f}", f"{k:.0f}", f"{a:.0f}", x or "--", f"{r:.0f}") for d, s_, k, a, x, r in case_tab],
        "The period 24 June -- 9 July 2026: space weather and reporting (daytime mean).", "tab:case")

tabular("rlllrl", ["\\#", "Station", "Region", "Grid", "Distance (km)", "When (UTC)"],
        [(i + 1, c.replace("/", "\\slash "), cn, g, fmt(d), t) for i, (c, g, cn, d, t) in enumerate(rec_rows)],
        "The eight farthest stations (one row per station, quality-controlled).", "tab:records")

for t_ in T:
    lab_ = re.search(r"\\label\{tab:(\w+)\}", t_).group(1)
    open(os.path.join(OUT, f"tab_{lab_}.tex"), "w").write(t_ + "\n")
open(os.path.join(OUT, "numbers.tex"), "w").write("\n".join(f"\\newcommand{{\\{k.translate(DIG)}}}{{{v}}}" for k, v in NUM.items()) + "\n")
json.dump(STAT, open(os.path.join(OUT, "stats.json"), "w"), indent=1, default=str)
print(f"{len(NUM)} macros, {len(T)} tables written to {OUT}")
