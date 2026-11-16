"""Daily step 1 (about 5 PM IST): collect news -> Gemini writes 9 stories -> find real photos
-> render 10 slides -> save to out/<date>/ -> send preview to Telegram for approval."""
import os, json, shutil, time, traceback
from datetime import datetime, timedelta, timezone
from PIL import Image

from jms import news, ai, photos, render, telegram

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
DAY = os.environ.get("RUN_DAY") or NOW.strftime("%Y-%m-%d")
DATE_TEXT = datetime.strptime(DAY, "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")
OUT = os.path.join("out", DAY)
AUTO_POST = os.environ.get("AUTO_POST", "false").lower() == "true"


def cleanup(keep_days=14):
    if not os.path.isdir("out"): return
    cutoff = (NOW - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for d in os.listdir("out"):
        if len(d) == 10 and d < cutoff:
            shutil.rmtree(os.path.join("out", d), ignore_errors=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(os.path.join(OUT, "meta.json")):
        print("Already prepared for", DAY); return
    stories_file = os.path.join(OUT, "stories.json")
    if os.path.exists(stories_file):
        print("Using stories written by Claude:", stories_file)
        plan = json.load(open(stories_file))
    else:
        print("No Claude stories today - Gemini fallback editor")
        plan = gemini_plan()
    build(plan)


def gemini_plan():
    items = news.collect()
    if len(items) < 15:
        raise RuntimeError(f"only {len(items)} news items found")
    # give Gemini fuller text for trade-press items (Google News links are redirects, so skip those)
    enriched = 0
    for it in items:
        if enriched >= 20: break
        if "news.google.com" in it["link"]: continue
        it["text"] = news.article_text(it["link"]); enriched += 1
        time.sleep(0.5)

    return ai.plan_carousel(items, DATE_TEXT)


def build(plan):
    stories = sorted(plan["stories"], key=lambda s: s["slot"])[:9]

    used, cover_photos = set(), []
    for s in stories:
        print(f"Slide {s['slot']}: {s['headline']}")
        s["photo_credit"], img = "", None
        cands = photos.candidates_for(s, used)
        thumbs = []
        for c in cands:
            try:
                thumbs.append((photos.fetch_image(c["small"]), c)); time.sleep(1)
            except Exception as ex:
                print("  thumb failed", ex)
        best, exact = ai.pick_photo(s, thumbs)
        if 0 <= best < len(thumbs):
            c = thumbs[best][1]
            try:
                img = photos.fetch_image(c["full"])
            except Exception:
                img = thumbs[best][0]
            used.add(c["full"])
            s["photo_credit"] = ("" if exact else "Representative · ") + c["credit"]
            s["photo_page"] = c["page"]
        s["_img"] = img
        if img is not None: cover_photos.append(img)

    paths = [os.path.join(OUT, "01.jpg")]
    render.cover(10, DATE_TEXT, cover_photos[:5], paths[0])
    for s in stories:
        p = os.path.join(OUT, f"{s['slot']:02d}.jpg")
        render.story(s["slot"], 10, s["headline"], s["summary"], s.get("sources", ""), s["photo_credit"], p, s["_img"])
        paths.append(p)

    for s in stories: s.pop("_img", None)
    meta = {"day": DAY, "caption": plan["caption"], "stories": stories,
            "created": NOW.isoformat(), "preview_unix": int(time.time()), "posted": None}
    if not AUTO_POST and telegram.TOKEN:
        telegram.send_preview(DAY, paths, plan["caption"])
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), indent=1, ensure_ascii=False)
    cleanup()
    print("Done:", OUT)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        traceback.print_exc()
        if telegram.TOKEN:
            telegram.send_text(f"⚠️ Jai Marine Shorts: today's carousel ({DAY}) could not be prepared.\n{str(ex)[:500]}")
        raise
