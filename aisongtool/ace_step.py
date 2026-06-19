"""ACE-Step-1.5 (https://github.com/ACE-Step/ACE-Step-1.5) — optional music
generation tool, installed into its own isolated `uv` project (clone + `uv
sync`) so its large, fast-moving dependency set (vLLM, diffusers,
transformers, its own pinned CUDA torch builds) never touches AiSongTool's
main env or the demucs-uv/whisperx-uv envs.

Unlike demucs-uv/whisperx-uv (where we author pyproject.toml ourselves and
force-reinstall a CUDA torch build after sync — see tools_install.py),
ACE-Step ships its own pyproject.toml with platform-specific torch markers
already baked in, so a plain `uv sync` picks the right CUDA build on its own.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .paths import data_dir
from .toolrunner import find_uv

LogFn = Callable[[str], None]

REPO_URL = "https://github.com/ACE-Step/ACE-Step-1.5"
DIR_NAME = "ace-step"

# [project.scripts] entries in ACE-Step's own pyproject.toml.
ENTRY_POINTS = {
    "app": "acestep",              # Gradio web UI
    "api": "acestep-api",          # REST API server
    "download": "acestep-download",  # pre-download model checkpoints
    "openrouter": "acestep-openrouter",
}


class AceStepError(RuntimeError):
    pass


def dest_dir() -> Path:
    return data_dir() / DIR_NAME


def is_cloned() -> bool:
    d = dest_dir()
    return (d / ".git").exists() and (d / "pyproject.toml").exists()


def is_synced() -> bool:
    from .toolrunner import venv_python
    return is_cloned() and venv_python(dest_dir()).exists()


def install(log: LogFn = print, update: bool = False) -> Path:
    """Clone (or update) ACE-Step-1.5 and `uv sync` its own isolated env."""
    if not shutil.which("git"):
        raise AceStepError("git not found on PATH. Required to clone ACE-Step-1.5.")
    try:
        uv = find_uv()
    except RuntimeError as exc:
        raise AceStepError(str(exc)) from exc

    dest = dest_dir()
    dest.parent.mkdir(parents=True, exist_ok=True)

    if is_cloned():
        if update:
            log(f"Updating existing ACE-Step-1.5 clone at {dest}...")
            _run(["git", "-C", str(dest), "fetch", "--all", "--tags"], log)
            _run(["git", "-C", str(dest), "pull", "--ff-only"], log)
        else:
            log(f"ACE-Step-1.5 already cloned at {dest} (pass update=True to pull latest).")
    else:
        log(f"Cloning ACE-Step-1.5 into {dest}...")
        _run(["git", "clone", REPO_URL, str(dest)], log)

    log(f"$ uv sync (cwd={dest}) — this installs ACE-Step's own torch/vLLM/diffusers stack")
    _run([uv, "sync"], log, cwd=dest)
    log("ACE-Step-1.5 ready.")
    return dest


def _run(cmd: list[str], log: LogFn, cwd: Path | None = None) -> None:
    log("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        raise AceStepError(f"command failed (exit {proc.returncode}): {' '.join(cmd)}")


def build_run_cmd(entry: str, extra_args: list[str] | None = None) -> list[str]:
    """`uv run <entry-point>` inside the ace-step env — used both for the
    blocking CLI launch and for streaming into the web app's Terminal tab."""
    if entry not in ENTRY_POINTS:
        raise AceStepError(f"unknown ACE-Step entry point '{entry}'. Known: {', '.join(ENTRY_POINTS)}")
    if not is_cloned():
        raise AceStepError("ACE-Step-1.5 is not installed yet. Run `aisongtool install-tool ace-step` first.")
    uv = find_uv()
    return [uv, "run", ENTRY_POINTS[entry], *(extra_args or [])]


def launch_blocking(entry: str, extra_args: list[str] | None = None) -> int:
    """Run an ACE-Step entry point in the foreground, inheriting stdio — for
    the gradio UI / API server, which block until the user stops them."""
    cmd = build_run_cmd(entry, extra_args)
    proc = subprocess.run(cmd, cwd=str(dest_dir()))
    return proc.returncode
