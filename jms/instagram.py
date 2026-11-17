"""Publish a carousel with the Instagram API with Instagram Login (no Facebook Page needed)."""
import os, time, requests

VER = os.environ.get("IG_API_VERSION", "v23.0")
IG_USER_ID = os.environ.get("IG_USER_ID", "17841414943506881").strip()   # @jaimarineshorts


def _token():
    return os.environ["IG_ACCESS_TOKEN"].strip()


def _fb_token():
    """Unified login / system-user tokens start with EAA and use the Facebook Graph host."""
    return _token().startswith("EAA")


BASE = f"https://graph.facebook.com/{VER}" if os.environ.get("IG_ACCESS_TOKEN", "").strip().startswith("EAA") else f"https://graph.instagram.com/{VER}"


def _post(path, **params):
    params["access_token"] = _token()
    r = requests.post(f"{BASE}/{path}", data=params, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Instagram {path}: {r.status_code} {r.text[:400]}")
    return r.json()


def _get(path, **params):
    params["access_token"] = _token()
    r = requests.get(f"{BASE}/{path}", params=params, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Instagram GET {path}: {r.status_code} {r.text[:400]}")
    return r.json()


def whoami():
    if _fb_token():
        me = _get(IG_USER_ID, fields="id,username")
        return {"user_id": me["id"], "username": me.get("username")}
    return _get("me", fields="user_id,username")


def _wait(container_id, tries=30):
    for _ in range(tries):
        st = _get(container_id, fields="status_code").get("status_code")
        if st == "FINISHED": return
        if st in ("ERROR", "EXPIRED"): raise RuntimeError(f"container {container_id} status {st}")
        time.sleep(5)
    raise RuntimeError(f"container {container_id} not ready")


def publish_carousel(image_urls, caption):
    me = whoami()
    uid = me["user_id"]
    children = []
    for u in image_urls[:10]:
        c = _post(f"{uid}/media", image_url=u, is_carousel_item="true")
        children.append(c["id"])
        time.sleep(2)
    for c in children:
        _wait(c)
    parent = _post(f"{uid}/media", media_type="CAROUSEL", children=",".join(children), caption=caption[:2200])
    _wait(parent["id"])
    pub = _post(f"{uid}/media_publish", creation_id=parent["id"])
    link = _get(pub["id"], fields="permalink").get("permalink", "")
    return pub["id"], link, me.get("username")


def refresh_token():
    """Long-lived tokens last 60 days; refreshing returns a token valid for another 60 days."""
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": _token()}, timeout=30)
    r.raise_for_status()
    return r.json()


def publish_reel(video_url, caption, cover_url=None, share_to_feed=True):
    """Reel from a public video URL. Instagram fetches and transcodes it; this can take a few minutes."""
    me = whoami()
    uid = me["user_id"]
    params = dict(media_type="REELS", video_url=video_url, caption=caption[:2200], share_to_feed=str(share_to_feed).lower())
    if cover_url:
        params["cover_url"] = cover_url
    c = _post(f"{uid}/media", **params)
    _wait(c["id"], tries=90)          # up to ~7.5 minutes
    pub = _post(f"{uid}/media_publish", creation_id=c["id"])
    link = _get(pub["id"], fields="permalink").get("permalink", "")
    return pub["id"], link, me.get("username")
