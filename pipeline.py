"""
Video pipeline — the same steps as your original main.py, rewritten as plain
functions so both the web UI (app.py) and the terminal (main.py) can use them.

Nothing here calls input(), and heavy libraries (moviepy, edge-tts, Gemini) are
imported only when needed, so the web server starts even if a key is missing and
shows the problem in the UI instead of crashing.
"""

import os
import re
import json
import time
import asyncio
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote
from pathlib import Path

import requests

from yt_common import fit_vertical, SHORTS_MAX_SECONDS, TARGET_W, TARGET_H, _LOW

BASE_DIR = Path(__file__).resolve().parent
VIDEOS_DIR = BASE_DIR / "videos"
WORK_DIR = BASE_DIR / "work"
VIDEOS_DIR.mkdir(exist_ok=True)
WORK_DIR.mkdir(exist_ok=True)

GEMINI_MODEL_FALLBACKS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

# code -> label + both voices, so the UI can offer a male/female choice
LANGUAGES = {
    "en-IN": {"label": "English (India)", "female": "en-IN-NeerjaNeural", "male": "en-IN-PrabhatNeural"},
    "hi-IN": {"label": "Hindi", "female": "hi-IN-SwaraNeural", "male": "hi-IN-MadhurNeural"},
    "ta-IN": {"label": "Tamil", "female": "ta-IN-PallaviNeural", "male": "ta-IN-ValluvarNeural"},
    "te-IN": {"label": "Telugu", "female": "te-IN-ShrutiNeural", "male": "te-IN-MohanNeural"},
    "kn-IN": {"label": "Kannada", "female": "kn-IN-SapnaNeural", "male": "kn-IN-GaganNeural"},
    "mr-IN": {"label": "Marathi", "female": "mr-IN-AarohiNeural", "male": "mr-IN-ManoharNeural"},
    "bn-IN": {"label": "Bengali", "female": "bn-IN-TanishaaNeural", "male": "bn-IN-BashkarNeural"},
    "gu-IN": {"label": "Gujarati", "female": "gu-IN-DhwaniNeural", "male": "gu-IN-NiranjanNeural"},
}

# Added to every video's hashtags regardless of topic (same as your main.py).
COMMON_HASHTAGS = ["benglore", "weather"]


def _noop(*_args, **_kwargs):
    pass


# =========================================
# GEMINI
# =========================================

_gemini_client = None
_last_good_model = None
_no_config_models = set()

# Small jobs (search terms, hashtags, description) go to the lightest models first.
GEMINI_FAST_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
]


def keys_status():
    return {
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
        "pexels": bool(os.environ.get("PEXELS_API_KEY")),
    }


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set. Paste it in the yellow box in the app.")
        from google import genai
        try:
            from google.genai import types
            _gemini_client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=45_000))
        except Exception:
            _gemini_client = genai.Client(api_key=key)
    return _gemini_client


def _fast_config():
    """Ask for minimal 'thinking' so answers come back quicker."""
    try:
        from google.genai import types
        return types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="low"))
    except Exception:
        return None


def _is_busy(msg):
    return any(c in msg for c in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND",
                                  "DEADLINE", "timed out", "Timeout", "500", "INTERNAL"))


def call_gemini_with_retry(prompt, log=_noop, models=None):
    """Tries each model once with no waiting (busy model -> next model straight
    away). Only if every model is busy does it pause briefly and go round once more.
    The model that last worked is tried first next time."""
    global _last_good_model
    client = _gemini()
    order = list(models or GEMINI_MODEL_FALLBACKS)
    if _last_good_model in order:
        order.remove(_last_good_model)
        order.insert(0, _last_good_model)

    last_error = None
    for round_no in range(2):
        for model in order:
            config = None if model in _no_config_models else _fast_config()
            try:
                try:
                    resp = client.models.generate_content(model=model, contents=prompt, config=config)
                except Exception as e:
                    if config is not None and ("thinking" in str(e).lower() or "INVALID_ARGUMENT" in str(e)):
                        _no_config_models.add(model)
                        resp = client.models.generate_content(model=model, contents=prompt)
                    else:
                        raise
                _last_good_model = model
                return resp
            except Exception as e:
                last_error = e
                if _is_busy(str(e)):
                    log(f"{model} is busy, switching model")
                    continue
                raise RuntimeError(f"Gemini request failed: {e}")
        if round_no == 0:
            log("All Gemini models busy, waiting 4 seconds")
            time.sleep(4)
    raise RuntimeError(f"All Gemini models are busy right now. Try again in a minute. ({last_error})")


