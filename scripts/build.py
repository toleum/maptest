"""Сводит OSM и Overture в один справочник: категории, склейка дублей, CSV, данные для карты, список изменений."""
import csv, json, math, re, datetime
from difflib import SequenceMatcher
from shapely.geometry import mapping
from common import RAW, DATA, SITE, config
from boundary import district_polygon

# (категория, ключевые слова в типе объекта). Порядок важен: первое совпадение побеждает.
RULES = [
    ("Транспорт", ["bus_stop", "platform", "bus_station", "taxi", "bicycle_rental", "charging_station", "parking", "fuel", "gas_station"]),
    ("Еда", ["restaurant", "cafe", "coffee", "fast_food", "food_court", "bar", "pub", "bakery", "ice_cream", "tea", "pizza", "burger", "sushi", "kebab", "canteen", "confectionery", "eat_and_drink", "dessert"]),
    ("Здоровье", ["pharmacy", "drugstore", "clinic", "hospital", "doctor", "dentist", "medical", "healthcare", "laboratory", "optician", "veterinar", "health"]),
    ("Красота", ["beauty", "hair", "barber", "nail", "cosmetic", "spa", "massage", "tattoo"]),
    ("Образование", ["school", "kindergarten", "college", "university", "education", "library", "training", "language", "driving_school", "tutor"]),
    ("Спорт и отдых", ["fitness", "gym", "sport", "pitch", "playground", "park", "swimming", "stadium", "cinema", "theatre", "club", "entertainment", "arts", "museum", "garden"]),
    ("Авто", ["car", "auto", "tyre", "tire", "motor", "vehicle"]),
    ("Финансы", ["bank", "atm", "bureau_de_change", "money", "insurance", "pawn", "financial", "payment_terminal"]),
    ("Магазины", ["shop", "store", "supermarket", "convenience", "grocery", "mall", "market", "boutique", "clothes", "shoes", "florist", "hardware", "electronics", "mobile_phone", "furniture", "jewel", "books", "pet", "retail", "butcher", "greengrocer", "doityourself", "variety", "kiosk", "department", "gift", "toys"]),
    ("Услуги", []),
]
CATS = [c for c, _ in RULES]

RU = {
    "restaurant": "Ресторан", "cafe": "Кафе", "coffee_shop": "Кофейня", "fast_food": "Фастфуд", "fast_food_restaurant": "Фастфуд",
    "bar": "Бар", "pub": "Паб", "bakery": "Пекарня", "pharmacy": "Аптека", "clinic": "Клиника", "hospital": "Больница",
    "dentist": "Стоматология", "doctors": "Врачи", "school": "Школа", "kindergarten": "Детский сад", "college": "Колледж",
    "university": "Университет", "supermarket": "Супермаркет", "convenience": "Продукты", "convenience_store": "Продукты",
    "grocery_store": "Продукты", "mall": "ТРЦ", "marketplace": "Рынок", "clothes": "Одежда", "clothing_store": "Одежда",
    "beauty": "Салон красоты", "beauty_salon": "Салон красоты", "hairdresser": "Парикмахерская", "hair_salon": "Парикмахерская",
    "barber": "Барбершоп", "bank": "Банк", "atm": "Банкомат", "fuel": "АЗС", "gas_station": "АЗС", "parking": "Парковка",
    "car_repair": "Автосервис", "car_wash": "Автомойка", "car_parts": "Автозапчасти", "bus_stop": "Остановка",
    "platform": "Остановка", "fitness_centre": "Фитнес", "gym": "Фитнес", "playground": "Детская площадка", "pitch": "Спортплощадка",
    "park": "Парк", "place_of_worship": "Храм / мечеть", "post_office": "Почта", "florist": "Цветы", "mobile_phone": "Связь",
    "hardware": "Хозтовары", "furniture": "Мебель", "optician": "Оптика", "veterinary": "Ветклиника", "library": "Библиотека",
    "cinema": "Кинотеатр", "hotel": "Гостиница", "office": "Офис", "government": "Госучреждение", "townhall": "Акимат",
    "police": "Полиция", "fire_station": "Пожарная часть", "charging_station": "Электрозарядка", "bicycle_rental": "Велопрокат", "bus_station": "Автовокзал", "fuel": "АЗС", "pawnbroker": "Ломбард",
    "dry_cleaning": "Химчистка", "laundry": "Прачечная", "toilets": "Туалет", "bench": "Скамейка", "waste_basket": "Урна",
}
# мелкая уличная инфраструктура — в справочник заведений не нужна
SKIP = {"bench", "waste_basket", "waste_disposal", "recycling", "drinking_water", "vending_machine", "bicycle_parking",
        "parking_entrance", "parking_space", "shelter", "clock", "post_box", "telephone", "fountain", "grit_bin",
        "hunting_stand", "picnic_table", "loading_dock", "motorcycle_parking", "smoking_area", "street_lamp"}

