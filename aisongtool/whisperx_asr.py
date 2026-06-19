from __future__ import annotations

import json
import os
from pathlib import Path

from .config import ToolFolders, WhisperXConfig
from .logging_utils import log
from .paths import workers_dir as _workers_dir
from .toolrunner import run_cmd, venv_python

def transcribe_with_whisperx(audio_path: Path, out_json_path: Path, tools: ToolFolders, cfg: WhisperXConfig, log_path: Path) -> dict:
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    log("Step 2: WhisperX transcribe + align", log_path)

    workers_dir = _workers_dir()
    whisperx_python = os.environ.get("WHISPERX_PYTHON")
    if not whisperx_python:
        # Native mode: use the isolated whisperx-uv venv's own Python directly
        # (provisioned by `aisongtool setup`) instead of `uv run`, which would
        # re-sync the env to its CPU-default lockfile and undo the CUDA build.
        wdir = tools.whisperx_env_dir
        if not wdir.exists():
            raise RuntimeError(f"Missing folder: {wdir}. Run `aisongtool setup` first.")
        whisperx_python = str(venv_python(wdir))
        if not Path(whisperx_python).exists():
            raise RuntimeError(f"Missing venv: {whisperx_python}. Run `aisongtool setup` first.")

    cmd = [whisperx_python, str(workers_dir / "transcribe.py")]
    cwd = out_json_path.parent

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
