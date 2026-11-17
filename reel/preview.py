"""Render an episode and send it to Telegram for the Chief to check."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import render
from jms import telegram

ep_path = Path(sys.argv[1])
_ep = json.loads(ep_path.read_text())
if _ep.get("voice") == "human" and os.environ.get("TTS_MODE") != "human":
    if not _ep.get("script_sent_unix"):
        import voice_inbox
        if voice_inbox.waiting():             # one script at a time, so recordings can't get mixed up
            _ep["script_pending"] = True; ep_path.write_text(json.dumps(_ep, indent=1, ensure_ascii=False))
            print("another episode is waiting for a recording; script queued")
        else:
            voice_inbox.send_script(ep_path)
            print("script sent; waiting for the Chief's recording")
    sys.exit(0)
final = render.build(ep_path, os.environ.get("TTS_MODE", "auto"))
ep = json.loads(ep_path.read_text())
size = final.stat().st_size / 1e6
print(f"video {size:.1f} MB")
slot = None
if ep.get("queue"):
    import reel_queue as rq
    slot = rq.add(ep["id"])
if os.environ.get("TELEGRAM_BOT_TOKEN"):
    telegram.send_video(final, f"🎬 Jai Marine Shorts — Reel preview: {ep['id']} ({size:.0f} MB)")
    telegram.send_text("REEL CAPTION:\n\n" + ep.get("caption", ""))
    if slot:
        telegram.send_text(f"This Reel will post automatically on {slot['date']} at 7:30 AM IST. Tap Reject to stop it.",
                           buttons=[{"text": "❌ Reject", "callback_data": f"reject:{ep['id']}"}])
