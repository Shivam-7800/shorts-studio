"""
Publish a local video as an Instagram Reel using Meta's official Graph API
(resumable upload, so the video doesn't need to be hosted anywhere public).

Needs an Instagram Business or Creator account and, in your .env:
    IG_USER_ID=...          your Instagram professional account ID
    IG_ACCESS_TOKEN=...     long-lived token with instagram_content_publish
Optional:
    IG_GRAPH_HOST=graph.facebook.com   (use graph.instagram.com for "Instagram Login" tokens)
    IG_GRAPH_VERSION=v23.0
"""

import os
import time

import requests


def is_configured():
    return bool(os.environ.get("IG_USER_ID") and os.environ.get("IG_ACCESS_TOKEN"))


def _cfg():
    if not is_configured():
        raise RuntimeError("Instagram isn't set up. Add IG_USER_ID and IG_ACCESS_TOKEN to your .env file and restart.")
    host = os.environ.get("IG_GRAPH_HOST", "graph.facebook.com")
    version = os.environ.get("IG_GRAPH_VERSION", "v23.0")
    return os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"], f"https://{host}/{version}", version


def _check(resp, what):
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or "error" in data:
        message = data.get("error", {}).get("message") or resp.text[:300]
        raise RuntimeError(f"Instagram {what} failed: {message}")
    return data


def publish_reel(video_path, caption, share_to_feed=True, log=print, on_progress=None):
    user_id, token, base, version = _cfg()

    log("Creating the Instagram Reel")
    data = _check(requests.post(f"{base}/{user_id}/media", data={
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption[:2200],
        "share_to_feed": "true" if share_to_feed else "false",
        "access_token": token,
    }, timeout=60), "container creation")
    container_id = data["id"]
    upload_uri = data.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{version}/{container_id}"

    log("Sending the video file to Instagram")
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        _check(requests.post(upload_uri, headers={
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(size),
        }, data=f, timeout=900), "video upload")
    if on_progress:
        on_progress(0.5)

    log("Waiting for Instagram to process the video")
    for i in range(60):  # up to ~10 minutes
        status = _check(requests.get(f"{base}/{container_id}", params={
            "fields": "status_code,status", "access_token": token}, timeout=30), "status check")
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram couldn't process the video: {status.get('status', code)}")
        if on_progress:
            on_progress(0.5 + 0.45 * (i + 1) / 60)
        time.sleep(10)
    else:
        raise RuntimeError("Instagram is still processing after 10 minutes. Check your account shortly.")

    log("Publishing the Reel")
    media_id = _check(requests.post(f"{base}/{user_id}/media_publish", data={
        "creation_id": container_id, "access_token": token}, timeout=60), "publish")["id"]

    try:
        link = _check(requests.get(f"{base}/{media_id}", params={
            "fields": "permalink", "access_token": token}, timeout=30), "link lookup").get("permalink")
    except RuntimeError:
        link = None
    link = link or "https://www.instagram.com/"
    log(f"Published on Instagram: {link}")
    if on_progress:
        on_progress(1.0)
    return link
