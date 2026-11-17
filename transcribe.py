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
            "noplaylist": True, "match_filter": yt_dlp.utils.match_filter_func("duration <? 1200")}
    log("Downloading the audio")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)
    # Use whatever file actually landed (the extension isn't always predictable).
    files = sorted((f for f in tmp.iterdir() if f.is_file() and f.stat().st_size > 0),
                   key=lambda f: f.stat().st_size, reverse=True)
    if not files:
        raise RuntimeError("the download finished but no file was saved")
    return files[0]


def _decode_pyav(path):
    """Reads the audio straight from the file in Python (no external program)."""
    import av
    import numpy as np
    chunks = []
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise RuntimeError("the video has no audio track")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def _decode_ffmpeg(path):
    import subprocess
    import numpy as np
    r = subprocess.run([_ffmpeg(), "-nostdin", "-loglevel", "error", "-i", str(path),
                        "-f", "s16le", "-ac", "1", "-ar", "16000", "-"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr.decode(errors="ignore").strip().splitlines() or ["ffmpeg failed"])[-1])
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0


def _transcribe_file(path, log, model_size="small"):
    """Decodes the audio to 16 kHz mono ourselves and hands Whisper the raw
    samples (faster-whisper's own decoder breaks with newer PyAV versions).
    Tries Python-only decoding first, then ffmpeg."""
    from faster_whisper import WhisperModel
    problems = []
    audio = None
    for decode in (_decode_pyav, _decode_ffmpeg):
        try:
            audio = decode(path)
            break
        except Exception as e:
            problems.append(f"{decode.__name__[8:]}: {str(e)[:150]}")
    if audio is None:
        raise RuntimeError("couldn’t read the audio (" + "; ".join(problems) + ")")
    if audio.size < 16000:  # under one second
        return ""
    log("Transcribing (a few minutes on a normal computer)")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio, vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments)


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
        raise RuntimeError(f"{site} doesn’t allow servers to download its videos. Save the video to your phone or PC "
                           f"and use “Upload the video” instead. [{detail}]")
    try:
        text = _transcribe_file(path, log).strip()
    except Exception as e:
        raise RuntimeError(f"The video downloaded but transcribing failed: {str(e).splitlines()[0][:180]}")
    if not text:
        raise RuntimeError("The video has no speech to transcribe (music only?). Paste a description instead.")
    return text
