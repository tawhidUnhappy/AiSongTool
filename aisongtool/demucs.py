from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import DemucsConfig, ToolFolders
from .logging_utils import log
from .paths import workers_dir as _workers_dir
from .toolrunner import run_cmd, venv_python

def find_vocals(out_dir: Path) -> Path:
    direct = out_dir / "vocals.wav"
    if direct.exists():
        return direct
    exts = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}
    for p in out_dir.rglob("*"):
        if p.is_file() and p.stem.lower() == "vocals" and p.suffix.lower() in exts:
            return p
    raise FileNotFoundError("Could not find vocals.* under output directory.")

def separate_vocals(song_path: Path, out_dir: Path, tools: ToolFolders, demucs: DemucsConfig, log_path: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    log("Step 1: Demucs separate", log_path)

    workers_dir = _workers_dir()
    demucs_python = os.environ.get("DEMUCS_PYTHON")
    if not demucs_python:
        # Native mode: use the isolated demucs-uv venv's own Python directly
        # (provisioned by `aisongtool setup`) instead of `uv run`, which would
        # re-sync the env to its CPU-default lockfile and undo the CUDA build.
        demucs_dir = tools.demucs_env_dir
        if not demucs_dir.exists():
            raise RuntimeError(f"Missing folder: {demucs_dir}. Run `aisongtool setup` first.")
        demucs_python = str(venv_python(demucs_dir))
        if not Path(demucs_python).exists():
            raise RuntimeError(f"Missing venv: {demucs_python}. Run `aisongtool setup` first.")

    cmd = [demucs_python, str(workers_dir / "demucs_separate.py"),
           str(song_path), str(out_dir), "--model", demucs.model]
    run_cmd(cmd, cwd=out_dir, log_path=log_path)

    vocals_src = find_vocals(out_dir)
    vocals_dst = out_dir / "vocals.wav"
    if vocals_src != vocals_dst:
        shutil.copyfile(vocals_src, vocals_dst)
        log(f"Copied vocals: {vocals_src} -> {vocals_dst}", log_path)
    return vocals_dst
