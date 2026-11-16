"""Gemini: pick the day's 9 stories, write slides, and check photos match the story."""
import os, json, time, io
from google import genai
from google.genai import types

import re
_ENV_MODELS = [m.strip() for m in os.environ.get("GEMINI_MODELS", "").split(",") if m.strip()]
MODELS = list(_ENV_MODELS)
LAST_MODEL = None
_client = None


def _discover():
    """Find the newest Flash text models this key may use (Google retires old names often)."""
    found = []
    try:
        for m in client().models.list():
            name = m.name.split("/")[-1]
            acts = getattr(m, "supported_actions", None) or []
            if acts and "generateContent" not in acts: continue
            if "flash" not in name or any(x in name for x in ("image", "tts", "live", "audio", "embed", "preview-0", "exp", "thinking")):
                continue
            v = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
            found.append((float(v.group(1)) if v else 0, "lite" not in name, "preview" not in name, name))
    except Exception as ex:
        print("  model list failed:", ex)
    found.sort(reverse=True)
    names = [x[3] for x in found]
    print("  Gemini models available:", names[:6])
    return names[:4]


def client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _call(contents, json_out=True, temperature=0.4, budget_s=150):
    """Try each available model once (each has its own free quota). Fail fast - never hang the daily run."""
    global MODELS, LAST_MODEL
    if not MODELS:
        MODELS = _discover() or ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    start, last = time.time(), None
    for model in MODELS:
        for attempt in range(2):
            if time.time() - start > budget_s:
                raise RuntimeError(f"Gemini time budget used up: {last}")
            try:
                cfg = types.GenerateContentConfig(temperature=temperature,
                                                  response_mime_type="application/json" if json_out else "text/plain")
                r = client().models.generate_content(model=model, contents=contents, config=cfg)
                LAST_MODEL = model
                return json.loads(r.text) if json_out else r.text
            except Exception as ex:
                last = ex
                msg = str(ex)
                print(f"  Gemini {model} failed: {msg[:160]}")
                if any(k in msg for k in ("404", "429", "RESOURCE_EXHAUSTED", "quota")) or "not found" in msg.lower():
                    break  # next model (separate quota)
                time.sleep(8)
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


def pick_photos(stories, cands_by_slot):
    """ONE Gemini call for all slides. cands_by_slot: {slot: [(PIL.Image, meta), ...]}.
    Returns {slot: (index or -1, exact_bool)}."""
    parts = ["""You are choosing news photos for an Instagram carousel about shipping.
For EACH slide below, look at its numbered candidate photos and choose the ONE real photo that best illustrates
that slide's story. It must show the right kind of subject (an LNG carrier for an LNG story, a tanker for a
tanker story, the named port/place/building if possible). Reject maps, satellite images, logos, diagrams,
drawings, old black-and-white archive pictures, unrelated people, animals or buildings. -1 if none fits.
"exact" = true only if the photo clearly shows the specifically named ship/place of the story.
Return JSON only: {"choices": [{"slot": <n>, "best": <index or -1>, "exact": <true/false>}, ...]}"""]
    for s in stories:
        cands = cands_by_slot.get(s["slot"]) or []
        if not cands: continue
        ph = s.get("photo", {})
        parts.append(f"\n=== SLIDE {s['slot']} ===\nHEADLINE: {s['headline']}\nSTORY: {s['summary']}\n"
                     f"Named subjects: {', '.join(ph.get('exact_subjects') or []) or 'none'} | Ship type: {ph.get('ship_type')}")
        for i, (im, meta) in enumerate(cands):
            buf = io.BytesIO(); im.convert("RGB").save(buf, "JPEG", quality=70)
            parts.append(f"Slide {s['slot']} photo {i}: {meta.get('title','')[:90]}")
            parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
    out = {}
    try:
        r = _call(parts, temperature=0.1, budget_s=180)
        for c in r.get("choices", []):
            out[int(c["slot"])] = (int(c.get("best", -1)), bool(c.get("exact", False)))
    except Exception as ex:
        print("  photo check failed, using best keyword match instead:", str(ex)[:200])
    return out
