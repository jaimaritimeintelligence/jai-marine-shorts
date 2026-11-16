"""Collect the last ~30 hours of shipping news from RSS feeds and Google News searches."""
import time, re, html, calendar
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
import feedparser, requests

UA = {"User-Agent": "Mozilla/5.0 (JaiMarineShorts news bot; +https://github.com/jaimaritimeintelligence/jai-marine-shorts)"}

# Trade press RSS feeds (headlines + short summaries only)
FEEDS = {
    "gCaptain": "https://gcaptain.com/feed/",
    "Splash247": "https://splash247.com/feed/",
    "The Maritime Executive": "https://maritime-executive.com/articles.rss",
    "Hellenic Shipping News": "https://www.hellenicshippingnews.com/feed/",
    "Marine Insight": "https://www.marineinsight.com/feed/",
    "Safety4Sea": "https://safety4sea.com/feed/",
    "Offshore Energy": "https://www.offshore-energy.biz/feed/",
    "LNG Prime": "https://lngprime.com/feed/",
    "Seatrade Maritime": "https://www.seatrade-maritime.com/rss.xml",
    "Baird Maritime": "https://www.bairdmaritime.com/feed/",
    "Ship & Bunker": "https://shipandbunker.com/news/rss",
    "Riviera": "https://www.rivieramm.com/rss",
}

# Google News searches - one per story theme the Chief wants every day
SEARCHES = [
    "ship collision OR grounding OR \"ship fire\" OR capsized vessel",
    "Strait of Hormuz tanker attack",
    "Red Sea OR \"Black Sea\" ship attack crew",
    "seafarers crew abandoned OR stranded OR wages",
    "Maritime Labour Convention OR MLC seafarers",
    "seafarers union OR dockworkers strike port",
    "shipping cyber attack OR ransomware maritime",
    "seafarer internet connectivity onboard OR Starlink ship crew",
    "LNG carrier OR LNG tanker",
    "Brent crude oil price today",
    "VLCC OR tanker freight rates",
    "tanker sold OR \"sale and purchase\" tanker",
    "shipyard newbuilding order LNG OR tanker OR container",
    "IMO regulation shipping",
    "port congestion container shipping",
]


def _clean(s, n=600):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def _ts(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            return datetime.fromtimestamp(calendar.timegm(e[k]), tz=timezone.utc)
    return None


def _fetch(url):
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except Exception as ex:
        print("  feed failed:", url, ex)
        return None


def collect(hours=30, max_items=140):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    items, seen = [], set()

    def add(title, link, summary, source, ts):
        key = re.sub(r"[^a-z0-9]", "", title.lower())[:70]
        if not title or key in seen: return
        if ts and ts < since: return
        seen.add(key)
        items.append({"title": _clean(title, 220), "link": link, "summary": _clean(summary),
                      "source": source, "time": ts.isoformat() if ts else ""})

    for name, url in FEEDS.items():
        fp = _fetch(url)
        if not fp: continue
        for e in fp.entries[:40]:
            add(e.get("title", ""), e.get("link", ""), e.get("summary", ""), name, _ts(e))
        time.sleep(0.5)

    for q in SEARCHES:
        url = f"https://news.google.com/rss/search?q={quote_plus(q + ' when:1d')}&hl=en-US&gl=US&ceid=US:en"
        fp = _fetch(url)
        if not fp: continue
        for e in fp.entries[:12]:
            title = e.get("title", "")
            src = (e.get("source") or {}).get("title") or ""
            if src and title.endswith(" - " + src):
                title = title[: -len(" - " + src)]
            add(title, e.get("link", ""), e.get("summary", ""), src or "Google News", _ts(e))
        time.sleep(1)

    items.sort(key=lambda x: x["time"], reverse=True)
    print(f"Collected {len(items)} news items")
    return items[:max_items]


def article_text(url, limit=3500):
    """Best-effort full text so Gemini has enough facts for 3-4 lines. Falls back silently."""
    try:
        import trafilatura
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        if r.status_code != 200: return ""
        txt = trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
        return re.sub(r"\s+", " ", txt)[:limit]
    except Exception:
        return ""
