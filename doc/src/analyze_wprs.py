#!/usr/bin/env python3
"""
analyze_wprs.py -- analysis and figures for the WPRS paper (position beaconing with WSPR).
Needs out/stats.json from analyze.py (shared station numbers) and the two SQLite databases.
Writes out/wprs_numbers.tex, out/wprs_tables.tex, out/fig_wprs_*.pdf
"""
from __future__ import annotations
import re, collections, datetime as dt, json, math, os, sqlite3, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, REPO)
import wspr_logger as w

DATA = sqlite3.connect(f"file:{os.path.join(REPO, 'wspr_data.db')}?mode=ro&immutable=1", uri=True)
REPLAY = sqlite3.connect(f"file:{os.path.join(REPO, 'wspr_replay.db')}?mode=ro&immutable=1", uri=True)
plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 8, "axes.titlesize": 8.5,
                     "axes.labelsize": 8, "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25,
                     "grid.linewidth": 0.5, "figure.dpi": 150, "savefig.bbox": "tight", "pdf.fonttype": 42})
BLUE, AMBER, GREEN, RED, GREY = "#2b6cb0", "#d9822b", "#2f855a", "#c53030", "#718096"
W = 6.3
DIG = str.maketrans("0123456789", "ABCDEFGHIJ")
NUM = {}


def macro(k, v):
    NUM[k] = str(v)


def fmt(n, nd=0):
    return f"{n:,.{nd}f}".replace(",", "\\,")


def hav(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(a))


# ------------------------------------------------------------------ load fixes
rows = DATA.execute("SELECT timestamp, tx_loc, lat, lon, reporter_count, max_distance FROM spots ORDER BY timestamp").fetchall()
T = [dt.datetime.fromisoformat(r[0]) for r in rows]
loc = [r[1] for r in rows]; lat = np.array([r[2] for r in rows]); lon = np.array([r[3] for r in rows])
nrep = np.array([r[4] for r in rows]); maxd = np.array([r[5] for r in rows])
N = len(rows)
HOME = "KP20jg"
hlat, hlon = [(r[2], r[3]) for r in rows if r[1] == HOME][0]
dist_home = np.array([hav(hlat, hlon, a, b) for a, b in zip(lat, lon)])
days = sorted({t.date().isoformat() for t in T})
D_all = (T[-1].date() - T[0].date()).days + 1
macro("wFixes", fmt(N)); macro("wFirst", T[0].date().isoformat()); macro("wLast", T[-1].date().isoformat())
macro("wSpan", D_all); macro("wDaysWith", len(days))
macro("wLocs", len(set(loc)))

homeflag_all = np.array([l == HOME for l in loc])
# ---- Maidenhead geometry at home latitude
dlat_km = 2.5 / 60 * 111.19
dlon_km = 5.0 / 60 * 111.19 * math.cos(math.radians(hlat))
macro("wSqNS", f"{dlat_km:.1f}"); macro("wSqEW", f"{dlon_km:.1f}")
rms = math.sqrt((dlat_km ** 2 + dlon_km ** 2) / 12)
half_diag = 0.5 * math.hypot(dlat_km, dlon_km)
macro("wRMS", f"{rms:.1f}"); macro("wHalfDiag", f"{half_diag:.1f}")
macro("wSqArea", f"{dlat_km * dlon_km:.1f}")
macro("wBits", f"{math.log2(18 * 18 * 10 * 10 * 24 * 24):.1f}")
macro("wNSq", fmt(18 * 18 * 10 * 10 * 24 * 24))
macro("wBitsFour", f"{math.log2(18 * 18 * 10 * 10):.1f}")
fe_lat, fe_lon = 1.0 * 111.19, 2.0 * 111.19 * math.cos(math.radians(hlat))
macro("wSqFourNS", f"{1.0 * 111.19:.0f}"); macro("wSqFourEW", f"{2.0 * 111.19 * math.cos(math.radians(hlat)):.0f}")

