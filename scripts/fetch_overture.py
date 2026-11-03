"""Скачивает места (places) из открытого набора Overture Maps в рамке района."""
import json
from shapely import from_wkb
from overturemaps import core
from common import RAW
from boundary import district_polygon

KEEP = ["id", "names", "categories", "basic_category", "confidence", "websites",
        "phones", "socials", "addresses", "brand", "operating_status", "sources"]

def main():
    osm = json.loads((RAW / "osm.json").read_text(encoding="utf-8"))
    _, poly = district_polygon(osm)
    xmin, ymin, xmax, ymax = poly.bounds
    release = core.get_latest_release()
    print(f"Overture release {release}, bbox {poly.bounds}")
    reader = core.record_batch_reader("place", bbox=(xmin, ymin, xmax, ymax), release=release, stac=True)
    rows = []
    if reader is not None:
        for batch in reader:
            for rec in batch.to_pylist():
                g = from_wkb(rec["geometry"])
                if not poly.contains(g):
                    continue
                out = {k: rec.get(k) for k in KEEP if k in rec}
                out["lon"], out["lat"] = g.x, g.y
                rows.append(out)
    (RAW / "overture.json").write_text(json.dumps({"release": release, "places": rows}, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Overture: {len(rows)} мест внутри района")

if __name__ == "__main__":
    main()
