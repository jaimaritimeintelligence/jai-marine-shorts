"""Jai Marine Shorts slide renderer - approved 'last 24 hours' style.
Full-bleed photo, dark fade, condensed uppercase headline with gold accent words.
Accent words in a headline are written inside [square brackets]."""
from PIL import Image, ImageDraw, ImageFont
import math, os

W, H = 1080, 1350
FD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts") + "/"
ANTON = FD + "Anton-Regular.ttf"
OSW = FD + "Oswald-Bold.ttf"
OSWS = FD + "Oswald-SemiBold.ttf"
WHITE = (255, 255, 255)
ACCENT = (242, 190, 60)
GREY = (195, 195, 195)


def f(p, s):
    return ImageFont.truetype(p, s)


# ---------- photo helpers ----------
def cover_fit(img, w, h, focus_y=0.45):
    img = img.convert("RGB")
    s = max(w / img.width, h / img.height)
    im = img.resize((math.ceil(img.width * s), math.ceil(img.height * s)), Image.LANCZOS)
    x = (im.width - w) // 2
    y = int((im.height - h) * focus_y)
    return im.crop((x, y, x + w, y + h))


def placeholder(w, h, seed=0):
    """Only used if no photo at all could be found (should be rare)."""
    im = Image.new("RGB", (w, h)); d = ImageDraw.Draw(im)
    hz = int(h * 0.58)
    sky = [(40, 70, 110), (120, 150, 180), (230, 170, 110)][seed % 3]
    for y in range(hz):
        t = y / hz
        d.line([(0, y), (w, y)], fill=tuple(int(18 + (sky[i] - 18) * t) for i in range(3)))
    for y in range(hz, h):
        t = (y - hz) / (h - hz)
        d.line([(0, y), (w, y)], fill=(int(20 - 10 * t), int(45 - 25 * t), int(75 - 40 * t)))
    return im


def fade(img, start=0.28):
    w, h = img.size
    grad = Image.new("L", (1, h))
    for y in range(h):
        t = (y / h - start) / (1 - start)
        grad.putpixel((0, y), int(255 * max(0, min(1, t * 1.35))))
    grad = grad.resize((w, h))
    return Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, grad)


# ---------- text helpers ----------
def tokens(text):
    out, acc = [], False
    for w in text.replace("[", " [ ").replace("]", " ] ").split():
        if w == "[": acc = True; continue
        if w == "]": acc = False; continue
        out.append((w.upper(), acc))
    return out


def wrap_tokens(d, toks, font, maxw):
    lines, cur = [], []
    for t in toks:
        trial = cur + [t]
        if d.textlength(" ".join(w for w, _ in trial), font=font) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur); cur = [t]
    if cur: lines.append(cur)
    return lines


def fit_headline(d, text, maxw, max_lines, start=118, minsize=70):
    toks = tokens(text)
    for size in range(start, minsize - 1, -4):
        fnt = f(ANTON, size)
        lines = wrap_tokens(d, toks, fnt, maxw)
        if len(lines) <= max_lines:
            return fnt, lines, size
    fnt = f(ANTON, minsize)
    return fnt, wrap_tokens(d, toks, fnt, maxw), minsize


