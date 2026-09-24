"""Маршрут тура: порядок объезда объектов и GPX для навигаторов (OsmAnd, Guru Maps, Garmin).

Линии между точками — порядок объезда, а не дорога: дорожный трек строит навигатор.
"""
from math import asin, cos, radians, sin, sqrt
from xml.sax.saxutils import escape

# Центр Актау по OpenStreetMap (Nominatim).
AKTAU = {"name": "Актау", "name_en": "Aktau", "lat": 43.63533, "lon": 51.16822}


def _km(a, b) -> float:
    la1, lo1, la2, lo2 = map(radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(h))


def order(sites: list) -> list:
    """Жадный порядок: из Актау каждый раз к ближайшему ещё не посещённому объекту."""
    left, route, cur = list(sites), [], AKTAU
    while left:
        nxt = min(left, key=lambda s: _km(cur, s))
        route.append(nxt)
        left.remove(nxt)
        cur = nxt
    return route


def gpx(title: str, sites: list, lang: str) -> str:
    name = lambda s: s.get(f"name_{lang}") or s.get("name_ru") or s.get("name")
    start = {"name_ru": AKTAU["name"], "name_en": AKTAU["name_en"], "name_kk": "Ақтау",
             "lat": AKTAU["lat"], "lon": AKTAU["lon"]}
    points = [start] + list(sites) + [start]
    wpts = "".join(
        f'  <wpt lat="{s["lat"]:.6f}" lon="{s["lon"]:.6f}"><name>{escape(name(s))}</name></wpt>\n'
        for s in [start] + list(sites)
    )
    rtepts = "".join(
        f'    <rtept lat="{s["lat"]:.6f}" lon="{s["lon"]:.6f}"><name>{escape(name(s))}</name></rtept>\n'
        for s in points
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="Joldas" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <metadata><name>{escape(title)}</name></metadata>\n"
        f"{wpts}"
        f"  <rte><name>{escape(title)}</name>\n{rtepts}  </rte>\n"
        "</gpx>\n"
    )
