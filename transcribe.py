"""Gets the spoken words of a video: YouTube's own captions first (fast),
then download + Whisper transcription. Used by the PC app and by GitHub."""
import re
import tempfile
from pathlib import Path


def video_id(url):
    m = re.search(r"(?:youtu\.be/|shorts/|live/|embed/|[?&]v=)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _captions(vid, log):
    from youtube_transcript_api import YouTubeTranscriptApi
    langs = ["hi", "en", "en-IN", "ta", "te", "kn", "mr", "bn", "gu"]
    try:  # youtube-transcript-api 1.x
        api = YouTubeTranscriptApi()
        try:
            snippets = api.fetch(vid, languages=langs)
        except Exception:
            snippets = next(iter(api.list(vid))).fetch()  # any language available
        return " ".join(s.text for s in snippets)
    except AttributeError:  # older 0.x versions
        return " ".join(s["text"] for s in YouTubeTranscriptApi.get_transcript(vid, languages=langs))


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil
        if shutil.which("ffmpeg"):
            return "ffmpeg"
        raise RuntimeError("ffmpeg is missing. Run: python -m pip install imageio-ffmpeg")


def _download(url, log):
    import yt_dlp
    tmp = Path(tempfile.mkdtemp())
    opts = {"format": "bestaudio/best", "outtmpl": str(tmp / "source.%(ext)s"), "quiet": True,
            "noplaylist": True, "match_filter": yt_dlp.utils.match_filter_func("duration < 1200")}
    log("Downloading the audio")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)


def _transcribe_file(path, log, model_size="small"):
    """Decodes audio with ffmpeg ourselves (16 kHz mono) and gives Whisper the
    raw samples. This avoids faster-whisper's own decoder, which breaks with
    newer versions of the PyAV library."""
    import subprocess
    import numpy as np
    from faster_whisper import WhisperModel
    raw = subprocess.run([_ffmpeg(), "-nostdin", "-loglevel", "error", "-i", str(path),
                          "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if audio.size < 16000:
        return ""
    log("Transcribing (a few minutes on a normal computer)")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio, vad_filter=True)
    return " ".join(s.text.strip() for s in segments)


def _site(url):
    u = url.lower()
    return "Instagram" if "instagram." in u else "YouTube" if ("youtu" in u) else "That site"


def get_transcript(url, log=print):
    site = _site(url)
    vid = video_id(url) if site == "YouTube" else None
    if vid:
        try:
            log("Reading YouTube’s subtitles")
            text = _captions(vid, log).strip()
            if text:
                return text
        except Exception:
            pass  # no subtitles or blocked: fall back to downloading the audio
    try:
        path = _download(url, log)
    except Exception as e:
        detail = str(e).splitlines()[0][:180]
        raise RuntimeError(f"{site} didn’t let us download this video. Big sites often block servers like GitHub, "
                           f"so use Remake in the PC app or paste the transcript. [{detail}]")
    try:
        text = _transcribe_file(path, log).strip()
    except Exception as e:
        raise RuntimeError(f"The video downloaded but transcribing failed: {str(e).splitlines()[0][:180]}")
    if not text:
        raise RuntimeError("The video has no speech to transcribe (music only?). Paste a description instead.")
    return text
