"""The "Syrex" video template — an audio-reactive visualizer (curved
baseline, tower-shaped frequency spikes, panning background, bass-driven
chromatic aberration) as an alternative to the Create flow's default
static-image + subtitle template. Installed into its own isolated `uv` env
(pure CPU: numpy/scipy/opencv/pillow, no torch) the same way
demucs-uv/whisperx-uv are — see tools_install.ENV_SPECS["syrex-uv"].

One-shot subprocess like zimage.py — no server lifecycle, just a command
for `jobs.run_blocking` to run to completion.
"""
from __future__ import annotations

from pathlib import Path

from .paths import data_dir, workers_dir
from .toolrunner import venv_python


class SyrexError(RuntimeError):
    pass


def dest_dir() -> Path:
    return data_dir() / "syrex-uv"


def is_synced() -> bool:
    return venv_python(dest_dir()).exists()


def install(log=print) -> None:
    """Provision the isolated syrex-uv env — CPU-only, no GPU mode to pick
    (see tools_install.ensure_env's `spec.get("cuda_index")` guard)."""
    from .tools_install import ensure_env

    ensure_env("syrex-uv", "cpu", log=log)


def build_render_cmd(
    audio_path: Path,
    background_path: Path,
    out_path: Path,
    srt_path: Path | None = None,
    title: str = "",
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> list[str]:
    if not is_synced():
        raise SyrexError(
            "The Syrex visualizer isn't installed yet. Run `aisongtool install-tool syrex` "
            "(or use the Setup tab) first."
        )
    py = venv_python(dest_dir())
    cmd = [
        str(py), str(workers_dir() / "syrex_visualizer.py"),
        "--audio", str(audio_path),
        "--background", str(background_path),
        "--out", str(out_path),
        "--width", str(width),
        "--height", str(height),
        "--fps", str(fps),
    ]
    if srt_path is not None:
        cmd += ["--srt", str(srt_path)]
    if title:
        cmd += ["--title", title]
    return cmd