def categorize(kind):
    k = kind.lower()
    for cat, words in RULES:
        if any(w in k for w in words):
            return cat
    return "Услуги"

def label(kind):
    return RU.get(kind, kind.replace("_", " ").capitalize())

def norm(s):
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'`’.,!?()\-–—#№&/]+", " ", s)
    s = re.sub(r"\b(тоо|ип|ооо|кафе|ресторан|магазин|аптека|салон)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def dist(a, b):
    kx = 111320 * math.cos(math.radians(a[0]))
    return math.hypot((a[1] - b[1]) * kx, (a[0] - b[0]) * 110540)

def same_name(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)) or SequenceMatcher(None, a, b).ratio() >= 0.8

def first(v):
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""

def osm_records(osm):
    out = []
    for e in osm["elements"]:
        if e["type"] == "relation" and e.get("tags", {}).get("boundary") == "administrative":
            continue
        t = e.get("tags", {})
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if lat is None:
            continue
        if t.get("highway") == "bus_stop" or t.get("public_transport") == "platform":
            kind = "bus_stop"
        else:
            kind = next((t[k] for k in ("amenity", "shop", "healthcare", "leisure", "tourism", "craft") if k in t), None)
            if kind is None and "office" in t:
                kind = "office"
            if kind in (None, "yes"):
                kind = "shop" if "shop" in t else (kind or "office")
        if kind in SKIP:
            continue
        addr = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
        out.append({
            "osm": f"{e['type']}/{e['id']}", "ovt": "", "src": "osm", "kind": kind,
            "name": t.get("name") or t.get("name:ru") or t.get("name:kk") or t.get("name:en") or "",
            "addr": addr, "hours": t.get("opening_hours", ""),
            "phone": (t.get("phone") or t.get("contact:phone") or "").split(";")[0].strip(),
            "web": t.get("website") or t.get("contact:website") or t.get("contact:instagram") or "",
            "lat": round(lat, 6), "lon": round(lon, 6), "conf": "",
        })
    return out

def ovt_records(ov, min_conf):
    out = []
    for p in ov["places"]:
        if (p.get("operating_status") or "open") not in ("open", None):
            continue
        conf = p.get("confidence") or 0
        if conf < min_conf:
            continue
        names = p.get("names") or {}
        cats = p.get("categories") or {}
        kind = p.get("basic_category") or cats.get("primary") or "place"
        a = first(p.get("addresses")) or {}
        out.append({
            "osm": "", "ovt": p["id"], "src": "overture", "kind": kind,
            "name": names.get("primary") or "",
            "addr": a.get("freeform") or "" if isinstance(a, dict) else "",
            "hours": "", "phone": first(p.get("phones")), "web": first(p.get("websites")) or first(p.get("socials")),
            "lat": round(p["lat"], 6), "lon": round(p["lon"], 6), "conf": round(conf, 2),
        })
    return out

