"""
Shorts Studio — local web app.

    python app.py
then open http://127.0.0.1:5000

The server only listens on your own computer (127.0.0.1) because it can post to
your channels. Don't change the host to 0.0.0.0 unless you add a login.
"""

import hashlib
import hmac
import os
import threading
import time
import traceback
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

import insta
import pipeline
import voice_clone
import yt_common

BASE_DIR = Path(__file__).resolve().parent

# On a hosting site (Hugging Face etc.) the Google files come from private
# Secrets instead of the repo. Write them to disk if they aren't there.
for env_name, file_name in (("CLIENT_SECRET_JSON", "client_secret.json"),
                            ("YT_TOKEN_S", "token_S.json"), ("YT_TOKEN_B", "token_B.json")):
    target = BASE_DIR / file_name
    if os.environ.get(env_name) and not target.exists():
        target.write_text(os.environ[env_name], encoding="utf-8")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5000"))
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
INCOMING_DIR = BASE_DIR / "incoming"
INCOMING_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB uploads
app.secret_key = hashlib.sha256(f"shorts-studio:{APP_PASSWORD or os.urandom(16).hex()}".encode()).digest()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax" if HOST == "127.0.0.1" else "None",
                  SESSION_COOKIE_SECURE=HOST != "127.0.0.1", PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)

LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Shorts Studio</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#1d1530;color:#f3ecfc;
font:16px/1.5 "Segoe UI",system-ui,sans-serif}form{background:#271d3e;padding:28px;border-radius:18px;
width:min(340px,90vw);display:grid;gap:12px}h1{margin:0 0 4px;font-size:1.4rem}input{padding:12px 14px;
border-radius:12px;border:1px solid #3e3160;background:#1d1530;color:inherit;font:inherit}
button{padding:12px;border:0;border-radius:12px;background:#ffb627;color:#2a1a00;font:600 1rem inherit;cursor:pointer}
p{margin:0;color:#ff6f91;font-size:.9rem}</style></head><body><form method="post">
<h1>Shorts Studio</h1><input type="password" name="password" placeholder="Password" autofocus required>
%s<button>Open studio</button></form></body></html>"""

JOBS = {}
JOBS_LOCK = threading.Lock()
HEAVY_LOCK = threading.Lock()  # one render at a time keeps the computer responsive


class Job:
    def __init__(self, kind, steps):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.steps = steps
        self.step = None
        self.pct = 0.0
        self.status = "queued"
        self.logs = []
        self.result = None
        self.error = None
        self.created = time.time()

    def log(self, msg):
        self.logs.append({"t": time.time(), "msg": str(msg)})
        print(f"[{self.kind} {self.id}] {msg}")

    def set_step(self, step):
        self.step, self.pct = step, 0.0

    def set_pct(self, value):
        self.pct = float(value)

    def to_dict(self, since=0):
        return {
            "id": self.id, "kind": self.kind, "status": self.status,
            "steps": self.steps, "step": self.step, "pct": round(self.pct, 3),
            "logs": self.logs[since:], "log_count": len(self.logs),
            "result": self.result, "error": self.error,
        }


def start_job(kind, steps, fn, heavy=True):
    job = Job(kind, steps)
    with JOBS_LOCK:
        JOBS[job.id] = job

    def runner():
        lock = HEAVY_LOCK if heavy else threading.Lock()
        if heavy and HEAVY_LOCK.locked():
            job.log("Waiting for the current render to finish")
        with lock:
            job.status = "running"
            try:
                job.result = fn(job)
                job.status = "done"
            except Exception as e:
                traceback.print_exc()
                job.error = str(e) or e.__class__.__name__
                job.status = "error"
                job.log(f"Stopped: {job.error}")

    threading.Thread(target=runner, daemon=True).start()
    return job


def video_path_or_404(name):
    safe = secure_filename(name or "")
    path = pipeline.VIDEOS_DIR / safe
    if not safe or not path.is_file():
        abort(404, description="That video file wasn't found in the videos folder.")
    return path


from flask import redirect, session


@app.before_request
def require_login():
    if not APP_PASSWORD or session.get("ok") or request.endpoint in ("login", "static"):
        return None
    if request.path.startswith("/api/") or request.path.startswith("/media/"):
        return jsonify(error="Please log in again."), 401
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect("/")
    error = ""
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), APP_PASSWORD):
            session.permanent = True
            session["ok"] = True
            return redirect("/")
        time.sleep(1.5)  # slows down password guessing
        error = "<p>Wrong password.</p>"
    return LOGIN_PAGE % error


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
def json_error(e):
    return jsonify(error=getattr(e, "description", str(e))), e.code


# ---------- pages & media ----------

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/media/<path:name>")
def media(name):
    path = video_path_or_404(name)
    return send_from_directory(pipeline.VIDEOS_DIR, path.name, conditional=True)


# ---------- api ----------

@app.get("/api/config")
def config():
    return jsonify(
        languages=[{"code": c, "label": v["label"]} for c, v in pipeline.LANGUAGES.items()],
        channels=yt_common.channel_status(),
        instagram=insta.is_configured(),
        keys=pipeline.keys_status(),
        youtube_ready=yt_common.CLIENT_SECRET.exists(),
        max_seconds=yt_common.SHORTS_MAX_SECONDS,
        styles=[{"code": k, "label": v} for k, v in pipeline.STYLES.items()],
        voice_clone=voice_clone.status(),
    )


@app.post("/api/script")
def script():
    body = request.get_json(force=True)
    topic = (body.get("topic") or "").strip()
    language = body.get("language", "en-IN")
    if not topic:
        abort(400, description="Type a topic first.")
    if language not in pipeline.LANGUAGES:
        abort(400, description="Pick a language from the list.")
    try:
        return jsonify(script=pipeline.generate_script(topic, language))
    except RuntimeError as e:
        return jsonify(error=str(e)), 502


@app.post("/api/build")
def build():
    body = request.get_json(force=True)
    topic = (body.get("topic") or "").strip()
    language = body.get("language", "en-IN")
    gender = body.get("gender", "female")
    style = body.get("style", "footage")
    script_text = (body.get("script") or "").strip()
    if not topic or not script_text:
        abort(400, description="A topic and a script are both needed to build the video.")
    if language not in pipeline.LANGUAGES:
        abort(400, description="Pick a language from the list.")
    if style not in pipeline.STYLES:
        abort(400, description="Pick a visual style from the list.")
    if gender == "mine" and voice_clone.supports(language):
        if not voice_clone.installed():
            abort(400, description="“My voice” needs the voice model installed first. See the instructions under Voice.")
        if not voice_clone.has_sample():
            abort(400, description="Record your voice sample first (Voice → My voice).")

    steps = ["voice", "visuals", "footage", "render"]
    job = start_job("build", steps, lambda j: pipeline.build_video(
        j.id, topic, language, gender, script_text, style=style,
        log=j.log, step=j.set_step, pct=j.set_pct))
    return jsonify(job=job.id)


@app.post("/api/describe")
def describe():
    body = request.get_json(force=True)
    title = (body.get("title") or "").strip()
    if not title:
        abort(400, description="Write a title first.")
    language = body.get("language", "en-IN")
    try:
        return jsonify(pipeline.describe_from_title(title, language, body.get("context") or ""))
    except Exception as e:
        return jsonify(error=f"Couldn't write the description: {e}"), 502


@app.post("/api/voice-sample")
def upload_voice_sample():
    f = request.files.get("file")
    if not f:
        abort(400, description="No recording received.")
    tmp = INCOMING_DIR / f"voice_{uuid.uuid4().hex[:8]}_{secure_filename(f.filename or 'rec.webm')}"
    f.save(tmp)
    try:
        voice_clone.save_sample(tmp)
    except RuntimeError as e:
        return jsonify(error=str(e)), 400
    finally:
        tmp.unlink(missing_ok=True)
    return jsonify(voice_clone=voice_clone.status())


@app.get("/api/voice-sample")
def get_voice_sample():
    if not voice_clone.has_sample():
        abort(404, description="No voice sample recorded yet.")
    return send_from_directory(voice_clone.SAMPLE_DIR, voice_clone.SAMPLE.name, conditional=True, max_age=0)


@app.post("/api/reframe")
def reframe():
    f = request.files.get("file")
    if not f or not f.filename:
        abort(400, description="Choose a video file to upload.")
    trim = request.form.get("trim", "true") == "true"
    original = f.filename
    dest = INCOMING_DIR / f"{uuid.uuid4().hex[:8]}_{secure_filename(original) or 'video.mp4'}"
    f.save(dest)
    job = start_job("reframe", ["load", "render"], lambda j: pipeline.reframe_existing(
        dest, original, trim, log=j.log, step=j.set_step, pct=j.set_pct))
    return jsonify(job=job.id)


@app.post("/api/publish")
def publish():
    body = request.get_json(force=True)
    path = video_path_or_404(body.get("video"))
    title = (body.get("title") or path.stem).strip()
    description = (body.get("description") or "").strip()
    tags = [t.strip().lstrip("#") for t in body.get("tags", []) if t.strip()]
    yt = body.get("youtube") or {}
    ig = body.get("instagram") or {}

    if not yt.get("enabled") and not ig.get("enabled"):
        abort(400, description="Turn on YouTube, Instagram, or both.")
    if yt.get("enabled"):
        if yt.get("channel") not in yt_common.CHANNELS:
            abort(400, description="Pick which YouTube channel to post to.")
        if yt.get("privacy") not in ("private", "unlisted", "public"):
            abort(400, description="Pick private, unlisted, or public.")
    if ig.get("enabled") and not ig.get("confirmed"):
        abort(400, description="Instagram Reels go public right away. Tick the confirmation box first.")

    steps = (["youtube"] if yt.get("enabled") else []) + (["instagram"] if ig.get("enabled") else [])

    def run(j):
        links = {}
        hashtag_line = " ".join(f"#{t}" for t in tags)
        full_description = "\n\n".join(p for p in (description, hashtag_line) if p)
        if yt.get("enabled"):
            j.set_step("youtube")
            links["youtube"] = yt_common.upload_short(
                path, title, full_description, tags or ["shorts"], yt["privacy"], yt["channel"],
                log=j.log, on_progress=j.set_pct, publish_at=yt.get("publish_at") or None)
        if ig.get("enabled"):
            j.set_step("instagram")
            caption = "\n\n".join(p for p in (title, description, hashtag_line) if p)
            try:
                links["instagram"] = insta.publish_reel(path, caption, log=j.log, on_progress=j.set_pct)
            except Exception as e:
                if links:  # YouTube worked, keep its link visible
                    j.log(f"Instagram failed: {e}")
                    links["instagram_error"] = str(e)
                else:
                    raise
        return {"links": links}

    job = start_job("publish", steps, run, heavy=False)
    return jsonify(job=job.id)


ENV_FILE = BASE_DIR / ".env"
KEY_FIELDS = {"gemini": "GEMINI_API_KEY", "pexels": "PEXELS_API_KEY",
              "ig_user_id": "IG_USER_ID", "ig_token": "IG_ACCESS_TOKEN"}


@app.post("/api/keys")
def save_keys():
    """Saves keys pasted in the UI into .env and applies them right away."""
    import os
    body = request.get_json(force=True)
    updates = {env: str(body[f]).strip() for f, env in KEY_FIELDS.items() if str(body.get(f) or "").strip()}
    if not updates:
        abort(400, description="Paste at least one key.")
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    kept = [l for l in lines if l.split("=", 1)[0].strip() not in updates]
    kept += [f"{k}={v}" for k, v in updates.items()]
    ENV_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.environ.update(updates)
    pipeline._gemini_client = None  # pick up a new Gemini key
    return jsonify(ok=True, keys=pipeline.keys_status(), instagram=insta.is_configured())


@app.post("/api/channels/<key>/connect")
def connect_channel(key):
    if key not in yt_common.CHANNELS:
        abort(404, description="Unknown channel.")

    def run(j):
        j.set_step("signin")
        yt_common.get_youtube_service(key, log=j.log)
        return {"channels": yt_common.channel_status()}

    job = start_job("connect", ["signin"], run, heavy=False)
    return jsonify(job=job.id)


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        abort(404, description="That job no longer exists. The app may have restarted.")
    return jsonify(job.to_dict(since=int(request.args.get("since", 0))))


@app.get("/api/videos")
def videos():
    files = sorted(pipeline.VIDEOS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonify(videos=[
        {"name": p.name, "size": p.stat().st_size, "modified": p.stat().st_mtime}
        for p in files if ".temp-audio" not in p.name
    ])


@app.delete("/api/videos/<name>")
def delete_video(name):
    video_path_or_404(name).unlink()
    return jsonify(ok=True)


if __name__ == "__main__":
    if HOST not in ("127.0.0.1", "localhost") and not APP_PASSWORD:
        raise SystemExit("Refusing to go public without a password. Set the APP_PASSWORD secret first.")
    print(f"\nShorts Studio is running at http://{'127.0.0.1' if HOST == '127.0.0.1' else HOST}:{PORT}\n")
    app.run(host=HOST, port=PORT, threaded=True, debug=False)
