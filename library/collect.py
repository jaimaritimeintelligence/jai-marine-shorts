"""Massive photo collection WITHOUT using Gemini quota.
Sources (all free, credit-only licences):
  1. Wikimedia Commons "Quality images" / "Featured pictures" / "Valued images" (human-vetted quality)
  2. Wikimedia Commons general search (keyword + local quality checks)
  3. Openverse (Flickr and other CC collections; only CC0 / PDM / CC BY / CC BY-SA)
  4. Pexels / Pixabay if PEXELS_API_KEY / PIXABAY_API_KEY secrets exist
Local checks: size, landscape, colour, sharpness, exposure, near-duplicate hash.
Photos are saved unscored ("score": null); build_library.py rates them with Gemini later.
Usage: python -u library/collect.py <per_category> <deadline_utc_HH:MM>"""
import os, sys, io, re, json, time, hashlib, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from PIL import Image, ImageFilter, ImageStat
from jms import photos

ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(ROOT, "index.json")
PER_CAT = int(sys.argv[1]) if len(sys.argv) > 1 else 30
DEADLINE = sys.argv[2] if len(sys.argv) > 2 else "09:55"
UA = photos.UA
PEXELS = os.environ.get("PEXELS_API_KEY", "").strip()
PIXABAY = os.environ.get("PIXABAY_API_KEY", "").strip()

