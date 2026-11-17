"""Send the Chief the script to record, and pick up his recording from Telegram."""
import json, os, sys, time, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jms import telegram

EPS = Path(__file__).resolve().parent / "episodes"


def send_script(ep_path):
    ep = json.loads(Path(ep_path).read_text())
    lines = [f"🎙 RECORD THIS — {ep['id']}",
             "Read it all in ONE recording (Telegram voice message is fine). Cabin, door closed, phone 15 cm away.",
             "Pause 2 seconds between parts. Made a mistake? Pause, then say the whole sentence again — I keep the last good take.",
             "Speak like you're telling a gripping story: slower and lower on the dramatic lines, faster when the tension builds.", ""]
    for i, sc in enumerate(ep["scenes"], 1):
        lines.append(f"{i}. {sc['narration']}")
    telegram.send_text("\n".join(lines))
    telegram.send_text(f"When done, send the recording here as a reply. (Episode: {ep['id']})")
    ep["script_sent_unix"] = int(time.time()); ep["awaiting_voice"] = True
    Path(ep_path).write_text(json.dumps(ep, indent=1, ensure_ascii=False))


def waiting():
    out = []
    for f in sorted(EPS.glob("*/episode.json")):
        ep = json.loads(f.read_text())
        if ep.get("awaiting_voice"):
            out.append((ep.get("script_sent_unix", 0), f))
    return [f for _, f in sorted(out)]


def fetch_recording(after_unix, dest):
    """Newest voice/audio message from the Chief sent after the script. Bot downloads are limited to 20 MB."""
    r = requests.get(f"{telegram.BASE}/getUpdates", params={"timeout": 0}, timeout=30); r.raise_for_status()
    best = None
    for u in r.json().get("result", []):
        m = u.get("message") or {}
        if str((m.get("chat") or {}).get("id")) != telegram.CHAT or m.get("date", 0) < after_unix:
            continue
        f = m.get("voice") or m.get("audio") or (m.get("document") if (m.get("document") or {}).get("mime_type", "").startswith(("audio", "video")) else None) or m.get("video")
        if f and (best is None or m["date"] > best[0]):
            best = (m["date"], f)
    if not best:
        return None
    info = requests.get(f"{telegram.BASE}/getFile", params={"file_id": best[1]["file_id"]}, timeout=30).json()
    if not info.get("ok"):
        telegram.send_text("⚠️ I couldn't download that recording (Telegram bots can only fetch files under 20 MB). "
                           "Please send it as a voice message, or as a shorter/compressed audio file.")
        return None
    url = f"https://api.telegram.org/file/bot{telegram.TOKEN}/{info['result']['file_path']}"
    Path(dest).write_bytes(requests.get(url, timeout=120).content)
    return dest
