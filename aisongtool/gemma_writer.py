"""Gemma 4 (google/gemma-4-E4B-it) — writes a song style caption, lyrics, and
an image-generation prompt from one short user description, for the Create
flow's "Let Gemma 4 write everything" option. Same isolated-env + one-shot
worker-script shape as zimage.py — no server lifecycle, just a command for
`jobs.run_blocking` to run to completion.
"""
from __future__ import annotations

import json
from pathlib import Path

from .paths import data_dir, workers_dir
from .toolrunner import venv_python


class GemmaWriterError(RuntimeError):
    pass


def dest_dir() -> Path:
    return data_dir() / "gemma-uv"


def is_synced() -> bool:
    return venv_python(dest_dir()).exists()


def install(log=print) -> None:
    """Provision the isolated gemma-uv env (`tools_install.ENV_SPECS`) — same
    one-call shape as `zimage.install()`."""
    from .tools_install import default_gpu_mode, ensure_env

    ensure_env("gemma-uv", default_gpu_mode(), log=log)


def build_write_cmd(prompt: str, out_json: Path) -> list[str]:
    return _build_mode_cmd(prompt, out_json, "full")


def build_write_image_prompt_cmd(prompt: str, out_json: Path) -> list[str]:
    """Same worker script, `--mode image_prompt` — for flows that want
    Gemma's help with just the background image, without writing song
    name/style/lyrics too."""
    return _build_mode_cmd(prompt, out_json, "image_prompt")


def build_detect_language_cmd(lyrics: str, out_json: Path) -> list[str]:
    """Same worker script, `--mode detect_language` — `lyrics` should be the
    literal lyrics text (not a description). Used instead of leaving
    vocal_language on "Auto" and letting acestep.cpp guess from the caption
    alone, which has been observed picking a wrong language entirely."""
    return _build_mode_cmd(lyrics, out_json, "detect_language")


def _selected_model() -> str:
    """Reads the same `desktop-settings.json` the Electron app's Setup view
    writes — single shared source of truth, see ace_step.py's
    `_desktop_settings()` for the same pattern."""
    import json
    settings_path = data_dir() / "desktop-settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    return settings.get("gemmaModel", "google/gemma-4-E4B-it")


def _build_mode_cmd(prompt: str, out_json: Path, mode: str) -> list[str]:
    if not is_synced():
        raise GemmaWriterError(
            "Gemma 4 isn't installed yet. Run `aisongtool install-tool gemma` "
            "(or use the Setup tab) first."
        )
    py = venv_python(dest_dir())
    return [
        str(py), str(workers_dir() / "gemma_write.py"),
        "--prompt", prompt, "--out", str(out_json), "--mode", mode,
        "--model", _selected_model(),
    ]


def read_result(out_json: Path) -> dict:
    """Validates the worker's JSON output has the keys the Create flow
    needs — raises GemmaWriterError with a clear message otherwise, rather
    than letting a malformed/missing field surface as a confusing KeyError
    deep in the orchestration code."""
    if not out_json.exists():
        raise GemmaWriterError("Gemma did not produce an output file.")
    data = json.loads(out_json.read_text(encoding="utf-8"))
    missing = [k for k in ("song_name", "song_style", "lyrics", "image_prompt") if not data.get(k)]
    if missing:
        raise GemmaWriterError(f"Gemma's output is missing: {', '.join(missing)}")
    return data


def read_detect_language_result(out_json: Path) -> str:
    if not out_json.exists():
        raise GemmaWriterError("Gemma did not produce an output file.")
    data = json.loads(out_json.read_text(encoding="utf-8"))
    if not data.get("language"):
        raise GemmaWriterError("Gemma's output is missing: language")
    return data["language"]


def build_gui_cmd(port: int = 7862) -> list[str]:
    """`gemma_gradio.py` — a standalone Gradio UI that loads the model once
    and serves repeated writes, the same shape as Z-Image's/ACE-Step's own
    GUI entry points."""
    if not is_synced():
        raise GemmaWriterError("Gemma 4 isn't installed yet. Install it from the Setup view first.")
    py = venv_python(dest_dir())
    return [str(py), str(workers_dir() / "gemma_gradio.py"), "--port", str(port)]


def read_image_prompt_result(out_json: Path) -> str:
    if not out_json.exists():
        raise GemmaWriterError("Gemma did not produce an output file.")
    data = json.loads(out_json.read_text(encoding="utf-8"))
    if not data.get("image_prompt"):
        raise GemmaWriterError("Gemma's output is missing: image_prompt")
    return data["image_prompt"]