def merge(osm, ovt, meters):
    cell = 0.001
    grid = {}
    for i, r in enumerate(osm):
        grid.setdefault((int(r["lat"] / cell), int(r["lon"] / cell)), []).append(i)
    used = set()
    result = list(osm)
    for o in ovt:
        gx, gy = int(o["lat"] / cell), int(o["lon"] / cell)
        best, bd = None, meters
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in grid.get((gx + dx, gy + dy), []):
                    if i in used:
                        continue
                    r = osm[i]
                    d = dist((o["lat"], o["lon"]), (r["lat"], r["lon"]))
                    if d < bd and same_name(o["name"], r["name"]):
                        best, bd = i, d
        if best is None:
            result.append(o)
            continue
        used.add(best)
        r = result[best]
        r["src"], r["ovt"], r["conf"] = "both", o["ovt"], o["conf"]
        for k in ("phone", "web", "addr", "name"):
            if not r[k] and o[k]:
                r[k] = o[k]
    return result

FIELDS = ["key", "src", "cat", "type", "name", "addr", "hours", "phone", "web", "lat", "lon", "osm", "ovt", "conf"]

def main():
    cfg = config()
    osm_raw = json.loads((RAW / "osm.json").read_text(encoding="utf-8"))
    tags, poly = district_polygon(osm_raw)
    ov_path = RAW / "overture.json"
    ov_raw = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {"release": "", "places": []}

    osm = osm_records(osm_raw)
    ovt = ovt_records(ov_raw, cfg.get("min_confidence", 0.5))
    rows = merge(osm, ovt, cfg.get("dedupe_meters", 60))
    for r in rows:
        r["key"] = r["osm"] or r["ovt"]
        r["cat"] = categorize(r["kind"])
        r["type"] = label(r["kind"])
    rows.sort(key=lambda r: (CATS.index(r["cat"]), r["name"] == "", r["name"].lower()))

    # что изменилось с прошлой сборки
    DATA.mkdir(exist_ok=True)
    prev_path = DATA / "places.csv"
    prev = {}
    if prev_path.exists():
        with prev_path.open(encoding="utf-8") as f:
            prev = {r["key"]: r for r in csv.DictReader(f)}
    now = {r["key"]: r for r in rows}
    added = [now[k] for k in now if k not in prev]
    removed = [prev[k] for k in prev if k not in now]
    today = datetime.date.today().isoformat()

    with prev_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    def line(r):
        return f"- {r['type']}: {r['name'] or 'без названия'} ({r['src']}, {r['key']})"
    log = [f"## {today}", f"Всего: {len(rows)}. Добавлено: {len(added)}. Пропало: {len(removed)}.", ""]
    if prev:
        log += ["### Новые", *[line(r) for r in added[:300]], "", "### Пропавшие", *[line(r) for r in removed[:300]], ""]
    chg = DATA / "changes.md"
    old = chg.read_text(encoding="utf-8") if chg.exists() else "# История изменений\n\n"
    head, _, tail = old.partition("\n\n")
    chg.write_text(head + "\n\n" + "\n".join(log) + "\n" + tail, encoding="utf-8")

    stats = {s: sum(r["src"] == s for r in rows) for s in ("both", "osm", "overture")}
    site = {
        "title": cfg["title"], "city": cfg["city"], "district": tags.get("name:ru") or tags.get("name"),
        "updated": today, "overture_release": ov_raw.get("release", ""),
        "added": len(added) if prev else None, "removed": len(removed) if prev else None,
        "stats": stats, "cats": CATS,
        "boundary": mapping(poly),
        "cols": ["src", "cat", "type", "name", "addr", "hours", "phone", "web", "lat", "lon", "osm", "ovt"],
        "rows": [[ {"both": 0, "osm": 1, "overture": 2}[r["src"]], CATS.index(r["cat"]), r["type"], r["name"], r["addr"],
                   r["hours"], r["phone"], r["web"], r["lat"], r["lon"], r["osm"], r["ovt"]] for r in rows],
    }
    (SITE / "data.json").write_text(json.dumps(site, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    import shutil
    shutil.copy(prev_path, SITE / "places.csv")
    print(f"Готово: {len(rows)} объектов; в обоих {stats['both']}, только OSM {stats['osm']}, только Overture {stats['overture']}")

if __name__ == "__main__":
    main()
