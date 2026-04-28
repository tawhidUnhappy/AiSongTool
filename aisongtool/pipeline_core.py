from __future__ import annotations

from pathlib import Path

from .align import align_words, extract_whisper_words
from .config import PipelineConfig
from .cues import Cue, build_line_cues, build_segment_cues, cues_to_ass, cues_to_lrc, cues_to_sbv, cues_to_srt, cues_to_vtt
from .demucs import separate_vocals
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

    if not raw_lyrics:
        log("Step 3: No lyrics — building cues directly from transcription", log_path)
        cues: list[Cue] = []
        for seg in whisper_json.get("segments", []):
            text = (seg.get("text") or "").strip()
            st = float(seg.get("start") or 0.0)
            en = float(seg.get("end") or 0.0)
            if text and en > st:
                cues.append(Cue(start=st, end=en, text=text))
        log(f"  transcript cues:      {len(cues)}", log_path)
        (out_dir / "lyrics_clean.txt").write_text("", encoding="utf-8")
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
    }
