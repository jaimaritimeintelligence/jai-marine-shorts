"""Render an episode and send it to Telegram for the Chief to check."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import render
from jms import telegram

ep_path = Path(sys.argv[1])
final = render.build(ep_path, os.environ.get("TTS_MODE", "auto"))
ep = json.loads(ep_path.read_text())
size = final.stat().st_size / 1e6
print(f"video {size:.1f} MB")
if os.environ.get("TELEGRAM_BOT_TOKEN"):
    telegram.send_video(final, f"🎬 Jai Marine Shorts — Reel preview: {ep['id']} ({size:.0f} MB)")
    telegram.send_text("REEL CAPTION:\n\n" + ep.get("caption", ""))
