"""
One-time helper for "My voice" on the GitHub website.

1. Record your voice in the PC app first (Voice → My voice → Start recording).
2. Run:  python make_voice_secret.py
3. It copies a code to your clipboard. Paste it into a new GitHub secret
   named VOICE_SAMPLE_B64.

The sample is squeezed into a small file so it fits GitHub's 48 KB secret limit.
It stays private: secrets are never shown in the repo or the logs.
"""
import base64
import subprocess
import tempfile
from pathlib import Path

import voice_clone

if not voice_clone.has_sample():
    raise SystemExit("No voice sample yet. Record one in the PC app (Voice → My voice), then run this again.")

with tempfile.TemporaryDirectory() as tmp:
    small = Path(tmp) / "voice.ogg"
    for bitrate in ("16k", "12k", "8k"):
        subprocess.run([voice_clone._ffmpeg(), "-y", "-loglevel", "error", "-i", str(voice_clone.SAMPLE),
                        "-t", "15", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", bitrate, str(small)],
                       check=True)
        code = base64.b64encode(small.read_bytes()).decode("ascii")
        if len(code) < 47_000:
            break
    else:
        raise SystemExit("The sample is too big. Record a shorter one (about 10 seconds).")

subprocess.run("clip", input=code.encode("ascii"), shell=True)
print(f"Copied to clipboard ({len(code) // 1024} KB).")
print("Now open your repo → Settings → Secrets and variables → Actions → New repository secret")
print("Name: VOICE_SAMPLE_B64    Secret: press Ctrl+V")
