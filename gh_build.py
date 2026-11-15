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

# Photo → Video: the website uploaded in/photo.* + in/sound.* + in/options.json
options_file = Path("in/options.json")
if options_file.exists():
    opts = json.loads(options_file.read_text(encoding="utf-8"))
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
