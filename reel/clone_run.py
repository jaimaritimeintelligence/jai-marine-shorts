"""Render an episode in the Chief's cloned voice, check it, send preview, and (optionally) post it now."""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).resolve().parent))
import clone_voice, render, voice_inbox
from jms import telegram

ep_path = Path(sys.argv[1]); ep = json.loads(ep_path.read_text())
if not clone_voice.REF.exists():
    src = voice_inbox.EPS / os.environ.get("REF_EPISODE", "nordbay-p1") / "episode.json"
    e1 = json.loads(src.read_text())
    later = [json.loads(g.read_text()).get("script_sent_unix") or 0 for g in voice_inbox.EPS.glob("*/episode.json")]
    later = [x for x in later if x > e1.get("script_sent_unix", 0)]
    rec = voice_inbox.fetch_recording(e1["script_sent_unix"], "/tmp/ref.rec", min(later) if later else None)
    if not rec:
        raise SystemExit("Could not find the Chief's recording on Telegram to copy the voice from")
    clone_voice.build_reference(rec, e1["scenes"])

final = render.build(ep_path, "clone")

# quality gate: Whisper must hear the script
import human_voice as hv
heard = hv.transcribe(final)
cov = hv.align(json.loads(ep_path.read_text())["scenes"], heard)
script_words = sum(len(s["narration"].split()) for s in ep["scenes"]); got = sum(len(w) for w in cov)
score = got / max(1, script_words)
print(f"intelligibility: {score:.0%} of script words heard back", flush=True)
size = final.stat().st_size / 1e6
telegram.send_video(final, f"🎬 {ep['id']} — narrated in your AI-cloned voice ({size:.0f} MB, {score:.0%} of words clear)")
cov_img = final.parent / "cover.jpg"
if cov_img.exists():
    telegram.send_album([str(cov_img)], "🖼 Thumbnail / cover")
if score < 0.85:
    telegram.send_text(f"⚠️ Not posting {ep['id']}: the cloned voice was unclear ({score:.0%}). Claude will check.")
    sys.exit(1)

if os.environ.get("POST_NOW") == "true":
    import reel_queue as rq
    q = rq.load(); q = [e for e in q if e["id"] != ep["id"]]
    q.append({"id": ep["id"], "date": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 19800)), "posted": None, "rejected": False}); rq.save(q)
    ep = json.loads(ep_path.read_text()); ep["voice_done"] = True; ep_path.write_text(json.dumps(ep, indent=1, ensure_ascii=False))
    import publish_reel
    publish_reel.main()
