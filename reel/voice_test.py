"""Send the Chief short voice samples (same thriller lines) so he can pick the narrator."""
import os, sys, subprocess, tempfile, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, render
from jms import telegram

LINE = ("Imagine you're on the bridge of this empty tanker. It's ten at night. The river is racing behind you... "
        "and she will not turn in time. Twenty-two thirteen. Impact.")
STYLES = {
 "A": ("Charon", "Narrate like a gripping true-crime documentary trailer, Indian English male voice. Fast and urgent, "
               "drop your voice low and slow on 'and she will not turn in time', pause before 'Impact', then hit it hard:\n\n"),
 "B": ("Fenrir", "Excited, intense movie-trailer narrator with an Indian English accent. Energetic pace, strong rises and falls, "
               "dramatic pause before the last word:\n\n"),
 "C": ("Algenib", "Deep, gravelly, suspenseful Indian English narrator, like a thriller audiobook. Whisper-tense in the middle, "
                "punchy at the end:\n\n"),
}
GEMINI_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]


def gemini(voice, style):
    from google import genai
    from google.genai import types
    c = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    listed = [m.name.split("/")[-1] for m in c.models.list() if "tts" in m.name.lower()]
    print("listed tts models:", listed)
    for model in listed + GEMINI_MODELS:
        try:
            r = c.models.generate_content(model=model, contents=style + LINE, config=types.GenerateContentConfig(
                response_modalities=["AUDIO"], speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
            d = r.candidates[0].content.parts[0].inline_data.data
            print("ok", model, voice); return np.frombuffer(d, dtype=np.int16).astype(np.float32) / 32768, model
        except Exception as e:
            print("fail", model, str(e)[:200])
    return None, None


def send(x, title):
    wav = tempfile.mktemp(suffix=".wav"); mp3 = wav.replace(".wav", ".mp3")
    render.write_wav(wav, x)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-af", "loudnorm=I=-14", "-b:a", "128k", mp3], check=True)
    with open(mp3, "rb") as fh:
        requests.post(f"{telegram.BASE}/sendAudio", data={"chat_id": telegram.CHAT, "title": title, "caption": title},
                      files={"audio": (title + ".mp3", fh)}, timeout=120).raise_for_status()


telegram.send_text("🎙 Voice samples for the case-file Reels — same lines, different narrators. Reply here or tell Claude which one you like.")
for k, (v, st) in STYLES.items():
    x, model = gemini(v, st)
    if x is not None:
        send(x, f"Voice {k} — {v} (Google)")
for k, (rate, pitch) in {"D": ("+12%", "-6Hz"), "E": ("+20%", "+0Hz")}.items():
    os.environ["EDGE_RATE"] = rate
    import asyncio, edge_tts
    tmp = tempfile.mktemp(suffix=".mp3")
    asyncio.run(edge_tts.Communicate(LINE, "en-IN-PrabhatNeural", rate=rate, pitch=pitch).save(tmp))
    with open(tmp, "rb") as fh:
        requests.post(f"{telegram.BASE}/sendAudio", data={"chat_id": telegram.CHAT, "caption": f"Voice {k} — Prabhat (Microsoft) {rate}"},
                      files={"audio": (f"voice-{k}.mp3", fh)}, timeout=120).raise_for_status()
