"""Lyric-video ASS generation (plain centered captions, no per-word
karaoke sweep) + retiming for the nightcore speed-up.

`cues_to_karaoke_ass` takes whatever `Cue` list the caller already built
(via `cues.build_line_cues` for the lyrics-aligned path, or built directly
from WhisperX segments for the transcript-only path — see
`pipeline_core.run_pipeline`) — it doesn't need its own word-level timing
since there's no per-word highlight to time anymore, just each line's own
start/end.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .cues import Cue, capcut_safe_text, sec_to_ass_ts

_ASS_TS_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})\.(\d{2})$")
_DIALOGUE_RE = re.compile(r"^(Dialogue:\s*\d+,)([^,]+),([^,]+),(.*)$")
_KF_RE = re.compile(r"\\kf(\d+)")


def _ass_ts_to_sec(ts: str) -> float:
    m = _ASS_TS_RE.match(ts.strip())
    if not m:
        raise ValueError(f"Not a valid ASS timestamp: {ts!r}")
    hh, mm, ss, cs = (int(g) for g in m.groups())
    return hh * 3600 + mm * 60 + ss + cs / 100


# Plain (non-karaoke) palette: one static colour, no per-word sweep.
# Centered (Alignment=5, mid-center) in the bundled Edo font (font/Edo/
# edo.ttf, registered via ffmpeg's `ass` filter `fontsdir` — see video.py —
# not a system font install).
_KARAOKE_HEADER = [
    "[Script Info]",
    "Title: AiSongTool Lyrics Export",
    "ScriptType: v4.00+",
    "WrapStyle: 0",
    "ScaledBorderAndShadow: yes",
    "YCbCr Matrix: TV.601",
    "PlayResX: 1920",
    "PlayResY: 1080",
    "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    "Style: Karaoke,Edo,96,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,1,0,1,3,1,5,80,80,90,1",
    "",
    "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
]


def cues_to_karaoke_ass(line_cues: Iterable[Cue]) -> str:
    """One Dialogue event per line, plain static text — no `\\kf` per-word
    sweep, just each cue's own start/end and text as-is.

    Line-mode cues only — segment-mode cues (multi-line `\\n`-joined text)
    don't map to one display line each, so the video feature requires
    `segment_mode=False` lyrics.
    """
    out = _KARAOKE_HEADER[:]
    for cue in line_cues:
        text = cue.text.strip()
        if not text:
            continue
        out.append(
            f"Dialogue: 0,{sec_to_ass_ts(cue.start)},{sec_to_ass_ts(cue.end)},Karaoke,,0,0,0,,{capcut_safe_text(text)}"
        )
    return "\n".join(out).rstrip() + "\n"


def retime_karaoke_ass(in_path: Path, out_path: Path, speed: float) -> Path:
    """Shrink every timestamp (and any `\\kf` sweep duration, if present) in a
    karaoke.ass by `speed`, so the lyrics stay in sync after the audio itself
    has been sped up by the same factor (see nightcore.py's asetrate trick).
    An exact linear transform (dividing every timestamp by the same constant
    factor), not an approximation — pure text transform, doesn't touch the
    original generation/transcription path."""
    out_lines = []
    for line in in_path.read_text(encoding="utf-8").splitlines():
        m = _DIALOGUE_RE.match(line)
        if not m:
            out_lines.append(line)
            continue
        prefix, start_ts, end_ts, rest = m.groups()
        new_start = sec_to_ass_ts(_ass_ts_to_sec(start_ts) / speed)
        new_end = sec_to_ass_ts(_ass_ts_to_sec(end_ts) / speed)
        new_rest = _KF_RE.sub(lambda km: f"\\kf{max(1, round(int(km.group(1)) / speed))}", rest)
        out_lines.append(f"{prefix}{new_start},{new_end},{new_rest}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")
    return out_path
