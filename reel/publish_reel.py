"""7:30 AM IST: post today's queued Reel unless the Chief tapped Reject."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).resolve().parent))
import reel_queue as rq
from jms import telegram

REPO = os.environ.get("GITHUB_REPOSITORY", "jaimaritimeintelligence/jai-marine-shorts")


def main():
    q = rq.load(); due = rq.due_today()
    if not due:
        print("No Reel due today"); return
    e = next(x for x in q if x["id"] == due[0]["id"])
    if telegram.read_decision(e["id"]) == "reject":
        e["rejected"] = True; rq.save(q)
        telegram.send_text(f"❌ OK — Reel {e['id']} will NOT be posted."); return
    import json
    ep = json.loads((Path(__file__).parent / "episodes" / e["id"] / "episode.json").read_text())
    if ep.get("voice") == "human" and not ep.get("voice_done"):
        telegram.send_text(f"⏸ Reel {e['id']} not posted today — still waiting for your new recording. It will take the next free morning.")
        e["date"] = "9999-12-31"; rq.save(q); return
    url = f"https://raw.githubusercontent.com/{REPO}/main/reel/episodes/{e['id']}/{e['id']}.mp4"
    from jms import instagram
    cover = f"https://raw.githubusercontent.com/{REPO}/main/reel/episodes/{e['id']}/cover.jpg"
    has_cover = (Path(__file__).parent / "episodes" / e["id"] / "cover.jpg").exists()
    cap = ep.get("caption", "")
    if ep.get("music"):
        cat = {m["key"]: m for m in json.loads((Path(__file__).parent / "music" / "catalog.json").read_text())}
        cr = cat[ep["music"]]["credit"]
        if cr not in cap:
            cap = cap.replace("\n\n#", f"\n{cr}\n\n#", 1) if "\n\n#" in cap else cap + "\n" + cr
    pid, link, user = instagram.publish_reel(url, cap, cover_url=cover if has_cover else None)
    e["posted"] = link or pid; rq.save(q)
    telegram.send_text(f"🎬 Reel posted to @{user}: {link}")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        if telegram.TOKEN:
            telegram.send_text(f"⚠️ Reel posting failed:\n{str(ex)[:600]}")
        raise
