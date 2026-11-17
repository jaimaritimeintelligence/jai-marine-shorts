"""Render one Reel episode: narration (TTS) + animated scenes + captions + music -> MP4.

usage: python reel/render.py reel/episodes/<id>/episode.json [--no-tts] [--preview SECONDS]
"""
import json, os, re, subprocess, sys, time, wave, io, base64
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
SR = 24000
FPS = 30
PAD_AFTER = 0.30          # silence after each scene's narration
PAD_FIRST = 0.30


# ---------------------------------------------------------------- TTS
VOICE_STYLE = ("Read this as a deep, calm, serious male documentary narrator with a clear Indian English accent. "
               "Build suspense, slight pauses at commas and full stops, never rushed:\n\n")


def _gemini_tts(text):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    models = [m.name.split("/")[-1] for m in client.models.list() if "tts" in m.name.lower()]
    models.sort(key=lambda n: ("pro" in n, n), reverse=False)   # flash first
    last = None
    for model in models:
        for attempt in range(3):
            try:
                r = client.models.generate_content(
                    model=model, contents=VOICE_STYLE + text,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=os.environ.get("TTS_VOICE", "Charon"))))))
                data = r.candidates[0].content.parts[0].inline_data.data
                if isinstance(data, str):
                    data = base64.b64decode(data)
                pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
                print(f"  tts ok via {model} ({len(pcm)/SR:.1f}s)", flush=True)
                return pcm
            except Exception as e:  # quota / transient
                last = e
                msg = str(e)
                print(f"  tts {model} try {attempt+1}: {msg[:160]}", flush=True)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    wait = re.search(r"retry in ([\d.]+)s", msg)
                    if wait and float(wait.group(1)) < 70:
                        time.sleep(float(wait.group(1)) + 2); continue
                    break
                if "404" in msg or "not found" in msg.lower():
                    break
                time.sleep(4)
    raise RuntimeError(f"Gemini TTS failed: {last}")


def _edge_tts(text):
    import asyncio, edge_tts, tempfile
    voice = os.environ.get("EDGE_VOICE", "en-IN-PrabhatNeural")
    tmp = tempfile.mktemp(suffix=".mp3")
    asyncio.run(edge_tts.Communicate(text, voice, rate=os.environ.get("EDGE_RATE", "+6%"), pitch="-3Hz").save(tmp))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", tmp, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    print(f"  tts ok via edge {voice}", flush=True)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def trim_silence(x, thr=0.012):
    idx = np.where(np.abs(x) > thr)[0]
    if len(idx) == 0:
        return x
    a = max(0, idx[0] - int(0.05 * SR)); b = min(len(x), idx[-1] + int(0.12 * SR))
    return x[a:b]


def tts(text, mode):
    if mode == "none":
        return None
    order = ["gemini", "edge"] if mode == "auto" else [mode]
    for prov in order:
        try:
            if prov == "gemini" and os.environ.get("GEMINI_API_KEY"):
                return trim_silence(_gemini_tts(text))
            if prov == "edge":
                return trim_silence(_edge_tts(text))
        except Exception as e:
            print(f"  provider {prov} failed: {str(e)[:200]}", flush=True)
    raise SystemExit("No TTS provider worked")


def est_duration(text):
    words = len(text.split())
    return words / 2.55 + text.count(".") * 0.25 + 0.3


# ---------------------------------------------------------------- word timing
def word_times(text, t0, dur):
    words = text.split()
    wts = []
    for w in words:
        k = len(re.sub(r"[^\w]", "", w)) + 2.5
        if re.search(r"[.!?]$", w) or w.endswith("..."): k += 6
        elif re.search(r"[,;:—]$", w): k += 3.5
        wts.append(k)
    tot = sum(wts); out = []; t = t0
    for w, k in zip(words, wts):
        d = dur * k / tot
        out.append({"w": w, "s": round(t, 3), "e": round(t + d * 0.92, 3)})
        t += d
    return out


# ---------------------------------------------------------------- music (generated here, licence-free)
INTENSITY = {"hook": .85, "alarm": 1.0, "title": .6, "ship_profile": .45, "photo": .6, "river": .7, "gauges": .8,
             "turn": .95, "impact": 1.0, "phone": .7, "quote": .9, "card": .55, "cta": .45}


def _lp(x, cutoff):
    """one-pole low-pass (cutoff Hz)"""
    a = np.exp(-2 * np.pi * cutoff / SR); y = np.empty_like(x); acc = 0.0
    # vectorised via scipy if present
    try:
        from scipy.signal import lfilter
        return lfilter([1 - a], [1, -a], x)
    except Exception:
        for i, v in enumerate(x):
            acc = (1 - a) * v + a * acc; y[i] = acc
        return y