# ---- cadence
minute_set = collections.Counter(t.minute % 10 for t in T)
macro("wMinuteOnly", ",".join(str(k) for k in minute_set))
gaps = np.array([(T[i + 1] - T[i]).total_seconds() / 60 for i in range(N - 1)])
macro("wGap10", f"{100 * np.mean(gaps == 10):.0f}")
macro("wGap30", f"{100 * np.mean(gaps <= 30):.0f}")
macro("wGap60", f"{100 * np.mean(gaps <= 60):.0f}")
macro("wGapMed", f"{np.median(gaps):.0f}")
macro("wGap6h", int(np.sum(gaps > 360)))
per_day = collections.Counter(t.date().isoformat() for t in T)
vals = np.array(list(per_day.values()))
macro("wPerDayMed", f"{np.median(vals):.0f}"); macro("wPerDayMax", int(vals.max()))
macro("wPerDayMean", f"{vals.mean():.0f}")
macro("wHeardPct", f"{100 * np.median(vals) / 144:.0f}")
macro("wTxFrac", f"{110.6 / 600 * 100:.1f}")

# ---- availability by UTC hour (active days: >= 20 fixes)
active = {d for d, n in per_day.items() if n >= 20}
macro("wActiveDays", len(active))
slot_has = {}
for t in T:
    slot_has[t.replace(second=0)] = 1
av = {k: np.zeros(24) for k in ("slot", "w30", "w60")}
tot = np.zeros(24)
fixset = sorted(slot_has)
import bisect
for d in sorted(active):
    d0 = dt.datetime.fromisoformat(d)
    for h in range(24):
        for m in range(2, 60, 10):
            s = d0 + dt.timedelta(hours=h, minutes=m)
            tot[h] += 1
            i = bisect.bisect_right(fixset, s) - 1
            if i >= 0:
                age = (s - fixset[i]).total_seconds() / 60
                av["slot"][h] += (age == 0)
                av["w30"][h] += (age <= 30)
                av["w60"][h] += (age <= 60)
for k in av:
    av[k] = 100 * av[k] / tot
macro("wAvSlotAvg", f"{np.mean(av['slot']):.0f}")
macro("wAv30Avg", f"{np.mean(av['w30']):.0f}"); macro("wAv60Avg", f"{np.mean(av['w60']):.0f}")
macro("wAv60Min", f"{av['w60'].min():.0f}"); macro("wAv60MinH", int(np.argmin(av['w60'])))
macro("wAv60Max", f"{av['w60'].max():.0f}")
macro("wAv30Min", f"{av['w30'].min():.0f}")
macro("wAvDay30", f"{np.mean(av['w30'][8:17]):.0f}")
macro("wAvDay60", f"{np.mean(av['w60'][8:17]):.0f}")
macro("wAvNight60", f"{np.mean(av['w60'][1:5]):.0f}")
macro("wAvSlotDay", f"{np.mean(av['slot'][8:17]):.0f}"); macro("wAvSlotNight", f"{np.mean(av['slot'][1:5]):.0f}")

fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.5), gridspec_kw={"width_ratios": [1.15, 1]})
dd = sorted(per_day)
xs = [dt.date.fromisoformat(d) for d in dd]
a1.bar(xs, [per_day[d] for d in dd], width=1.0, color=BLUE, alpha=0.8)
a1.axhline(144, color=GREY, ls="--", lw=0.8); a1.text(xs[0], 146, "144 = every 10 min", fontsize=6.3, color=GREY, va="bottom")
a1.set_ylabel("fixes per day (heard transmissions)"); a1.set_ylim(0, 165)
a1.set_title("(a) Position fixes per UTC day"); a1.tick_params(axis="x", rotation=30)
h = np.arange(24)
a2.plot(h, av["slot"], color=AMBER, lw=1.4, label="this slot")
a2.plot(h, av["w30"], color=GREEN, lw=1.4, label="within 30 min")
a2.plot(h, av["w60"], color=BLUE, lw=1.6, label="within 60 min")
a2.set_xlabel("UTC hour"); a2.set_ylabel("probability of a fix (%)"); a2.set_xlim(0, 23); a2.set_ylim(0, 102)
a2.legend(frameon=False, loc="lower right", fontsize=6.3); a2.set_title("(b) Availability by hour")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_wprs_avail.pdf")); plt.close(fig)

