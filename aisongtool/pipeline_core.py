from __future__ import annotations

from pathlib import Path

from .align import align_words, extract_whisper_words
from .config import PipelineConfig
from .cues import (
    _PUNCT_END,
    _norm_word_for_wrap,
    Cue,
    STOPWORDS,
    build_line_cues,
    build_segment_cues,
    cues_to_ass,
    cues_to_lrc,
    cues_to_sbv,
    cues_to_srt,
    cues_to_vtt,
)
from .demucs import separate_vocals
from .karaoke import cues_to_karaoke_ass
from .logging_utils import log
from .lyrics import build_lyric_lines, build_lyric_segments
from .whisperx_asr import transcribe_with_whisperx


def _flatten_lines(lyric_lines):
    lyrics_words: list[str] = []
    ranges: list[tuple[int, int]] = []
    line_texts: list[str] = []
    cur = 0
    for ll in lyric_lines:
        line_texts.append(ll.text)
        start = cur
        lyrics_words.extend(ll.words)
        cur = len(lyrics_words)
        ranges.append((start, cur))
    return lyrics_words, ranges, line_texts


def _flatten_segments(segments):
    """Flatten segments into lines, also return per-segment line index ranges."""
    all_lines = [ll for seg in segments for ll in seg]
    lyrics_words, ranges, line_texts = _flatten_lines(all_lines)
    seg_line_ranges: list[tuple[int, int]] = []
    cur = 0
    for seg in segments:
        seg_line_ranges.append((cur, cur + len(seg)))
        cur += len(seg)
    return lyrics_words, ranges, line_texts, seg_line_ranges


# How long a pause between two words has to be, within one Whisper segment,
# to treat it as a line break — Whisper's own segmenter sometimes merges a
# whole continuous vocal run (a verse with no big enough pause for its VAD to
# split on) into one "segment" spanning 20-30+ seconds and a dozen lyric
# lines; treating that as a single subtitle cue is unusable for a video.
_TRANSCRIPT_LINE_GAP_SECONDS = 0.6


