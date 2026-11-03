"""Скачивает границу района и все заведения/остановки из OpenStreetMap через Overpass API."""
import json, sys, time
import requests
from common import RAW, config

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

def query(cfg):
    s, w, n, e = cfg["search_bbox"]
    rx = cfg["district_regex"]
    return f"""
[out:json][timeout:300];
(
  rel["boundary"="administrative"]["name"~"{rx}"]({s},{w},{n},{e});
  rel["boundary"="administrative"]["name:ru"~"{rx}"]({s},{w},{n},{e});
)->.r;
.r out geom;
.r map_to_area->.d;
(
  nwr(area.d)["amenity"];
  nwr(area.d)["shop"];
  nwr(area.d)["office"];
  nwr(area.d)["leisure"];
  nwr(area.d)["tourism"];
  nwr(area.d)["healthcare"];
  nwr(area.d)["craft"];
  node(area.d)["public_transport"="platform"];
  node(area.d)["highway"="bus_stop"];
);
out center tags;
"""

def main():
    cfg = config()
    RAW.mkdir(exist_ok=True)
    q = query(cfg)
    last = None
    for url in MIRRORS:
        for attempt in range(2):
            try:
                print(f"Overpass: {url} (попытка {attempt + 1})")
                r = requests.post(url, data={"data": q}, timeout=360,
                                  headers={"User-Agent": "maptest-open-poi-builder/1.0"})
                r.raise_for_status()
                data = r.json()
                rels = [e for e in data["elements"] if e["type"] == "relation"]
                if not rels:
                    raise RuntimeError("граница района не найдена — проверьте district_regex в config.json")
                (RAW / "osm.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                print(f"OSM: {len(data['elements'])} элементов, граница: {rels[0].get('tags', {}).get('name')}")
                return
            except Exception as ex:
                last = ex
                print("  ошибка:", ex)
                time.sleep(20)
    sys.exit(f"Не удалось получить данные OSM: {last}")

if __name__ == "__main__":
    main()
