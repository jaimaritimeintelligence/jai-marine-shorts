"""Reel queue: rendered episodes waiting for their 7:30 AM IST slot."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
Q = Path(__file__).resolve().parent / "queue.json"


def load():
    return json.loads(Q.read_text()) if Q.exists() else []


def save(q):
    Q.write_text(json.dumps(q, indent=1, ensure_ascii=False))


def add(ep_id):
    """Give the episode the next free morning slot (today if before 05:00 IST, else tomorrow onward)."""
    q = load()
    old = next((e for e in q if e["id"] == ep_id), None)
    if old and not old.get("posted") and old["date"] != "9999-12-31":
        return old
    if old:
        q.remove(old)
    now = datetime.now(IST)
    day = now.date() if now.hour < 5 else now.date() + timedelta(days=1)
    taken = {e["date"] for e in q if not e.get("rejected")}
    while day.isoformat() in taken:
        day += timedelta(days=1)
    e = {"id": ep_id, "date": day.isoformat(), "posted": None, "rejected": False}
    q.append(e); save(q)
    return e


def due_today():
    today = datetime.now(IST).date().isoformat()
    return [e for e in load() if e["date"] == today and not e.get("posted") and not e.get("rejected")]
