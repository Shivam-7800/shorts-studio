"""Runs inside GitHub Actions: posts a video made by an earlier run to YouTube
and/or Instagram. Prints no links, because Actions logs on a public repo are public."""
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
for env_name, file_name in (("CLIENT_SECRET_JSON", "client_secret.json"),
                            ("YT_TOKEN_S", "token_S.json"), ("YT_TOKEN_B", "token_B.json")):
    if os.environ.get(env_name):
        (BASE / file_name).write_text(os.environ[env_name], encoding="utf-8")

import insta  # noqa: E402
import yt_common  # noqa: E402

res = json.loads(Path("out/result.json").read_text(encoding="utf-8"))
video = Path("out/short.mp4")
title = (os.environ.get("TITLE") or "").strip() or res.get("title") or res.get("topic", "Short")
description = (os.environ.get("DESCRIPTION") or "").strip() or res.get("description", "")
typed = (os.environ.get("HASHTAGS") or "").replace(",", " ").split()
tags = [t.lstrip("#") for t in typed if t.strip("#")] or res.get("hashtags") or ["shorts"]
hashtag_line = " ".join(f"#{t}" for t in tags)
quiet = lambda _msg: None  # noqa: E731

want_youtube = os.environ.get("YOUTUBE", "true") == "true"
want_instagram = os.environ.get("INSTAGRAM", "false") == "true"
errors = []

if want_youtube:
    publish_at = (os.environ.get("PUBLISH_AT") or "").strip() or None
    yt_common.upload_short(video, title, "\n\n".join(p for p in (description, hashtag_line) if p), tags,
                           os.environ.get("PRIVACY", "private"), os.environ.get("CHANNEL", "S"),
                           log=quiet, publish_at=publish_at)
    print("YouTube: uploaded" + (f", scheduled for {publish_at}" if publish_at else "") + ". See YouTube Studio.")

if want_instagram:
    if not insta.is_configured():
        errors.append("Instagram isn't set up: add the IG_USER_ID and IG_ACCESS_TOKEN secrets.")
    else:
        try:
            insta.publish_reel(video, "\n\n".join(p for p in (title, description, hashtag_line) if p), log=quiet)
            print("Instagram: Reel published.")
        except Exception as e:
            errors.append(f"Instagram failed: {e}")

if errors:
    raise SystemExit("\n".join(errors))
