"""Runs inside GitHub Actions for the website's AI buttons:
"Write script", "Write from title", and Remake / Reaction from a video link.
The answer goes back to the page as a GitHub annotation (base64, so Hindi
and line breaks survive). Errors go back the same way, so the page can say why."""
import base64
import json
import os
import sys

import pipeline


def send(title, payload):
    data = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    print(f"::notice title={title}::{data}")


def fail(message):
    print("::error title=Why it stopped::" + str(message).replace("\r", "").replace("\n", " "))
    sys.exit(1)


def main():
    mode = os.environ.get("MODE", "script")
    language = os.environ.get("LANGUAGE") or "hi-IN"
    if mode == "script":
        send("script", {"script": pipeline.generate_script(os.environ["TOPIC"].strip(), language, log=print)})
    elif mode == "describe":
        send("describe", pipeline.describe_from_title(os.environ["TITLE"].strip(), language,
                                                      os.environ.get("CONTEXT", ""), log=print))
    else:  # remake / react
        from pathlib import Path
        uploaded = [f for f in Path("in").glob("media.*")] if Path("in").exists() else []
        if uploaded:
            send("script", pipeline.rewrite_from_audio(uploaded[0], mode, language, log=print))
            print("Done.")
            return
        transcript = (os.environ.get("CONTEXT") or "").strip()
        if not transcript:
            url = (os.environ.get("URL") or "").strip()
            if not url:
                fail("Paste a video link or a transcript.")
            import transcribe
            transcript = transcribe.get_transcript(url, log=print)
        send("script", pipeline.rewrite_from_transcript(transcript, mode, language, log=print))
    print("Done.")


try:
    main()
except SystemExit:
    raise
except Exception as e:
    fail(e)
