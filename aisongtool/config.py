from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ToolFolders:
    demucs_env_dir: Path
    whisperx_env_dir: Path

@dataclass(frozen=True)
class DemucsConfig:
    model: str = "htdemucs"
    # Random-shift ensembling (demucs.apply.apply_model's `shifts` param) —
    # 0 = a single pass (fast, today's default). Each extra shift re-runs
    # separation on a small random time-shift of the audio and averages the
    # results, which measurably improves vocal isolation on a heavily
    # blended mix at a proportional cost in compute time (shifts=N is ~N+1x
    # slower than shifts=0).
    shifts: int = 0

@dataclass(frozen=True)
class WhisperXConfig:
    model: str = "large-v3"
    language: str | None = None
    device: str | None = None
    compute_type: str | None = None
    batch_size: int | None = None
    align: bool = True
    align_model: str | None = None
    vad: str = "silero"

@dataclass(frozen=True)
class LyricsConfig:
    line_pad_ms: int = 80
    min_line_ms: int = 350
    max_gap_seconds: float = 3.0
    max_chars_per_line: int = 46
    capcut_safe_apostrophes: bool = True
    max_lines_per_cue: int = 2
    segment_mode: bool = False
    # "auto": use provided lyrics if any, else fall back to the raw WhisperX
    # transcript (today's behavior). "transcript": always use the transcript,
    # ignoring any provided lyrics — more reliable when a song skips, repeats,
    # or otherwise deviates from the literal lyrics text, since aligning
    # mismatched lyrics against the wrong audio produces wrong timing.
    # "lyrics": force the lyrics-alignment path (same as "auto" when lyrics
    # are actually provided).
    caption_source: str = "auto"

@dataclass(frozen=True)
class PipelineConfig:
    tools: ToolFolders
    demucs: DemucsConfig = DemucsConfig()
    whisperx: WhisperXConfig = WhisperXConfig()
    lyrics: LyricsConfig = LyricsConfig()
    skip_demucs: bool = False
