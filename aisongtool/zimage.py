"""Z-Image-Turbo (https://huggingface.co/Tongyi-MAI/Z-Image-Turbo) — optional
background-image generation for the Create flow's "generate from the song's
prompt" option, installed into its own isolated `uv` env (see tools_install.py
ENV_SPECS["zimage-uv"]) the same way demucs-uv/whisperx-uv are.

Unlike ACE-Step (a persistent API server with its own multi-minute model-load
timing problems), each Z-Image generation is a one-shot subprocess that loads
the model, makes one image, saves it, and exits — no server lifecycle to
manage, just a command for `jobs.run_blocking` to run to completion.
"""
from __future__ import annotations

from pathlib import Path

from .paths import data_dir, workers_dir
from .toolrunner import venv_python


class ZImageError(RuntimeError):
    pass


def dest_dir() -> Path:
    return data_dir() / "zimage-uv"


def is_synced() -> bool:
    return venv_python(dest_dir()).exists()


def install(log=print) -> None:
    """Provision the isolated zimage-uv env (`tools_install.ENV_SPECS`) —
    same one-call shape as `ace_step.install()`, kept here so callers don't
    need to know it's just another `tools_install.ensure_env` entry."""
    from .tools_install import default_gpu_mode, ensure_env

    ensure_env("zimage-uv", default_gpu_mode(), log=log)


# Backgrounds sit behind centered lyric text, so a busy/photorealistic image
# fights for attention with the subtitles — a consistent minimalist sky/cloud
# aesthetic (think 7CLOUD album-cover style art) keeps every generated
# background calm and legible regardless of the song's own prompt. See
# desktop/src/main/tools/zimage.ts for the same suffix.
_STYLE_SUFFIX = (
    ", minimalistic red sky, soft gradient clouds, dreamy pastel sky background, "
    "7cloud album cover aesthetic"
)


def build_generate_cmd(
    prompt: str, out_path: Path, width: int = 1280, height: int = 720,
    seed: int | None = None,
) -> list[str]:
    if not is_synced():
        raise ZImageError(
            "Z-Image-Turbo isn't installed yet. Run `aisongtool install-tool z-image` "
            "(or use the Setup tab) first."
        )
    py = venv_python(dest_dir())
    cmd = [
        str(py), str(workers_dir() / "zimage_generate.py"),
        "--prompt", prompt + _STYLE_SUFFIX, "--out", str(out_path),
        "--width", str(width), "--height", str(height),
    ]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    return cmd
