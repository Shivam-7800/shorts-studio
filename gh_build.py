"""Runs inside GitHub Actions: writes the script (unless one is given), builds
the video and saves out/short.mp4 + out/result.json as the run's artifact."""
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

if voice == "mine":
    import tempfile
    import voice_clone
    sample_b64 = os.environ.get("VOICE_SAMPLE_B64", "").strip()
    if not sample_b64:
        raise SystemExit("“My voice” needs the VOICE_SAMPLE_B64 secret. Run make_voice_secret.py on your PC (see README).")
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