# ---- receiver count per fix
cnt = np.minimum(nrep, 30)
macro("wRepMed", f"{np.median(nrep):.0f}"); macro("wRepMean", f"{nrep.mean():.1f}")
macro("wRep1", f"{100 * np.mean(nrep == 1):.0f}"); macro("wRep3", f"{100 * np.mean(nrep >= 3):.0f}")
macro("wRep10", f"{100 * np.mean(nrep >= 10):.0f}")
hr = np.array([t.hour for t in T])
p3 = np.array([100 * np.mean(nrep[hr == k] >= 3) if (hr == k).sum() else np.nan for k in range(24)])
med_h = np.array([np.median(nrep[hr == k]) if (hr == k).sum() else np.nan for k in range(24)])
macro("wRep3Min", f"{np.nanmin(p3):.0f}"); macro("wRep3Max", f"{np.nanmax(p3):.0f}")
macro("wMedHMax", f"{np.nanmax(med_h):.0f}")
fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.3))
a1.hist(cnt, bins=np.arange(0.5, 31.5, 1), color=BLUE, alpha=0.8)
a1.set_xlabel("receiving stations per fix (30 = 30 or more)"); a1.set_ylabel("number of fixes"); a1.set_title("(a) Redundancy of a fix")
a2.bar(h, p3, color=GREEN, alpha=0.85)
a2.set_xlabel("UTC hour"); a2.set_ylabel("fixes heard by $\\geq$3 stations (%)"); a2.set_title("(b) Share of well-confirmed fixes"); a2.set_xlim(-0.6, 23.6)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_wprs_redundancy.pdf")); plt.close(fig)

# ------------------------------------------------------------------ positions
cls_edges = [(0, 1, "home square"), (1, 6, "adjacent squares ($\\leq$ 5 km)"), (6, 25, "5--25 km"), (25, 100, "25--100 km"), (100, 1e9, "$>$ 100 km")]
home_n = sum(1 for l in loc if l == HOME)
macro("wHomePct", f"{100 * home_n / N:.0f}")
crows = []
for lo_, hi_, lab in cls_edges:
    m = (dist_home >= lo_) & (dist_home < hi_) if lo_ else (dist_home < hi_)
    if lo_ == 0:
        m = np.array([l == HOME for l in loc])
    elif lo_ == 1:
        m = (dist_home > 0.5) & (dist_home < 6) & np.array([l != HOME for l in loc])
    crows.append((lab, int(m.sum()), 100 * m.sum() / N))
macro("wNear", f"{crows[1][2]:.0f}"); macro("wMid", f"{crows[2][2]:.0f}"); macro("wFar", f"{crows[3][2] + crows[4][2]:.0f}")
macro("wFar100", f"{crows[4][2]:.1f}")
macro("wMaxDist", fmt(dist_home.max()))
macro("wMaxLoc", loc[int(np.argmax(dist_home))])
macro("wMaxDate", T[int(np.argmax(dist_home))].date().isoformat())
macro("wKP20kg", f"{100 * sum(1 for l in loc if l == 'KP20kg') / N:.0f}")
# trips: fixes > 25 km from home, merged when separated by < 8 h
trips = []
cur = None
for i in range(N):
    if dist_home[i] > 25:
        if cur and (T[i] - cur["end"]).total_seconds() < 8 * 3600:
            cur["end"] = T[i]; cur["idx"].append(i)
        else:
            cur = {"start": T[i], "end": T[i], "idx": [i]}; trips.append(cur)
for tr in trips:
    ii = tr["idx"]
    tr["n"] = len(ii); tr["maxd"] = dist_home[ii].max(); tr["far"] = loc[ii[int(np.argmax(dist_home[ii]))]]
    tr["locs"] = len({loc[i] for i in ii}); tr["hours"] = (tr["end"] - tr["start"]).total_seconds() / 3600
macro("wTrips", len(trips))
big = sorted(trips, key=lambda t: t["start"])[:14]
macro("wTripDays", sum(1 for _ in {T[i].date() for tr in trips for i in tr["idx"]}))

