"""Daily step 1 (about 5 PM IST): collect news -> Gemini writes 9 stories -> find real photos
-> render 10 slides -> save to out/<date>/ -> send preview to Telegram for approval."""
import os, json, shutil, time, traceback
from datetime import datetime, timedelta, timezone
from PIL import Image

from jms import news, ai, photos, render, telegram, library

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


def original_url(u):
    if "/thumb/" in u:
        u = u.replace("/thumb/", "/").rsplit("/", 1)[0]
    return u


def get_photo(url):
    """Original file first (no thumbnail rendering on Wikimedia's side), then 1920px thumbnail."""
    for u in (original_url(url), url):
        try:
            im = photos.fetch_image(u); im.thumbnail((2000, 2000)); return im
        except Exception as ex:
            print("  download failed:", u[-60:], str(ex)[:80])
    return None


def build(plan):
    stories = sorted(plan["stories"], key=lambda s: s["slot"])[:9]
    t0 = time.time()
    used, cands_by_slot = set(), {}
    # 1) photos fixed in stories.json (chosen by Claude) - just download
    for s in stories:
        s["photo_credit"], s["_img"] = "", None
        fx = (s.get("photo") or {}).get("fixed")
        if fx:
            s["_img"] = get_photo(fx["url"])
            if s["_img"] is not None:
                s["photo_credit"] = fx.get("credit", ""); used.add(original_url(fx["url"]))
            time.sleep(1)
    # 2) photo library (instant) + one quick Wikimedia search only for specifically named ships/places
    taken = set()
    for s in stories:
        if s["_img"] is not None: continue
        cands = library.candidates(s, taken)
        if (s.get("photo") or {}).get("exact_subjects"):
            try:
                for c in photos.search(s["photo"]["exact_subjects"][0], n=6)[:2]:
                    cands.append((photos.fetch_image(c["small"]), c)); time.sleep(1)
            except Exception as ex:
                print("  exact search skipped:", str(ex)[:80])
        if not cands:   # library empty for this type: fall back to normal search
            for c in photos.candidates_for(s, used)[:4]:
                try:
                    cands.append((photos.fetch_image(c["small"]), c)); time.sleep(1)
                except Exception as ex:
                    print("  thumb failed", str(ex)[:80])
        cands_by_slot[s["slot"]] = cands
        for _, m in cands[:1]:
            if m.get("library_file"): taken.add(m["library_file"])
    print(f"photo candidates ready in {time.time()-t0:.0f}s")
    # 3) ONE Gemini call checks all candidate photos
    choices = ai.pick_photos([s for s in stories if s["slot"] in cands_by_slot], cands_by_slot) if cands_by_slot else {}
    taken = set()
    for s in stories:
        if s["_img"] is not None or s["slot"] not in cands_by_slot: continue
        thumbs = cands_by_slot[s["slot"]]
        best, exact = choices.get(s["slot"], (0 if thumbs else -1, False))
        # never use the same library photo twice in one carousel
        if 0 <= best < len(thumbs) and thumbs[best][1].get("library_file") in taken:
            best = next((i for i, (_, m) in enumerate(thumbs) if m.get("library_file") not in taken), -1)
        if 0 <= best < len(thumbs):
            c = thumbs[best][1]
            if c.get("library_file"):
                s["_img"] = c["_full"]; s["library_file"] = c["library_file"]; taken.add(c["library_file"])
            else:
                s["_img"] = get_photo(c["full"]) or thumbs[best][0]; used.add(c["full"])
            s["photo_credit"] = ("" if exact else "Representative · ") + c["credit"]
    cover_photos = [s["_img"] for s in stories if s["_img"] is not None]
    print(f"photos ready in {time.time()-t0:.0f}s")

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