def music(total, impacts, scenes=None, starts=None):
    """Cinematic tension bed: dark detuned pad, driving low pulse, ticking clock, risers into impacts, booms."""
    n = int(total * SR); t = np.arange(n) / SR; rng = np.random.default_rng(11)
    # intensity envelope per scene
    env = np.full(n, 0.6)
    if scenes and starts:
        for sc, st in zip(scenes, starts):
            a = int(st * SR); b = min(n, int((st + sc["_dur"]) * SR))
            env[a:b] = INTENSITY.get(sc["type"], .6)
        env = _lp(env, 0.6)
    # pad: detuned saws around A minor with a tense flat-2 (Bb)
    pad = np.zeros(n)
    for f, g in ((55, 1), (55.4, .8), (82.4, .6), (110, .45), (116.5, .35), (164.8, .25)):
        ph = (t * f + rng.random()) % 1.0
        pad += g * (2 * ph - 1)
    pad = _lp(pad, 700) * (0.7 + 0.3 * np.sin(2 * np.pi * t / 7.5))
    # driving pulse at 92 bpm: low thump + muted tick on off-beats
    beat = 60 / 92; pulse = np.zeros(n); tick = np.zeros(n)
    L = int(0.35 * SR); kenv = np.exp(-np.linspace(0, 7, L)); kick = kenv * np.sin(2 * np.pi * (52 + 40 * kenv) * np.arange(L) / SR)
    T = int(0.03 * SR); tk = rng.standard_normal(T) * np.exp(-np.linspace(0, 8, T))
    k = 0
    for st in np.arange(0.2, total, beat / 2):
        i = int(st * SR)
        if k % 2 == 0 and i + L < n: pulse[i:i + L] += kick
        if i + T < n: tick[i:i + T] += tk * (1.0 if k % 2 else 0.5)
        k += 1
    tick = tick - _lp(tick, 3000)            # high-passed clicks
    # risers + booms
    fx = np.zeros(n)
    for it in impacts:
        i = int(it * SR); r0 = max(0, i - int(3.5 * SR))
        if i > r0:
            ramp = np.linspace(0, 1, i - r0) ** 2.2
            fx[r0:i] += ramp * (0.6 * rng.standard_normal(i - r0) * 0.5 + np.sin(2 * np.pi * np.cumsum(150 + 650 * ramp) / SR))
        Lb = int(3 * SR)
        if i + Lb < n:
            e = np.exp(-np.linspace(0, 4.5, Lb))
            fx[i:i + Lb] += 2.2 * e * (np.sin(2 * np.pi * 36 * np.arange(Lb) / SR) + 0.5 * rng.standard_normal(Lb) * np.exp(-np.linspace(0, 25, Lb)))
    fx = _lp(fx, 4000)
    mix = 0.5 * pad * (0.5 + 0.5 * env) + 0.9 * pulse * env ** 1.5 + 0.18 * tick * env + 0.8 * fx
    fade = int(1.2 * SR); mix[:fade] *= np.linspace(0, 1, fade); mix[-fade:] *= np.linspace(1, 0, fade)
    return mix / (np.abs(mix).max() + 1e-6) * 0.95


def write_wav(path, x):
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- frames
def render_frames(ep, total, out_mp4, preview=None):
    from playwright.sync_api import sync_playwright
    n = int(total * FPS) if not preview else int(preview * FPS)
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg",
                           "-i", "-", "-c:v", "libx264", "-preset", "faster", "-crf", "23", "-maxrate", "2800k", "-bufsize", "5600k", "-pix_fmt", "yuv420p", str(out_mp4)],
                          stdin=subprocess.PIPE)
    with sync_playwright() as p:
        kw = {"args": ["--force-device-scale-factor=1"]}
        try:
            b = p.chromium.launch(channel="chrome", **kw)
        except Exception:
            b = p.chromium.launch(**kw)
        page = b.new_page(viewport={"width": 1080, "height": 1920})
        page.goto((ROOT / "engine.html").as_uri())
        page.wait_for_function("document.fonts.ready.then(()=>true)")
        page.evaluate("ep=>setEpisode(ep)", ep)
        page.evaluate("document.fonts.load('900 40px M')")
        t0 = time.time()
        for i in range(n):
            page.evaluate(f"renderFrame({i / FPS})")
            ff.stdin.write(page.screenshot(type="jpeg", quality=88))
            if i % 300 == 0:
                print(f"  frame {i}/{n}  {time.time()-t0:.0f}s", flush=True)
        b.close()
    ff.stdin.close(); ff.wait()


def snapshot(ep, times, outdir):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome")
        except Exception:
            b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1080, "height": 1920})
        page.goto((ROOT / "engine.html").as_uri())
        page.wait_for_function("document.fonts.ready.then(()=>true)")
        page.evaluate("ep=>setEpisode(ep)", ep)
        for t in times:
            page.evaluate(f"renderFrame({t})")
            page.wait_for_timeout(60)
            page.screenshot(path=str(Path(outdir) / f"snap_{t:06.2f}.jpg"), type="jpeg", quality=80)
        b.close()


