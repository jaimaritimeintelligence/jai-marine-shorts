"""Pick photos from the repo's own photo library (library/index.json) - instant, no downloads."""
import os, json, glob, random
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "library")
TYPE_CATS = {
    "crude oil tanker": ["crude-tanker", "vlcc"], "VLCC": ["vlcc", "crude-tanker"],
    "product tanker": ["product-tanker"], "LNG carrier": ["lng-carrier", "lng-terminal"],
    "LPG carrier": ["lpg-carrier"], "container ship": ["container-ship", "port-terminal"],
    "bulk carrier": ["bulk-carrier"], "car carrier": ["car-carrier"], "cruise ship": ["cruise-ship"],
    "riverboat": ["riverboat"], "offshore vessel": ["offshore"], "tug": ["tug"],
    "naval": ["navy-escort", "coast-guard"], "port": ["port-terminal", "oil-terminal"],
    "shipyard": ["shipyard"], "other": ["general-cargo", "ship-at-sunset", "aerial-ship"],
}
WORD_CATS = [
    (("fire", "blaze", "explosion"), ["ship-fire"]), (("rescue", "rescued", "evacuat"), ["rescue", "coast-guard"]),
    (("aground", "grounding", "capsiz", "sank", "sink"), ["grounding-wreck"]),
    (("crew", "seafarer", "sailor", "wages", "abandon", "mlc", "union", "strike"), ["seafarers"]),
    (("brent", "crude price", "oil price", "wti", "opec"), ["oil-terminal", "refinery", "vlcc"]),
    (("cyber", "hack", "ransomware", "internet", "starlink"), ["ship-bridge"]),
    (("suez", "panama", "canal", "strait", "bosphorus", "malacca"), ["canal-strait"]),
    (("engine", "machinery"), ["engine-room"]), (("lng",), ["lng-carrier"]), (("lpg", "ammonia"), ["lpg-carrier"]),
    (("shipyard", "newbuild", "order", "delivery", "delivered"), ["shipyard"]),
    (("port", "terminal", "congestion", "dockworker"), ["port-terminal"]), (("attack", "drone", "missile", "navy"), ["navy-escort"]),
    (("ice", "arctic", "polar", "northern sea route"), ["ice-arctic"]), (("anchorage", "waiting", "stranded", "stuck"), ["anchorage"]),
    (("storm", "typhoon", "cyclone", "weather"), ["storm-sea"]), (("ferry",), ["ferry"]), (("pilot",), ["pilot-boat"]),
    (("coast guard", "coastguard"), ["coast-guard"]), (("refinery", "refining"), ["refinery"]),
]


def index():
    p = os.path.join(ROOT, "index.json")
    return json.load(open(p))["photos"] if os.path.exists(p) else []


def recently_used(days=10):
    used = set()
    for m in sorted(glob.glob("out/*/meta.json"))[-days:]:
        try:
            for s in json.load(open(m)).get("stories", []):
                if s.get("library_file"): used.add(s["library_file"])
        except Exception:
            pass
    return used


def candidates(story, taken, n=6):
    photos = index()
    if not photos: return []
    ph = story.get("photo", {})
    cats = list(TYPE_CATS.get(ph.get("ship_type", "other"), ["ship-at-sunset"]))
    text = (story.get("headline", "") + " " + story.get("summary", "")).lower()
    for words, cs in WORD_CATS:
        if any(w in text for w in words): cats += cs
    cats = list(dict.fromkeys(cats))
    avoid = recently_used() | taken
    pool = [p for p in photos if p["category"] in cats and p["file"] not in avoid]
    random.shuffle(pool)
    pool.sort(key=lambda p: (cats.index(p["category"]) // 2, -(p.get("score") or 6)))  # main type first, best first
    out = []
    for p in pool[:n]:
        try:
            im = Image.open(os.path.join(ROOT, p["file"])).convert("RGB")
            th = im.copy(); th.thumbnail((400, 400))
            out.append((th, {"title": f"[{p['category']}] {p['title']}", "credit": p["credit"],
                             "library_file": p["file"], "_full": im}))
        except Exception:
            pass
    return out