# category: (search phrases, words that must appear in title/tags for keyword-only sources)
CATS = {
    "vlcc": (["VLCC", "very large crude carrier", "supertanker"], ["vlcc", "supertanker", "crude", "tanker"]),
    "crude-tanker": (["crude oil tanker", "Aframax tanker", "Suezmax tanker", "oil tanker"], ["tanker"]),
    "product-tanker": (["product tanker", "chemical tanker", "oil products tanker"], ["tanker", "chemical"]),
    "lng-carrier": (["LNG carrier", "LNG tanker", "liquefied natural gas carrier"], ["lng", "gas carrier", "liquefied"]),
    "lpg-carrier": (["LPG carrier", "LPG tanker", "gas carrier ship"], ["lpg", "gas carrier", "gas tanker"]),
    "container-ship": (["container ship", "containership", "container vessel", "Maersk ship", "MSC container ship", "CMA CGM ship", "Evergreen container ship"], ["container", "maersk", "msc", "cma cgm", "evergreen", "cosco", "hapag", "one "]),
    "bulk-carrier": (["bulk carrier", "bulker ship", "Capesize", "Panamax bulk carrier"], ["bulk", "capesize", "panamax", "bulker"]),
    "car-carrier": (["car carrier", "ro-ro ship", "vehicle carrier"], ["car carrier", "ro-ro", "roro", "vehicle"]),
    "cruise-ship": (["cruise ship"], ["cruise"]),
    "riverboat": (["paddle steamer", "riverboat", "paddlewheel"], ["paddle", "riverboat", "steamboat", "river"]),
    "offshore": (["offshore supply vessel", "anchor handling tug", "FPSO", "drilling rig", "oil platform"], ["offshore", "supply", "fpso", "rig", "platform", "anchor handling"]),
    "tug": (["tugboat", "harbour tug", "tug boat"], ["tug"]),
    "coast-guard": (["coast guard cutter", "coast guard ship", "coast guard helicopter"], ["coast guard", "cutter", "uscg"]),
    "navy-escort": (["frigate", "destroyer warship", "naval vessel at sea"], ["frigate", "destroyer", "navy", "uss ", "hms ", "warship"]),
    "port-terminal": (["container terminal", "container port", "gantry crane port", "port cranes"], ["terminal", "port", "crane", "harbour", "harbor"]),
    "oil-terminal": (["oil terminal", "oil jetty", "tanker terminal", "oil storage tanks port"], ["oil", "terminal", "jetty", "refinery"]),
    "lng-terminal": (["LNG terminal", "LNG plant", "FSRU"], ["lng", "fsru"]),
    "shipyard": (["shipyard", "ship under construction", "dry dock ship", "ship launch shipyard"], ["shipyard", "dry dock", "drydock", "floating dock", "under construction", "launch", "newbuilding"]),
    "seafarers": (["ship crew on deck", "merchant seafarers", "mooring operation ship", "crew members ship deck"], ["seafarer", "seafarers", "crew", "mariner", "mariners", "mooring", "deckhand", "merchant navy"]),
    "ship-bridge": (["ship bridge", "wheelhouse", "ship navigation bridge"], ["bridge", "wheelhouse"]),
    "engine-room": (["ship engine room", "marine diesel engine", "engine control room"], ["engine"]),
    "canal-strait": (["Suez Canal ship", "Panama Canal ship", "Bosphorus ship", "Kiel Canal ship", "Strait of Gibraltar"], ["canal", "bosphorus", "bosporus", "strait"]),
    "ship-fire": (["ship fire", "fireboat", "burning ship", "fire on ship"], ["fire", "burning", "fireboat"]),
    "rescue": (["sea rescue", "lifeboat rescue", "search and rescue helicopter", "rescue boat"], ["rescue", "lifeboat", "sar"]),
    "grounding-wreck": (["ship aground", "shipwreck", "stranded ship", "capsized ship"], ["aground", "wreck", "stranded", "capsized"]),
    "refinery": (["oil refinery", "petrochemical plant", "refinery night"], ["refinery", "petrochemical"]),
    "ship-at-sunset": (["ship at sunset", "tanker sunset", "cargo ship sunset", "ship sunrise sea"], ["sunset", "sunrise", "dusk", "dawn"]),
    "storm-sea": (["ship in storm", "rough sea ship", "heavy seas ship", "ship waves"], ["storm", "rough", "heavy sea", "waves"]),
    "ice-arctic": (["ship in ice", "icebreaker", "Arctic ship"], ["ice", "arctic", "icebreaker", "polar"]),
    "anchorage": (["ships at anchor", "anchorage ships", "ships waiting anchor"], ["anchor"]),
    "general-cargo": (["general cargo ship", "multipurpose cargo ship", "heavy lift ship"], ["cargo", "heavy lift", "multipurpose"]),
    "ferry": (["ferry ship", "ro-pax ferry"], ["ferry", "ropax", "ro-pax"]),
    "dredger": (["dredger", "dredging ship"], ["dredg"]),
    "pilot-boat": (["pilot boat", "harbour pilot boarding"], ["pilot"]),
    "lighthouse": (["lighthouse sea", "lighthouse ship"], ["lighthouse"]),
    "aerial-ship": (["aerial view ship", "drone view cargo ship", "aerial container ship"], ["aerial", "drone", "from above"]),
}
BAD = ("map", "logo", "diagram", "drawing", "flag", "coat of arms", "chart", "plan", "painting", "poster", "butterfly",
       "model", "stamp", "postcard", "sketch", "lithograph", "engraving", "toy", "lego", "illustration", "render",
       "memorial", "plaque", "fish", "insect", "bird", "flower", "museum exhibit", "1800s", "battle")


def now_utc(): return datetime.datetime.now(datetime.timezone.utc)


def deadline_passed():
    h, m = map(int, DEADLINE.split(":"))
    d = now_utc().replace(hour=h, minute=m, second=0, microsecond=0)
    return now_utc() >= d


def load():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else {"photos": []}


def save(idx):
    json.dump(idx, open(INDEX, "w"), indent=1, ensure_ascii=False)


