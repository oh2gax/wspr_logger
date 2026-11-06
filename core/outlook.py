"""DX outlook: how likely is a long-distance window (a reporter beyond 6000 km) in each region over
the next hours, from what the history says.

Model (deliberately simple and transparent; the adjustments are applied only if the back-test shows they help):
  base[region][hour]   share of days on which the region had a DX report in that UTC hour;
  lift for the MUF     how much more (or less) often a window happened when the Juliusruh MUF was
                       low / mid / high *for that hour of the day* (terciles of MUF / typical MUF),
                       measured as observed hits divided by the hits the hour-of-day alone predicts;
  lift for the K index the same for quiet (K <= 2) and active (K >= 3) hours.
  p = base * lift_muf * lift_k, capped at 95 %.
For the next hours the current MUF class and K class are assumed to persist. This is a
descriptive estimate from one station's history, not a physical forecast; it is back-tested
(fit on the first 70 % of the days, scored on the rest) against the hour-of-day alone.
"""
from collections import defaultdict
from datetime import datetime, timedelta

MIN_EVENT_DAYS = 10
MIN_EXPECTED = 5.0        # a lift is only used when the hour-of-day model expects at least this many hits
PSEUDO = 20.0             # shrinks every lift toward 1: lift = (observed + PSEUDO) / (expected + PSEUDO)
K_ACTIVE = 3
CAP = 0.95
LIKELY = 0.40
POSSIBLE = 0.15
HORIZON = 12
LEAD_HOURS = 6            # back-test: predict this many hours ahead of the issue time
ZONE_NAMES = {"n_america": "North America", "africa": "Africa", "pacific": "Oceania",
              "s_america": "South America", "asia": "Asia"}


def _median(v):
    v = sorted(v)
    n = len(v)
    return None if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


def _tables(rows):
    hour_days = defaultdict(set)
    muf_h, k_h = defaultdict(list), defaultdict(list)
    for ts, n, mx, dx6, k, muf, sfi in rows:
        d, h = ts[:10], int(ts[11:13])
        hour_days[h].add(d)
        if muf is not None and muf > 0:
            muf_h[(d, h)].append(muf)
        if k is not None:
            k_h[(d, h)].append(k)
    return hour_days, {key: sum(v) / len(v) for key, v in muf_h.items()}, {key: max(v) for key, v in k_h.items()}


