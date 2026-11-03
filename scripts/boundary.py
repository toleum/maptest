"""Собирает полигон района из relation Overpass (out geom)."""
from shapely.geometry import LineString, Polygon, MultiPolygon
from shapely.ops import linemerge, polygonize, unary_union

def district_polygon(osm):
    rel = next(e for e in osm["elements"] if e["type"] == "relation")
    lines = []
    for m in rel.get("members", []):
        if m.get("type") == "way" and m.get("role") in ("outer", "") and m.get("geometry"):
            lines.append(LineString([(p["lon"], p["lat"]) for p in m["geometry"]]))
    polys = list(polygonize(linemerge(lines)))
    if not polys:
        raise RuntimeError("не удалось собрать полигон района")
    return rel.get("tags", {}), unary_union(polys)
