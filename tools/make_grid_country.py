#!/usr/bin/env python3
"""
Build core/grid_country.py: the countries of every 4-character Maidenhead square (2° × 1°).

Used by callsign_to_country() in wspr_logger.py to name the country of a reporter from its locator
when the callsign cannot tell (SWL names, CB numbers, unknown prefixes, a prefix that does not fit the
locator).  Run once; the result is committed, so the server needs neither this script nor its inputs.

Input: the Natural Earth 1:50m country borders (public domain) as TopoJSON, e.g. countries-50m.json
from the npm package world-atlas 2.0.2:
    https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json
Needs shapely 2 (pip install shapely).

    python3 tools/make_grid_country.py path/to/countries-50m.json > core/grid_country.py

Each square is tested at 7 × 7 points: its main country is the one found at most of them, and every
other country found is listed for it too.  Every island of a country also counts
once in the square of its representative point, so small islands that no test point hits (Malta,
Pantelleria …) are not lost.  Border squares
(more than one country) also get the country of each of their 24 × 24 six-character subsquares.  Squares entirely at sea
are left out.  The names follow the country names of _COUNTRY_MAP in wspr_logger.py.
"""
import json
import sys
from collections import Counter, defaultdict

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon

# Natural Earth name -> the name used by wspr_logger._COUNTRY_MAP
RENAME = {
    "United Kingdom": "UK", "United States of America": "USA", "Bosnia and Herz.": "Bosnia",
    "Central African Rep.": "C. African Rep.", "Dem. Rep. Congo": "DR Congo", "Dominican Rep.": "Dom. Rep.",
    "Faeroe Is.": "Faroe Is.", "Macedonia": "N. Macedonia", "South Africa": "S. Africa",
    "South Korea": "S. Korea", "Trinidad and Tobago": "Trinidad", "U.S. Virgin Is.": "US Virgin Is.",
    "United Arab Emirates": "UAE", "eSwatini": "Eswatini", "Åland": "Finland", "N. Cyprus": "Cyprus",
    "Somaliland": "Somalia", "Siachen Glacier": "India",
}


def refine(name: str, lat: float, lon: float) -> str:
    """Parts of a country that amateur radio counts on their own (and _COUNTRY_MAP names)."""
    if name == "USA":
        if lat > 51 and lon < -129:
            return "Alaska"
        if lat < 23 and lon < -150:
            return "Hawaii"
    if name == "Spain" and lat < 30 and lon < -12:
        return "Canary Is."
    return name


def gm_name(c: str) -> str:
    return {"Alaska": "USA", "Hawaii": "USA", "Canary Is.": "Spain"}.get(c, c)


def decode(topo: dict) -> list:
    """[(name, shapely geometry)] of the TopoJSON object "countries"."""
    sc, tr = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sc[0] + tr[0], y * sc[1] + tr[1]))
        arcs.append(pts)

    def ring(idx):
        pts = []
        for i in idx:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts.extend(a if not pts else a[1:])
        return pts

    out = []
    for g in topo["objects"]["countries"]["geometries"]:
        name = g.get("properties", {}).get("name")
        if not name or name == "Antarctica":
            continue
        if g["type"] == "Polygon":
            polys = [g["arcs"]]
        elif g["type"] == "MultiPolygon":
            polys = g["arcs"]
        else:
            continue
        parts = []
        for p in polys:
            rings = [ring(r) for r in p]
            if len(rings[0]) >= 4:
                parts.append(Polygon(rings[0], [r for r in rings[1:] if len(r) >= 4]))
        if parts:
            out.append((RENAME.get(name, name), shapely.make_valid(MultiPolygon(parts))))
    return out


