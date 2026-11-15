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


def _whisper(url, log):
    import yt_dlp
    from faster_whisper import WhisperModel
    tmp = Path(tempfile.mkdtemp())
    opts = {"format": "bestaudio/best", "outtmpl": str(tmp / "source.%(ext)s"), "quiet": True,
            "noplaylist": True, "match_filter": yt_dlp.utils.match_filter_func("duration < 1200")}
    log("Downloading the audio")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
    log("Transcribing (a few minutes on a normal computer)")
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(path, vad_filter=True)
    return " ".join(s.text.strip() for s in segments)


def get_transcript(url, log=print):
    problems = []
    vid = video_id(url)
    if vid:
        try:
            log("Reading YouTube’s subtitles")
            text = _captions(vid, log).strip()
            if text:
                return text
        except Exception as e:
            problems.append(f"subtitles: {str(e).splitlines()[0][:160]}")
    try:
        text = _whisper(url, log).strip()
        if text:
            return text
        problems.append("no speech found in the video")
    except Exception as e:
        problems.append(f"download: {str(e).splitlines()[0][:160]}")
    raise RuntimeError(
        "YouTube didn’t let us read this video (it often blocks GitHub’s servers). "
        "Paste the transcript in the box instead, or use Remake in the PC app. "
        f"[{'; '.join(problems)}]")