def commit(msg):
    subprocess.run(["git", "add", "library"], check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
        subprocess.run(["git", "commit", "-q", "-m", msg], check=False)
        for _ in range(3):
            subprocess.run(["git", "pull", "-q", "--rebase"], check=False)
            if subprocess.run(["git", "push", "-q"]).returncode == 0: break
            time.sleep(5)


def ahash(im):
    g = im.convert("L").resize((16, 16))
    px = list(g.getdata()); avg = sum(px) / len(px)
    return "".join("1" if p > avg else "0" for p in px)


def hamming(a, b): return sum(x != y for x, y in zip(a, b))


def quality_ok(im):
    """Local checks: colour, exposure, contrast, sharpness."""
    small = im.copy(); small.thumbnail((800, 800))
    hsv = small.convert("HSV"); sat = ImageStat.Stat(hsv).mean[1]
    st = ImageStat.Stat(small.convert("L")); bright, contrast = st.mean[0], st.stddev[0]
    edges = small.convert("L").filter(ImageFilter.FIND_EDGES); sharp = ImageStat.Stat(edges).var[0]
    ok = sat > 14 and 50 < bright < 210 and contrast > 22 and sharp > 300
    return ok, {"sat": round(sat), "bright": round(bright), "contrast": round(contrast), "sharp": round(sharp)}


def get_img(url, tries=3):
    for a in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=60)
        except Exception as ex:
            time.sleep(5); continue
        if r.status_code == 429:
            w = int(r.headers.get("retry-after", 10) or 10); time.sleep(min(w, 90) + 5); continue
        if r.status_code != 200: return None
        try: return Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception: return None
    return None


# ---------------- sources ----------------
def commons(q, quality_only):
    extra = ' incategory:"Quality_images"' if quality_only == "qi" else (' incategory:"Featured_pictures_on_Wikimedia_Commons"' if quality_only == "fp" else "")
    try:
        res = photos.search(q + extra, n=40, min_w=1600)
    except Exception as ex:
        print("   commons failed", ex); return []
    out = []
    for c in res:
        out.append({"title": c["title"], "url": c["full"], "credit": c["credit"], "page": c["page"],
                    "source": "commons", "vetted": bool(extra)})
    return out


OV_OK = {"cc0", "pdm", "by", "by-sa"}


def openverse(q):
    try:
        r = requests.get("https://api.openverse.org/v1/images/",
                         params={"q": q, "license": "cc0,pdm,by,by-sa", "page_size": 40, "aspect_ratio": "wide,square",
                                 "size": "large", "mature": "false"}, headers=UA, timeout=40)
        if r.status_code != 200:
            print("   openverse", r.status_code, r.text[:120]); return []
        out = []
        for it in r.json().get("results", []):
            if (it.get("license") or "").lower() not in OV_OK: continue
            if (it.get("width") or 0) < 1600: continue
            lic = f"CC {it['license'].upper()} {it.get('license_version') or ''}".strip().replace("CC CC0", "CC0").replace("CC PDM", "Public domain")
            who = (it.get("creator") or "Unknown")[:40]
            src = (it.get("source") or it.get("provider") or "Openverse").title()
            out.append({"title": it.get("title") or "", "url": it["url"], "credit": f"{who} / {src} ({lic})",
                        "page": it.get("foreign_landing_url", ""), "source": "openverse", "vetted": False,
                        "tags": " ".join(t.get("name", "") for t in (it.get("tags") or []))})
        return out
    except Exception as ex:
        print("   openverse failed", ex); return []


def pexels(q):
    if not PEXELS: return []
    try:
        r = requests.get("https://api.pexels.com/v1/search", params={"query": q, "per_page": 40, "orientation": "landscape"},
                         headers={"Authorization": PEXELS}, timeout=30)
        return [{"title": p.get("alt") or q, "url": p["src"]["large2x"], "credit": f"{p['photographer'][:40]} / Pexels",
                 "page": p["url"], "source": "pexels", "vetted": True} for p in r.json().get("photos", [])]
    except Exception as ex:
        print("   pexels failed", ex); return []


