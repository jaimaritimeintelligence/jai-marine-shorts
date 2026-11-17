"""Build a reusable photo library (free-licence Wikimedia Commons photos, quality-checked by Gemini).
Runs slowly on purpose to stay inside Wikimedia's rate limits. Commits after each category so progress is kept.
Usage: python -u library/build_library.py [max_per_category]"""
import os, sys, io, json, re, time, hashlib, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from PIL import Image
from jms import photos, ai
from google.genai import types

ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(ROOT, "index.json")
MAX_KEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 14

CATEGORIES = {
    "vlcc":             ["VLCC tanker", "very large crude carrier", "supertanker at sea", "crude oil tanker underway"],
    "crude-tanker":     ["Aframax tanker", "Suezmax tanker", "oil tanker at sea", "crude oil tanker port"],
    "product-tanker":   ["product tanker", "chemical tanker", "oil products tanker", "MR tanker"],
    "lng-carrier":      ["LNG carrier", "LNG tanker at sea", "Q-Max LNG", "membrane LNG carrier", "Moss LNG carrier"],
    "lpg-carrier":      ["LPG carrier", "LPG tanker ship", "gas carrier ship", "ammonia carrier"],
    "container-ship":   ["container ship at sea", "ultra large container ship", "Maersk container ship", "MSC container ship", "container ship port"],
    "bulk-carrier":     ["bulk carrier at sea", "Capesize bulk carrier", "bulk carrier loading", "bulk carrier port"],
    "car-carrier":      ["car carrier ship", "pure car truck carrier", "ro-ro ship"],
    "cruise-ship":      ["cruise ship at sea", "cruise ship port"],
    "riverboat":        ["paddlewheel riverboat", "riverboat Mississippi", "river cruise ship"],
    "offshore":         ["offshore supply vessel", "anchor handling tug supply", "FPSO", "offshore platform supply ship"],
    "tug":              ["tugboat harbour", "tugboats assisting ship", "harbour tug"],
    "coast-guard":      ["coast guard cutter", "coast guard rescue ship", "coast guard helicopter rescue"],
    "navy-escort":      ["frigate at sea", "destroyer escort merchant ship", "warship Gulf"],
    "port-terminal":    ["container terminal cranes", "port gantry cranes ship", "container port aerial"],
    "oil-terminal":     ["oil terminal tanker", "oil jetty tanker loading", "crude oil terminal"],
    "lng-terminal":     ["LNG terminal", "LNG import terminal ship", "LNG export terminal"],
    "shipyard":         ["shipyard ship construction", "ship under construction", "dry dock ship", "ship launch shipyard"],
    "seafarers":        ["seafarers on deck", "ship crew", "merchant navy sailors", "mooring operation crew"],
    "ship-bridge":      ["ship bridge", "ship wheelhouse", "bridge of merchant ship"],
    "engine-room":      ["ship engine room", "marine diesel engine", "engine control room ship"],
    "canal-strait":     ["Suez Canal ship", "Panama Canal ship", "Bosphorus tanker", "Strait of Gibraltar ship", "Strait of Malacca ship"],
    "ship-fire":        ["ship fire", "fireboat ship fire", "burning ship"],
    "rescue":           ["sea rescue", "lifeboat rescue ship", "search and rescue helicopter sea"],
    "grounding-wreck":  ["ship aground", "shipwreck coast", "capsized ship"],
    "refinery":         ["oil refinery", "oil refinery night", "petrochemical plant port"],
    "ship-at-sunset":   ["ship at sunset", "tanker sunset", "cargo ship sunset"],
}

RATE_PROMPT = """These are candidate photos for a professional Instagram news page about shipping.
Category: "{cat}" (search phrases: {qs}).
For EACH photo give: keep (true/false), score 1-10, tags (3-6 short words).
keep=true ONLY if: it is a real photograph (not map/diagram/drawing/logo/satellite image/painting), sharp, well exposed,
in colour, attractive enough for a news post, and clearly shows the category subject (e.g. for "lng-carrier" a real LNG carrier).
Reject old black-and-white archive photos, blurry/tiny/cluttered images, close-up portraits of identifiable people,
and photos where the subject is tiny or hidden. score = how good it would look as a full-screen news photo.
Return JSON only: {{"photos":[{{"i":0,"keep":true,"score":8,"tags":["..."]}}, ...]}}"""


def load_index():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else {"photos": []}


def save_index(idx):
    json.dump(idx, open(INDEX, "w"), indent=1, ensure_ascii=False)


def original_url(u):
    return u.replace("/thumb/", "/").rsplit("/", 1)[0] if "/thumb/" in u else u


def get(url, tries=3):
    for a in range(tries):
        r = requests.get(url, headers=photos.UA, timeout=90)
        if r.status_code == 429:
            w = int(r.headers.get("retry-after", 10) or 10)
            print(f"   429, waiting {min(w, 120)}s"); time.sleep(min(w, 120) + 5); continue
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    raise RuntimeError("rate limited")


