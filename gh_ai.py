"""Runs inside GitHub Actions for the website's AI buttons:
"Write script", "Write from title", and Remake / Reaction from a video link.
The answer goes back to the page as a GitHub annotation (base64, so Hindi
and line breaks survive)."""
import base64
import json
import os

import pipeline


def send(title, payload):
    data = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    print(f"::notice title={title}::{data}")


def transcribe(url):
    import yt_dlp
    from faster_whisper import WhisperModel
    print("Downloading the audio")
    opts = {"format": "bestaudio/best", "outtmpl": "/tmp/source.%(ext)s", "quiet": True, "noplaylist": True,
            "match_filter": yt_dlp.utils.match_filter_func("duration < 1200")}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
    except Exception as e:
        raise SystemExit("Couldn't download that video (YouTube often blocks GitHub's servers, and videos "
                         f"over 20 minutes are skipped). Paste the transcript instead. Details: {e}")
    print("Transcribing")
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(path, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not text:
        raise SystemExit("No speech found in that video.")
    return text


mode = os.environ.get("MODE", "script")
language = os.environ.get("LANGUAGE") or "hi-IN"

if mode == "script":
    send("script", {"script": pipeline.generate_script(os.environ["TOPIC"].strip(), language, log=print)})
elif mode == "describe":
    send("describe", pipeline.describe_from_title(os.environ["TITLE"].strip(), language,
                                                  os.environ.get("CONTEXT", ""), log=print))
else:  # remake / react
    transcript = (os.environ.get("CONTEXT") or "").strip()
    if not transcript:
        url = (os.environ.get("URL") or "").strip()
        if not url:
            raise SystemExit("Paste a video link or a transcript.")
        transcript = transcribe(url)
    send("script", pipeline.rewrite_from_transcript(transcript, mode, language, log=print))
print("Done.")
