"""Runs inside GitHub Actions: writes the script (unless one is given), builds
the video and saves out/short.mp4 + out/result.json as the run's artifact."""
import sys as _sys


def _report(exc_type, exc, tb):
    import traceback
    traceback.print_exception(exc_type, exc, tb)
    msg = str(exc) if str(exc) else exc_type.__name__
    print("::error title=Why it stopped::" + msg.replace("\r", "").replace("\n", " "))


_sys.excepthook = _report

import base64
import json
import os
import shutil
import uuid
from pathlib import Path

import pipeline

topic = os.environ["TOPIC"].strip()
language = os.environ.get("LANGUAGE") or "hi-IN"
voice = os.environ.get("VOICE") or "female"
style = os.environ.get("STYLE") or "footage"
script = (os.environ.get("SCRIPT") or "").strip()
title = (os.environ.get("TITLE") or "").strip()

if title.startswith("HELPER_ERROR:"):  # the PC helper couldn't download the link
    print("::error title=Why it stopped::" + title[len("HELPER_ERROR:"):].strip())
    raise SystemExit(1)

# Photo → Video: the website uploaded in/photo.* + in/sound.* + in/options.json
options_file = Path("in/options.json")
if options_file.exists():
    opts = json.loads(options_file.read_text(encoding="utf-8"))
    if opts.get("kind") == "dance":
        import dance
        from datetime import datetime
        media = next(Path("in").glob("media.*"))
        meta_file = Path("in/info.json")
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        photo = next(iter(Path("in").glob("photo.*")), None)
        out_video = pipeline.VIDEOS_DIR / f"dance_{datetime.now():%Y%m%d_%H%M%S}.mp4"
        info = dance.make_dance(media, out_video, opts.get("dancer", "mascot"), opts.get("style", "bolt"),
                                photo_path=photo, log=print)
        try:
            song = pipeline.identify_song(media, meta, log=print)
        except Exception as e:
            print(f"Couldn't identify the song: {e}")
            song = {}
        song_name = " – ".join(x for x in (song.get("title"), song.get("artist")) if x)
        video_title = title or (f"{song.get('title')} dance 🔥" if song.get("title") else "Dance video 🔥")
        try:
            meta_text = pipeline.describe_from_title(video_title, language, song_name, log=print)
        except Exception:
            meta_text = {}
        result = {"video": out_video.name, "duration": info["duration"], "format": "reel", "silent": True,
                  "tempo": info["tempo"], "song": song, "title": video_title,
                  "description": meta_text.get("description", ""),
                  "hashtags": meta_text.get("hashtags") or ["dance", "reels", "trending"]}
        out = Path("out")
        out.mkdir(exist_ok=True)
        shutil.copy(out_video, out / "short.mp4")
        result.update(video="short.mp4", topic=topic, language=language)
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {k: result.get(k) for k in ("title", "description", "hashtags", "duration", "format", "song", "silent", "tempo")}
        print("::notice title=result::" + base64.b64encode(json.dumps(summary, ensure_ascii=False).encode("utf-8")).decode("ascii"))
        raise SystemExit(0)
    if opts.get("kind") == "photo":
        photo = next(Path("in").glob("photo.*"))
        sound = next(Path("in").glob("sound.*"))
        result = pipeline.photo_video(photo, sound, opts.get("format", "reel"), opts.get("effect", "cinematic"),
                                      log=print)
        result["title"] = title or topic
        try:
            meta = pipeline.describe_from_title(result["title"], language, log=print) if title else {}
        except Exception:
            meta = {}
        result["description"] = meta.get("description", "")
        result["hashtags"] = meta.get("hashtags") or ["reels", "video", "viral"]
        out = Path("out")
        out.mkdir(exist_ok=True)
        shutil.copy(pipeline.VIDEOS_DIR / result["video"], out / "short.mp4")
        result.update(video="short.mp4", topic=topic, language=language)
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {k: result.get(k) for k in ("title", "description", "hashtags", "duration", "format")}
        print("::notice title=result::" + base64.b64encode(json.dumps(summary, ensure_ascii=False).encode("utf-8")).decode("ascii"))
        raise SystemExit(0)

if voice == "mine":
    import tempfile
    import voice_clone
    sample_b64 = os.environ.get("VOICE_SAMPLE_B64", "").strip()
    if not sample_b64:
        print("::error title=Why it stopped::“My voice” needs the VOICE_SAMPLE_B64 secret. Run make_voice_secret.py on your PC.")
        raise SystemExit(1)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(base64.b64decode(sample_b64))
    voice_clone.save_sample(f.name)
    print("Using your voice sample")

if not script:
    script = pipeline.generate_script(topic, language, log=print)
print("\n== SCRIPT ==\n" + script + "\n")

result = pipeline.build_video(uuid.uuid4().hex[:12], topic, language, voice, script, style=style,
                              log=print, step=lambda s: print(f"\n== {s} =="))
if title:
    result["title"] = title

out = Path("out")
out.mkdir(exist_ok=True)
shutil.copy(pipeline.VIDEOS_DIR / result["video"], out / "short.mp4")
result.update(video="short.mp4", script=script, topic=topic, language=language)
(out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
# Hand the AI title/description/hashtags back to the website (see gh_ai.py).
summary = {k: result.get(k) for k in ("title", "description", "hashtags", "duration")}
print("::notice title=result::" + base64.b64encode(json.dumps(summary, ensure_ascii=False).encode("utf-8")).decode("ascii"))
print(f"\nDone: {result['duration']}s video. Download it from the 'short' artifact below.")
