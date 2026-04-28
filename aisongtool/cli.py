#!/usr/bin/env python3
"""AiSongTool CLI — run the full pipeline from the command line."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DemucsConfig, LyricsConfig, PipelineConfig, ToolFolders, WhisperXConfig
from .pipeline_core import run_pipeline


def main() -> int:
    ap = argparse.ArgumentParser(
        description="AiSongTool: Demucs + WhisperX + line-by-line lyrics subtitles",
    )
    ap.add_argument("--song", required=True, help="Path to song file (mp3/wav/m4a)")
    ap.add_argument("--lyrics", default="", help="Path to lyrics text file (omit to transcribe only)")
    ap.add_argument("--out", required=True, help="Output directory")

    ap.add_argument("--demucs_env", default="demucs-uv", help="Demucs uv environment directory")
    ap.add_argument("--whisperx_env", default="whisperx-uv", help="WhisperX uv environment directory")

    ap.add_argument("--demucs_model", default="htdemucs", help="Demucs model name")
    ap.add_argument("--whisper_model", default="large-v3", help="WhisperX model name")
    ap.add_argument("--language", default="", help="Language code, e.g. en (empty=auto)")

    ap.add_argument("--line_pad_ms", type=int, default=80, help="Padding before/after each line (ms)")
    ap.add_argument("--min_line_ms", type=int, default=350, help="Minimum subtitle duration (ms)")
    ap.add_argument("--max_gap_seconds", type=float, default=3.0, help="Max gap for unaligned lines")
    ap.add_argument("--max_chars", type=int, default=46, help="Max characters per subtitle line")
    ap.add_argument("--max_lines", type=int, default=2, help="Max lines per subtitle cue")
    ap.add_argument("--no_capcut_apostrophe_fix", action="store_true", help="Disable CapCut apostrophe fix")
    ap.add_argument("--segment_mode", action="store_true",
                    help="One subtitle cue per verse/chorus block instead of per line")
    ap.add_argument("--skip_demucs", action="store_true",
                    help="Skip vocal separation — use raw audio directly")
    ap.add_argument("--vad", default="silero", choices=["silero", "pyannote"],
                    help="VAD backend for WhisperX (default: silero)")

    args = ap.parse_args()

    cfg = PipelineConfig(
        skip_demucs=args.skip_demucs,
        tools=ToolFolders(
            demucs_env_dir=Path(args.demucs_env).resolve(),
            whisperx_env_dir=Path(args.whisperx_env).resolve(),
        ),
        demucs=DemucsConfig(model=args.demucs_model),
        whisperx=WhisperXConfig(
            model=args.whisper_model,
            language=args.language.strip() or None,
            align=True,
            vad=args.vad,
        ),
        lyrics=LyricsConfig(
            line_pad_ms=args.line_pad_ms,
            min_line_ms=args.min_line_ms,
            max_gap_seconds=args.max_gap_seconds,
            max_chars_per_line=args.max_chars,
            max_lines_per_cue=max(1, min(3, args.max_lines)),
            capcut_safe_apostrophes=(not args.no_capcut_apostrophe_fix),
            segment_mode=args.segment_mode,
        ),
    )

    lyrics_path = Path(args.lyrics).resolve() if args.lyrics.strip() else None
    run_pipeline(
        song_path=Path(args.song).resolve(),
        lyrics_path=lyrics_path,
        out_dir=Path(args.out).resolve(),
        cfg=cfg,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
