"""Gemini: pick the day's 9 stories, write slides, and check photos match the story."""
import os, json, time, io
from google import genai
from google.genai import types

MODELS = [m.strip() for m in os.environ.get("GEMINI_MODELS", "gemini-2.5-flash,gemini-flash-latest,gemini-2.5-flash-lite").split(",") if m.strip()]
_client = None


def client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _call(contents, json_out=True, temperature=0.4):
    last = None
    for model in MODELS:
        for attempt in range(3):
            try:
                cfg = types.GenerateContentConfig(temperature=temperature,
                                                  response_mime_type="application/json" if json_out else "text/plain")
                r = client().models.generate_content(model=model, contents=contents, config=cfg)
                time.sleep(13)  # stay inside free-tier requests-per-minute
                return json.loads(r.text) if json_out else r.text
            except Exception as ex:
                last = ex
                msg = str(ex)
                print(f"  Gemini {model} attempt {attempt+1} failed: {msg[:200]}")
                if "404" in msg or "not found" in msg.lower():
                    break  # try next model name
                time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"Gemini failed: {last}")


EDITOR_RULES = """
You are the news editor of "Jai Marine Shorts", an Instagram page for seafarers and marine engineers.
Pick EXACTLY 9 stories from the candidate list for today's 10-slide carousel (slide 1 is the cover).

SLIDE MIX (follow strictly; this is the owner's approved daily format):
- Slide 2: CRUDE OIL PRICE today (Brent/WTI level, change, reason). If no oil-price item exists, use the strongest tanker/freight market story.
- Slides 3-8: the human and safety side of shipping, choosing the most important of:
  ship accidents/collisions/fires/groundings; attacks on ships (Strait of Hormuz, Red Sea, Black Sea);
  crew and seafarer stories (crew safe/rescued/injured/killed, abandonment, wages, court rulings, MLC, unions, strikes);
  cyber attacks / internet / connectivity for seafarers; and AT LEAST ONE LNG story (LNG carriers, deliveries, orders, disputes, trade).
- Slides 9-10: commercial news - tanker/gas sale & purchase, newbuilding orders and deliveries, company deals, ports, regulation.
Prefer stories with concrete facts (ship names, numbers, places). Never pick two slides about the exact same event
unless one is clearly the human/crew angle of it. Ignore opinion pieces, adverts, webinars, job ads and stories older than 30 hours.

WRITING RULES:
- headline: 5-9 words, punchy, news-style. Wrap the 1-3 most important words in [square brackets] (they print in gold).
  Example: "Tanker hits New Orleans riverboat - [all aboard survive]"
- summary: 3 or 4 short sentences, 45-65 words, plain simple English. ONLY facts stated in the candidate text.
  Never invent numbers, names, causes or quotes. If something is a claim, say who claims it and that it is not confirmed.
  If a candidate has too few facts for 45 words, write fewer words rather than invent.
- sources: the outlet names of the candidates you used, max 3, e.g. "Splash247, Reuters".
- photo: help find a REAL photo. Give
    exact_subjects: list of specific named ships / ports / places / buildings in the story (may be empty),
    ship_type: one of "crude oil tanker","VLCC","product tanker","LNG carrier","LPG carrier","container ship","bulk carrier",
               "car carrier","cruise ship","riverboat","offshore vessel","tug","naval","port","shipyard","other",
    queries: 3-4 Wikimedia Commons search phrases from most specific to most general
             (e.g. ["Knutsen LNG carrier", "LNG carrier at sea", "LNG tanker"]). For oil price use tanker/oil terminal scenes.
Also write:
- caption: Instagram caption. First line: "Everything that happened in the shipping industry in the last 24 hours ({date}) 🚢"
  then a numbered list of the 9 headlines (no brackets), then "Sources are credited on each slide. Follow @jaimarineshorts for daily shipping news.",
  then 15-20 relevant hashtags (#shipping #seafarers #maritime #merchantnavy #tanker #LNG ...). Max 2000 characters.

Return JSON only:
{"stories":[{"slot":2,"candidate_ids":[..],"headline":"..","summary":"..","sources":"..",
  "photo":{"exact_subjects":[..],"ship_type":"..","queries":[..]}} ... 9 items, slots 2..10 ...],
 "caption":".."}
"""


def plan_carousel(candidates, date_text):
    lines = []
    for i, c in enumerate(candidates):
        body = c.get("text") or c.get("summary") or ""
        lines.append(f"[{i}] ({c['source']}, {c['time'][:16]}) {c['title']}\n    {body[:1500]}")
    prompt = EDITOR_RULES.replace("{date}", date_text) + "\n\nTODAY: " + date_text + "\n\nCANDIDATES:\n" + "\n".join(lines)
    plan = _call(prompt, temperature=0.3)
    stories = sorted(plan["stories"], key=lambda s: s["slot"])[:9]
    for k, s in enumerate(stories):
        s["slot"] = k + 2
    plan["stories"] = stories
    return plan


def pick_photo(story, thumbs):
    """thumbs: list of (PIL.Image, meta). Returns (index or -1, is_exact_subject)."""
    if not thumbs:
        return -1, False
    parts = [f"""News story for an Instagram slide:
HEADLINE: {story['headline']}
SUMMARY: {story['summary']}
Specific subjects: {', '.join(story['photo'].get('exact_subjects') or []) or 'none'}
Ship type: {story['photo'].get('ship_type')}

Below are {len(thumbs)} candidate photos, numbered from 0. Choose the ONE photo that best illustrates this story
as a real, good-looking news photo. It must show the right kind of subject (e.g. an LNG carrier for an LNG story,
a tanker for a tanker story, the named port/place if possible). Reject maps, logos, diagrams, drawings, old
black-and-white archive pictures, people's close-up portraits and low-quality images.
Return JSON: {{"best": <index or -1 if none fits>, "exact": <true only if the photo shows the specifically named ship/place>}}"""]
    for i, (im, meta) in enumerate(thumbs):
        buf = io.BytesIO(); im.convert("RGB").save(buf, "JPEG", quality=80)
        parts.append(f"Photo {i}: {meta.get('title','')}")
        parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
    try:
        r = _call(parts, temperature=0.1)
        return int(r.get("best", -1)), bool(r.get("exact", False))
    except Exception as ex:
        print("  photo check failed:", ex)
        return 0, False