# ---- the seasons side by side
yrs = sorted({t.year for t in T})
yr_arr = np.array([t.year for t in T])
srows = []
for y in yrs:
    sel = yr_arr == y
    dys = collections.Counter(t.date().isoformat() for t, k in zip(T, sel) if k)
    v = np.array(list(dys.values()))
    act = sum(1 for n_ in v if n_ >= 20)
    ntr = [tr for tr in trips if tr["start"].year == y]
    srows.append((str(y), len(dys), fmt(int(sel.sum())), f"{np.median(v):.0f}", act, f"{100 * np.mean(nrep[sel] >= 3):.0f}",
                  f"{np.median(nrep[sel]):.0f}", len(ntr), fmt(dist_home[sel].max()), f"{100 * np.mean(homeflag_all[sel]):.0f}"))
    macro(f"s{y}Fixes", fmt(int(sel.sum()))); macro(f"s{y}Days", len(dys)); macro(f"s{y}PerDay", f"{np.median(v):.0f}")
    macro(f"s{y}Trips", len(ntr)); macro(f"s{y}Max", fmt(dist_home[sel].max())); macro(f"s{y}Rep3", f"{100 * np.mean(nrep[sel] >= 3):.0f}")
    macro(f"s{y}Home", f"{100 * np.mean(homeflag_all[sel]):.0f}")

# speed estimate between consecutive fixes (10-min apart) -> bounds on movement
mv = []
for i in range(N - 1):
    if gaps[i] == 10 and loc[i] != loc[i + 1]:
        mv.append(hav(lat[i], lon[i], lat[i + 1], lon[i + 1]))
mv = np.array(mv)
macro("wMoves", len(mv)); macro("wMoveMed", f"{np.median(mv):.1f}"); macro("wMoveP90", f"{np.percentile(mv, 90):.0f}")
macro("wMoveMax", f"{mv.max():.0f}")
macro("wSpeedP90", f"{np.percentile(mv, 90) * 6:.0f}")
# fraction of 10-min steps where position changed
steps = int(np.sum(gaps == 10))
macro("wChangePct", f"{100 * len(mv) / steps:.0f}")
macro("wSteps", fmt(steps))

# ---- map figure
fig = plt.figure(figsize=(W, 3.5))
gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.0])
a1 = fig.add_subplot(gs[0]); a2 = fig.add_subplot(gs[1])
cnt_loc = collections.Counter(loc)
uloc = {l: (lat[loc.index(l)], lon[loc.index(l)]) for l in cnt_loc}
for l, (la, lo) in uloc.items():
    a1.add_patch(Rectangle((lo - 2.5 / 60, la - 1.25 / 60), 5 / 60, 2.5 / 60, fc=BLUE, ec="none", alpha=min(0.15 + 0.85 * math.log10(cnt_loc[l]) / 4.2, 1)))
# trip lines
for tr in big:
    ii = tr["idx"]
    a1.plot(lon[ii], lat[ii], color=AMBER, lw=0.7, alpha=0.8)
a1.plot(hlon, hlat, marker="*", color=RED, ms=9, ls="none", label="home KP20jg", zorder=5)
a1.set_aspect(1 / math.cos(math.radians(hlat)))
xl, xr = lon.min() - 0.2, lon.max() + 0.2; yb, yt = lat.min() - 0.1, lat.max() + 0.1
a1.set_xlim(xl, xr); a1.set_ylim(yb, yt)
for gx in np.arange(math.floor(xl / 2) * 2, xr + 2, 2):
    a1.axvline(gx, color="black", lw=0.5, alpha=0.5)
for gy in np.arange(math.floor(yb), yt + 1, 1):
    a1.axhline(gy, color="black", lw=0.5, alpha=0.5)
a1.set_xlabel("longitude (°E)"); a1.set_ylabel("latitude (°N)"); a1.set_title("(a) All 6-character positions")
a1.legend(frameon=False, loc="upper left", fontsize=6.3)
a1.grid(False)
# zoom
zx, zy = 0.45, 0.22
for l, (la, lo) in uloc.items():
    if abs(lo - hlon) < zx and abs(la - hlat) < zy:
        c = cnt_loc[l]
        a2.add_patch(Rectangle((lo - 2.5 / 60, la - 1.25 / 60), 5 / 60, 2.5 / 60, fc=BLUE, ec="white", lw=0.4, alpha=min(0.3 + 0.7 * math.log10(c) / 4.1, 1)))
        if c >= 60:
            a2.text(lo, la, l[4:], ha="center", va="center", fontsize=5.5, color="white" if c > 3000 else "black")
a2.set_xlim(hlon - zx, hlon + zx); a2.set_ylim(hlat - zy, hlat + zy)
a2.set_aspect(1 / math.cos(math.radians(hlat)))
a2.set_xlabel("longitude (°E)"); a2.set_title("(b) Home area, one rectangle = one square"); a2.grid(False)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_wprs_map.pdf")); plt.close(fig)

