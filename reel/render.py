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
def music(total, impacts, tense_until=None):
    n = int(total * SR); t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    lfo = 0.6 + 0.4 * np.sin(2 * np.pi * t / 9)
    drone = (np.sin(2 * np.pi * 55 * t) + 0.6 * np.sin(2 * np.pi * 82.4 * t) + 0.35 * np.sin(2 * np.pi * 110 * t + np.sin(2*np.pi*0.2*t))) * lfo
    # soft filtered noise "air"
    noise = rng.standard_normal(n)
    k = 400; air = np.convolve(noise, np.ones(k) / k, mode="same") * 3
    # heartbeat pulse ~ 62 bpm
    beat = np.zeros(n); period = 60 / 62
    for s in np.arange(0.5, total, period):
        for off, amp in ((0, 1.0), (0.22, 0.6)):
            i = int((s + off) * SR); L = int(0.25 * SR)
            if i + L < n:
                env = np.exp(-np.linspace(0, 9, L))
                beat[i:i+L] += amp * env * np.sin(2 * np.pi * 48 * np.arange(L) / SR)
    mix = 0.22 * drone + 0.05 * air + 0.5 * beat
    # impact booms + risers
    for it in impacts:
        i = int(it * SR); L = int(2.5 * SR)
        if i + L < n:
            env = np.exp(-np.linspace(0, 5, L))
            boom = env * (np.sin(2 * np.pi * 38 * np.arange(L) / SR) + 0.4 * rng.standard_normal(L) * np.exp(-np.linspace(0, 30, L)))
            mix[i:i+L] += 1.6 * boom
        r0 = max(0, i - int(3 * SR))
        if i > r0:
            ramp = np.linspace(0, 1, i - r0) ** 2
            mix[r0:i] += 0.25 * ramp * rng.standard_normal(i - r0) * 0.4 + 0.25 * ramp * np.sin(2*np.pi*(80+200*ramp)*np.arange(i-r0)/SR)
    fade = int(1.5 * SR)
    mix[:fade] *= np.linspace(0, 1, fade); mix[-fade:] *= np.linspace(1, 0, fade)
    return mix / (np.abs(mix).max() + 1e-6) * 0.9


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
            page.wait_for_timeout(30)
            page.screenshot(path=str(Path(outdir) / f"snap_{t:06.2f}.jpg"), type="jpeg", quality=80)
        b.close()


# ---------------------------------------------------------------- main
def build(ep_path, mode="auto", preview=None, snaps=None):
    ep_path = Path(ep_path); work = ep_path.parent
    ep = json.loads(ep_path.read_text())
    voice = []; words = []; t = PAD_FIRST; impacts = []
    for i, sc in enumerate(ep["scenes"]):
        print(f"scene {i+1}/{len(ep['scenes'])} {sc['type']}", flush=True)
        a = tts(sc["narration"], mode)
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
        words += word_times(sc["narration"], st, d)
        if a is not None:
            j = int(st * SR); voice_track[j:j + len(a)] += a
        if sc["type"] == "impact":
            impacts.append(starts[i])
    ep["words"] = words
    (work / "timeline.json").write_text(json.dumps(ep, indent=1))
    print(f"total {total:.1f}s, {len(words)} words", flush=True)
    if snaps is not None:
        snapshot(ep, snaps if snaps else [s + 1.5 for s in starts], work)
        return
    write_wav(work / "voice.wav", voice_track)
    write_wav(work / "music.wav", music(total + 1, impacts))
    render_frames(ep, total, work / "video.mp4", preview)
    final = work / f"{ep['id']}.mp4"
    # voice chain: rumble cut, warmth, presence, gentle compression; music ducked under voice
    fc = ("[0:a]highpass=f=80,equalizer=f=180:t=q:w=1:g=2,equalizer=f=3200:t=q:w=1.2:g=3,"
          "acompressor=threshold=-20dB:ratio=3:attack=10:release=150,asplit=2[v][vsc];"
          "[1:a]volume=0.22[m];[m][vsc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[md];"
          "[v][md]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(work / "voice.wav"), "-i", str(work / "music.wav"),
                    "-i", str(work / "video.mp4"), "-filter_complex", fc, "-map", "2:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(final)],
                   check=True)
    print("done", final, flush=True)
    return final


if __name__ == "__main__":
    a = sys.argv[1:]
    mode = "none" if "--no-tts" in a else os.environ.get("TTS_MODE", "auto")
    prev = float(a[a.index("--preview") + 1]) if "--preview" in a else None
    snaps = [] if "--snaps" in a else None
    build(a[0], mode, prev, snaps)
