"""Speak the script in the Chief's cloned voice (Chatterbox, MIT licence, Resemble AI).

Reference: a clean 10-20 s slice of one of his own recordings, kept only in the Actions cache (never in the public repo)."""
import os, re, json
from pathlib import Path
import numpy as np

REF = Path(os.environ.get("VOICE_REF_DIR", str(Path.home() / "voice_ref"))) / "ref.wav"
_model = None


def build_reference(rec_path, scenes):
    """Pick the scene from his recording whose clean speech is closest to 15 s and save it as the reference."""
    import human_voice as hv, render
    heard = hv.transcribe(rec_path); audio = hv.load_audio(rec_path)
    per = hv.align(scenes, heard)
    best = None
    for w in per:
        a, _ = hv.cut_scene(audio, w, max_gap=0.4)
        if a is None: continue
        d = len(a) / hv.SR
        if 8 <= d <= 25 and (best is None or abs(d - 15) < abs(len(best) / hv.SR - 15)):
            best = a
    if best is None:
        raise SystemExit("no clean 8-25 s stretch found in the recording")
    REF.parent.mkdir(parents=True, exist_ok=True)
    render.write_wav(REF, best)
    print(f"reference voice saved: {len(best)/hv.SR:.1f}s", flush=True)


def _load():
    global _model
    if _model is None:
        import torch
        from chatterbox.tts import ChatterboxTTS
        torch.set_num_threads(os.cpu_count() or 4)
        _model = ChatterboxTTS.from_pretrained(device="cpu")
    return _model


def speak(text):
    """Returns float32 mono at the model rate (24 kHz)."""
    m = _load()
    ex = float(os.environ.get("CLONE_EXAGGERATION", "0.65")); cfg = float(os.environ.get("CLONE_CFG", "0.4"))
    # chatterbox reads best sentence by sentence
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    out = []
    for p in parts:
        wav = m.generate(p, audio_prompt_path=str(REF), exaggeration=ex, cfg_weight=cfg)
        x = wav.squeeze().cpu().numpy().astype(np.float32)
        if m.sr != 24000:
            import subprocess
            raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(m.sr), "-ac", "1", "-i", "-", "-f", "f32le", "-ar", "24000", "-"],
                                 input=x.tobytes(), capture_output=True, check=True).stdout
            x = np.frombuffer(raw, dtype=np.float32)
        out += [x, np.zeros(int(0.28 * 24000), dtype=np.float32)]
    return np.concatenate(out)
