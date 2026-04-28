from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_APOS_IN_WORD = re.compile(r"(?<=\w)'(?=\w)")
_PUNCT_END = re.compile(r"[,.!?;:]+$")

STOPWORDS = {
    "a","an","the","and","or","but","so","to","of","in","on","at","for","with","from","by","as",
    "that","this","these","those","it","its","i","you","we","they","he","she","me","my","your","our","their",
}

def capcut_safe_text(s: str) -> str:
    return _APOS_IN_WORD.sub("’", s)

def sec_to_srt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    if ms < 0:
        ms = 0
    s = ms // 1000
    ms = ms % 1000
    hh = s // 3600
    mm = (s % 3600) // 60
    ss = s % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

def sec_to_vtt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    if ms < 0:
        ms = 0
    s = ms // 1000
    ms = ms % 1000
    hh = s // 3600
    mm = (s % 3600) // 60
    ss = s % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"

def sec_to_ass_ts(t: float) -> str:
    cs = int(round(t * 100))
    if cs < 0:
        cs = 0
    s = cs // 100
    cs = cs % 100
    hh = s // 3600
    mm = (s % 3600) // 60
    ss = s % 60
    return f"{hh}:{mm:02d}:{ss:02d}.{cs:02d}"

def _norm_word_for_wrap(w: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", w.lower())

def wrap_natural(text: str, max_len: int = 46, max_lines: int = 2) -> list[str]:
    text = capcut_safe_text(text).strip()
    words = text.split()
    if not words:
        return [""]
    full = " ".join(words)
    if len(full) <= max_len or max_lines <= 1:
        return [full]

    best = None
    for i in range(1, len(words)):
        l1 = " ".join(words[:i])
        l2 = " ".join(words[i:])
        if len(l1) > max_len or len(l2) > max_len:
            continue

        score = abs(len(l1) - len(l2))
        if _PUNCT_END.search(words[i-1]):
            score -= 18

        w2 = _norm_word_for_wrap(words[i])
        if w2 in STOPWORDS:
            score += 20

        w1 = _norm_word_for_wrap(words[i-1])
        if w1 in STOPWORDS:
            score += 12

        if len(words[i:]) == 1:
            score += 1000

        if len(l1) < len(l2):
            score += 3

        if best is None or score < best[0]:
            best = (score, l1, l2)

    if best is not None:
        return [best[1], best[2]]

    line1 = ""
    i = 0
    while i < len(words):
        cand = (line1 + " " + words[i]).strip()
        if len(cand) <= max_len:
            line1 = cand
            i += 1
        else:
            break
    rest = " ".join(words[i:]).strip()
    return [line1] if not rest else [line1, rest]

@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str

def _clamp_duration(st: float, en: float, min_ms: int) -> tuple[float, float]:
    if en <= st:
        en = st + (min_ms / 1000.0)
    else:
        min_s = min_ms / 1000.0
        if (en - st) < min_s:
            en = st + min_s
    return st, en

def _pad(st: float, en: float, pad_ms: int) -> tuple[float, float]:
    pad = pad_ms / 1000.0
    return max(0.0, st - pad), en + pad

def build_line_cues(
    lyric_lines_text: list[str],
    line_word_ranges: list[tuple[int, int]],
    whisper_words,
    pairs,
    *,
    pad_ms: int = 80,
    min_line_ms: int = 350,
    max_gap_seconds: float = 3.0,
) -> list[Cue]:
    lyric_to_time: dict[int, tuple[float, float]] = {}
    for li, wi in pairs:
        if li is None or wi is None:
            continue
        lyric_to_time[li] = (whisper_words[wi].start, whisper_words[wi].end)

    aligned_indices = sorted(lyric_to_time.keys())

    def nearest_prev_time(idx: int):
        for k in reversed(aligned_indices):
            if k < idx:
                return lyric_to_time[k]
        return None

    def nearest_next_time(idx: int):
        for k in aligned_indices:
            if k > idx:
                return lyric_to_time[k]
        return None

    cues: list[Cue] = []
    for line_i, (a, b) in enumerate(line_word_ranges):
        text = lyric_lines_text[line_i].strip()
        if not text:
            continue

        times = [lyric_to_time[i] for i in range(a, b) if i in lyric_to_time]
        if times:
            st = min(t[0] for t in times)
            en = max(t[1] for t in times)
        else:
            prev_t = nearest_prev_time(a)
            next_t = nearest_next_time(b - 1)
            if prev_t and next_t:
                st = prev_t[1]
                en = next_t[0]
                if (en - st) > max_gap_seconds:
                    en = st + max_gap_seconds
            elif prev_t:
                st = prev_t[1]
                en = st + (min_line_ms / 1000.0)
            elif next_t:
                en = next_t[0]
                st = max(0.0, en - (min_line_ms / 1000.0))
            else:
                st = 0.0
                en = min_line_ms / 1000.0

        st, en = _pad(st, en, pad_ms)
        st, en = _clamp_duration(st, en, min_line_ms)
        cues.append(Cue(st, en, text))

    fixed: list[Cue] = []
    last_end = 0.0
    for c in cues:
        st = max(c.start, 0.0)
        en = max(c.end, st + 0.05)
        if st < last_end:
            st = last_end
            en = max(en, st + 0.05)
        fixed.append(Cue(st, en, c.text))
        last_end = en
    return fixed

def build_segment_cues(
    line_cues: list[Cue],
    seg_line_ranges: list[tuple[int, int]],
) -> list[Cue]:
    """
    Merge line-level cues into segment cues.
    seg_line_ranges[i] = (first_line_idx, last_line_idx_exclusive) for segment i.
    Text is joined with \\n so output functions can split on it.
    """
    merged: list[Cue] = []
    for a, b in seg_line_ranges:
        group = line_cues[a:b]
        if not group:
            continue
        st = min(c.start for c in group)
        en = max(c.end for c in group)
        text = "\n".join(c.text for c in group)
        merged.append(Cue(st, en, text))
    return merged


def _display_lines(text: str, max_chars: int, max_lines: int, capcut_safe: bool) -> list[str]:
    """Return display lines for a cue text. Preserves \\n-separated lines for segment mode."""
    t = capcut_safe_text(text) if capcut_safe else text.strip()
    if "\n" in t:
        return [ln.strip() for ln in t.split("\n") if ln.strip()]
    return wrap_natural(t, max_len=max_chars, max_lines=max_lines)


def cues_to_srt(cues: Iterable[Cue], max_chars: int = 46, capcut_safe: bool = True, max_lines: int = 2) -> str:
    out_lines: list[str] = []
    for i, c in enumerate(cues, start=1):
        lines = _display_lines(c.text, max_chars, max_lines, capcut_safe)
        out_lines.append(str(i))
        out_lines.append(f"{sec_to_srt_ts(c.start)} --> {sec_to_srt_ts(c.end)}")
        out_lines.extend(lines)
        out_lines.append("")
    return "\n".join(out_lines).rstrip() + "\n"


def cues_to_vtt(cues: Iterable[Cue], max_chars: int = 46, capcut_safe: bool = True, max_lines: int = 2) -> str:
    out = ["WEBVTT", ""]
    for c in cues:
        lines = _display_lines(c.text, max_chars, max_lines, capcut_safe)
        out.append(f"{sec_to_vtt_ts(c.start)} --> {sec_to_vtt_ts(c.end)}")
        out.extend(lines)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def cues_to_ass(cues: Iterable[Cue], max_chars: int = 46, capcut_safe: bool = True, max_lines: int = 2) -> str:
    header = [
        "[Script Info]",
        "Title: AiSongTool Export",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.601",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,35,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    out = header[:]
    for c in cues:
        lines = _display_lines(c.text, max_chars, max_lines, capcut_safe)
        ass_text = r"\N".join(lines)
        out.append(f"Dialogue: 0,{sec_to_ass_ts(c.start)},{sec_to_ass_ts(c.end)},Default,,0,0,0,,{ass_text}")
    return "\n".join(out).rstrip() + "\n"


def cues_to_lrc(cues: Iterable[Cue], capcut_safe: bool = True) -> str:
    # LRC is inherently one line per timestamp.
    # For segment cues (multi-line text), emit each lyric line at the segment start time.
    out: list[str] = []
    for c in cues:
        t = capcut_safe_text(c.text) if capcut_safe else c.text.strip()
        mm = int(c.start // 60)
        ss = c.start - mm * 60
        ts = f"[{mm:02d}:{ss:05.2f}]"
        for ln in t.split("\n"):
            ln = ln.strip()
            if ln:
                out.append(f"{ts}{ln}")
    return "\n".join(out).rstrip() + "\n"


def cues_to_sbv(cues: Iterable[Cue], max_chars: int = 46, capcut_safe: bool = True, max_lines: int = 2) -> str:
    """YouTube SubViewer (.sbv) format — upload directly to YouTube Studio."""
    def _ts(t: float) -> str:
        ms = int(round(t * 1000))
        h = ms // 3_600_000; ms %= 3_600_000
        m = ms // 60_000;    ms %= 60_000
        s = ms // 1_000;     ms %= 1_000
        return f"{h}:{m:02d}:{s:02d}.{ms:03d}"

    out: list[str] = []
    for c in cues:
        lines = _display_lines(c.text, max_chars, max_lines, capcut_safe)
        out.append(f"{_ts(c.start)},{_ts(c.end)}")
        out.extend(lines)
        out.append("")
    return "\n".join(out).rstrip() + "\n"
