"""
"My voice" — speaks the script in your own voice using Chatterbox Multilingual
(Resemble AI, MIT licence, free). You record ~15 seconds once in the app.

Optional install (large: PyTorch + ~2 GB model download on first use):
    python -m pip install --user chatterbox-tts

Works in English and Hindi. A computer with an NVIDIA graphics card is much
faster; on a normal laptop CPU expect several seconds per line.
"""

import importlib.util
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = BASE_DIR / "my_voice"
SAMPLE_DIR.mkdir(exist_ok=True)
SAMPLE = SAMPLE_DIR / "sample.wav"

LANG_IDS = {"en-IN": "en", "hi-IN": "hi"}

_model = None


def installed():
    return importlib.util.find_spec("chatterbox") is not None


def has_sample():
    return SAMPLE.exists() and SAMPLE.stat().st_size > 10_000


def supports(language_code):
    return language_code in LANG_IDS


def status():
    return {"installed": installed(), "sample": has_sample(), "languages": list(LANG_IDS)}


def _ffmpeg():
    try:
        import imageio_ffmpeg  # ships with moviepy
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def save_sample(src_path):
    """Converts any recording/upload (webm, m4a, mp3, wav...) to a clean mono WAV,
    trimmed to 20 seconds."""
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-i", str(src_path),
           "-t", "20", "-ac", "1", "-ar", "24000", str(SAMPLE)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not has_sample():
        raise RuntimeError("Couldn't read that recording. Try again, speaking for at least 8 seconds.")


def _load(log):
    global _model
    if _model is not None:
        return _model
    if not installed():
        raise RuntimeError("The voice model isn't installed. Run: python -m pip install --user chatterbox-tts "
                           "then restart the app.")
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"Loading your-voice model on {'graphics card' if device == 'cuda' else 'CPU (slower)'}. "
        "The first time downloads about 2 GB.")
    try:
        _model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
    except TypeError:  # older chatterbox versions
        _model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    return _model


def synthesize(lines, language_code, audio_dir, log=print, pct=None):
    if not has_sample():
        raise RuntimeError("Record your voice sample first (Voice → My voice).")
    import torchaudio as ta
    model = _load(log)
    lang = LANG_IDS[language_code]
    paths = []
    for i, line in enumerate(lines):
        wav = model.generate(line, language_id=lang, audio_prompt_path=str(SAMPLE))
        path = Path(audio_dir) / f"line_{i}.wav"
        ta.save(str(path), wav, model.sr)
        paths.append(path)
        log(f"Spoke line {i + 1} of {len(lines)} in your voice")
        if pct:
            pct((i + 1) / len(lines))
    return paths