def _fit(events, rows, zones=None):
    hour_days, mean_muf, kmax = _tables(rows)
    dh = {(d, h) for h, ds in hour_days.items() for d in ds}
    hits = defaultdict(set)
    for day, hour, zone in events:
        hits[zone].add((day, hour))
    if zones is None:
        zones = [z for z, hs in hits.items() if len({d for d, _ in hs}) >= MIN_EVENT_DAYS]
    typ = [_median([m for (d, hh), m in mean_muf.items() if hh == h]) for h in range(24)]
    ratio = {key: m / typ[key[1]] for key, m in mean_muf.items() if typ[key[1]]}
    rv = sorted(ratio.values())
    cut = [rv[len(rv) // 3], rv[2 * len(rv) // 3]] if len(rv) >= 60 else None

    def mclass(r):
        return None if cut is None or r is None else "low" if r < cut[0] else "high" if r >= cut[1] else "mid"

    def kclass(k):
        return None if k is None else "active" if k >= K_ACTIVE else "quiet"

    out = {}
    for z in zones:
        base = [(len({d for d, hh in hits[z] if hh == h}) / len(hour_days[h])) if hour_days.get(h) else 0.0
                for h in range(24)]
        lift_m, lift_k, n_m, n_k = {}, {}, {}, {}
        for cls in ("low", "mid", "high"):
            keys = [key for key in dh if mclass(ratio.get(key)) == cls]
            exp = sum(base[h] for _, h in keys)
            obs = sum(1 for key in keys if key in hits[z])
            lift_m[cls] = round((obs + PSEUDO) / (exp + PSEUDO), 2) if exp >= MIN_EXPECTED else 1.0
            n_m[cls] = len(keys)
        for cls in ("quiet", "active"):
            keys = [key for key in dh if kclass(kmax.get(key)) == cls]
            exp = sum(base[h] for _, h in keys)
            obs = sum(1 for key in keys if key in hits[z])
            lift_k[cls] = round((obs + PSEUDO) / (exp + PSEUDO), 2) if exp >= MIN_EXPECTED else 1.0
            n_k[cls] = len(keys)
        out[z] = {"base": [round(b, 3) for b in base], "lift_muf": lift_m, "lift_k": lift_k, "n_muf": n_m, "n_k": n_k,
                  "hits": hits[z]}
    return {"zones": out, "typ_muf": typ, "cut": cut, "_mclass": mclass, "_kclass": kclass,
            "_ratio": ratio, "_kmax": kmax, "_dh": dh, "_hits": hits}


def _p(zmodel, hour, mcls, kcls):
    p = zmodel["base"][hour] * zmodel["lift_muf"].get(mcls, 1.0) * zmodel["lift_k"].get(kcls, 1.0)
    return min(max(p, 0.0), CAP)


def _backtest(events, rows):
    days = sorted({ts[:10] for ts, *_ in rows})
    if len(days) < 40:
        return None
    split = days[int(len(days) * 0.7)]
    ev_tr = [e for e in events if e[0] < split]
    rows_tr = [r for r in rows if r[0][:10] < split]
    m = _fit(ev_tr, rows_tr)
    if not m["zones"] or m["_kclass"] is None or m["cut"] is None:
        return None
    full = _fit(events, rows, zones=list(m["zones"]))          # only for the test-period facts
    dh, hits = full["_dh"], full["_hits"]
    ratio, kmax = full["_ratio"], full["_kmax"]
    se_c = se_m = 0.0
    n = 0
    for d in [x for x in days if x >= split]:
        day0 = datetime.fromisoformat(d)
        for h0 in range(24):
            if (d, h0) not in dh:
                continue
            mc = m["_mclass"](ratio.get((d, h0)))
            kc = m["_kclass"](kmax.get((d, h0)))
            for lead in range(1, LEAD_HOURS + 1):
                t = day0 + timedelta(hours=h0 + lead)
                key = (t.strftime("%Y-%m-%d"), t.hour)
                if key not in dh:
                    continue
                for z, zm in m["zones"].items():
                    y = 1.0 if key in hits[z] else 0.0
                    se_c += (min(zm["base"][t.hour], CAP) - y) ** 2
                    se_m += (_p(zm, t.hour, mc, kc) - y) ** 2
                    n += 1
    if n < 200:
        return None
    bc, bm = se_c / n, se_m / n
    return {"split": split, "test_days": len([x for x in days if x >= split]), "samples": n,
            "brier_climatology": round(bc, 4), "brier_model": round(bm, 4),
            "skill": round(1 - bm / bc, 3) if bc > 0 else None}


def fit(events, rows):
    """events: iterable of (day, hour, zone); rows: snapshot rows (ts, n, mx, dx6, kindex, muf, sfi).
    Returns the model: JSON-safe tables plus private helpers under keys starting with '_'."""
    events = list(events)
    m = _fit(events, rows)
    for z in m["zones"].values():
        z.pop("hits", None)
    m["skill"] = _backtest(events, rows)
    # The MUF / K adjustment is only applied when it beat the hour of the day alone in the back-test.
    m["adjusted"] = bool(m["skill"] and m["skill"]["skill"] is not None and m["skill"]["skill"] > 0)
    m["names"] = {z: ZONE_NAMES.get(z, z) for z in m["zones"]}
    return m


def public(model):
    """The model without its private helpers (safe to send to the browser)."""
    return {k: v for k, v in model.items() if not k.startswith("_")}


def forecast(model, now, muf_now, k_now, horizon=HORIZON):
    """Per region the probability of a DX window in each of the next `horizon` UTC hours."""
    if not model or not model.get("zones"):
        return None
    typ = model["typ_muf"][now.hour]
    ratio = (muf_now / typ) if (muf_now and muf_now > 0 and typ) else None
    adjusted = model.get("adjusted", False)
    mcls = model["_mclass"](ratio) if adjusted else None
    kcls = model["_kclass"](k_now) if adjusted else None
    zones = []
    for z, zm in model["zones"].items():
        cells = []
        for i in range(horizon):
            h = (now.hour + i) % 24
            cells.append({"hour": h, "p": round(_p(zm, h, mcls, kcls), 3), "base": round(zm["base"][h], 3)})
        top = max(cells[:3], key=lambda c: c["p"])
        best = max(cells, key=lambda c: c["p"])
        label = "likely" if top["p"] >= LIKELY else "possible" if top["p"] >= POSSIBLE else "unlikely"
        zones.append({"zone": z, "name": model["names"][z], "cells": cells, "next3": top["p"], "label": label,
                      "best_hour": best["hour"], "best_p": best["p"]})
    zones.sort(key=lambda r: -r["next3"])
    return {"hour": now.hour, "adjusted": adjusted, "muf": muf_now, "muf_ratio": round(ratio, 2) if ratio else None, "muf_class": mcls,
            "k": k_now, "k_class": kcls, "zones": zones}
