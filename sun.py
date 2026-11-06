"""Sun position and sunrise / sunset (NOAA-style low-precision formulas, good to about a minute).

Used by the grey-line analysis. Times are naive UTC datetimes; hours are UTC hours as floats.
"""
import math
from datetime import datetime, timedelta

_J2000 = datetime(2000, 1, 1, 12, 0, 0)


def solar_elevation(lat, lon, when):
    """Elevation of the sun in degrees (no refraction) at lat/lon (degrees, east positive)."""
    n = (when - _J2000).total_seconds() / 86400.0
    mean_long = (280.460 + 0.9856474 * n) % 360.0
    g = math.radians((357.528 + 0.9856003 * n) % 360.0)
    lam = math.radians(mean_long + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    decl = math.asin(math.sin(eps) * math.sin(lam))
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    gmst = (280.46061837 + 360.98564736629 * n) % 360.0
    lha = math.radians(gmst + lon) - ra
    phi = math.radians(lat)
    s = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(lha)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def sunrise_sunset(lat, lon, day, step_min=10):
    """(sunrise, sunset) as UTC hours within the UTC date `day` (datetime.date); None if the sun
    does not cross the horizon (-0.833 deg) in that direction during the day."""
    t0 = datetime(day.year, day.month, day.day)
    prev = solar_elevation(lat, lon, t0)
    rise = sset = None
    for i in range(1, 24 * 60 // step_min + 1):
        t = t0 + timedelta(minutes=i * step_min)
        cur = solar_elevation(lat, lon, t)
        if prev < -0.833 <= cur and rise is None:
            rise = ((i - 1) + (-0.833 - prev) / (cur - prev)) * step_min / 60.0
        elif prev >= -0.833 > cur and sset is None:
            sset = ((i - 1) + (prev + 0.833) / (prev - cur)) * step_min / 60.0
        prev = cur
    return rise, sset
