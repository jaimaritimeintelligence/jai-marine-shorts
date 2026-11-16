"""Telegram: send the daily preview and read the Chief's Approve / Reject answer."""
import os, json, requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
BASE = f"https://api.telegram.org/bot{TOKEN}"


def send_text(text, buttons=None):
    data = {"chat_id": CHAT, "text": text[:4000], "disable_web_page_preview": True}
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": [buttons]})
    r = requests.post(f"{BASE}/sendMessage", data=data, timeout=30)
    r.raise_for_status()
    return r.json()["result"]["message_id"]


def send_album(paths, first_caption=""):
    """Telegram allows 10 photos per album."""
    files, media = {}, []
    for i, p in enumerate(paths[:10]):
        key = f"p{i}"
        files[key] = open(p, "rb")
        m = {"type": "photo", "media": f"attach://{key}"}
        if i == 0 and first_caption:
            m["caption"] = first_caption[:1000]
        media.append(m)
    r = requests.post(f"{BASE}/sendMediaGroup", data={"chat_id": CHAT, "media": json.dumps(media)}, files=files, timeout=120)
    for fh in files.values(): fh.close()
    r.raise_for_status()


def song_text(song):
    if not song: return ""
    out = f"🎵 Today's song: {song.get('title','')} — {song.get('artist','')} ({song.get('language','')})"
    if song.get("start"): out += f"\nUse the 60-second part starting at {song['start']}"
    if song.get("why"): out += f"\nWhy: {song['why']}"
    return out


def send_preview(day, paths, caption, song=None):
    send_album(paths, f"📰 Jai Marine Shorts — preview for {day}")
    send_text("CAPTION:\n\n" + caption + ("\n\n" + song_text(song) if song else ""))
    return send_text(f"Post today's carousel ({day}) to Instagram at 7:30 PM IST?",
                     buttons=[{"text": "✅ Approve", "callback_data": f"approve:{day}"},
                              {"text": "❌ Reject", "callback_data": f"reject:{day}"}])


def read_decision(day, after_unix=0):
    """Look through recent bot updates for the answer to today's preview.
    Accepts the buttons or a typed reply: 'approve'/'yes'/'ok' or 'reject'/'no'."""
    r = requests.get(f"{BASE}/getUpdates", params={"timeout": 0, "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=30)
    r.raise_for_status()
    decision = None
    for u in r.json().get("result", []):
        cq = u.get("callback_query")
        if cq and str(cq["message"]["chat"]["id"]) == CHAT and cq.get("data", "").endswith(day):
            decision = cq["data"].split(":")[0]
            try:
                requests.post(f"{BASE}/answerCallbackQuery", data={"callback_query_id": cq["id"], "text": "Noted ✔"}, timeout=10)
            except Exception:
                pass
        msg = u.get("message")
        if msg and str(msg["chat"]["id"]) == CHAT and msg.get("date", 0) >= after_unix:
            t = (msg.get("text") or "").strip().lower()
            if t in ("approve", "approved", "yes", "ok", "post", "✅"):
                decision = "approve"
            elif t in ("reject", "no", "skip", "❌"):
                decision = "reject"
    return decision