def commit(msg):
    subprocess.run(["git", "add", "library"], check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
        subprocess.run(["git", "commit", "-q", "-m", msg], check=False)
        subprocess.run(["git", "pull", "-q", "--rebase"], check=False)
        subprocess.run(["git", "push", "-q"], check=False)


def build_category(cat, queries, idx):
    have = [p for p in idx["photos"] if p["category"] == cat]
    if len(have) >= MAX_KEEP:
        print(f"{cat}: already {len(have)} photos"); return
    known = {p["source"] for p in idx["photos"]}
    cands = []
    for q in queries:
        try:
            for c in photos.search(q, n=30, min_w=1400):
                if original_url(c["full"]) in known or any(c["full"] == x["full"] for x in cands): continue
                cands.append(c)
        except Exception as ex:
            print("  search failed", q, ex)
        time.sleep(4)
    cands = cands[:24]
    print(f"{cat}: {len(cands)} candidates")
    thumbs = []
    for c in cands:
        try:
            thumbs.append((get(c["small"]), c)); time.sleep(2.5)
        except Exception as ex:
            print("  thumb failed", str(ex)[:60]); time.sleep(10)
    if not thumbs: return
    ratings = []
    for start in range(0, len(thumbs), 24):            # Gemini: ONE call per category (free daily quota is small)
        batch = thumbs[start:start + 24]
        parts = [RATE_PROMPT.format(cat=cat, qs=", ".join(queries))]
        for i, (im, c) in enumerate(batch):
            b = io.BytesIO(); im.save(b, "JPEG", quality=70)
            parts += [f"Photo {i}: {c['title'][:80]}", types.Part.from_bytes(data=b.getvalue(), mime_type="image/jpeg")]
        try:
            r = ai._call(parts, temperature=0.1, budget_s=240)
            for p in r.get("photos", []):
                i = int(p.get("i", -1))
                if 0 <= i < len(batch) and p.get("keep") and int(p.get("score", 0)) >= 7:
                    ratings.append((int(p["score"]), batch[i][1], p.get("tags", [])))
        except Exception as ex:
            print("  rating failed:", str(ex)[:150])
            if "RESOURCE_EXHAUSTED" in str(ex) or "quota" in str(ex).lower():
                raise SystemExit("Gemini daily quota used up - stopping; the next scheduled run continues")
        time.sleep(15)
    ratings.sort(key=lambda x: -x[0])
    os.makedirs(os.path.join(ROOT, "photos", cat), exist_ok=True)
    added = 0
    for score, c, tags in ratings[: MAX_KEEP - len(have)]:
        src = original_url(c["full"])
        try:
            im = get(src)
        except Exception:
            try: im = get(c["full"])
            except Exception as ex: print("  full failed", str(ex)[:60]); time.sleep(20); continue
        im.thumbnail((1600, 1600))
        name = re.sub(r"[^a-z0-9]+", "-", c["title"].lower())[:50].strip("-") + "-" + hashlib.md5(src.encode()).hexdigest()[:6] + ".jpg"
        path = os.path.join("photos", cat, name)
        im.save(os.path.join(ROOT, path), quality=86, optimize=True)
        idx["photos"].append({"file": path, "category": cat, "title": c["title"], "credit": c["credit"],
                              "page": c["page"], "source": src, "score": score, "tags": tags,
                              "w": im.width, "h": im.height})
        added += 1
        time.sleep(4)
    save_index(idx)
    print(f"{cat}: +{added} (total {added + len(have)})")


REVIEW_PROMPT = """Quality check for a shipping-news Instagram photo library. For EACH photo (category in brackets) answer:
keep = true only if it is a real, sharp, attractive colour photograph that clearly shows its category subject.
Reject maps, drawings, paintings, models/toys, logos, satellite images, blurry/dark/cluttered images, tiny subjects,
and close-up portraits of identifiable people. score 1-10 = how good it looks full-screen.
Return JSON only: {"photos":[{"i":0,"keep":true,"score":8}, ...]}"""


def review_unscored(idx, limit_calls=40):
    """Gemini check for photos collected without Gemini (score None). Deletes rejects."""
    todo = [p for p in idx["photos"] if p.get("score") is None]
    print("Unscored photos to review:", len(todo))
    calls = 0
    for start in range(0, len(todo), 24):
        if calls >= limit_calls: break
        batch = todo[start:start + 24]
        parts = [REVIEW_PROMPT]
        for i, p in enumerate(batch):
            im = Image.open(os.path.join(ROOT, p["file"])).convert("RGB"); im.thumbnail((400, 400))
            b = io.BytesIO(); im.save(b, "JPEG", quality=70)
            parts += [f"Photo {i} [{p['category']}]: {p['title'][:70]}", types.Part.from_bytes(data=b.getvalue(), mime_type="image/jpeg")]
        try:
            r = ai._call(parts, temperature=0.1, budget_s=240); calls += 1
        except Exception as ex:
            print("  review stopped:", str(ex)[:150]); break
        verdict = {int(x["i"]): x for x in r.get("photos", []) if "i" in x}
        for i, p in enumerate(batch):
            v = verdict.get(i)
            if not v: continue
            if v.get("keep") and int(v.get("score", 0)) >= 6:
                p["score"] = int(v["score"])
            else:
                try: os.remove(os.path.join(ROOT, p["file"]))
                except FileNotFoundError: pass
                p["_drop"] = True
        idx["photos"] = [p for p in idx["photos"] if not p.get("_drop")]
        save_index(idx); commit("Photo library: Gemini review")
        time.sleep(15)


def main():
    idx = load_index()
    if os.environ.get("REVIEW_ONLY") == "1":
        review_unscored(idx); return
    t0 = time.time()
    for cat, qs in CATEGORIES.items():
        if time.time() - t0 > 5.3 * 3600: print("time limit reached"); break
        try:
            build_category(cat, qs, idx)
        except Exception as ex:
            print(cat, "FAILED", ex)
        commit(f"Photo library: {cat}")
    print("Library size:", len(idx["photos"]))


if __name__ == "__main__":
    main()
