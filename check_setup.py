"""Quick test of every connection. Run from GitHub: Actions -> '0 - Check setup' -> Run workflow."""
import os
from jms import telegram, ai, news, photos

ok = []
for name in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
    ok.append(f"{name}: {'present' if os.environ.get(name) else 'MISSING'}")
try:
    r = ai._call("Reply with JSON {\"ok\": true}")
    ok.append(f"Gemini: working ({ai.LAST_MODEL}) -> {r}")
except Exception as ex:
    ok.append(f"Gemini: FAILED {str(ex)[:300]}")
try:
    n = len(news.collect(hours=30, max_items=200)); ok.append(f"News feeds: {n} items in last 30 h")
except Exception as ex:
    ok.append(f"News: FAILED {ex}")
try:
    ok.append(f"Wikimedia photos: {len(photos.search('LNG carrier'))} results for 'LNG carrier'")
except Exception as ex:
    ok.append(f"Wikimedia: FAILED {ex}")
if os.environ.get("IG_ACCESS_TOKEN"):
    try:
        from jms import instagram
        ok.append(f"Instagram: connected as @{instagram.whoami().get('username')}")
    except Exception as ex:
        ok.append(f"Instagram: FAILED {str(ex)[:300]}")
else:
    ok.append("Instagram: not connected yet (Step 4)")
report = "🔧 Jai Marine Shorts setup check\n\n" + "\n".join(ok)
print(report)
try:
    telegram.send_text(report); print("Telegram: message sent")
except Exception as ex:
    print("Telegram: FAILED", ex)
