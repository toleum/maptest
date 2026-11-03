import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
DATA = ROOT / "data"
SITE = ROOT / "site"
def config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