def _group_words_by_gap(words: list[dict]) -> list[list[dict]]:
    """Splits a word list at real acoustic pauses (>_TRANSCRIPT_LINE_GAP_SECONDS
    between consecutive words) — these are genuine pauses/breaths, always
    honored as a line boundary regardless of how short the resulting group is."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    prev_end: float | None = None
    for w in words:
        token = (w.get("word") or "").strip()
        if not token:
            continue
        w_start = float(w.get("start") or (prev_end if prev_end is not None else 0.0))
        gap = (w_start - prev_end) if prev_end is not None else 0.0
        if cur and gap > _TRANSCRIPT_LINE_GAP_SECONDS:
            groups.append(cur)
            cur = []
        cur.append(w)
        prev_end = float(w.get("end") or w_start)
    if cur:
        groups.append(cur)
    return groups


def _best_word_split(words: list[dict], max_chars: int) -> int | None:
    """Picks the best index to split `words` in two so each side reads as a
    plausible line — same scoring `cues.wrap_natural` uses for display
    wrapping (prefer breaking right after punctuation, avoid stopwords on
    either side of the cut, avoid balance reasons, never leave a 1-word
    orphan unless it's actually clause-final). Returns None if no split
    point is needed or none is viable."""
    tokens = [(w.get("word") or "").strip() for w in words]
    full = " ".join(tokens)
    if len(full) <= max_chars or len(tokens) < 2:
        return None

    best: tuple[float, int] | None = None
    for i in range(1, len(tokens)):
        l1 = " ".join(tokens[:i])
        l2 = " ".join(tokens[i:])
        score = abs(len(l1) - len(l2))
        if _PUNCT_END.search(tokens[i - 1]):
            score -= 25
        if _norm_word_for_wrap(tokens[i]) in STOPWORDS:
            score += 20
        if _norm_word_for_wrap(tokens[i - 1]) in STOPWORDS:
            score += 12
        # A lone leftover word only reads as a meaningful line on its own if
        # it actually ends a clause — otherwise it's a meaningless fragment
        # ("...into the" / "the" on its own line), so penalize heavily.
        if len(tokens) - i == 1 and not _PUNCT_END.search(tokens[i - 1]):
            score += 1000
        if i == 1 and not _PUNCT_END.search(tokens[0]):
            score += 1000
        if len(l1) > max_chars or len(l2) > max_chars:
            score += 200
        if best is None or score < best[0]:
            best = (score, i)
    return best[1] if best is not None else None


def _wrap_words(words: list[dict], max_chars: int) -> list[list[dict]]:
    """Recursively splits an over-long, gap-delimited word run into shorter
    chunks at the best available point, until every chunk fits `max_chars`
    (or no viable split remains)."""
    full = " ".join((w.get("word") or "").strip() for w in words)
    if len(full) <= max_chars or len(words) < 2:
        return [words]
    i = _best_word_split(words, max_chars)
    if i is None or i <= 0 or i >= len(words):
        return [words]
    return _wrap_words(words[:i], max_chars) + _wrap_words(words[i:], max_chars)


def _split_segment_into_lines(seg: dict, max_chars: int) -> list[tuple[float, float, str]]:
    """Breaks one Whisper segment into shorter (start, end, text) chunks
    using its own word-level timestamps: first at real pauses
    (`_group_words_by_gap`), then — for any resulting group that's still too
    long to read as one line — at the most natural-sounding point within it
    (`_wrap_words`), so a forced split never lands mid-clause or leaves a
    meaningless one-word fragment on its own line. Falls back to the
    segment's own text/boundaries verbatim if it has no word-level data
    (alignment failed for it)."""
    words = seg.get("words")
    if not isinstance(words, list) or not words:
        text = (seg.get("text") or "").strip()
        st = float(seg.get("start") or 0.0)
        en = float(seg.get("end") or 0.0)
        return [(st, en, text)] if text else []

    chunks: list[tuple[float, float, str]] = []
    for group in _group_words_by_gap(words):
        for chunk in _wrap_words(group, max_chars):
            text = " ".join((w.get("word") or "").strip() for w in chunk).strip()
            if not text:
                continue
            st = float(chunk[0].get("start") or 0.0)
            en = float(chunk[-1].get("end") or st)
            chunks.append((st, en, text))
    return chunks


def run_pipeline(song_path: Path, lyrics_path: Path, out_dir: Path, cfg: PipelineConfig) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "pipeline.log"
    log_path.write_text("", encoding="utf-8")

    log(f"Song:   {song_path}", log_path)
    log(f"Lyrics: {lyrics_path}", log_path)
    log(f"Out:    {out_dir}", log_path)

    if cfg.skip_demucs:
        log("Step 1: Demucs skipped — using raw audio", log_path)
        vocals_wav = song_path
    else:
        vocals_wav = separate_vocals(song_path, out_dir, cfg.tools, cfg.demucs, log_path)

    whisper_json_path = out_dir / "whisperx.json"
    whisper_json = transcribe_with_whisperx(vocals_wav, whisper_json_path, cfg.tools, cfg.whisperx, log_path)

    raw_lyrics = lyrics_path.read_text(encoding="utf-8", errors="ignore").strip() if lyrics_path and lyrics_path.exists() else ""
    karaoke_ass_path: Path | None = None

    # "transcript" always wins regardless of whether lyrics were provided —
    # the point is robustness against a song that skips/repeats lines vs the
    # literal lyrics text, where aligning mismatched text to the wrong audio
    # produces wrong timing. "auto" (default) only falls back to it when no
    # lyrics were given at all, matching prior behavior.
    use_transcript = cfg.lyrics.caption_source == "transcript" or (
        cfg.lyrics.caption_source == "auto" and not raw_lyrics
    )

    if use_transcript:
        log("Step 3: Building cues directly from the WhisperX transcript", log_path)
        cues: list[Cue] = []
        for seg in whisper_json.get("segments", []):
            # Whisper's own segment start/end are loose VAD-chunk boundaries
            # (often padded with a second or more of silence) and a single
            # segment can span a whole continuous verse with no internal line
            # breaks at all — split on each segment's own word-level
            # timestamps instead, both for tight per-line timing and to avoid
            # one giant multi-line cue covering 20-30+ seconds.
            for st, en, text in _split_segment_into_lines(seg, max_chars=cfg.lyrics.max_chars_per_line):
                if en > st and text:
                    cues.append(Cue(st, en, text))
        log(f"  transcript cues:      {len(cues)}", log_path)
        (out_dir / "lyrics_clean.txt").write_text("", encoding="utf-8")
        if not cfg.lyrics.segment_mode:
            karaoke_ass_path = out_dir / "karaoke.ass"
            karaoke_ass_path.write_text(cues_to_karaoke_ass(cues), encoding="utf-8")
    else:
        seg_line_ranges: list[tuple[int, int]] | None = None
        if cfg.lyrics.segment_mode:
            segments = build_lyric_segments(raw_lyrics)
            lyric_lines = [ll for seg in segments for ll in seg]
            lyrics_words, line_ranges, line_texts, seg_line_ranges = _flatten_segments(segments)
            log(f"  segments detected:    {len(segments)}", log_path)
        else:
            lyric_lines = build_lyric_lines(raw_lyrics)
            lyrics_words, line_ranges, line_texts = _flatten_lines(lyric_lines)

        (out_dir / "lyrics_clean.txt").write_text("\n".join(ll.text for ll in lyric_lines), encoding="utf-8")
        (out_dir / "lyrics_words_flat.txt").write_text(" ".join(lyrics_words), encoding="utf-8")

        whisper_words = extract_whisper_words(whisper_json)
        log("Step 3: Prepare alignment", log_path)
        log(f"  lyric lines:          {len(lyric_lines)}", log_path)
        log(f"  cleaned lyrics words: {len(lyrics_words)}", log_path)
        log(f"  whisper words:        {len(whisper_words)}", log_path)

        log("Step 4: DP align (lyrics ↔ whisper words)", log_path)
        pairs = align_words(lyrics_words, whisper_words)

        log("Step 5: Build cues", log_path)
        line_cues = build_line_cues(
            lyric_lines_text=line_texts,
            line_word_ranges=line_ranges,
            whisper_words=whisper_words,
            pairs=pairs,
            pad_ms=cfg.lyrics.line_pad_ms,
            min_line_ms=cfg.lyrics.min_line_ms,
            max_gap_seconds=cfg.lyrics.max_gap_seconds,
        )

        if seg_line_ranges is not None:
            cues = build_segment_cues(line_cues, seg_line_ranges)
            log(f"  segment cues:         {len(cues)}", log_path)
        else:
            cues = line_cues
            karaoke_ass_path = out_dir / "karaoke.ass"
            karaoke_ass_path.write_text(cues_to_karaoke_ass(line_cues), encoding="utf-8")

    max_chars = cfg.lyrics.max_chars_per_line
    max_lines = cfg.lyrics.max_lines_per_cue
    capcut = cfg.lyrics.capcut_safe_apostrophes

    srt = cues_to_srt(cues, max_chars=max_chars, capcut_safe=capcut, max_lines=max_lines)
    vtt = cues_to_vtt(cues, max_chars=max_chars, capcut_safe=capcut, max_lines=max_lines)
    ass = cues_to_ass(cues, max_chars=max_chars, capcut_safe=capcut, max_lines=max_lines)
    lrc = cues_to_lrc(cues, capcut_safe=capcut)
    sbv = cues_to_sbv(cues, max_chars=max_chars, capcut_safe=capcut, max_lines=max_lines)

    p_srt = out_dir / "final.srt"
    p_vtt = out_dir / "final.vtt"
    p_ass = out_dir / "final.ass"
    p_lrc = out_dir / "final.lrc"
    p_sbv = out_dir / "final.sbv"

    p_srt.write_text(srt, encoding="utf-8")
    p_vtt.write_text(vtt, encoding="utf-8")
    p_ass.write_text(ass, encoding="utf-8")
    p_lrc.write_text(lrc, encoding="utf-8")
    p_sbv.write_text(sbv, encoding="utf-8")

    (out_dir / f"{song_path.stem}.srt").write_text(srt, encoding="utf-8")

    log("DONE", log_path)
    return {
        "srt": p_srt,
        "vtt": p_vtt,
        "ass": p_ass,
        "lrc": p_lrc,
        "sbv": p_sbv,
        "lyrics": out_dir / "lyrics_clean.txt",
        "log": log_path,
        "whisper_json": whisper_json_path,
        "karaoke_ass": karaoke_ass_path,
    }