# ---------------------------------------------------------------- main
def build(ep_path, mode="auto", preview=None, snaps=None):
    ep_path = Path(ep_path); work = ep_path.parent
    ep = json.loads(ep_path.read_text())
    voice = []; words = []; t = PAD_FIRST; impacts = []
    human = None
    if mode == "human":
        import human_voice as hv
        rec = os.environ["VOICE_FILE"]
        heard = hv.transcribe(rec); audio = hv.load_audio(rec)
        per = hv.align(ep["scenes"], heard)
        rate = hv.speaking_rate(per)
        target = float(os.environ.get("TARGET_WPS", "2.6"))       # brisk storytelling pace
        factor = max(1.0, min(1.12, target / rate)) if rate else 1.0
        print(f"speaking rate {rate:.2f} words/s -> tempo x{factor:.2f}", flush=True)
        human = []
        for w in per:
            a_, t_ = hv.cut_scene(audio, w, max_gap=0.75)   # keep dramatic pauses
            a_ = hv.stretch(a_, factor)
            human.append((a_, [{"w": x["w"], "s": x["s"] / factor, "e": x["e"] / factor} for x in t_]))
        cov = [round(sc["_coverage"], 2) for sc in ep["scenes"]]
        print("coverage per scene:", cov, flush=True)
        missing = [i + 1 for i, c in enumerate(cov) if c < 0.6]
        if missing:
            raise SystemExit(f"VOICE_MISSING:{missing}")
    for i, sc in enumerate(ep["scenes"]):
        print(f"scene {i+1}/{len(ep['scenes'])} {sc['type']}", flush=True)
        a = human[i][0] if human else tts(sc["narration"], mode)
        d = len(a) / SR if a is not None else est_duration(sc["narration"])
        lead = PAD_FIRST if i == 0 else 0.0
        sc["_dur"] = round(lead + d + PAD_AFTER + sc.get("extra", 0), 3)
        start = t if i == 0 else t
        words += word_times(sc["narration"], start + (0 if i else 0), d)
        voice.append((start, a))
        if sc["type"] == "impact":
            impacts.append(t - lead + 0.02 if i else t)
        t = (t - lead if i == 0 else t) + sc["_dur"] if i else sc["_dur"]
        if i == 0:
            t = sc["_dur"]
        # next scene's narration starts at its scene start
    # recompute scene starts exactly as the engine will
    starts = []; acc = 0
    for sc in ep["scenes"]:
        starts.append(acc); acc += sc["_dur"]
    total = acc
    words = []; impacts = []; voice_track = np.zeros(int((total + 1) * SR), dtype=np.float32)
    for i, sc in enumerate(ep["scenes"]):
        lead = PAD_FIRST if i == 0 else 0.0
        st = starts[i] + lead
        a = voice[i][1]
        d = len(a) / SR if a is not None else est_duration(sc["narration"])
        if human:
            words += [{"w": x["w"], "s": round(st + x["s"], 3), "e": round(st + x["e"], 3)} for x in human[i][1]]
        else:
            words += word_times(sc["narration"], st, d)
        if a is not None:
            j = int(st * SR); voice_track[j:j + len(a)] += a
        if sc["type"] == "impact" or (sc.get("p") or {}).get("flash"):
            impacts.append(starts[i])
        if sc["type"] == "hook" and (sc.get("p") or {}).get("hitAt") is not None and not (sc.get("p") or {}).get("src"):
            impacts.append(starts[i] + sc["p"]["hitAt"])
    ep["words"] = words
    (work / "timeline.json").write_text(json.dumps(ep, indent=1))
    print(f"total {total:.1f}s, {len(words)} words", flush=True)
    if snaps is not None:
        snapshot(ep, snaps if snaps else [s + 1.5 for s in starts], work)
        return
    write_wav(work / "voice.wav", voice_track)
    write_wav(work / "music.wav", music(total + 1, impacts, ep["scenes"], starts))
    render_frames(ep, total, work / "video.mp4", preview)
    final = work / f"{ep['id']}.mp4"
    # voice chain: rumble cut, warmth, presence, gentle compression; music ducked under voice
    fc = ("[0:a]highpass=f=80,equalizer=f=180:t=q:w=1:g=2,equalizer=f=3200:t=q:w=1.2:g=3,"
          "deesser=i=0.4,acompressor=threshold=-21dB:ratio=3.5:attack=8:release=140:makeup=2,asplit=2[v][vsc];"
          "[1:a]volume=0.75[m];[m][vsc]sidechaincompress=threshold=0.06:ratio=2.5:attack=30:release=500[md];"
          "[v][md]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(work / "voice.wav"), "-i", str(work / "music.wav"),
                    "-i", str(work / "video.mp4"), "-filter_complex", fc, "-map", "2:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(final)],
                   check=True)
    try:   # cover / thumbnail = the hook frame
        snapshot(dict(ep, words=[]), [min(2.8, ep["scenes"][0]["_dur"] - 0.3)], work)
        snap = sorted(work.glob("snap_*.jpg"))[0]; snap.rename(work / "cover.jpg")
    except Exception as e:
        print("cover failed", e)
    print("done", final, flush=True)
    return final


if __name__ == "__main__":
    a = sys.argv[1:]
    mode = "none" if "--no-tts" in a else os.environ.get("TTS_MODE", "auto")
    prev = float(a[a.index("--preview") + 1]) if "--preview" in a else None
    snaps = [] if "--snaps" in a else None
    build(a[0], mode, prev, snaps)