# ---- pattern of life
wd = np.array([t.weekday() for t in T]); homeflag = np.array([l == HOME for l in loc])
near = dist_home < 6
fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.4))
for sel, lab, col in ((wd < 5, "Mon--Fri", BLUE), (wd >= 5, "Sat--Sun", AMBER)):
    y = [100 * np.mean(homeflag[sel & (hr == k)]) if (sel & (hr == k)).sum() > 20 else np.nan for k in range(24)]
    a1.plot(range(24), y, color=col, lw=1.5, label=lab)
a1.set_xlabel("UTC hour"); a1.set_ylabel("fixes in home square KP20jg (%)"); a1.set_xlim(0, 23); a1.legend(frameon=False, fontsize=6.5)
a1.set_title("(a) Where the car is during the day")
pos = dist_home[dist_home > 0.5]
a2.hist(np.log10(pos), bins=np.linspace(0.3, 3.0, 28), color=GREEN, alpha=0.8)
a2.set_xticks([0.7, 1, 1.7, 2, 2.7, 3]); a2.set_xticklabels(["5", "10", "50", "100", "500", "1000"])
a2.set_xlabel("distance from home (km)"); a2.set_ylabel("number of fixes"); a2.set_title("(b) Fixes outside the home square")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_wprs_life.pdf")); plt.close(fig)
wk = homeflag[(wd < 5) & (hr >= 6) & (hr <= 14)]; we = homeflag[(wd >= 5) & (hr >= 6) & (hr <= 14)]
macro("wHomeWk", f"{100 * wk.mean():.0f}"); macro("wHomeWe", f"{100 * we.mean():.0f}")

# ---- home vs away: hour-adjusted reporter index, compared with home fixes of the SAME day (removes season/day effects)
hour_exp = {k: nrep[(hr == k) & homeflag].mean() for k in range(24)}
rel = np.array([nrep[i] / hour_exp[hr[i]] for i in range(N)])
away = dist_home > 25
dday = np.array([t.date().toordinal() for t in T])
pairs_d = []
for u in np.unique(dday):
    a = away & (dday == u); b = homeflag & (dday == u)
    if a.sum() >= 3 and b.sum() >= 3:
        pairs_d.append((rel[a].mean(), rel[b].mean(), a.sum()))
pairs_d = np.array(pairs_d)
macro("wNAway", fmt(int(away.sum()))); macro("wPairDays", len(pairs_d))
if len(pairs_d):
    rng = np.random.default_rng(1)
    ratio = pairs_d[:, 0].sum() / pairs_d[:, 1].sum()
    bs = []
    for _ in range(2000):
        s_ = pairs_d[rng.integers(0, len(pairs_d), len(pairs_d))]
        bs.append(100 * s_[:, 0].sum() / s_[:, 1].sum())
    macro("wRelAway", f"{100 * ratio:.0f}"); macro("wRelAwayLo", f"{np.percentile(bs, 2.5):.0f}"); macro("wRelAwayHi", f"{np.percentile(bs, 97.5):.0f}")
else:
    macro("wRelAway", "--"); macro("wRelAwayLo", "--"); macro("wRelAwayHi", "--")
macro("wRelHome", "100")

# ------------------------------------------------------------------ power reach (from per-report SNR)
bad = {tuple(x) for x in json.load(open(os.path.join(OUT, "qc_bad.json")))}      # written by analyze.py
rep = [r for r in REPLAY.execute("SELECT callsign, grid, snr, distance FROM reporters_log").fetchall() if (r[0], r[1]) not in bad]
snr = np.array([r[2] for r in rep]); dist = np.array([r[3] for r in rep])
FLOOR = -34
macro("wFloor", FLOOR); macro("wSnrMin", int(snr.min())); macro("wSnrMax", int(snr.max()))
macro("wSnrMed", f"{np.median(snr):.0f}"); macro("wSnrQ1", f"{np.percentile(snr, 25):.0f}"); macro("wSnrQ3", f"{np.percentile(snr, 75):.0f}")
macro("wSnrP5", f"{np.percentile(snr, 5):.0f}")
st_max = {}
for c, g, s, d in rep:
    k = (c, g)
    if k not in st_max:
        st_max[k] = [s, d]
    else:
        st_max[k][0] = max(st_max[k][0], s)
        st_max[k][1] = max(st_max[k][1], d)
