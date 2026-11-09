"""Unusual DX openings (from 2026-11-09): a region beyond 6000 km heard at an hour when, at this time of
year, it is seldom heard ("opening"), or heard by many more stations than usual at that hour ("strong").

Pure functions, no Flask and no database access.

Inputs
  hits     {(day, hour, zone): set of callsigns} -- the DX stations (beyond 6000 km) per UTC day and hour
  on_hours {day: set of hours} -- the hours in which the transmitter was on (analysis.tx_on), the chances

The yardstick is seasonal: the days within SEASON_DAYS (day of the year, any year) of the day in question,
the day itself left out; with fewer than MIN_DAYS such days at that hour the whole history is used.
  p      = share of those days on which the region was heard at that hour (shrunk: (hits + 0.5) / (n + 1))
  opening: the region is heard now with at least 2 stations (or 1 station in two hours running) and p < P_OPEN
  strong:  p >= P_OPEN, and the stations now exceed the STRONG_Q level of the station counts on the (at least
           10) days the region was heard at that hour, are at least STRONG_MIN and at least twice the median
Stations are counted by base callsign (K1RA-4 and K1RA-PI are one station).
Consecutive hours of the same region and kind on one day are one event.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

P_OPEN = 0.025         # tuned on the history to about one event a week (see the backtest in CHANGELOG)
STRONG_Q = 0.99        # about "more than ever usual": with few comparable days this is near the highest
STRONG_MIN = 4
SEASON_DAYS = 45
MIN_DAYS = 20
ZONE_NAMES = {"n_america": "North America", "africa": "Africa", "pacific": "Oceania",
              "s_america": "South America", "asia": "Asia"}


def base_call(call: str) -> str:
    """K1RA-4 -> K1RA, OH2GAX/P -> OH2GAX: one station however many receivers or suffixes it reports with."""
    return (call or "").upper().split("-")[0].split("/")[0]


def _doy(d: str) -> int:
    return date.fromisoformat(d).timetuple().tm_yday


def _near(a: int, b: int) -> bool:
    x = abs(a - b)
    return min(x, 366 - x) <= SEASON_DAYS


def _pct(v: list, q: float):
    v = sorted(v)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


class Model:
    """The yardstick for one band: built once from the history, asked for any day / hour / zone."""

    def __init__(self, hits: dict, on_hours: dict):
        self.hits = hits
        self.days_at = defaultdict(list)          # hour -> [day, ...] with the transmitter on
        for d, hs in on_hours.items():
            for h in hs:
                self.days_at[h].append(d)
        self.doy = {d: _doy(d) for d in on_hours}
        self.zones = sorted({z for (_d, _h, z) in hits} | set(ZONE_NAMES))

    def usual(self, day: str, hour: int, zone: str) -> dict:
        """p (share of comparable days with the zone heard at this hour), the station counts on those days
        when it was heard (median, STRONG_Q level), how many days, and whether the season or all was used."""
        t = _doy(day)
        days = [d for d in self.days_at[hour] if d != day and _near(self.doy[d], t)]
        basis = "season"
        if len(days) < MIN_DAYS:
            days, basis = [d for d in self.days_at[hour] if d != day], "all"
        counts = [len(self.hits[(d, hour, zone)]) for d in days if (d, hour, zone) in self.hits]
        n = len(days)
        return {"p": (len(counts) + 0.5) / (n + 1), "days": n, "heard_days": len(counts), "basis": basis,
                "median": _pct(counts, 0.5), "high": _pct(counts, STRONG_Q)}

    def judge(self, day: str, hour: int, zone: str, stations: int, also_prev_hour: bool) -> dict | None:
        """The kind of event ("opening" / "strong") for `stations` DX stations of `zone` now, or None."""
        if stations <= 0:
            return None
        u = self.usual(day, hour, zone)
        if u["p"] < P_OPEN:
            if stations >= 2 or also_prev_hour:
                return {"kind": "opening", **u}
            return None
        if (u["high"] is not None and u["heard_days"] >= 10 and stations > u["high"]
                and stations >= STRONG_MIN and stations >= 2 * (u["median"] or 0)):
            return {"kind": "strong", **u}
        return None


def history(model: Model) -> list:
    """Every unusual event in the history, newest first: consecutive hours of one zone and kind on one day
    merged.  {day, zone, name, kind, from_h, to_h, stations (most in one hour), calls (a few), p (lowest),
    median, days, basis}."""
    found = []
    for (d, h, z), calls in model.hits.items():
        if h not in model.days_at or d not in model.doy:
            continue
        prev = (d, h - 1, z) in model.hits
        j = model.judge(d, h, z, len(calls), prev)
        if j:
            found.append((d, z, j["kind"], h, len(calls), sorted(calls), j))
    found.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    events = []
    for d, z, kind, h, n, calls, j in found:
        last = events[-1] if events else None
        if last and (last["day"], last["zone"], last["kind"]) == (d, z, kind) and last["to_h"] == h - 1:
            last["to_h"] = h
            last["stations"] = max(last["stations"], n)
            last["calls"] = sorted(set(last["calls"]) | set(calls))[:6]
            last["p"] = min(last["p"], j["p"])
            continue
        events.append({"day": d, "zone": z, "name": ZONE_NAMES.get(z, z), "kind": kind, "from_h": h, "to_h": h,
                       "stations": n, "calls": calls[:6], "p": j["p"], "median": j["median"],
                       "days": j["days"], "basis": j["basis"]})
    for e in events:
        e["p"] = round(100 * e["p"], 1)
    events.sort(key=lambda e: (e["day"], e["from_h"]), reverse=True)
    return events
