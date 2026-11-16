"""Find real, free-licence photos on Wikimedia Commons (credit-only licences)."""
import io, re, time, requests
from PIL import Image

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "JaiMarineShorts/1.0 (https://github.com/jaimaritimeintelligence/jai-marine-shorts; jaimaritimeintelligence@gmail.com)"}
OK_LIC = ("cc0", "public domain", "pd", "cc by", "cc-by")  # includes CC BY-SA
BAD_WORDS = ("map", "logo", "diagram", "plan", "drawing", "flag of", "coat of arms", "chart", "svg", "icon", "signature")

GENERIC = {
    "crude oil tanker": ["crude oil tanker at sea", "oil tanker"],
    "VLCC": ["VLCC tanker", "very large crude carrier", "oil tanker at sea"],
    "product tanker": ["product tanker", "chemical tanker at sea"],
    "LNG carrier": ["LNG carrier", "LNG tanker at sea"],
    "LPG carrier": ["LPG carrier", "gas carrier ship"],
    "container ship": ["container ship at sea", "container ship"],
    "bulk carrier": ["bulk carrier at sea", "bulk carrier"],
    "car carrier": ["car carrier ship", "roro ship"],
    "cruise ship": ["cruise ship", "river cruise ship"],
    "riverboat": ["paddlewheel riverboat", "riverboat Mississippi"],
    "offshore vessel": ["offshore supply vessel", "offshore vessel"],
    "tug": ["tugboat harbour", "tug boat"],
    "naval": ["warship at sea", "navy ship"],
    "port": ["container terminal cranes", "port container terminal"],
    "shipyard": ["shipyard ship construction", "shipyard dry dock"],
    "other": ["merchant ship at sea", "cargo ship at sea"],
}


def _clean(s):
    return re.sub("<[^>]+>", "", s or "").strip()


def _get(params):
    for a in range(3):
        r = requests.get(API, params=params, headers=UA, timeout=30)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("retry-after", 3)) + 3 * a); continue
        r.raise_for_status()
        return r.json()
    return {}


def _upload_host(url):
    return url.replace("https://thumb.wikimedia.org/", "https://upload.wikimedia.org/").split("?")[0]


def search(q, n=10, min_w=1100):
    p = {"action": "query", "format": "json", "generator": "search",
         "gsrsearch": f"filetype:bitmap {q}", "gsrnamespace": 6, "gsrlimit": n,
         "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1920}
    data = _get(p)
    out = []
    for pg in (data.get("query", {}).get("pages", {}) or {}).values():
        if "imageinfo" not in pg: continue
        ii = pg["imageinfo"][0]; md = ii.get("extmetadata", {})
        lic = _clean(md.get("LicenseShortName", {}).get("value", ""))
        title = pg["title"]
        if not any(lic.lower().startswith(x) for x in OK_LIC): continue
        if ii["width"] < min_w or ii["width"] < ii["height"] * 0.7: continue
        if any(b in title.lower() for b in BAD_WORDS): continue
        author = _clean(md.get("Artist", {}).get("value", "")) or "Unknown"
        author = re.sub(r"\s+", " ", author)[:40]
        thumb = (ii.get("thumburl") or ii["url"])
        out.append({"title": title.replace("File:", ""), "full": _upload_host(thumb),
                    "small": _upload_host(thumb).replace("/1920px-", "/330px-") if "/1920px-" in thumb else _upload_host(thumb),
                    "credit": f"{author} / Wikimedia Commons ({lic})", "page": ii.get("descriptionurl", "")})
    return out


def fetch_image(url):
    for a in range(3):
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 429:
            wait = int(r.headers.get("retry-after", 5) or 5)
            if wait > 30: break          # long block: give up on this URL instead of hanging
            time.sleep(wait + 3 * a); continue
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    raise RuntimeError("image download rate-limited")


KEYWORDS = {
    "crude oil tanker": ["tanker", "vlcc", "crude"], "VLCC": ["vlcc", "tanker", "crude"],
    "product tanker": ["tanker", "chemical", "product"], "LNG carrier": ["lng"], "LPG carrier": ["lpg", "gas carrier"],
    "container ship": ["container", "maersk", "msc", "cosco"], "bulk carrier": ["bulk"], "car carrier": ["car carrier", "roro", "ro-ro"],
    "cruise ship": ["cruise"], "riverboat": ["riverboat", "paddle", "steamboat"], "offshore vessel": ["offshore", "supply"],
    "tug": ["tug"], "naval": ["uss", "navy", "hms"], "port": ["port", "terminal", "harbour", "harbor"],
    "shipyard": ["shipyard", "dock", "launch"], "other": ["ship", "vessel"],
}


def keyword_score(story, meta):
    t = meta["title"].lower()
    ph = story.get("photo", {})
    score = sum(3 for s in (ph.get("exact_subjects") or []) if s.lower() in t)
    score += sum(1 for k in KEYWORDS.get(ph.get("ship_type", "other"), []) if k in t)
    return score


def candidates_for(story, used, max_cands=5):
    ph = story.get("photo", {})
    queries = list(dict.fromkeys((ph.get("queries") or [])[:2]))
    queries += GENERIC.get(ph.get("ship_type", "other"), GENERIC["other"])[:1]
    cands = []
    for q in queries:
        try:
            for c in search(q):
                if c["full"] in used or any(c["full"] == x["full"] for x in cands): continue
                cands.append(c)
        except Exception as ex:
            print("  commons search failed:", q, ex)
        time.sleep(1)
        if len(cands) >= max_cands: break
    cands.sort(key=lambda c: -keyword_score(story, c))
    return cands[:max_cands]