def wrap_words(d, text, fnt, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= maxw: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines


def ellipsize(d, text, fnt, maxw):
    if d.textlength(text, font=fnt) <= maxw: return text
    while text and d.textlength(text + "…", font=fnt) > maxw: text = text[:-1]
    return text + "…"


def draw_centered_line(d, y, line, fnt):
    sp = d.textlength(" ", font=fnt)
    total = sum(d.textlength(w, font=fnt) for w, _ in line) + sp * (len(line) - 1)
    x = (W - total) / 2
    for w, acc in line:
        d.text((x, y), w, font=fnt, fill=ACCENT if acc else WHITE)
        x += d.textlength(w, font=fnt) + sp


def brand_rule(d, y, text="JAI MARINE SHORTS"):
    fnt = f(OSW, 30)
    tw = d.textlength(text, font=fnt)
    d.line([(90, y + 20), (W / 2 - tw / 2 - 20, y + 20)], fill=WHITE, width=3)
    d.line([(W / 2 + tw / 2 + 20, y + 20), (W - 90, y + 20)], fill=WHITE, width=3)
    d.text((W / 2, y + 20), text, font=fnt, fill=WHITE, anchor="mm")


def counter(d, n, total):
    s = f"{n}/{total}"; fnt = f(OSWS, 28)
    tw = d.textlength(s, font=fnt)
    d.rounded_rectangle([W - 50 - tw - 36, 40, W - 50, 88], 24, fill=(0, 0, 0, 160))
    d.text((W - 50 - tw / 2 - 18, 64), s, font=fnt, fill=WHITE, anchor="mm")


def watermark(d):
    d.rounded_rectangle([36, 40, 330, 88], 24, fill=(0, 0, 0, 140))
    d.text((52, 64), "@JAIMARINESHORTS", font=f(OSW, 26), fill=WHITE, anchor="lm")


# ---------- slides ----------
def story(n, total, headline, summary, source_credit, photo_credit, out, photo=None):
    base = cover_fit(photo, W, H, 0.4) if photo is not None else placeholder(W, H, seed=n)
    img = fade(base)
    d = ImageDraw.Draw(img, "RGBA")
    watermark(d); counter(d, n, total)
    hfont, hlines, hs = fit_headline(d, headline, W - 100, 3)
    sfont = f(OSWS, 35)
    sub_lines = wrap_words(d, summary.upper(), sfont, W - 120)[:7]
    lh = int(hs * 1.08); sh = 46
    block = 60 + len(hlines) * lh + 30 + len(sub_lines) * sh
    y = H - 120 - block
    brand_rule(d, y); y += 60
    for ln in hlines:
        draw_centered_line(d, y, ln, hfont); y += lh
    y += 24
    for ln in sub_lines:
        d.text((W / 2, y + sh / 2), ln, font=sfont, fill=WHITE, anchor="mm"); y += sh
    # two credit lines + swipe
    cf = f(OSWS, 21)
    sw = "SWIPE FOR MORE »" if n < total else "FOLLOW @JAIMARINESHORTS"
    swf = f(OSW, 24)
    sww = d.textlength(sw, font=swf)
    d.text((50, H - 66), ellipsize(d, ("SOURCE: " + source_credit).upper(), cf, W - 100), font=cf, fill=GREY, anchor="lm")
    if photo_credit:
        d.text((50, H - 36), ellipsize(d, ("PHOTO: " + photo_credit).upper(), cf, W - 140 - sww), font=cf, fill=GREY, anchor="lm")
    d.text((W - 50, H - 36), sw, font=swf, fill=ACCENT, anchor="rm")
    img.save(out, quality=92)


def cover(total, date_text, photos, out):
    """Collage: 3 vertical panels + 2 circle insets, big headline."""
    photos = [p for p in (photos or []) if p is not None]
    img = Image.new("RGB", (W, H), (0, 0, 0))
    panel_h = 760; pw = W // 3
    for i in range(3):
        ph = photos[i] if i < len(photos) else placeholder(pw, panel_h, seed=i)
        img.paste(cover_fit(ph, pw, panel_h), (i * pw, 0))
    img = fade(img, start=0.30)
    d = ImageDraw.Draw(img, "RGBA")
    for j, cx in enumerate([W * 0.30, W * 0.70]):
        r = 125
        src = photos[3 + j] if len(photos) > 3 + j else placeholder(2 * r, 2 * r, seed=j + 1)
        c = cover_fit(src, 2 * r, 2 * r)
        mask = Image.new("L", (2 * r, 2 * r), 0); ImageDraw.Draw(mask).ellipse([0, 0, 2 * r, 2 * r], fill=255)
        img.paste(c, (int(cx - r), 520), mask)
        d.ellipse([cx - r - 4, 516, cx + r + 4, 520 + 2 * r + 4], outline=ACCENT, width=8)
    watermark(d); counter(d, 1, total)
    y = 820
    for t, col in [("EVERYTHING THAT HAPPENED", WHITE), ("IN SHIPPING INDUSTRY", ACCENT), ("IN THE LAST 24 HOURS!", WHITE)]:
        s = 104; fnt = f(ANTON, s)
        while d.textlength(t, font=fnt) > W - 80: s -= 4; fnt = f(ANTON, s)
        d.text((W / 2, y), t, font=fnt, fill=col, anchor="mt"); y += int(s * 1.12)
    y += 18
    d.rounded_rectangle([50, y, 260, y + 58], 29, fill=WHITE)
    d.text((155, y + 29), "« SWIPE", font=f(OSW, 30), fill=(0, 0, 0), anchor="mm")
    d.text((W - 50, y + 29), date_text.upper(), font=f(OSW, 34), fill=ACCENT, anchor="rm")
    d.rectangle([0, H - 64, W, H], fill=ACCENT)
    d.text((W / 2, H - 32), "J A I   M A R I N E   S H O R T S   ·   D A I L Y   S H I P P I N G   N E W S",
           font=f(OSW, 26), fill=(0, 0, 0), anchor="mm")
    img.save(out, quality=92)
