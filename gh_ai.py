"""Runs inside GitHub Actions for the website's "Write script" and
"Write from title" buttons. The answer is passed back to the page as a
GitHub annotation (base64 so Hindi and line breaks survive)."""
import base64
import json
import os

import pipeline


def send(title, payload):
    data = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    print(f"::notice title={title}::{data}")


mode = os.environ.get("MODE", "script")
language = os.environ.get("LANGUAGE") or "hi-IN"

if mode == "script":
    script = pipeline.generate_script(os.environ["TOPIC"].strip(), language, log=print)
    send("script", {"script": script})
else:
    result = pipeline.describe_from_title(os.environ["TITLE"].strip(), language,
                                          os.environ.get("CONTEXT", ""), log=print)
    send("describe", result)
print("Done.")
