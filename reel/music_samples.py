"""Download licence-free tense instrumentals (CC BY 4.0), keep them in reel/music/, send 45-s previews to Telegram."""
import json, subprocess, sys, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jms import telegram
D = Path(__file__).resolve().parent / "music"
cat = json.loads((D / "catalog.json").read_text())
telegram.send_text("🎵 Background music options for the case-file Reels (all free, CC BY licence, credited in the caption). "
                   "Listen and tell Claude the number you like.")
for i, m in enumerate(cat, 1):
    f = D / f"{m['key']}.mp3"
    try:
        if not f.exists():
            r = requests.get(m["url"], timeout=60, headers={"User-Agent": "Mozilla/5.0"}); r.raise_for_status()
            if len(r.content) < 100000: raise RuntimeError("too small")
            f.write_bytes(r.content)
        prev = f"/tmp/prev_{m['key']}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "8", "-t", "45", "-i", str(f), "-af", "afade=t=in:d=1,afade=t=out:st=43:d=2,loudnorm=I=-16",
                        "-b:a", "128k", prev], check=True)
        with open(prev, "rb") as fh:
            requests.post(f"{telegram.BASE}/sendAudio", data={"chat_id": telegram.CHAT, "caption": f"Option {i}: {m['title']} — {m['artist']}",
                          "title": f"Option {i}: {m['title']}"}, files={"audio": (f"option{i}.mp3", fh)}, timeout=120).raise_for_status()
        print("sent", m["key"])
    except Exception as e:
        print("skip", m["key"], e); f.unlink(missing_ok=True)
