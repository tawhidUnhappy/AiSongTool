"""Per-word lyric timing + karaoke-style ASS generation, for the lyric-video feature.

Builds on the same word alignment data `pipeline_core.run_pipeline` already
produces (`align.extract_whisper_words` + `align.align_words`) — no changes to
the alignment step itself, just a finer-grained view of its output than
`cues.build_line_cues` exposes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .align import WWord
from .cues import Cue, capcut_safe_text, sec_to_ass_ts


@dataclass(frozen=True)
class WordTiming:
    word: str
    start: float
    end: float


def _fill_line_words(
    words_in_line: list[tuple[int, str]],
    lyric_to_time: dict[int, tuple[float, float]],
    cue_start: float,
    cue_end: float,
) -> list[WordTiming]:
    """Time every word in a line, using aligned words as anchors and spreading
    any unaligned words evenly across the gap to the next anchor (or to the
    line's end, if there is no next anchor)."""
    timings: list[WordTiming] = []
    i = 0
    cursor = cue_start
    n = len(words_in_line)
    while i < n:
        idx, word = words_in_line[i]
        if idx in lyric_to_time:
            st, en = lyric_to_time[idx]
            st = max(st, cursor)
            en = max(en, st + 0.05)
            timings.append(WordTiming(word, st, en))
            cursor = en
            i += 1
            continue

        j = i
        while j < n and words_in_line[j][0] not in lyric_to_time:
            j += 1
        next_start = lyric_to_time[words_in_line[j][0]][0] if j < n else cue_end

        gap_words = j - i
        seg_dur = max(0.05 * gap_words, next_start - cursor)
        step = seg_dur / gap_words
        for k in range(gap_words):
            st = cursor + k * step
            en = cursor + (k + 1) * step
            timings.append(WordTiming(words_in_line[i + k][1], st, en))
        cursor += seg_dur
        i = j
    return timings


def build_word_cues(
    lyrics_words: list[str],
    line_word_ranges: list[tuple[int, int]],
    line_cues: list[Cue],
    whisper_words: list[WWord],
    pairs: list[tuple[int | None, int | None]],
) -> list[list[WordTiming]]:
    """Returns, per line cue, the list of (word, start, end) actually displayed."""
    lyric_to_time: dict[int, tuple[float, float]] = {}
    for li, wi in pairs:
        if li is None or wi is None:
            continue
        lyric_to_time[li] = (whisper_words[wi].start, whisper_words[wi].end)

    result: list[list[WordTiming]] = []
    for line_i, (a, b) in enumerate(line_word_ranges):
        if line_i >= len(line_cues):
            result.append([])
            continue
        cue = line_cues[line_i]
        words_in_line = [(i, lyrics_words[i]) for i in range(a, b)]
        if not words_in_line:
            result.append([])
            continue
        result.append(_fill_line_words(words_in_line, lyric_to_time, cue.start, cue.end))
    return result


# Karaoke palette: PrimaryColour = not-yet-sung, SecondaryColour = highlight
# sweep colour while a word is being sung. ASS colours are &HAABBGGRR.
_KARAOKE_HEADER = [
    "[Script Info]",
    "Title: AiSongTool Karaoke Export",
    "ScriptType: v4.00+",
    "WrapStyle: 0",
    "ScaledBorderAndShadow: yes",
    "YCbCr Matrix: TV.601",
    "PlayResX: 1920",
    "PlayResY: 1080",
    "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    "Style: Karaoke,Arial Black,72,&H00FFFFFF,&H0000D7FF,&H00101010,&H80000000,1,0,0,0,100,100,1,0,1,3,1,2,80,80,90,1",
    "",
    "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
]


def cues_to_karaoke_ass(line_cues: Iterable[Cue], word_cues: list[list[WordTiming]]) -> str:
    """One Dialogue event per line, with `\\kf` tags driving the per-word sweep.

    Line-mode cues only — segment-mode cues (multi-line `\\n`-joined text) don't
    have a clean per-display-line word mapping, so the video feature requires
    `segment_mode=False` lyrics.
    """
    out = _KARAOKE_HEADER[:]
    for cue, words in zip(line_cues, word_cues):
        if not words:
            continue
        parts = []
        for w in words:
            dur_cs = max(1, round((w.end - w.start) * 100))
            parts.append(f"{{\\kf{dur_cs}}}{capcut_safe_text(w.word)} ")
        text = "".join(parts).rstrip()
        out.append(f"Dialogue: 0,{sec_to_ass_ts(cue.start)},{sec_to_ass_ts(cue.end)},Karaoke,,0,0,0,,{text}")
    return "\n".join(out).rstrip() + "\n"