def _strip_fences(text):
    return re.sub(r"^```(json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()


def generate_script(topic, language_code, log=_noop):
    language_name = LANGUAGES[language_code]["label"]
    log(f"Writing a {language_name} script with Gemini")
    prompt = f"""Create a viral YouTube Shorts script about: {topic}

Write the ENTIRE script in {language_name}. Use natural, everyday spoken {language_name} the way a
real content creator would talk — not a stiff or overly formal/literary register.

Requirements:
- Strong hook in the first line
- Human sounding, natural spoken tone
- Fast pacing, short sentences (one idea per sentence)
- 30-45 seconds when read aloud
- High retention, curiosity driven
- End with a call to action

Do NOT use the phrase "Today we are talking about" (or its equivalent in {language_name}).
Return ONLY the script text, no headings, no labels, no markdown."""
    script = (call_gemini_with_retry(prompt, log).text or "").strip()
    if not script:
        raise RuntimeError("Gemini returned an empty script. Try again or check your API quota.")
    return script


def split_into_lines(script):
    raw = re.split(r"(?<=[.!?।])\s+", script.replace("\n", " "))
    return [line.strip() for line in raw if line.strip()]


def _merge_common(tags):
    tags = [str(t).lstrip("#").replace(" ", "") for t in tags if str(t).strip()]
    for tag in COMMON_HASHTAGS:
        if tag.lower() not in [t.lower() for t in tags]:
            tags.append(tag)
    return tags


def plan_video(lines, topic, language_code, log=_noop):
    """ONE Gemini call for everything the build needs besides the script:
    a footage search per line, a catchy title, a description and hashtags."""
    language_name = LANGUAGES[language_code]["label"]
    log("Planning visuals, title, description and hashtags")
    numbered = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines))
    prompt = f"""You are preparing a YouTube Short about "{topic}". The script is in {language_name}.

Script lines:
{numbered}

Return ONLY a JSON object (no markdown) with exactly these keys:
"queries": an array with exactly {len(lines)} strings, one per line in order. Each is a 2-4 word
  ENGLISH stock-footage search query showing that line with concrete nouns. The audience is Indian:
  when a line involves people, clothing, places or festivals, prefer Indian context
  (e.g. "indian family dinner"), but not for abstract things, maps or objects.
"title": a catchy Shorts title under 70 characters, in {language_name} (English words are fine).
"description": 2-3 short engaging sentences for the YouTube description, in {language_name}.
"hashtags": an array of 6 relevant hashtags, English, no # symbol, no spaces."""
    try:
        data = json.loads(_strip_fences(call_gemini_with_retry(prompt, log, GEMINI_FAST_MODELS).text))
        queries = data.get("queries")
        if not isinstance(queries, list) or len(queries) != len(lines):
            raise ValueError("query count mismatch")
        return {
            "queries": [str(q) for q in queries],
            "title": str(data.get("title") or topic).strip()[:100],
            "description": str(data.get("description") or "").strip(),
            "hashtags": _merge_common(data.get("hashtags") or []),
        }
    except Exception as e:
        log(f"Planning fell back to simple defaults ({e})")
        return {"queries": [topic] * len(lines), "title": topic, "description": "",
                "hashtags": _merge_common(re.sub(r"[^\w\s]", "", topic).split())}


def describe_from_title(title, language_code, context="", log=_noop):
    """Description + hashtags written from a title you typed."""
    language_name = LANGUAGES.get(language_code, LANGUAGES["en-IN"])["label"]
    prompt = f"""Write YouTube Shorts metadata for a video titled: "{title}"
{f"The video's script, for context: {context[:1500]}" if context else ""}

Return ONLY a JSON object (no markdown) with:
"description": 2-3 short engaging sentences in {language_name} (English words are fine), ending with
  a call to like, comment or subscribe.
"hashtags": an array of 8 relevant hashtags, English, no # symbol, no spaces."""
    data = json.loads(_strip_fences(call_gemini_with_retry(prompt, log, GEMINI_FAST_MODELS).text))
    return {"description": str(data.get("description") or "").strip(),
            "hashtags": _merge_common(data.get("hashtags") or [])}


