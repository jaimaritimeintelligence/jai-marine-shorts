"""Narration (Microsoft neural voice via edge-tts) with word timings -> plan.json + voice.wav"""
import asyncio, json, math, subprocess, sys, io
import numpy as np
import edge_tts

SR = 24000; FPS = 24; PAD = 0.55; LEAD = 0.4
ep = json.load(open(sys.argv[1])); out = sys.argv[2]


async def _say(text, boundary):
    kw = dict(rate=ep.get("rate", "+0%"))
    c = edge_tts.Communicate(text, ep["voice"], boundary=boundary, **kw) if boundary else edge_tts.Communicate(text, ep["voice"], **kw)
    audio = bytearray(); words = []
    async for ch in c.stream():
        if ch["type"] == "audio": audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            words.append({"w": ch["text"], "s": ch["offset"] / 1e7, "e": (ch["offset"] + ch["duration"]) / 1e7})
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", "-", "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         input=bytes(audio), capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768, words


async def say(text):
    import time
    last = None
    for attempt in range(6):
        for b in ("WordBoundary", None):
            try:
                return await _say(text, b)
            except Exception as e:
                last = e; print("tts retry", attempt, b, str(e)[:120], flush=True)
        time.sleep(5 + attempt * 5)
    raise last

track = []; plan = []; t = 0.0; allw = []
for i, sc in enumerate(ep["scenes"]):
    a, words = asyncio.run(say(sc["narration"]))
    lead = LEAD if i == 0 else 0.15
    dur = lead + len(a) / SR + PAD
    frames = math.ceil(dur * FPS); dur = frames / FPS
    track.append((t + lead, a))
    # map boundary words to script words (keeps punctuation for captions)
    script = sc["narration"].split()
    if not words:     # no boundaries: spread words over the audio
        tot = sum(len(x) + 2 for x in script); acc = 0.0; d = len(a) / SR
        for x in script:
            words.append({"w": x, "s": acc / tot * d, "e": (acc + len(x) + 1) / tot * d}); acc += len(x) + 2
    if len(words) == len(script):
        ws = [{"w": s, "s": t + lead + w["s"], "e": t + lead + w["e"]} for s, w in zip(script, words)]
    else:
        ws = [{"w": w["w"], "s": t + lead + w["s"], "e": t + lead + w["e"]} for w in words]
    allw += ws
    plan.append({"shot": sc["shot"], "start": round(t, 3), "dur": round(dur, 3), "frames": frames, "labels": sc.get("labels", [])})
    t += dur
n = int((t + 1) * SR); v = np.zeros(n, np.float32)
for st, a in track:
    j = int(st * SR); v[j:j + len(a)] += a
import wave
with wave.open(f"{out}/voice.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(v, -1, 1) * 32767).astype(np.int16).tobytes())
json.dump({"total": t, "fps": FPS, "shots": plan, "words": allw}, open(f"{out}/plan.json", "w"), indent=1)
print("total", round(t, 1), "s;", [p["frames"] for p in plan])
