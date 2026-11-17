"""Use the Chief's own recording as the narration.

He records the whole script in one go (pauses between parts, retakes allowed).
Whisper gives word timestamps; we match them to the script, keep only the matched words
(so false starts and long pauses fall away) and cut the audio per scene.
"""
import re, subprocess, difflib
import numpy as np

SR = 24000


def norm(w):
    w = w.lower().replace("’", "'")
    return re.sub(r"[^a-z0-9']", "", w)


def load_audio(path):
    """Decode any format, clean it: rumble cut, noise reduction, de-click, level."""
    af = "highpass=f=75,lowpass=f=12000,afftdn=nr=14:nf=-42:tn=1,adeclick,dynaudnorm=f=250:g=9:p=0.9"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-af", af, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def transcribe(path):
    from faster_whisper import WhisperModel
    m = WhisperModel("small.en", device="cpu", compute_type="int8")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    pcm = np.frombuffer(raw, dtype=np.float32)          # decode ourselves (avoids PyAV version issues)
    segs, _ = m.transcribe(pcm, word_timestamps=True, vad_filter=False, beam_size=5,
                           initial_prompt="Marine accident case file. Nordbay, NTSB, Algiers Point, allision, rpm.")
    out = []
    for s in segs:
        for w in s.words:
            if norm(w.word):
                out.append({"w": norm(w.word), "s": w.start, "e": w.end})
    return out


def numbers_to_words_hint(tokens):
    return tokens


def align(scenes, heard):
    """Per scene: kept heard spans + caption words with times.
    equal/replace -> keep (replace covers numbers like '817' vs 'eight hundred and seventeen');
    insert (extra heard words, e.g. a false start before a retake) -> dropped."""
    script = []
    for si, sc in enumerate(scenes):
        for w in sc["narration"].split():
            if norm(w):
                script.append((si, w, norm(w)))
    A = [x[2] for x in script]; B = [h["w"] for h in heard]
    sm = difflib.SequenceMatcher(a=A, b=B, autojunk=False)
    per = [[] for _ in scenes]          # list of (caption_word, start, end)
    matched = [0] * len(scenes); total = [0] * len(scenes)
    for x in script: total[x[0]] += 1
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                si, w, _ = script[a0 + k]; h = heard[b0 + k]
                per[si].append((w, h["s"], h["e"])); matched[si] += 1
        elif tag == "replace" and (b1 - b0) <= 3 * (a1 - a0) + 2:
            s0, e0 = heard[b0]["s"], heard[b1 - 1]["e"]
            n = a1 - a0
            for k in range(n):          # spread script words over the heard span
                si, w, _ = script[a0 + k]
                per[si].append((w, s0 + (e0 - s0) * k / n, s0 + (e0 - s0) * (k + 1) / n))
            si0 = script[a0][0]; matched[si0] += 0.5 * n
    for si, sc in enumerate(scenes):
        per[si].sort(key=lambda x: x[1])
        sc["_coverage"] = matched[si] / max(1, total[si])
    return per


def cut_scene(audio, words, max_gap=0.45, pad=0.08):
    """Concatenate spans of matched words; long silences (and retake junk between words) shrink to max_gap."""
    if not words:
        return None, []
    pieces, times, t = [], [], 0.0
    spans = []
    for w, s, e in words:
        if spans and s - spans[-1][1] <= max_gap:
            spans[-1][1] = e; spans[-1][2].append((w, s, e))
        else:
            spans.append([s, e, [(w, s, e)]])
    for k, (s, e, ws) in enumerate(spans):
        a = max(0, int((s - pad) * SR)); b = min(len(audio), int((e + pad) * SR))
        seg = audio[a:b].copy()
        f = min(len(seg) // 4, int(0.015 * SR))
        if f > 0:
            seg[:f] *= np.linspace(0, 1, f); seg[-f:] *= np.linspace(1, 0, f)
        base = t - (s - pad)
        for w, ws_, we in ws:
            times.append({"w": w, "s": round(ws_ + base, 3), "e": round(we + base, 3)})
        pieces.append(seg); t += len(seg) / SR
        if k < len(spans) - 1:
            gap = min(max_gap, spans[k + 1][0] - e)
            pieces.append(np.zeros(int(max(0.12, gap) * SR), dtype=np.float32)); t += max(0.12, gap)
    return np.concatenate(pieces), times


def speaking_rate(per):
    """Words per second over the spoken spans."""
    n = sum(len(w) for w in per); dur = sum((w[-1][2] - w[0][1]) for w in per if w)
    return n / dur if dur else 0


def stretch(x, factor):
    """Speed up speech without changing pitch (rubberband if available, else atempo)."""
    if abs(factor - 1) < 0.01 or x is None:
        return x
    raw = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
    for flt in (f"rubberband=tempo={factor:.3f}:pitchq=quality", f"atempo={factor:.3f}"):
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-", "-af", flt,
                            "-f", "s16le", "-ar", str(SR), "-ac", "1", "-"], input=raw, capture_output=True)
        if r.returncode == 0 and r.stdout:
            return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768
    return x