def rewrite_from_transcript(transcript, mode, language_code, log=_noop):
    """Turns another video's transcript into an ORIGINAL script (mode "remake")
    or your own commentary on it (mode "react"). Never a copy: reposting someone
    else's words gets flagged by YouTube/Instagram as reused content."""
    language_name = LANGUAGES[language_code]["label"]
    if mode == "react":
        task = f"""Write a REACTION / COMMENTARY Shorts script in {language_name}, spoken by me (the creator)
responding to the main claims in this video: say what's interesting, what's missing or doubtful, add
context or a counter-point, and give my own opinion. Refer to it as "a video I saw"; quote at most
5 words from it."""
    else:
        task = f"""Write a NEW, ORIGINAL Shorts script in {language_name} on the same topic as this video.
Do NOT copy its sentences, structure or distinctive phrases. Use your own hook, your own order and
wording, and add at least one extra fact or angle the video didn't mention."""
    prompt = f"""{task}

Rules: natural spoken {language_name}, short sentences, strong hook in the first line, 30-45 seconds
read aloud, end with a call to action, no headings or markdown.

Transcript of the other video (for understanding only):
\"\"\"{transcript[:12000]}\"\"\"

Return ONLY a JSON object (no markdown): {{"topic": "<short topic in English>", "script": "<the script>"}}"""
    log("Gemini is writing your version")
    data = json.loads(_strip_fences(call_gemini_with_retry(prompt, log).text))
    script = str(data.get("script") or "").strip()
    if not script:
        raise RuntimeError("Gemini returned an empty script. Try again.")
    return {"topic": str(data.get("topic") or "").strip(), "script": script}


# =========================================
# VOICE (edge-tts)
# =========================================

async def _line_audio(lines, voice, audio_dir, log):
    """Records every line at the same time (5 at once) instead of one by one."""
    import edge_tts
    sem = asyncio.Semaphore(5)
    done = 0

    async def one(i, line):
        nonlocal done
        path = audio_dir / f"line_{i}.mp3"
        async with sem:
            for attempt in range(3):
                try:
                    await edge_tts.Communicate(text=line, voice=voice, rate="-4%", pitch="+2Hz").save(str(path))
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.5)
        done += 1
        log(f"Voiced {done} of {len(lines)} lines")
        return path

    return await asyncio.gather(*(one(i, l) for i, l in enumerate(lines)))


# =========================================
# PEXELS
# =========================================

def _pexels_headers():
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise RuntimeError("PEXELS_API_KEY is not set. Add it to your .env file and restart the app.")
    return {"Authorization": key}


def search_pexels_video(query):
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": 1, "orientation": "portrait"},
            headers=_pexels_headers(), timeout=30,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
        if not videos:
            return None
        # Smallest file that's still full-HD wide: much faster to download and
        # render than the 4K versions, with no visible difference on a phone.
        files = [f for f in videos[0]["video_files"] if f.get("width")]
        big_enough = sorted((f for f in files if f["width"] >= TARGET_W), key=lambda f: f["width"])
        if big_enough:
            return big_enough[0]["link"]
        files.sort(key=lambda f: f["width"], reverse=True)
        return files[0]["link"] if files else None
    except RuntimeError:
        raise
    except Exception:
        return None


def search_pexels_photo(query):
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 1, "orientation": "portrait"},
            headers=_pexels_headers(), timeout=30,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        return photos[0]["src"]["large2x"] if photos else None
    except RuntimeError:
        raise
    except Exception:
        return None


def _download(url, path):
    with requests.get(url, timeout=120, stream=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)


def fetch_segment_asset(query, topic, index, assets_dir):
    """Returns (path, is_image). Tries query -> 'indian <topic>' -> topic."""
    for q in (query, f"indian {topic}", topic):
        video_url = search_pexels_video(q)
        if video_url:
            path = assets_dir / f"segment_{index}.mp4"
            _download(video_url, path)
            return path, False
        photo_url = search_pexels_photo(q)
        if photo_url:
            path = assets_dir / f"segment_{index}.jpg"
            _download(photo_url, path)
            return path, True
    return None, None


# =========================================
# AI CARTOON IMAGES (Pollinations — free, no key; anonymous use is limited to
# about one image every 15 seconds, so this style is slower than stock footage)
# =========================================