smax = np.array([v[0] for v in st_max.values()]); sdist = np.array([v[1] for v in st_max.values()])
levels = [(200, "200 mW (as used)"), (100, "100 mW"), (50, "50 mW"), (25, "25 mW"), (10, "10 mW"), (5, "5 mW"), (1, "1 mW")]
prow = []
curve_p = np.arange(23, -1, -0.5)
for mw, lab in levels:
    dB = 10 * math.log10(200 / mw)
    prow.append((lab, 10 * math.log10(mw), dB, 100 * np.mean(snr - dB >= FLOOR), 100 * np.mean(smax - dB >= FLOOR),
                 100 * np.mean((smax - dB >= FLOOR)[sdist > 3000]) if (sdist > 3000).any() else np.nan,
                 100 * np.mean((smax - dB >= FLOOR)[sdist > 6000])))
for r in prow:
    nm = {200: "TwoH", 100: "OneH", 50: "Fifty", 25: "TwentyFive", 10: "Ten", 5: "Five", 1: "One"}[round(10 ** (r[1] / 10))]
    macro("pw" + nm, f"{r[4]:.0f}"); macro("pwDx" + nm, f"{r[6]:.0f}"); macro("pwRep" + nm, f"{r[3]:.0f}")
macro("wKmW", fmt(15619 / 0.2)); macro("wRecord", "15\\,619")
macro("wAbove", f"{100 * np.mean(snr >= -20):.0f}")
macro("wStrongMargin", f"{np.median(snr) - FLOOR:.0f}")
fig, ax = plt.subplots(figsize=(W * 0.62, 2.5))
pw = np.arange(0, 23.01, 0.25)
for arr, mask, lab, col in ((smax, np.ones(len(smax), bool), "all stations", BLUE), (smax, sdist > 3000, "stations $>$ 3000 km", AMBER), (smax, sdist > 6000, "stations $>$ 6000 km", RED)):
    y = [100 * np.mean((arr[mask] - (23 - p)) >= FLOOR) for p in pw]
    ax.plot(pw, y, color=col, lw=1.5, label=lab)
ax.set_xlabel("transmit power (dBm); 23 dBm = 200 mW"); ax.set_ylabel("stations still decoding (%)")
ax.axvline(23, color=GREY, ls="--", lw=0.8); ax.set_ylim(0, 102); ax.set_xlim(0, 23.5)
sec = ax.secondary_xaxis("top", functions=(lambda x: x, lambda x: x)); sec.set_xticks([0, 10, 20, 23]); sec.set_xticklabels(["1 mW", "10 mW", "100 mW", "200 mW"], fontsize=6); sec.spines["top"].set_visible(False)
ax.legend(frameon=False, loc="lower right", fontsize=6.5)
fig.savefig(os.path.join(OUT, "fig_wprs_power.pdf")); plt.close(fig)

# ------------------------------------------------------------------ energy budget
cap_wh = 30.0 * 3.7; eff = 0.85
duty = 110.6 / 600
i_avg = duty * 0.250 + (1 - duty) * 0.100
p_avg = 5.0 * i_avg
days_pred = cap_wh * eff / p_avg / 24
macro("eCapWh", f"{cap_wh:.0f}"); macro("eAvgmA", f"{i_avg * 1000:.0f}"); macro("eAvgW", f"{p_avg:.2f}")
macro("eDays", f"{days_pred:.1f}"); macro("eUsable", f"{cap_wh * eff:.0f}")
macro("eDaily", f"{p_avg * 24:.1f}")
macro("eIdleOnlyDays", f"{cap_wh * eff / (5 * 0.100) / 24:.1f}"); macro("eTxOnlyDays", f"{cap_wh * eff / (5 * 0.250) / 24:.1f}")
macro("eObsLo", "4"); macro("eObsHi", "5")
macro("eImpliedLo", f"{100 * 4 / days_pred:.0f}"); macro("eImpliedHi", f"{100 * 5 / days_pred:.0f}")

# ------------------------------------------------------------------ tables
Tt = []