def pixabay(q):
    if not PIXABAY: return []
    try:
        r = requests.get("https://pixabay.com/api/", params={"key": PIXABAY, "q": q, "image_type": "photo", "per_page": 40,
                                                            "orientation": "horizontal", "min_width": 1600, "safesearch": "true"}, timeout=30)
        return [{"title": h.get("tags") or q, "url": h["largeImageURL"], "credit": f"{h['user'][:40]} / Pixabay",
                 "page": h["pageURL"], "source": "pixabay", "vetted": True, "tags": h.get("tags", "")} for h in r.json().get("hits", [])]
    except Exception as ex:
        print("   pixabay failed", ex); return []


# ---------------- main ----------------
def collect_category(cat, idx, hashes):
    queries, must = CATS[cat]
    have = [p for p in idx["photos"] if p["category"] == cat]
    need = PER_CAT - len(have)
    if need <= 0:
        print(f"{cat}: full ({len(have)})"); return 0
    known = {p.get("source_url") or p.get("source") for p in idx["photos"]}
    cands = []
    for q in queries:
        for mode in ("fp", "qi", ""):
            cands += commons(q, mode); time.sleep(3)
        cands += openverse(q); time.sleep(4)
        cands += pexels(q) + pixabay(q)
        if deadline_passed(): break
    seen, ranked = set(), []
    for c in cands:
        if c["url"] in seen or c["url"] in known: continue
        seen.add(c["url"])
        text = " " + re.sub(r"[^a-z0-9]+", " ", (c["title"] + " " + c.get("tags", "")).lower()) + " "
        if any(f" {b.strip()} " in text for b in BAD): continue
        if c["source"] in ("commons", "openverse") and not any(f" {m.strip()} " in text for m in must): continue
        ranked.append(c)
    ranked.sort(key=lambda c: (not c["vetted"], c["source"] != "commons"))
    print(f"{cat}: {len(cands)} found, {len(ranked)} pass filters, need {need}")
    os.makedirs(os.path.join(ROOT, "photos", cat), exist_ok=True)
    added = 0
    for c in ranked:
        if added >= need or deadline_passed(): break
        url = c["url"]
        if c["source"] == "commons" and "/thumb/" in url:
            url = url.replace("/1920px-", "/1280px-")
        im = get_img(url)
        time.sleep(2.5 if c["source"] == "commons" else 1)
        if im is None or im.width < 1000 or im.width < im.height * 0.9: continue
        ok, q = quality_ok(im)
        if not ok: continue
        h = ahash(im)
        if any(hamming(h, x) < 20 for x in hashes): continue
        im.thumbnail((1280, 1280))
        name = re.sub(r"[^a-z0-9]+", "-", c["title"].lower())[:45].strip("-") or "photo"
        name += "-" + hashlib.md5(c["url"].encode()).hexdigest()[:6] + ".jpg"
        path = os.path.join("photos", cat, name)
        im.save(os.path.join(ROOT, path), quality=82, optimize=True)
        idx["photos"].append({"file": path, "category": cat, "title": c["title"][:150], "credit": c["credit"],
                              "page": c["page"], "source_url": c["url"], "origin": c["source"], "vetted": c["vetted"],
                              "score": None, "checks": q, "hash": h, "w": im.width, "h": im.height})
        hashes.append(h); added += 1
    save(idx)
    print(f"{cat}: +{added} (now {len(have) + added})")
    return added


def main():
    idx = load()
    hashes = [p["hash"] for p in idx["photos"] if p.get("hash")]
    total = 0
    # fill the emptiest categories first
    order = sorted(CATS, key=lambda c: sum(1 for p in idx["photos"] if p["category"] == c))
    for rnd in range(3):
        added_round = 0
        for cat in order:
            if deadline_passed(): break
            try:
                n = collect_category(cat, idx, hashes); total += n; added_round += n
            except Exception as ex:
                print(cat, "FAILED", ex)
            commit(f"Photo library: {cat}")
        if deadline_passed(): print("Deadline reached"); break
        if added_round == 0: print("Nothing new found this round"); break
    print(f"Added {total}. Library size: {len(idx['photos'])}")


if __name__ == "__main__":
    main()