def square(lon: float, lat: float) -> str:
    lon += 180
    lat += 90
    return (chr(65 + int(lon // 20)) + chr(65 + int(lat // 10)) + str(int(lon % 20 // 2)) + str(int(lat % 10)))


def main(path: str) -> None:
    countries = decode(json.load(open(path, encoding="utf-8")))
    n = 7
    fx = (np.arange(n) + 0.5) / n
    found = defaultdict(Counter)          # square -> Counter(country -> points)
    geoms = defaultdict(list)             # refined country name -> [geometry, …]
    for name, geom in countries:
        for rn in {"USA": ("USA", "Alaska", "Hawaii"), "Spain": ("Spain", "Canary Is.")}.get(name, (name,)):
            geoms[rn].append(geom)
        shapely.prepare(geom)
        x0, y0, x1, y1 = geom.bounds
        for lo in range(int((x0 + 180) // 2) * 2 - 180, int(x1) + 2, 2):
            for la in range(int(np.floor(y0)), int(np.floor(y1)) + 1):
                if lo < -180 or lo >= 180 or la < -90 or la >= 90:
                    continue
                xs, ys = np.meshgrid(lo + 2 * fx, la + fx)
                hits = shapely.contains_xy(geom, xs.ravel(), ys.ravel())
                for x, y in zip(xs.ravel()[hits], ys.ravel()[hits]):
                    found[square(lo + 1, la + 0.5)][refine(name, y, x)] += 1
        for part in getattr(geom, "geoms", [geom]):   # every island, also one that no test point hit
            if part.geom_type != "Polygon":
                continue
            rp = part.representative_point()
            found[square(rp.x, rp.y)][refine(name, rp.y, rp.x)] += 1
    main_of = defaultdict(list)                   # country -> squares where it covers most of the square
    also = defaultdict(list)                      # country -> border squares where it covers less than another
    for sq, cnt in found.items():
        ranked = [c for c, _ in cnt.most_common()]
        if not ranked:
            continue
        main_of[ranked[0]].append(sq)
        for c in ranked[1:]:
            also[c].append(sq)
    # Border squares: the country of each of the 24 × 24 six-character subsquares, so that a full locator
    # resolves to the right side of the border.  One character per subsquare: the index of the country in
    # the square's list ('.' at sea), run-length encoded ("40a3b…" = 40 × a, 3 × b …).
    fine = {}
    sub_x = (np.arange(24) + 0.5) / 24
    for sq, cnt in found.items():
        ranked = [c for c, _ in cnt.most_common()]
        if len(ranked) < 2:
            continue
        lo = (ord(sq[0]) - 65) * 20 - 180 + int(sq[2]) * 2
        la = (ord(sq[1]) - 65) * 10 - 90 + int(sq[3])
        xs, ys = np.meshgrid(lo + 2 * sub_x, la + sub_x)          # row = latitude letter, column = longitude letter
        cell = np.full(xs.shape, -1)
        for k, c in enumerate(ranked):
            for gm in geoms[c]:
                hit = shapely.contains_xy(gm, xs, ys) & (cell < 0)
                if c in ("Alaska", "Hawaii", "Canary Is.", "USA", "Spain"):
                    keep = np.vectorize(lambda x, y: refine(gm_name(c), y, x) == c)(xs, ys)
                    hit &= keep
                cell[hit] = k
        flat = "".join("." if v < 0 else "abcdefgh"[v] for v in cell.ravel())   # lat letter a…x, then lon letter a…x
        enc, i = [], 0
        while i < len(flat):
            j = i
            while j < len(flat) and flat[j] == flat[i]:
                j += 1
            enc.append(f"{j - i if j - i > 1 else ''}{flat[i]}")
            i = j
        fine[sq] = (ranked, "".join(enc))
    out = ['"""The countries of every 4-character Maidenhead square (2° × 1°) that holds land.',
           "",
           "Generated by tools/make_grid_country.py from the Natural Earth 1:50m country borders (public domain).",
           "Do not edit by hand: run the script again.  _MAIN: country -> the squares it covers most of;",
           '_ALSO: country -> the border squares it reaches into while another country covers more;',
           '_FINE: border square -> (its countries, the country of each 6-character subsquare, run-length encoded)."""',
           "", "_MAIN = {"]
    out += [f"    {c!r}: {' '.join(sorted(main_of[c]))!r}," for c in sorted(main_of)]
    out += ["}", "", "_ALSO = {"]
    out += [f"    {c!r}: {' '.join(sorted(also[c]))!r}," for c in sorted(also)]
    out += ["}", "", "_FINE = {"]
    out += [f"    {sq!r}: ({tuple(r)!r}, {e!r})," for sq, (r, e) in sorted(fine.items())]
    out += ["}", "",
            "_PRIMARY = {s: c for c, sqs in _MAIN.items() for s in sqs.split()}",
            "_ALL: dict = {}",
            "for _c, _sqs in list(_MAIN.items()) + list(_ALSO.items()):",
            "    for _s in _sqs.split():",
            "        _ALL.setdefault(_s, set()).add(_c)",
            "", "",
            "def _square(grid: str) -> str:",
            "    g = (grid or '').strip()",
            "    return g[:2].upper() + g[2:4] if len(g) >= 4 else ''",
            "", "",
            "_fine_cache: dict = {}",
            "", "",
            "def _fine_cell(sq: str, sub: str):",
            "    \"\"\"The country of the 6-character subsquare `sub` (two letters) of the border square `sq`; None at sea.\"\"\"",
            "    if sq not in _fine_cache:",
            "        names, enc = _FINE[sq]",
            "        flat, num = [], ''",
            "        for ch in enc:",
            "            if ch.isdigit():",
            "                num += ch",
            "            else:",
            "                flat.append(ch * int(num or 1))",
            "                num = ''",
            "        _fine_cache[sq] = (names, ''.join(flat))",
            "    names, flat = _fine_cache[sq]",
            "    lon_i, lat_i = ord(sub[0]) - 97, ord(sub[1]) - 97",
            "    if not (0 <= lon_i < 24 and 0 <= lat_i < 24):",
            "        return None",
            "    ch = flat[lat_i * 24 + lon_i]",
            "    return None if ch == '.' else names['abcdefgh'.index(ch)]",
            "", "",
            "def country_of(grid: str):",
            '    """The country of `grid`: for a 6-character locator in a border square the country of that',
            '    subsquare, otherwise the country covering most of the 4-character square.  None at sea or for a',
            '    grid shorter than 4 characters."""',
            "    sq = _square(grid)",
            "    g = (grid or '').strip().lower()",
            "    if sq in _FINE and len(g) >= 6:",
            "        c = _fine_cell(sq, g[4:6])",
            "        if c:",
            "            return c",
            "    return _PRIMARY.get(sq)",
            "", "",
            "def countries_of(grid: str) -> set:",
            '    """Every country that reaches into the 4-character square of `grid` (empty at sea)."""',
            "    return _ALL.get(_square(grid), set())",
            ]
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "countries-50m.json")