STYLES = {
    "footage": "Real stock footage",
    "cartoon": "Cartoon (AI images)",
    "anime": "Anime (AI images)",
}
_STYLE_PROMPTS = {
    "cartoon": "colorful 2D cartoon illustration, bold outlines, friendly characters, vertical composition",
    "anime": "anime style illustration, vibrant colors, cinematic lighting, vertical composition",
}
_last_ai_request = 0.0


def fetch_ai_image(query, style, path, log=_noop):
    global _last_ai_request
    prompt = f"{query}, {_STYLE_PROMPTS[style]}"
    url = "https://image.pollinations.ai/prompt/" + quote(prompt)
    for attempt in range(3):
        wait = 15 - (time.time() - _last_ai_request)
        if wait > 0:
            time.sleep(wait)
        _last_ai_request = time.time()
        try:
            r = requests.get(url, params={"width": TARGET_W, "height": TARGET_H, "nologo": "true",
                                          "seed": random.randint(1, 10**6)}, timeout=120)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                path.write_bytes(r.content)
                return True
            log(f"AI image service replied {r.status_code}, retrying")
        except Exception as e:
            log(f"AI image request failed ({e}), retrying")
    return False


# =========================================
# RENDERING
# =========================================

def _render_logger(on_pct):
    """MoviePy progress -> 0..1 callback. Falls back to the normal console bar."""
    try:
        from proglog import ProgressBarLogger
    except ImportError:
        return "bar"

    class _Logger(ProgressBarLogger):
        def bars_callback(self, bar, attr, value, old_value=None):
            if attr == "index" and bar in ("frame_index", "t"):
                total = self.bars[bar].get("total") or 0
                if total:
                    on_pct(min(value / total, 1.0))

    return _Logger()


def _write(clip, out_path, on_pct):
    # H.264 + AAC + yuv420p + faststart: plays in every browser and meets
    # Instagram's Reels requirements (Instagram rejects MP3 audio).
    clip.write_videofile(
        str(out_path),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(out_path.with_suffix(".temp-audio.m4a")),
        remove_temp=True,
        preset="ultrafast" if _LOW else "veryfast",  # faster encode, small size cost
        threads=1 if _LOW else (os.cpu_count() or 4),
        ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        logger=_render_logger(on_pct),
    )


def _build_segment_clip(path, is_image, duration):
    from moviepy import VideoFileClip, ImageClip
    if is_image:
        clip = fit_vertical(ImageClip(str(path)).with_duration(duration))
        clip = clip.resized(lambda t: 1 + 0.06 * (t / max(duration, 0.01)))  # slow zoom
    else:
        clip = fit_vertical(VideoFileClip(str(path)).without_audio())
        if clip.duration < duration:
            try:
                from moviepy import vfx
                clip = clip.with_effects([vfx.Loop(duration=duration)])
            except Exception:
                pass
        else:
            clip = clip.subclipped(0, duration)
    return clip


LOGO_PATH = BASE_DIR / "assets" / "logo.png"


def _add_logo(clip, log=_noop):
    """Puts assets/logo.png in the top-right corner (transparent PNG works best).
    Turn off with the environment variable ADD_LOGO=false."""
    if os.environ.get("ADD_LOGO", "true").lower() == "false" or not LOGO_PATH.exists():
        return clip
    from moviepy import ImageClip, CompositeVideoClip
    w = int(clip.w * 0.2)
    margin = int(clip.w * 0.04)
    logo = (ImageClip(str(LOGO_PATH)).resized(width=w).with_opacity(0.9)
            .with_duration(clip.duration))
    logo = logo.with_position((clip.w - logo.w - margin, margin + int(clip.h * 0.03)))
    log("Adding your logo")
    return CompositeVideoClip([clip, logo], size=clip.size)


def _safe_name(text, fallback="short"):
    # ASCII only, so the file name survives URLs and secure_filename()
    name = re.sub(r"[^A-Za-z0-9\-]+", "_", text).strip("_")[:60]
    return name or fallback


