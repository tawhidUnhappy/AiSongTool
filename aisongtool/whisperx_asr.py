from __future__ import annotations

import json
import os
from pathlib import Path

from .config import ToolFolders, WhisperXConfig
from .logging_utils import log
from .toolrunner import find_uv, run_cmd

def transcribe_with_whisperx(audio_path: Path, out_json_path: Path, tools: ToolFolders, cfg: WhisperXConfig, log_path: Path) -> dict:
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    log("Step 2: WhisperX transcribe + align", log_path)

    whisperx_python = os.environ.get("WHISPERX_PYTHON")
    if whisperx_python:
        # Docker mode: call worker directly with the isolated venv Python
        workers_dir = Path(__file__).resolve().parent.parent / "workers"
        cmd = [whisperx_python, str(workers_dir / "transcribe.py")]
        cwd = out_json_path.parent
    else:
        # Native mode: use uv to run worker from the whisperx env directory
        uv = find_uv()
        wdir = tools.whisperx_env_dir
        if not wdir.exists():
            raise RuntimeError(f"Missing folder: {wdir}")
        cmd = [uv, "run", "../workers/transcribe.py"]
        cwd = wdir

    cmd += [
        "--audio", str(audio_path),
        "--out", str(out_json_path),
        "--overwrite",
        "--model", cfg.model,
    ]
    if cfg.language:
        cmd += ["--language", cfg.language]
    if cfg.device:
        cmd += ["--device", cfg.device]
    if cfg.compute_type:
        cmd += ["--compute_type", cfg.compute_type]
    if cfg.batch_size is not None:
        cmd += ["--batch_size", str(cfg.batch_size)]
    if cfg.align:
        cmd += ["--align"]
    if cfg.align_model:
        cmd += ["--align_model", cfg.align_model]
    if cfg.vad:
        cmd += ["--vad", cfg.vad]

    run_cmd(cmd, cwd=cwd, log_path=log_path)

    if not out_json_path.exists():
        raise RuntimeError("whisperx.json not produced")
    return json.loads(out_json_path.read_text(encoding="utf-8", errors="ignore"))
