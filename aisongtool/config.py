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

@dataclass(frozen=True)
class PipelineConfig:
    tools: ToolFolders
    demucs: DemucsConfig = DemucsConfig()
    whisperx: WhisperXConfig = WhisperXConfig()
    lyrics: LyricsConfig = LyricsConfig()
    skip_demucs: bool = False
