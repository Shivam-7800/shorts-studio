"""
Dance video: a dancer moves to the beat of a song, on a party stage.
The video is SILENT on purpose: add the same song later in the Instagram /
YouTube app ("Use audio"), which is licensed, so nothing gets muted.

Dancer: "mascot" (cartoon with moving arms and legs) or "photo" (your photo,
cut out from its background).
"""
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

W, H = 1080, 1920
FPS = 30
MAX_SECONDS = 90  # Instagram music clips and Reels-with-music limit


# =====================================================================
# MUSIC ANALYSIS: tempo, beats, energy
# =====================================================================

def analyze(samples, sr=16000):
    """samples: mono float audio. Returns beat times, bar starts and an
    energy curve (0..1) per video frame."""
    n_fft, hop = 1024, 256
    if len(samples) < n_fft * 4:
        raise RuntimeError("The sound is too short to dance to.")
    frames = np.lib.stride_tricks.sliding_window_view(samples, n_fft)[::hop]
    mag = np.abs(np.fft.rfft(frames * np.hanning(n_fft), axis=1))
    logmag = np.log1p(10 * mag)
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    diff = np.maximum(0, np.diff(logmag, axis=0))
    # Dancers follow the kick drum / bass, not the hi-hats: measure each band on
    # its own scale, then let the bass band count most.
    flux = np.zeros(len(diff))
    for lo_f, hi_f, w in ((20, 180, 0.65), (180, 2000, 0.25), (2000, 8000, 0.10)):
        band = diff[:, (freqs >= lo_f) & (freqs < hi_f)].sum(axis=1)
        flux += w * band / (np.percentile(band, 99) + 1e-9)
    onset = np.concatenate([[0], flux])
    onset -= np.convolve(onset, np.ones(16) / 16, mode="same")  # remove slow trend
    onset = np.maximum(onset, 0)
    onset /= onset.max() + 1e-9
    fps_onset = sr / hop

    # Tempo: autocorrelation, prefer around 115 BPM (most pop / Bollywood / dance)
    ac = np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    lags = np.arange(len(ac))
    bpm = 60 * fps_onset / np.maximum(lags, 1)
    valid = (bpm >= 70) & (bpm <= 180)
    weight = np.exp(-0.5 * (np.log2(np.maximum(bpm, 1) / 115) / 0.9) ** 2)
    period = int(lags[valid][np.argmax((ac * weight)[valid])])

    # Beat tracking by dynamic programming (Ellis 2007)
    n = len(onset)
    score = onset.copy()
    back = np.full(n, -1)
    lo, hi = max(1, period // 2), period * 2
    for t in range(n):
        a, b = max(0, t - hi), t - lo
        if b <= a:
            continue
        prev = np.arange(a, b)
        cand = score[prev] - 100 * (np.log((t - prev) / period)) ** 2 * 0.01
        k = int(np.argmax(cand))
        score[t] = onset[t] + cand[k]
        back[t] = prev[k]
    t = int(np.argmax(score[-period:]) + n - period)
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    # + half a window: a frame "hears" a hit about half a window after it starts
    beat_times = np.array(beats[::-1]) / fps_onset + (n_fft / 2) / sr

    # Bars: the beat phase (0..3) with the strongest onsets is the downbeat
    idx = lambda bt: np.clip(((bt - (n_fft / 2) / sr) * fps_onset).astype(int), 0, n - 1)
    strength = [onset[idx(beat_times[i::4])].sum() for i in range(4)]
    bar_starts = beat_times[int(np.argmax(strength))::4]

    # Energy per video frame: loudness smoothed over ~2 s, 0..1
    duration = len(samples) / sr
    hop_v = sr // FPS
    nv = int(duration * FPS)
    rms = np.sqrt((samples[: nv * hop_v].reshape(nv, hop_v) ** 2).mean(axis=1))
    smooth = np.convolve(rms, np.ones(FPS * 2) / (FPS * 2), mode="same")
    lo_e, hi_e = np.percentile(smooth, 10), np.percentile(smooth, 95)
    energy = np.clip((smooth - lo_e) / (hi_e - lo_e + 1e-9), 0, 1)
    tempo = 60 * fps_onset / period
    return {"tempo": round(float(tempo)), "beats": beat_times, "bars": bar_starts,
            "energy": energy, "duration": duration}


def beat_phase(t, beats):
    """(index of current beat, 0..1 progress to the next beat)."""
    i = int(np.searchsorted(beats, t, side="right") - 1)
    if i < 0:
        return -1, 0.0
    nxt = beats[i + 1] if i + 1 < len(beats) else beats[i] + (beats[i] - beats[i - 1] if i else 0.5)
    return i, min(1.0, (t - beats[i]) / max(nxt - beats[i], 1e-3))


# =====================================================================
# STAGE: gradient, rotating light beams, floor, strobe, confetti
# =====================================================================

PALETTES = [
    [(255, 64, 129), (124, 77, 255), (0, 229, 255)],
    [(255, 182, 39), (255, 87, 34), (233, 30, 99)],
    [(0, 230, 118), (41, 121, 255), (213, 0, 249)],
]


class Stage:
    def __init__(self, seed):
        rng = random.Random(seed)
        self.pal = rng.choice(PALETTES)
        self.sw, self.sh = W // 2, H // 2  # drawn at half size, then scaled up (soft light)
        base = Image.new("RGB", (self.sw, self.sh))
        d = ImageDraw.Draw(base)
        for y in range(self.sh):
            k = y / self.sh
            d.line([(0, y), (self.sw, y)], fill=(int(14 + 20 * k), int(8 + 6 * k), int(30 + 30 * k)))
        # floor
        fy = int(self.sh * 0.72)
        for i in range(-12, 13):
            d.line([(self.sw / 2 + i * 12, fy), (self.sw / 2 + i * 70, self.sh)], fill=(60, 40, 90), width=1)
        for j in range(8):
            y = fy + (self.sh - fy) * (j / 8) ** 1.6
            d.line([(0, y), (self.sw, y)], fill=(55, 35, 85), width=1)
        self.base = base
        self.confetti = [(rng.random(), rng.random(), rng.choice(self.pal), rng.uniform(0.5, 1.5)) for _ in range(70)]

    def draw(self, t, pulse, energy, drop):
        img = self.base.copy()
        beams = Image.new("RGB", (self.sw, self.sh))
        d = ImageDraw.Draw(beams)
        for k, col in enumerate(self.pal):
            for side in (-1, 1):
                ang = math.radians(90 + side * (25 + 22 * math.sin(t * (0.6 + 0.2 * k) + k)))
                x0 = self.sw * (0.2 + 0.3 * k)
                L = self.sh * 1.2
                spread = math.radians(6 + 4 * energy)
                pts = [(x0, -10), (x0 + L * math.cos(ang - spread), L * math.sin(ang - spread)),
                       (x0 + L * math.cos(ang + spread), L * math.sin(ang + spread))]
                strength = 0.25 + 0.45 * energy + 0.3 * pulse
                d.polygon(pts, fill=tuple(int(c * strength) for c in col))
        beams = beams.filter(ImageFilter.GaussianBlur(6))
        img = Image.fromarray(np.minimum(255, np.asarray(img, np.int16) + np.asarray(beams, np.int16)).astype(np.uint8))
        if drop > 0:  # confetti during big moments
            d = ImageDraw.Draw(img)
            for x, y, col, sp in self.confetti:
                yy = ((y + t * 0.25 * sp) % 1.0) * self.sh
                xx = (x * self.sw + 12 * math.sin(t * 3 * sp + x * 9)) % self.sw
                d.rectangle([xx, yy, xx + 4, yy + 7], fill=col)
        img = img.resize((W, H), Image.BILINEAR)
        if pulse > 0.05:  # strobe on the beat
            arr = np.asarray(img, np.float32) * (1 + 0.25 * pulse)
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        return img


# =====================================================================
# MASCOT: cartoon with real moving limbs
# =====================================================================

# pose = angles in degrees (0 = straight down for limbs), + body offsets
P = dict
POSES = {
    "idle":      P(ls=15, le=10, rs=-15, re=-10, lh=4, lk=0, rh=-4, rk=0, tilt=0, head=0),
    "arms_up":   P(ls=160, le=10, rs=-160, re=-10, lh=8, lk=0, rh=-8, rk=0, tilt=0, head=0),
    "clap_l":    P(ls=70, le=80, rs=-70, re=-80, lh=10, lk=20, rh=-2, rk=0, tilt=4, head=6),
    "clap_r":    P(ls=70, le=80, rs=-70, re=-80, lh=2, lk=0, rh=-10, rk=20, tilt=-4, head=-6),
    "point_ur":  P(ls=20, le=60, rs=-150, re=0, lh=6, lk=0, rh=-14, rk=10, tilt=-8, head=-10),
    "point_dl":  P(ls=40, le=0, rs=-20, re=-70, lh=14, lk=10, rh=-6, rk=0, tilt=8, head=8),
    "wave_l":    P(ls=120, le=40, rs=-30, re=-60, lh=6, lk=0, rh=-6, rk=0, tilt=6, head=8),
    "wave_r":    P(ls=30, le=60, rs=-120, re=-40, lh=6, lk=0, rh=-6, rk=0, tilt=-6, head=-8),
    "hips_l":    P(ls=40, le=110, rs=-40, re=-110, lh=12, lk=8, rh=-2, rk=0, tilt=10, head=-6),
    "hips_r":    P(ls=40, le=110, rs=-40, re=-110, lh=2, lk=0, rh=-12, rk=8, tilt=-10, head=6),
    "robot_a":   P(ls=90, le=90, rs=-10, re=-90, lh=4, lk=0, rh=-4, rk=0, tilt=0, head=12),
    "robot_b":   P(ls=10, le=90, rs=-90, re=-90, lh=4, lk=0, rh=-4, rk=0, tilt=0, head=-12),
    "jump":      P(ls=150, le=20, rs=-150, re=-20, lh=30, lk=60, rh=-30, rk=-60, tilt=0, head=0),
    "squat":     P(ls=80, le=20, rs=-80, re=-20, lh=40, lk=-70, rh=-40, rk=70, tilt=0, head=0),
}
MOVES_CALM = [["clap_l", "clap_r"], ["hips_l", "hips_r"], ["wave_l", "wave_r"], ["robot_a", "robot_b"]]
MOVES_HIGH = [["arms_up", "squat"], ["point_ur", "point_dl"], ["jump", "squat"], ["clap_l", "arms_up", "clap_r", "arms_up"]]

MASCOT_STYLES = {
    "bolt": dict(body=(255, 196, 0), limb=(255, 160, 0), pants=(90, 60, 200), skin=(255, 214, 170), cap=(124, 77, 255)),
    "mint": dict(body=(0, 214, 160), limb=(0, 180, 140), pants=(40, 40, 70), skin=(240, 200, 160), cap=(255, 64, 129)),
    "coral": dict(body=(255, 99, 99), limb=(230, 70, 80), pants=(30, 60, 140), skin=(200, 150, 110), cap=(0, 200, 255)),
}


def _ease(x):
    return 0.5 - 0.5 * math.cos(math.pi * min(max(x, 0), 1))


def _mix(a, b, k):
    return {key: a[key] + (b[key] - a[key]) * k for key in a}


class Mascot:
    S = 1.5  # drawn larger then scaled down, for smooth edges

    def __init__(self, style):
        self.c = MASCOT_STYLES.get(style, MASCOT_STYLES["bolt"])
        self.cw, self.ch = 760, 1150

    def render(self, pose, bounce, blink):
        S, c = self.S, self.c
        img = Image.new("RGBA", (int(self.cw * S), int(self.ch * S)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        hip = (self.cw / 2 * S, (self.ch * 0.58 + bounce) * S)
        tilt = math.radians(pose["tilt"])

        def at(origin, angle_deg, length):  # 0° = straight down
            a = math.radians(angle_deg) + tilt
            return origin[0] + length * S * math.sin(a), origin[1] + length * S * math.cos(a)

        def limb(p0, p1, col, wdt):
            d.line([p0, p1], fill=col, width=int(wdt * S))
            r = wdt * S / 2
            for p in (p0, p1):
                d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col)

        neck = at(hip, 180, 250)
        sh_l, sh_r = at(neck, 100, 95), at(neck, -100, 95)
        hp_l, hp_r = at(hip, 90, 50), at(hip, -90, 50)
        # legs
        for hp, h, k in ((hp_l, pose["lh"], pose["lk"]), (hp_r, pose["rh"], pose["rk"])):
            knee = at(hp, h, 150)
            foot = at(knee, h + k, 150)
            limb(hp, knee, c["pants"], 62)
            limb(knee, foot, c["pants"], 56)
            d.ellipse([foot[0] - 52 * S, foot[1] - 22 * S, foot[0] + 52 * S, foot[1] + 28 * S], fill=(250, 250, 250))
        # torso (hoodie)
        corners = [at(neck, 100, 105), at(neck, -100, 105), at(hip, -90, 80), at(hip, 90, 80)]
        d.polygon(corners, fill=c["body"])
        d.line([corners[0], corners[1]], fill=c["body"], width=int(60 * S))
        # arms
        for sh, s_ang, e_ang in ((sh_l, pose["ls"], pose["le"]), (sh_r, pose["rs"], pose["re"])):
            elbow = at(sh, s_ang, 130)
            hand = at(elbow, s_ang + e_ang, 125)
            limb(sh, elbow, c["limb"], 50)
            limb(elbow, hand, c["limb"], 44)
            r = 30 * S
            d.ellipse([hand[0] - r, hand[1] - r, hand[0] + r, hand[1] + r], fill=c["skin"])
        # head
        head_c = at(neck, 180 + pose["head"], 120)
        R = 115 * S
        d.ellipse([head_c[0] - R, head_c[1] - R, head_c[0] + R, head_c[1] + R], fill=c["skin"])
        d.chord([head_c[0] - R, head_c[1] - R * 1.05, head_c[0] + R, head_c[1] + R * 0.5], 180, 360, fill=c["cap"])
        d.rectangle([head_c[0] - R * 0.2, head_c[1] - R * 0.35, head_c[0] + R * 1.25, head_c[1] - R * 0.15], fill=c["cap"])
        ey = head_c[1] + R * 0.12
        for ex in (head_c[0] - R * 0.38, head_c[0] + R * 0.38):
            if blink:
                d.line([ex - 16 * S, ey, ex + 16 * S, ey], fill=(30, 20, 40), width=int(6 * S))
            else:
                d.ellipse([ex - 15 * S, ey - 20 * S, ex + 15 * S, ey + 20 * S], fill=(30, 20, 40))
                d.ellipse([ex - 5 * S, ey - 13 * S, ex + 4 * S, ey - 4 * S], fill=(255, 255, 255))
        d.arc([head_c[0] - R * 0.45, head_c[1] + R * 0.2, head_c[0] + R * 0.45, head_c[1] + R * 0.7], 15, 165,
              fill=(30, 20, 40), width=int(8 * S))
        return img.resize((self.cw, self.ch), Image.BICUBIC)


# =====================================================================
# PHOTO DANCER: cut-out photo that bounces, sways, hops and clones
# =====================================================================

def _mask_quality(rgba):
    """(coverage, ghostliness): how much is kept, and how much is half-transparent."""
    a = np.asarray(rgba)[..., 3].astype(np.float32) / 255
    kept = (a > 0.5).mean()
    ghost = ((a > 0.12) & (a < 0.88)).sum() / max((a > 0.12).sum(), 1)
    return kept, ghost


def _solid_edges(rgba):
    """Makes the cut-out fully solid inside with a soft 2-px edge (no see-through body)."""
    a = rgba.getchannel("A").point(lambda v: 255 if v > 110 else 0).filter(ImageFilter.GaussianBlur(1.5))
    out = rgba.copy()
    out.putalpha(a)
    return out


def cut_out(photo_path, log):
    img = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGBA")
    img.thumbnail((1400, 1400))
    out = None
    try:
        from rembg import new_session, remove
        log("Cutting the person out of the photo")
        for model in ("u2net_human_seg", "isnet-general-use"):
            candidate = remove(img, session=new_session(model))
            kept, ghost = _mask_quality(candidate)
            if 0.05 < kept < 0.95 and ghost < 0.35:
                out = _solid_edges(candidate)
                break
            log(f"The {model} cut-out looked unclear, trying another way")
    except Exception as e:
        log(f"Background removal unavailable ({str(e)[:80]})")
    if out is None:  # fall back: the whole photo with rounded corners and a white border
        log("Using the whole photo in a frame")
        framed = ImageOps.expand(img.convert("RGB"), border=18, fill=(255, 255, 255)).convert("RGBA")
        mask = Image.new("L", framed.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, framed.width - 1, framed.height - 1], 48, fill=255)
        framed.putalpha(mask)
        out = framed
    bbox = out.getbbox() or (0, 0, out.width, out.height)
    out = out.crop(bbox)
    scale = (H * 0.62) / out.height
    if out.width * scale > W * 0.9:
        scale = (W * 0.9) / out.width
    return out.resize((max(1, int(out.width * scale)), max(1, int(out.height * scale))), Image.LANCZOS)


# =====================================================================
# RENDER
# =====================================================================

def make_dance(audio_path, out_path, dancer="mascot", style="bolt", photo_path=None, log=print, pct=None):
    import transcribe  # decodes any audio/video to 16 kHz mono
    from moviepy import VideoClip

    samples = transcribe._decode_pyav(audio_path)[: 16000 * MAX_SECONDS]
    music = analyze(samples)
    duration = music["duration"]
    beats, bars, energy = music["beats"], music["bars"], music["energy"]
    log(f"Song: {music['tempo']} BPM, {len(beats)} beats, {duration:.0f} s")

    seed = int(music["tempo"] * 1000 + len(beats))
    rng = random.Random(seed)
    stage = Stage(seed)
    mascot = Mascot(style) if dancer == "mascot" else None
    cutout = cut_out(photo_path, log) if dancer == "photo" else None
    # one move per bar (4 beats), chosen by how energetic that bar is
    bar_moves = []
    for b in bars:
        e = energy[min(int(b * FPS), len(energy) - 1)]
        bar_moves.append(rng.choice(MOVES_HIGH if e > 0.6 else MOVES_CALM))
    blink_at = {int(x * FPS) for x in np.arange(2.0, duration, 3.7)}
    shadow = Image.new("RGBA", (460, 90), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([20, 20, 440, 70], fill=(0, 0, 0, 130))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))

    def frame(t):
        fi = min(int(t * FPS), len(energy) - 1)
        e = float(energy[fi])
        bi, ph = beat_phase(t, beats)
        pulse = max(0.0, 1 - ph * 4) if bi >= 0 else 0.0  # flash right on the beat
        drop = 1.0 if e > 0.75 else 0.0
        img = stage.draw(t, pulse, e, drop).convert("RGBA")
        floor_y = int(H * 0.86)

        if mascot:
            bar_i = max(0, int(np.searchsorted(bars, t, side="right") - 1))
            seq = bar_moves[bar_i] if bar_moves else ["idle"]
            step = bi % len(seq) if bi >= 0 else 0
            a, b = POSES[seq[step]], POSES[seq[(step + 1) % len(seq)]]
            pose = _mix(a, b, _ease((ph - 0.5) * 2)) if ph > 0.5 else a  # hold, then move into next pose
            amp = 0.55 + 0.45 * e
            pose = _mix(POSES["idle"], pose, amp)
            bounce = 26 * (1 - abs(math.cos(math.pi * ph))) * amp  # dip down on every beat
            if seq[step] == "jump" and ph < 0.5:
                bounce -= 120 * math.sin(math.pi * ph * 2)
            body = mascot.render(pose, bounce, fi in blink_at)
            x = (W - body.width) // 2 + int(30 * math.sin(t * math.pi * music["tempo"] / 120))
            y = floor_y - int(body.height * 0.97)
            img.alpha_composite(shadow, (x + body.width // 2 - shadow.width // 2, floor_y - shadow.height // 2))
            img.alpha_composite(body, (x, y))
        else:
            amp = 0.5 + 0.5 * e
            squash = 1 - 0.06 * amp * (1 - abs(math.cos(math.pi * ph)))
            sway = 7 * amp * math.sin(math.pi * (bi + ph) / 2) if bi >= 0 else 0
            hop = 0
            on_bar = bi >= 0 and any(abs(bt - beats[bi]) < 1e-6 for bt in bars)
            if on_bar and ph < 0.5:
                hop = int(70 * amp * math.sin(math.pi * ph * 2))
            mirror = bi >= 0 and (bi // 8) % 2 == 1 and e > 0.5
            dancer_img = ImageOps.mirror(cutout) if mirror else cutout
            dw, dh = int(dancer_img.width * (2 - squash)), int(dancer_img.height * squash)
            d2 = dancer_img.resize((dw, dh), Image.BILINEAR).rotate(sway, resample=Image.BILINEAR, expand=True)
            if drop:  # two smaller clones behind on the big parts
                small = d2.resize((int(d2.width * 0.62), int(d2.height * 0.62)), Image.BILINEAR)
                sa = np.asarray(small).copy()
                sa[..., 3] = (sa[..., 3] * 0.7).astype(np.uint8)
                small = Image.fromarray(sa)
                for sx in (-1, 1):
                    img.alpha_composite(small, (W // 2 - small.width // 2 + sx * int(W * 0.3), floor_y - small.height - hop // 2))
            img.alpha_composite(d2, (W // 2 - d2.width // 2 + int(25 * math.sin(t * 1.3)), floor_y - d2.height - hop))

        arr = np.asarray(img.convert("RGB"))
        fade = min(1.0, t / 0.5, (duration - t) / 0.7)
        if fade < 1:
            arr = (arr * max(fade, 0)).astype(np.uint8)
        return arr

    clip = VideoClip(frame, duration=duration)
    log("Rendering the dance (silent)")
    clip.write_videofile(str(out_path), fps=FPS, codec="libx264", audio=False, preset="veryfast",
                         ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", "19"],
                         logger=None if pct is None else "bar")
    return {"duration": round(float(duration), 1), "tempo": music["tempo"], "beats": len(beats)}
