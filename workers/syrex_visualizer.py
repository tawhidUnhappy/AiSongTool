#!/usr/bin/env python3
"""Syrex-style audio-reactive visualizer — an alternative Create-flow video
template to the default static-image + subtitle render. Composites, per
frame: a panning background, bass-driven chromatic aberration, a blurred
top lyric bar (real timed cues from an .srt, not a placeholder), a
parabolic-baseline frequency spectrum drawn as stepped "tower" spikes, and
optional bottom title text — then pipes raw frames straight into ffmpeg for
muxing with the original audio.

Runs inside the isolated syrex-uv venv only (numpy/scipy/opencv/pillow, no
torch) — no `aisongtool` package imports here, matching
workers/demucs_separate.py's pattern.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH")
    return exe


def _nvenc_available(ffmpeg: str) -> bool:
    """Probes h264_nvenc with a throwaway 0.1s null-output encode — fast
    (well under a second) and run once before the (potentially many-minute)
    frame-rendering loop, rather than discovering an unusable GPU encoder
    only after the whole video has already been composited."""
    try:
        # 256x256 — below NVENC's minimum supported frame dimensions (some
        # cards reject anything under roughly 145x49), a too-small probe
        # size like 64x64 fails with "Frame Dimension less than the minimum
        # supported value" even when the encoder itself is fully usable.
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "nullsrc=s=256x256:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=15,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _build_ffmpeg_cmd(ffmpeg: str, width: int, height: int, fps: int,
                       audio_path: Path, out_path: Path, use_gpu: bool) -> list[str]:
    encode_args = (
        ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr", "-cq", "19"]
        if use_gpu
        else ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]
    )
    return [
        ffmpeg, "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}", "-pix_fmt", "bgr24", "-r", str(fps),
        "-i", "-",
        "-i", str(audio_path),
        *encode_args, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "320k",
        "-shortest",
        str(out_path),
    ]


def _to_mono_wav(audio_path: Path, out_wav: Path, sample_rate: int = 44100) -> None:
    """Converts any input audio to mono 16-bit PCM WAV — the only format
    `scipy.io.wavfile` can read, used for spectral analysis only (the
    original `audio_path` is what actually gets muxed into the output)."""
    ffmpeg = _find_ffmpeg()
    cmd = [
        ffmpeg, "-y", "-i", str(audio_path),
        "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le",
        str(out_wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio conversion failed: {proc.stderr[-2000:]}")


_SRT_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})")


def _srt_time_to_sec(s: str) -> float:
    m = _SRT_TIME_RE.search(s)
    if not m:
        raise ValueError(f"Not a valid SRT timestamp: {s!r}")
    hh, mm, ss, ms = (int(x) for x in m.groups())
    return hh * 3600 + mm * 60 + ss + ms / 1000


def parse_srt(srt_path: Path) -> list[tuple[float, float, str]]:
    """Minimal .srt parser — numbered blocks of
    `start --> end` then one or more text lines, blank-line separated.
    Good enough for the karaoke .srt this app's own pipeline produces."""
    cues: list[tuple[float, float, str]] = []
    blocks = re.split(r"\r?\n\r?\n", srt_path.read_text(encoding="utf-8").strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        # First line is the cue index (if numeric) or already the timing line.
        time_line_idx = 1 if lines[0].strip().isdigit() else 0
        if time_line_idx >= len(lines) or "-->" not in lines[time_line_idx]:
            continue
        start_s, end_s = (p.strip() for p in lines[time_line_idx].split("-->"))
        text = " ".join(lines[time_line_idx + 1:]).strip()
        if not text:
            continue
        cues.append((_srt_time_to_sec(start_s), _srt_time_to_sec(end_s), text))
    return cues


def active_cue_text(cues: list[tuple[float, float, str]], t: float) -> str:
    for start, end, text in cues:
        if start <= t < end:
            return text
        if start > t:
            break
    return ""


def extract_audio_features(audio_path: Path, fps: int = 30, n_fft: int = 2048,
                            n_bands: int = 64, f_min: float = 20, f_max: float = 8000):
    """Reads a mono 16-bit PCM WAV, performs a windowed STFT, and bins the
    linear frequency spectrum into logarithmic bands with asymmetric
    attack/release temporal smoothing (see SyrexVisualizerPythonGuide.txt
    for the derivation of every constant below)."""
    import numpy as np
    from scipy.io import wavfile
    from scipy.signal import get_window

    sample_rate, data = wavfile.read(str(audio_path))
    if data.ndim > 1:
        data = np.mean(data, axis=1)
    data = data.astype(np.float32) / 32768.0

    hop_length = max(1, int(sample_rate / fps))
    total_frames = max(1, int(len(data) / hop_length))

    bands_freq = f_min * ((f_max / f_min) ** (np.arange(n_bands + 1) / n_bands))
    fft_freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    bin_mapping = [
        np.where((fft_freqs >= bands_freq[b]) & (fft_freqs < bands_freq[b + 1]))[0]
        for b in range(n_bands)
    ]

    window = get_window("hann", n_fft)
    smoothed = np.zeros(n_bands, dtype=np.float32)
    alpha_attack, alpha_release = 0.15, 0.85

    visual_frames: list = []
    bass_history: list = []
    bass_band_limit = max(1, int(n_bands * (150.0 / f_max)))

    for m in range(total_frames):
        start = m * hop_length
        end = start + n_fft
        if end > len(data):
            chunk = np.zeros(n_fft, dtype=np.float32)
            valid = data[start:]
            chunk[: len(valid)] = valid
        else:
            chunk = data[start:end]

        fft_mag = np.abs(np.fft.rfft(chunk * window, n=n_fft))
        raw_bands = np.array(
            [np.mean(fft_mag[idx]) if len(idx) else 0.0 for idx in bin_mapping], dtype=np.float32
        )

        rising = raw_bands > smoothed
        smoothed = np.where(
            rising, alpha_attack * raw_bands + (1 - alpha_attack) * smoothed,
            alpha_release * raw_bands + (1 - alpha_release) * smoothed,
        )

        bass_history.append(float(np.mean(smoothed[:bass_band_limit])))
        visual_frames.append(smoothed.copy())

    visual_frames = np.array(visual_frames, dtype=np.float32)
    if visual_frames.max() > 0:
        visual_frames /= visual_frames.max()
    bass_history = np.array(bass_history, dtype=np.float32)
    if bass_history.max() > 0:
        bass_history /= bass_history.max()

    return visual_frames, bass_history, total_frames


class ChromaticAberration:
    """Lateral chromatic aberration — shifts red/blue channels radially
    outward/inward from frame center, scaled by bass intensity.

    Runs on the GPU via OpenCV's OpenCL backend (`cv2.UMat`) when available —
    pip's opencv-python ships OpenCL support out of the box (no CUDA build
    needed), and NVIDIA's driver exposes it. Benchmarked against this exact
    workload: naively uploading freshly-`numpy`-computed remap maps to the
    GPU every frame is *slower* than just staying on CPU (the upload cost
    eats the whole win) — the actual speedup only shows up once the constant
    per-pixel direction grids are uploaded ONCE in `__init__` and every
    per-frame map update (`x_grid + dx*shift`) is also done on-device via
    `cv2.add`/`cv2.multiply`, so the only thing crossing the PCIe bus each
    frame is the source image itself (measured ~3x over the CPU path this
    way, vs *slower* than CPU when maps are rebuilt in numpy first)."""

    def __init__(self, width: int, height: int):
        import cv2
        import numpy as np

        cx, cy = width / 2.0, height / 2.0
        x_grid, y_grid = np.meshgrid(
            np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32)
        )
        dx, dy = x_grid - cx, y_grid - cy
        r = np.sqrt(dx ** 2 + dy ** 2)
        r[r == 0] = 1.0
        dx_scaled = (dx / r * cx).astype(np.float32)
        dy_scaled = (dy / r * cy).astype(np.float32)

        self.use_gpu = cv2.ocl.haveOpenCL()
        if self.use_gpu:
            cv2.ocl.setUseOpenCL(True)
            self._x_grid = cv2.UMat(x_grid)
            self._y_grid = cv2.UMat(y_grid)
            self._dx_scaled = cv2.UMat(dx_scaled)
            self._dy_scaled = cv2.UMat(dy_scaled)
        else:
            self._x_grid = x_grid
            self._y_grid = y_grid
            self._dx_scaled = dx_scaled
            self._dy_scaled = dy_scaled

    def apply(self, image, intensity: float):
        import cv2

        if intensity < 1e-4:
            return image

        shift = 0.015 * intensity

        if self.use_gpu:
            dx_shift = cv2.multiply(self._dx_scaled, shift)
            dy_shift = cv2.multiply(self._dy_scaled, shift)
            map_x_r = cv2.add(self._x_grid, dx_shift)
            map_y_r = cv2.add(self._y_grid, dy_shift)
            map_x_b = cv2.subtract(self._x_grid, dx_shift)
            map_y_b = cv2.subtract(self._y_grid, dy_shift)
            b_chan, g_chan, r_chan = cv2.split(cv2.UMat(image))
        else:
            map_x_r = self._x_grid + self._dx_scaled * shift
            map_y_r = self._y_grid + self._dy_scaled * shift
            map_x_b = self._x_grid - self._dx_scaled * shift
            map_y_b = self._y_grid - self._dy_scaled * shift
            b_chan, g_chan, r_chan = cv2.split(image)

        # INTER_NEAREST, not INTER_LINEAR — this shift is at most a couple
        # pixels and meant to read as a subtle glitch, not a precise optical
        # simulation, so the much cheaper interpolation is not visibly
        # different but meaningfully faster across 2M pixels x2 channels.
        r_shifted = cv2.remap(r_chan, map_x_r, map_y_r, cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
        b_shifted = cv2.remap(b_chan, map_x_b, map_y_b, cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
        merged = cv2.merge([b_shifted, g_chan, r_shifted])
        return merged.get() if self.use_gpu else merged


def _font_path() -> Path:
    return Path(__file__).resolve().parent.parent / "font" / "Edo" / "edo.ttf"


class TextOverlayCache:
    """Renders centered text (Edo font, via Pillow for proper TTF support —
    cv2's built-in fonts are Hershey-stroke only) onto a small transparent
    RGBA strip and caches the last rendered (text, size) so unchanged cues
    across many consecutive frames don't get re-rasterized every frame."""

    def __init__(self, font_size: int):
        from PIL import ImageFont

        self._font = ImageFont.truetype(str(_font_path()), font_size)
        self._cache_key: tuple | None = None
        self._cache_rgba = None

    def render(self, text: str, width: int, height: int, fill=(255, 255, 255, 255),
               stroke_fill=(0, 0, 0, 255), stroke_width: int = 4):
        import numpy as np
        from PIL import Image, ImageDraw

        key = (text, width, height)
        if key == self._cache_key:
            return self._cache_rgba

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if text:
            draw = ImageDraw.Draw(img)
            bbox = draw.textbbox((0, 0), text, font=self._font, stroke_width=stroke_width)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            xy = ((width - tw) / 2 - bbox[0], (height - th) / 2 - bbox[1])
            draw.text(xy, text, font=self._font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)

        rgba = np.array(img)
        self._cache_key = key
        self._cache_rgba = rgba
        return rgba


def _alpha_composite(frame_bgr, overlay_rgba, x: int, y: int):
    """Alpha-blends an RGBA overlay (from TextOverlayCache) onto `frame_bgr`
    at top-left (x, y) — in place, region-sized rather than full-frame."""
    import numpy as np

    h, w = overlay_rgba.shape[:2]
    region = frame_bgr[y:y + h, x:x + w]
    alpha = (overlay_rgba[:, :, 3:4].astype(np.float32)) / 255.0
    overlay_bgr = overlay_rgba[:, :, [2, 1, 0]].astype(np.float32)
    region[:] = (overlay_bgr * alpha + region.astype(np.float32) * (1 - alpha)).astype(np.uint8)


# BGR — a warm amber rim-light, matching the reference "Syrex"-style
# city-skyline visualizers (a thin warm highlight catching each peak's
# edge against a dark silhouette, not a flat-color filled bar chart).
ACCENT_BGR = (60, 130, 235)
SILHOUETTE_BGR = (12, 9, 10)


class SkylineRenderer:
    """Draws the frequency spectrum as ONE continuous dark panel spanning
    the full frame width, with a glowing neon outline traced along just its
    top edge — not a row of separate gapped towers. At rest (no/low audio
    in a given band) the top edge collapses to a single smooth dome/arc —
    confirmed against a reference frame with the background removed,
    showing exactly that smooth-arc panel as the visualizer's resting
    shape — and only gets jagged/stepped where the spectrum actually has
    energy, since bars touch edge-to-edge with no gap between them.

    Geometry (the smooth per-column baseline, band-to-column mapping) only
    depends on frame size and band count, so it's precomputed once; only
    each band's quantized height changes per frame."""

    def __init__(self, width: int, height: int, n_bands: int):
        import numpy as np

        self.width = width
        self.height = height
        self.n_bands = n_bands
        # Reference frames showed dramatic, mirrored tall peaks at both
        # edges with a flat, shallow center (not bars mapped left-to-right
        # in band order) — bass dominates most music's energy, so mapping
        # band 0 (bass) to the outer edges and the highest band (treble) to
        # the center is what actually produces that look from real audio,
        # reinforced by an explicit envelope below so it holds up regardless
        # of a given song's specific spectral balance.
        self.max_bar_height = height * 0.5
        self.block_height = max(8.0, height / 70.0)
        self.arc_dip = height * 0.03
        self.base_margin = height * 0.01
        self.center_x = width / 2.0

        x = np.arange(width, dtype=np.float32)
        norm_x = (x - self.center_x) / self.center_x
        mirrored_frac = np.abs(norm_x)  # 0 at center, 1 at edges

        # Continuous baseline evaluated at every column, not just band
        # centers — this is what makes silence collapse to one smooth arc
        # instead of a flat stepped line with band-sized notches in it.
        self._y_base = (height - self.base_margin) - self.arc_dip * (1 - norm_x ** 2)

        # Twin-peak envelope, not a monotonic center->edge ramp — reference
        # frames show the tallest peaks sitting INWARD from the very edges,
        # with both the center AND the absolute corners reading as low
        # points (the corners taper back down rather than being the
        # tallest point). A Gaussian bump centered away from frac=1
        # reproduces exactly that: low at frac=0 (center) and low again at
        # frac=1 (the very edge), peaking at frac≈0.78 in between.
        peak_frac, sigma, floor = 0.78, 0.16, 0.08
        self._envelope = (floor + (1 - floor) * np.exp(-((mirrored_frac - peak_frac) ** 2) / (2 * sigma ** 2))).astype(np.float32)
        self._xs = x.astype(np.int32)
        self._mirrored_frac = mirrored_frac

        # Band b sits at mirrored_frac = 1 - b/(n_bands-1) (band 0/bass at
        # the edges, the highest band/treble at center) — `np.interp`
        # needs its sample x-coords ascending, so this is stored reversed.
        # Per-column heights are then linearly interpolated BETWEEN these
        # band samples (not bucketed flat within one band's column range)
        # and only quantized into stepped notches afterwards: a reference
        # frame showed pointed, sloped mountain-peak silhouettes with small
        # staircase notches on the *slope*, not flat-topped rectangular
        # towers — that shape only comes from interpolating a continuous
        # curve first and quantizing second, not the reverse.
        self._band_frac_asc = (1.0 - np.arange(n_bands, dtype=np.float32) / (n_bands - 1))[::-1].copy()

        # An always-present ground floor: a gentle central mound that gives
        # the song-title text a solid dark backdrop ("inside the ground at
        # center"), tapering to a thin floor at the edges. Audio peaks rise
        # ABOVE this — at the twin-peak positions the mound has already
        # decayed to the thin base floor, so it doesn't fight the peaks; in
        # the center (where audio is low by the envelope) it's the mound
        # that holds the ground up under the title.
        center_mound = height * 0.11
        base_floor = height * 0.025
        self._floor_height = (base_floor + center_mound * np.exp(-(mirrored_frac / 0.30) ** 2)).astype(np.float32)

        # Every bar lives within this row range regardless of audio (rows
        # above it never change) — confining the per-frame mask draw to just
        # this crop, instead of the full frame, keeps it affordable at 1080p.
        self._crop_top = max(0, int(self._y_base.min() - self.max_bar_height) - 20)
        self._crop_h = height - self._crop_top

        # Glow halo sigmas — a real Avee Player "Syrex"-style project file
        # (extracted from a shared .viz template) builds the soft rim-light
        # around its skyline bars from SEVERAL stacked blurred duplicates of
        # the same bars (a tight one for a crisp rim, a wide one for ambient
        # bleed), composited under a final crisp top layer — not a single
        # blur pass. Two Gaussian sigmas approximate that same multi-radius
        # falloff cheaply (full per-pixel layer duplication isn't needed,
        # just the resulting falloff shape).
        self._glow_sigma_tight = max(2.0, height * 0.006)
        self._glow_sigma_wide = max(6.0, height * 0.022)

    def draw(self, frame, frame_bands, glow_intensity: float = 0.4):
        import cv2
        import numpy as np

        # Interpolate the raw per-band amplitude across every column FIRST
        # (smooth sloped curve between band sample points), then convert to
        # height and quantize SECOND — quantizing per-band first (as a flat
        # bucketed value across that band's whole column range) is what
        # produced flat-topped rectangular towers instead of sloped peaks.
        amp_per_col = np.interp(self._mirrored_frac, self._band_frac_asc, frame_bands[::-1])
        # Audio rides ON TOP of the always-present floor mound (added, not
        # max'd) — so the center keeps its jagged bar texture sitting on the
        # title pedestal rather than collapsing to a smooth featureless dome,
        # and the edge peaks rise from the thin edge floor. Quantize the
        # combined height so the staircase notches cover the mound too.
        height_per_col = amp_per_col * self.max_bar_height * self._envelope + self._floor_height
        steps_per_col = (height_per_col / self.block_height).astype(np.int32)
        col_height = steps_per_col * self.block_height

        top_y = self._y_base - col_height - self._crop_top
        np.clip(top_y, 0, self._crop_h - 1, out=top_y)
        top_edge = np.column_stack([self._xs, top_y.astype(np.int32)])

        mask = np.zeros((self._crop_h, self.width), dtype=np.uint8)
        poly = np.vstack([[[0, self._crop_h - 1]], top_edge, [[self.width - 1, self._crop_h - 1]]])
        cv2.fillPoly(mask, [poly], 255)

        region = frame[self._crop_top:, :]

        # Soft amber glow halo, bled outward from the mask edge by two
        # blur radii (tight rim + wide ambient) and blended additively
        # before the crisp silhouette is drawn on top — the crisp draw
        # below overwrites the glow everywhere INSIDE the mask, leaving
        # only the outward bleed visible as a halo around each peak. The
        # colored neon edge itself is chromatic-aberration fringe, applied
        # to the whole frame AFTER this draw (see the render loop), not
        # drawn here.
        #
        # Blurred at 1/4 scale, not full-res — a full-res GaussianBlur with
        # a large auto-sized kernel (the wide-sigma pass needs a ~140px
        # kernel at 1080p) measured at ~180ms/frame, by far the dominant
        # cost in the whole render loop. Downsampling first shrinks both the
        # pixel count AND the required kernel size by the same factor, so
        # the blur itself gets ~16x cheaper for a softness difference that's
        # imperceptible once upsampled back (standard "fast bloom" trick).
        ds = 4
        small_w, small_h = max(1, self.width // ds), max(1, self._crop_h // ds)
        mask_small = cv2.resize(mask, (small_w, small_h), interpolation=cv2.INTER_AREA).astype(np.float32) * (1.0 / 255.0)
        glow_tight = cv2.GaussianBlur(mask_small, (0, 0), sigmaX=self._glow_sigma_tight / ds)
        glow_wide = cv2.GaussianBlur(mask_small, (0, 0), sigmaX=self._glow_sigma_wide / ds)
        glow_small = np.clip(glow_tight * 0.6 + glow_wide * 0.4, 0.0, 1.0)
        glow_alpha = cv2.resize(glow_small, (self.width, self._crop_h), interpolation=cv2.INTER_LINEAR) * glow_intensity
        glow_alpha = glow_alpha[:, :, None]
        accent = np.array(ACCENT_BGR, dtype=np.float32)
        region[:] = (region.astype(np.float32) * (1 - glow_alpha) + accent * glow_alpha).astype(np.uint8)

        # Just a flat dark silhouette on top of the glow.
        region[mask > 0] = SILHOUETTE_BGR


def render_visualizer_video(audio_path: Path, bg_path: Path, out_path: Path,
                             srt_path: Path | None = None, title: str = "",
                             fps: int = 30, width: int = 1920, height: int = 1080) -> None:
    import numpy as np
    import cv2

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "analysis.wav"
        print("[syrex] converting audio for analysis...", flush=True)
        _to_mono_wav(audio_path, wav_path)

        print("[syrex] extracting audio features (FFT/log-bands)...", flush=True)
        # n_bands=96, not the default 64 — a reference frame showed a much
        # denser skyline texture (many narrow peaks) than 64 wide columns
        # produce at 1080p.
        bands_data, bass_history, total_frames = extract_audio_features(wav_path, fps=fps, n_bands=96)

    cues = parse_srt(srt_path) if srt_path is not None and srt_path.exists() else []

    bg_img = cv2.imread(str(bg_path))
    if bg_img is None:
        raise FileNotFoundError(f"Could not load background image: {bg_path}")
    bg_img = cv2.resize(bg_img, (width, height), interpolation=cv2.INTER_CUBIC)
    bg_tiled = np.hstack([bg_img, bg_img])

    ffmpeg = _find_ffmpeg()
    use_gpu = _nvenc_available(ffmpeg)
    print(f"[syrex] encoding with {'GPU (h264_nvenc)' if use_gpu else 'CPU (libx264)'}...", flush=True)
    ffmpeg_cmd = _build_ffmpeg_cmd(ffmpeg, width, height, fps, audio_path, out_path, use_gpu)
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, bufsize=10 ** 8)

    n_bands = bands_data.shape[1]
    skyline = SkylineRenderer(width, height, n_bands)
    aberration = ChromaticAberration(width, height)

    # Lyric text near the top — no background box/blur bar, just outlined
    # text directly over the (panning, aberrated) image, matching the
    # reference templates rather than the original guide's blurred strip.
    lyric_h = int(height * 0.12)
    lyric_overlay = TextOverlayCache(font_size=int(height * 0.045))

    # Song info is two stacked lines (reference: artist small/dim on top,
    # song title big/bold below — "SOLEN" / "RUDE"). Split on " - "/" — ";
    # a single-part title just renders as the big bottom line with no artist.
    artist_text, song_text = "", title
    for sep in (" — ", " - "):
        if sep in title:
            artist_text, song_text = (p.strip() for p in title.split(sep, 1))
            break
    artist_overlay = TextOverlayCache(font_size=int(height * 0.028)) if (title and artist_text) else None
    song_overlay = TextOverlayCache(font_size=int(height * 0.05)) if title else None

    # Precomputed once: a soft dark gradient over the bottom ~16% of the
    # frame, strongest at the very bottom — legibility for the title text
    # sitting inside the (now much thinner, panel-sized) skyline strip.
    vignette_h = int(height * 0.16)
    vignette_alpha = (np.linspace(0, 0.85, vignette_h, dtype=np.float32) ** 1.5)[:, None, None]

    pan_x, pan_speed = 0.0, max(1.0, width / 1600.0)

    print(f"[syrex] rendering {total_frames} frames...", flush=True)
    for idx in range(total_frames):
        pan_x = (pan_x + pan_speed) % width
        x_start = int(pan_x)
        frame = bg_tiled[:, x_start:x_start + width].copy()

        t = idx / fps
        current_bass = float(bass_history[idx]) if idx < len(bass_history) else 0.0

        vignette_region = frame[height - vignette_h:, :]
        vignette_region[:] = (vignette_region.astype(np.float32) * (1 - vignette_alpha)).astype(np.uint8)

        # Draw the dark skyline FIRST, then aberration over the whole frame
        # — that's what gives the bar edges the cyan/orange neon fringe seen
        # in the reference (it's chromatic aberration on the silhouette, not
        # a drawn outline). A small constant baseline keeps the fringe subtly
        # present even in quiet sections, scaling up on bass hits.
        skyline.draw(frame, bands_data[idx], glow_intensity=min(1.0, 0.25 + 0.6 * current_bass))
        frame = aberration.apply(frame, min(1.0, 0.25 + 0.85 * current_bass))

        # Text is drawn AFTER aberration so it stays crisp (no color fringe
        # on the lyrics/title).
        if cues:
            text = active_cue_text(cues, t)
            overlay = lyric_overlay.render(text, width, lyric_h, stroke_width=3)
            _alpha_composite(frame, overlay, 0, int(height * 0.03))
            # Thin guide-line separator under the lyrics — a layout element,
            # not a blur box (the original guide's blurred strip was the
            # part that needed to go, not this line on its own).
            line_y = int(height * 0.095)
            cv2.line(frame, (0, line_y), (width, line_y), (255, 255, 255), 1, cv2.LINE_AA)

        # Two-line song info sitting inside the central ground mound.
        if song_overlay is not None:
            song_h = int(height * 0.085)
            song_y = height - song_h - int(height * 0.02)
            overlay = song_overlay.render(song_text, width, song_h, stroke_width=3)
            _alpha_composite(frame, overlay, 0, song_y)
            if artist_overlay is not None:
                artist_h = int(height * 0.05)
                overlay = artist_overlay.render(
                    artist_text, width, artist_h, fill=(210, 210, 210, 255), stroke_width=2
                )
                _alpha_composite(frame, overlay, 0, song_y - artist_h + int(height * 0.012))

        proc.stdin.write(frame.tobytes())
        if idx % 100 == 0:
            sys.stdout.write(f"\r[syrex] encoding {idx}/{total_frames} ({idx / total_frames * 100:.1f}%)")
            sys.stdout.flush()

    sys.stdout.write("\n[syrex] finalizing video container...\n")
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0 or not out_path.exists():
        hint = (
            " (GPU encode failed mid-render — possibly out of VRAM if another tool is using the GPU; "
            "the next run will still try GPU first, since the pre-flight probe passed)"
            if use_gpu else ""
        )
        raise RuntimeError(f"ffmpeg muxing failed (exit {proc.returncode}){hint}")
    print(f"[syrex] done -> {out_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, required=True)
    ap.add_argument("--background", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--srt", type=Path, default=None)
    ap.add_argument("--title", default="")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        render_visualizer_video(
            args.audio.expanduser().resolve(),
            args.background.expanduser().resolve(),
            args.out.expanduser().resolve(),
            srt_path=args.srt.expanduser().resolve() if args.srt else None,
            title=args.title,
            fps=args.fps, width=args.width, height=args.height,
        )
        return 0
    except Exception as exc:
        print(f"\n[syrex] ERROR: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
