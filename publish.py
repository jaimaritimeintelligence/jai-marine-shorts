"""Daily step 2 (7:30 PM IST, retried until 9 PM): post the approved carousel to Instagram."""
import os, json, sys
from datetime import datetime, timedelta, timezone
from jms import telegram

IST = timezone(timedelta(hours=5, minutes=30))
DAY = os.environ.get("RUN_DAY") or datetime.now(IST).strftime("%Y-%m-%d")
OUT = os.path.join("out", DAY)
META = os.path.join(OUT, "meta.json")
AUTO_POST = os.environ.get("AUTO_POST", "false").lower() == "true"
FINAL_TRY = os.environ.get("FINAL_TRY", "false").lower() == "true"
REPO = os.environ.get("GITHUB_REPOSITORY", "jaimaritimeintelligence/jai-marine-shorts")


def main():
    if not os.path.exists(META):
        print("No carousel prepared for", DAY); return
    meta = json.load(open(META))
    if meta.get("posted") or meta.get("rejected"):
        print("Already handled:", meta.get("posted") or "rejected"); return

    decision = "approve" if AUTO_POST else telegram.read_decision(DAY, meta.get("preview_unix", 0))
    print("Decision:", decision)
    if decision == "reject":
        meta["rejected"] = True
        telegram.send_text(f"❌ OK — {DAY} carousel will NOT be posted.")
    elif decision != "approve":
        if FINAL_TRY:
            telegram.send_text(f"⏰ No approval received for {DAY} — not posted today.")
        return
    else:
        if not os.environ.get("IG_ACCESS_TOKEN"):
            telegram.send_text(f"✅ Approved {DAY}, but Instagram is not connected yet (Step 4). Nothing was posted.")
            meta["rejected"] = True
        else:
            from jms import instagram
            files = sorted(f for f in os.listdir(OUT) if f.endswith(".jpg"))
            urls = [f"https://raw.githubusercontent.com/{REPO}/main/out/{DAY}/{f}" for f in files]
            pid, link, user = instagram.publish_carousel(urls, meta["caption"])
            meta["posted"] = link or pid
            msg = f"🚢 Posted to Instagram @{user}: {link}"
            if meta.get("song"):
                msg += ("\n\n" + telegram.song_text(meta["song"]) +
                        "\n\nAdd it (20 sec, Instagram app): open the post → ⋯ (top right) → Edit → Replace audio "
                        "→ search the song → pick the 60-second part above → Done.")
            telegram.send_text(msg)
    json.dump(meta, open(META, "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        if telegram.TOKEN:
            telegram.send_text(f"⚠️ Instagram posting failed for {DAY}:\n{str(ex)[:600]}")
        raise