def build_video(job_id, topic, language_code, gender, script, style="footage",
                log=_noop, step=_noop, pct=_noop):
    """Full build from an (optionally edited) script. Returns a result dict.
    gender: "female", "male", or "mine" (your cloned voice)."""
    from moviepy import AudioFileClip, concatenate_videoclips, concatenate_audioclips

    lang = LANGUAGES[language_code]
    work = WORK_DIR / job_id
    audio_dir, assets_dir = work / "audio", work / "assets"
    audio_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    lines = split_into_lines(script)
    if not lines:
        raise RuntimeError("The script is empty. Write or generate a script first.")

    with ThreadPoolExecutor(max_workers=8) as pool:
        # Gemini planning runs in the background while the voice is recorded.
        plan_future = pool.submit(plan_video, lines, topic, language_code, log)

        step("voice")
        use_clone = gender == "mine"
        if use_clone:
            import voice_clone
            if not voice_clone.supports(language_code):
                log(f"Your voice works in English and Hindi only, so {lang['label']} uses the standard voice")
                use_clone = False
        if use_clone:
            audio_paths = voice_clone.synthesize(lines, language_code, audio_dir, log=log, pct=pct)
        else:
            voice = lang["male" if gender == "male" else "female"]
            audio_paths = asyncio.run(_line_audio(lines, voice, audio_dir, log))

        step("visuals")
        plan = plan_future.result()
        queries = plan["queries"]

        step("footage")
        assets = [None] * len(lines)
        if style in _STYLE_PROMPTS:
            log("Drawing AI images (free service allows about one every 15 seconds)")
            for i, q in enumerate(queries):
                path = assets_dir / f"segment_{i}.jpg"
                if fetch_ai_image(q, style, path, log):
                    assets[i] = (path, True)
                else:
                    log(f"Line {i + 1}: AI image failed, using stock footage instead")
                    assets[i] = fetch_segment_asset(q, topic, i, assets_dir)
                log(f"Image {i + 1} of {len(lines)} ready")
                pct((i + 1) / len(lines))
        else:
            # All clips searched and downloaded at the same time.
            futures = {pool.submit(fetch_segment_asset, q, topic, i, assets_dir): i for i, q in enumerate(queries)}
            for n, fut in enumerate(futures, 1):
                i = futures[fut]
                assets[i] = fut.result()
                log(f"Clip {n} of {len(lines)} downloaded")
                pct(n / len(lines))

    audio_clips, video_clips = [], []
    for i, (asset, audio_path) in enumerate(zip(assets, audio_paths)):
        asset_path, is_image = asset
        if asset_path is None:
            raise RuntimeError(f"No footage or photo found for line {i + 1} (search: “{queries[i]}”). Edit that line and build again.")
        line_audio = AudioFileClip(str(audio_path))
        audio_clips.append(line_audio)
        video_clips.append(_build_segment_clip(asset_path, is_image, line_audio.duration))

    step("render")
    final = concatenate_videoclips(video_clips, method="compose").with_audio(concatenate_audioclips(audio_clips))
    final = _add_logo(final, log)
    out = VIDEOS_DIR / f"{_safe_name(topic)}_{datetime.now():%Y%m%d_%H%M%S}.mp4"
    log("Rendering the final video")
    _write(final, out, pct)
    duration = final.duration
    final.close()

    return {
        "video": out.name,
        "title": plan["title"],
        "description": plan["description"],
        "hashtags": plan["hashtags"],
        "lines": lines,
        "queries": queries,
        "duration": round(float(duration), 1),
    }


def reframe_existing(source_path, original_name, trim, log=_noop, step=_noop, pct=_noop):
    """Your upload_existing.py, as a function: crop to 9:16, optionally trim."""
    from moviepy import VideoFileClip

    step("load")
    clip = VideoFileClip(str(source_path))
    log(f"Loaded {clip.w}×{clip.h}, {clip.duration:.1f}s")
    if clip.duration > SHORTS_MAX_SECONDS:
        if trim:
            log(f"Trimming to the first {SHORTS_MAX_SECONDS}s")
            clip = clip.subclipped(0, SHORTS_MAX_SECONDS)
        else:
            log(f"Longer than {SHORTS_MAX_SECONDS}s, so YouTube may treat it as a regular video")

    step("render")
    vertical = _add_logo(fit_vertical(clip), log)
    base = _safe_name(Path(original_name).stem, "video")
    out = VIDEOS_DIR / f"{base}_short_{datetime.now():%Y%m%d_%H%M%S}.mp4"
    _write(vertical, out, pct)
    duration = vertical.duration
    clip.close()
    return {"video": out.name, "title": Path(original_name).stem.replace("_", " "),
            "hashtags": ["shorts"], "duration": round(float(duration), 1)}
