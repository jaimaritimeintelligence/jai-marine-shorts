"""Hourly: if the Chief has sent his recording for a waiting episode, render it with his voice and queue it."""
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).resolve().parent))
import voice_inbox
from jms import telegram

for f in voice_inbox.waiting():
    ep = json.loads(f.read_text())
    rec = voice_inbox.fetch_recording(ep.get("script_sent_unix", 0), f"/tmp/{ep['id']}.rec")
    if not rec:
        print("no recording yet for", ep["id"]); continue
    telegram.send_text(f"🎙 Got your recording for {ep['id']} — cleaning it up and editing the Reel now (about 5 minutes).")
    env = dict(os.environ, TTS_MODE="human", VOICE_FILE=rec)
    r = subprocess.run([sys.executable, "-u", str(Path(__file__).parent / "preview.py"), str(f)], env=env, capture_output=True, text=True)
    print(r.stdout[-3000:], r.stderr[-3000:])
    if "VOICE_MISSING" in (r.stdout + r.stderr):
        parts = (r.stdout + r.stderr).split("VOICE_MISSING:")[1].split("\n")[0]
        telegram.send_text(f"⚠️ I couldn't clearly hear part(s) {parts} of the script in that recording. "
                           "Please record the full script again (or just those parts, in one message).")
        continue
    if r.returncode != 0:
        telegram.send_text(f"⚠️ Editing {ep['id']} failed — Claude will check it."); continue
    ep = json.loads(f.read_text()); ep["awaiting_voice"] = False; ep["voice_done"] = True
    f.write_text(json.dumps(ep, indent=1, ensure_ascii=False))
    nxt = sorted(Path(voice_inbox.EPS).glob("*/episode.json"))
    for g in nxt:
        e2 = json.loads(g.read_text())
        if e2.get("script_pending"):
            e2.pop("script_pending"); g.write_text(json.dumps(e2, indent=1, ensure_ascii=False))
            voice_inbox.send_script(g); break
    break        # one per run
