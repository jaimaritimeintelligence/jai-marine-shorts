"""Rendered 3D frames + captions + labels + voice + music -> final MP4"""
import json, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path

ep = json.load(open(sys.argv[1])); work = Path(sys.argv[2]); out = sys.argv[3]
plan = json.load(open(work / "plan.json")); FPS = plan["fps"]; W, H = 1080, 1920
F = Path(__file__).resolve().parents[1] / "fonts"
f_cap = ImageFont.truetype(str(F / "Montserrat-700.ttf"), 44)
f_lab = ImageFont.truetype(str(F / "Montserrat-800.ttf"), 64)
f_small = ImageFont.truetype(str(F / "Montserrat-800.ttf"), 46)
f_brand = ImageFont.truetype(str(F / "Montserrat-800.ttf"), 30)
GOLD = (242, 182, 50); RED = (255, 77, 77)
words = plan["words"]


def chunks():
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        if len(cur) >= 5 or w["w"][-1:] in ".,!?;:":
            out.append(cur); cur = []
    if cur: out.append(cur)
    return out
CH = chunks()


def caption_at(t):
    for c in CH:
        s, e = words[c[0]]["s"], words[c[-1]]["e"] + 0.25
        if s - 0.05 <= t <= e:
            return " ".join(words[i]["w"] for i in c)
    return None


def draw_text_box(d, txt, font, cy, pad=(26, 14), fill=(255, 255, 255), box=(0, 0, 0, 150)):
    tw = d.textlength(txt, font=font); asc, desc = font.getmetrics()
    x0 = (W - tw) / 2 - pad[0]; y0 = cy - (asc + desc) / 2 - pad[1]
    d.rounded_rectangle([x0, y0, x0 + tw + 2 * pad[0], y0 + asc + desc + 2 * pad[1]], radius=18, fill=box)
    d.text(((W - tw) / 2, y0 + pad[1]), txt, font=font, fill=fill)


def wrap(d, txt, font, maxw):
    lines, cur = [], ""
    for w in txt.split():
        if d.textlength((cur + " " + w).strip(), font=font) > maxw and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + [cur]


def overlay(img, t, shot):
    d = ImageDraw.Draw(img, "RGBA")
    d.text((50, 70), "JAI MARINE SHORTS · HOW IT WORKS", font=f_brand, fill=GOLD)
    lt = t - shot["start"]; y = 330
    for lab in shot["labels"]:
        if lab["at"] <= lt <= lab.get("until", 99):
            a = min(1, (lt - lab["at"]) / 0.3)
            font = f_small if lab.get("style") in ("small", "cross") else f_lab
            txt = ("×  " if lab.get("style") == "cross" else "") + lab["text"]
            col = RED if lab.get("style") == "cross" else (255, 255, 255)
            for line in wrap(d, txt, font, 960):
                tw = d.textlength(line, font=font)
                d.text(((W - tw) / 2, y), line, font=font, fill=(*col, int(255 * a)), stroke_width=6, stroke_fill=(0, 0, 0, int(200 * a)))
                y += font.size + 18
            if lab.get("arrows"):
                import math as _m
                off = 40 * _m.sin(lt * 9)
                for sgn in (-1, 1):
                    x0 = W / 2 + sgn * 60 + off; x1 = W / 2 + sgn * 260 + off; yy = y + 30
                    d.line([(x0, yy), (x1, yy)], fill=(*GOLD, int(255 * a)), width=12)
                    d.polygon([(x1 + sgn * 34, yy), (x1, yy - 26), (x1, yy + 26)], fill=(*GOLD, int(255 * a)))
                y += 90
            y += 10
    cap = caption_at(t)
    if cap:
        lines = wrap(d, cap, f_cap, 880)
        cy = 1500 - (len(lines) - 1) * 32
        for line in lines:
            draw_text_box(d, line, f_cap, cy); cy += 66
    return img


ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                       "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(work / "video.mp4")], stdin=subprocess.PIPE)
for k, shot in enumerate(plan["shots"]):
    fd = work / f"shot{k + 1}"
    for f in range(1, shot["frames"] + 1):
        p = fd / f"f{f:05d}.jpg"
        img = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS) if p.exists() else Image.new("RGB", (W, H))
        t = shot["start"] + (f - 1) / FPS
        img = overlay(img, t, shot)
        # gentle fade between shots
        if f <= 6:
            img = Image.blend(Image.new("RGB", (W, H)), img, f / 6)
        b = __import__("io").BytesIO(); img.save(b, "JPEG", quality=92); ff.stdin.write(b.getvalue())
ff.stdin.close(); ff.wait()

# music: licensed track, looped, soft under the voice
root = Path(__file__).resolve().parents[1]
music = root / "reel" / "music" / f"{ep['music']}.mp3"
fc = ("[0:a]highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=8:release=140:makeup=2,asplit=2[v][vsc];"
      "[1:a]volume=0.30,afade=t=in:d=1[m];[m][vsc]sidechaincompress=threshold=0.06:ratio=2.5:attack=30:release=500[md];"
      "[v][md]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(work / "voice.wav"), "-stream_loop", "-1", "-i", str(music), "-i", str(work / "video.mp4"),
                "-filter_complex", fc, "-map", "2:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-shortest", "-movflags", "+faststart", out], check=True)
# cover = first shot mid-frame with the hook label
c = Image.open(work / "shot1" / f"f{max(1, plan['shots'][0]['frames'] // 2):05d}.jpg").convert("RGB").resize((W, H), Image.LANCZOS)
d = ImageDraw.Draw(c, "RGBA")
for i, line in enumerate(["WHY DON'T", "VIBRATING BOLTS", "SHAKE LOOSE?"]):
    f = ImageFont.truetype(str(F / "Montserrat-800.ttf"), 104 if i != 1 else 92)
    tw = d.textlength(line, font=f); d.text(((W - tw) / 2, 300 + i * 125), line, font=f, fill=GOLD if i == 2 else (255, 255, 255), stroke_width=8, stroke_fill=(0, 0, 0))
c.save(Path(out).with_name("cover.jpg"), quality=92)
print("done", out)