def tab(cols, head, body, cap, lab, notes=None):
    s = ["\\begin{table}[htbp]\\centering\\small", f"\\caption{{{cap}}}\\label{{{lab}}}", f"\\begin{{tabular}}{{{cols}}}", "\\toprule", " & ".join(head) + " \\\\", "\\midrule"]
    s += [" & ".join(str(c) for c in r) + " \\\\" for r in body]
    s += ["\\bottomrule", "\\end{tabular}"]
    if notes:
        s.append(f"\\\\[2pt]{{\\footnotesize {notes}}}")
    s.append("\\end{table}")
    Tt.append("\n".join(s))


tab("lrr", ["Distance from home square", "Fixes", "Share (\\%)"], [(a, fmt(b), f"{c:.1f}") for a, b, c in crows],
    "Where the position fixes were: distance of the reported square centre from the home square KP20jg.", "tab:wdist")
tab("lllrrr", ["Start (UTC)", "End (UTC)", "Hours", "Fixes", "Squares", "Max.\\ dist.\\ (km)"],
    [(t["start"].strftime("%Y-%m-%d %H:%M"), t["end"].strftime("%m-%d %H:%M"), f"{t['hours']:.0f}", t["n"], t["locs"], fmt(t["maxd"])) for t in big],
    "All trips beyond 25 km from home as seen through WPRS fixes alone (fixes less than eight hours apart are merged into one trip; consecutive days of one journey can appear as separate trips).", "tab:wtrips")
tab("lrrrrr", ["Transmit power", "dBm", "$\\Delta$ (dB)", "All reports (\\%)", "Stations (\\%)", "Stations $>$ 6000 km (\\%)"],
    [(a, f"{b:.0f}", f"{c:.1f}", f"{d:.0f}", f"{e:.0f}", f"{g:.0f}") for a, b, c, d, e, g in [(r[0], r[1], r[2], r[3], r[4], r[6]) for r in prow]],
    "Emulated power reduction: share of the actual reports and of the receiving stations that would still lie above the decoding floor of $-34$\\,dB if the output were lowered by $\\Delta$.", "tab:wpower")
tab("lrrr", ["Load case", "Current (mA)", "Power (W)", "Runtime (days)"],
    [("Idle (GPS acquiring / waiting)", "100", "0.50", f"{cap_wh * eff / 0.5 / 24:.1f}"),
     ("Transmitting continuously", "250", "1.25", f"{cap_wh * eff / 1.25 / 24:.1f}"),
     ("WPRS duty cycle (18.4\\,\\% transmitting)", f"{i_avg * 1000:.0f}", f"{p_avg:.2f}", f"{days_pred:.1f}")],
    "Energy budget of the 30\\,000\\,mAh battery pack (nominal 3.7\\,V, 111\\,Wh; 85\\,\\% assumed conversion efficiency to 5\\,V).", "tab:wenergy")
heads_ = ["Days with fixes", "Fixes", "Median fixes per day", "Days with $\\geq$ 20 fixes", "Fixes heard by $\\geq$ 3 stations (\\%)", "Median stations per fix",
          "Trips beyond 25 km", "Farthest fix from home (km)", "Fixes in the home square (\\%)"]
tab("l" + "r" * len(srows), ["Quantity"] + [r[0] for r in srows],
    [(h_, *[r[k + 1] for r in srows]) for k, h_ in enumerate(heads_)],
    "The three seasons side by side.", "tab:wseasons")
for t_ in Tt:
    lab_ = re.search(r"\\label\{tab:(\w+)\}", t_).group(1)
    open(os.path.join(OUT, f"tab_{lab_}.tex"), "w").write(t_ + "\n")
open(os.path.join(OUT, "wprs_numbers.tex"), "w").write("\n".join(f"\\providecommand{{\\{k.translate(DIG)}}}{{{v}}}" for k, v in NUM.items()) + "\n")
print(len(NUM), "macros;", len(Tt), "tables")
for k in ("wGap10", "wGap30", "wGap60", "wAv60Avg", "wAv60Min", "wAv60MinH", "wAvDay60", "wAvNight60", "wRep3", "wHomePct", "wNear", "wMid", "wFar", "wTrips", "wMaxDist", "wRelHome", "wRelAway", "wRelAwayLo", "wRelAwayHi", "eDays", "pwTwoH", "pwTen", "pwOne", "wHomeWk", "wHomeWe", "wChangePct", "wMoveP90"):
    print(k, NUM[k])
