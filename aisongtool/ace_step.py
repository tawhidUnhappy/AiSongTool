"""ACE-Step music generation — via acestep.cpp
(https://github.com/ServeurpersoCom/acestep.cpp), a portable C++17/GGML port
of ACE-Step-1.5. Prebuilt Windows binaries + GGUF-quantized models
(~4.2GB total) are downloaded directly into `acestep-cpp/` — no git clone,
no `uv sync`, no separate Python/CUDA torch stack of its own (unlike the
original diffusers/vLLM-based ACE-Step-1.5, which this replaces: that one
needed ~11GB of checkpoints and its own isolated uv env).

This module only builds the install plan and the server launch command —
the actual HTTP job protocol (`/lm`, `/synth`) lives in `ace_step_api.py`,
matching the split between this module and `ace_step_api.py` before.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Callable

from .paths import data_dir

LogFn = Callable[[str], None]

DIR_NAME = "acestep-cpp"

# Defaults mirror desktop/src/main/settings.ts's DEFAULT_SETTINGS — picked to
# fit comfortably in 12GB VRAM while maximizing quality (acestep.cpp loads
# one component at a time, never all simultaneously, so peak VRAM is bounded
# by the single largest component, not the sum). DiT defaults to *turbo*
# (8-step, distilled), not *sft* (50-step full diffusion) — the sft variant
# produced glitchy audio in practice, plausibly more numerical drift over 50
# steps in a GGUF-quantized reimplementation than an 8-step distilled model.
_DEFAULT_LM_MODEL = "acestep-5Hz-lm-4B-Q8_0.gguf"
_DEFAULT_DIT_MODEL = "acestep-v15-xl-turbo-Q8_0.gguf"

BIN_FILES = [
    "ace-server.exe",
    "ace-lm.exe",
    "ace-synth.exe",
    "ggml.dll",
    "ggml-base.dll",
    "ggml-cuda.dll",
    "ggml-cpu-alderlake.dll",
    "ggml-cpu-cannonlake.dll",
    "ggml-cpu-cascadelake.dll",
    "ggml-cpu-haswell.dll",
    "ggml-cpu-icelake.dll",
    "ggml-cpu-sandybridge.dll",
    "ggml-cpu-skylakex.dll",
    "ggml-cpu-sse42.dll",
    "ggml-cpu-x64.dll",
]

# Only one published choice each (Q8_0 embedding, BF16 VAE — no quantized
# VAE variant exists), so these aren't user-selectable like LM/DiT are — see
# desktop/src/main/tools/ace-step.ts's LM_MODEL_OPTIONS/DIT_MODEL_OPTIONS for
# the curated set of LM/DiT variants offered in the Setup view.
_FIXED_FILES = {
    "embedding": "Qwen3-Embedding-0.6B-Q8_0.gguf",
    "vae": "vae-BF16.gguf",
}

BINARIES_BASE = "https://www.serveurperso.com/temp/acestep.cpp-win64/build/Release"
MODELS_BASE = "https://www.serveurperso.com/temp/acestep.cpp-win64/models"


class AceStepError(RuntimeError):
    pass


def dest_dir() -> Path:
    return data_dir() / DIR_NAME


def bin_dir() -> Path:
    return dest_dir() / "bin"


def models_dir() -> Path:
    return dest_dir() / "models"


def server_exe() -> Path:
    return bin_dir() / "ace-server.exe"


def _desktop_settings() -> dict:
    """Reads the same `desktop-settings.json` the Electron app's Setup view
    writes (settings.ts) — single shared source of truth for which model
    variant is currently selected, rather than each side tracking its own
    copy. Falls back to the defaults if the file is missing/malformed (e.g.
    the Electron app has never been run)."""
    settings_path = data_dir() / "desktop-settings.json"
    try:
        return json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def selected_model_files() -> dict:
    settings = _desktop_settings()
    return {
        "lm": settings.get("aceStepLmModel", _DEFAULT_LM_MODEL),
        "dit": settings.get("aceStepDitModel", _DEFAULT_DIT_MODEL),
        **_FIXED_FILES,
    }


def is_cloned() -> bool:
    """Binaries downloaded (name kept from the old git-clone-based
    implementation so `doctor()`/the Electron Setup view don't need their
    field names updated)."""
    d = bin_dir()
    return all((d / f).exists() for f in BIN_FILES)


def is_synced() -> bool:
    """Binaries + the currently-selected LM/DiT + the fixed embedding/VAE
    all present — ready to run."""
    if not is_cloned():
        return False
    d = models_dir()
    return all((d / f).exists() for f in selected_model_files().values())


def _download_plan() -> list[tuple[str, Path]]:
    plan: list[tuple[str, Path]] = []
    for f in BIN_FILES:
        dest = bin_dir() / f
        if not dest.exists():
            plan.append((f"{BINARIES_BASE}/{f}", dest))
    for f in selected_model_files().values():
        dest = models_dir() / f
        if not dest.exists():
            plan.append((f"{MODELS_BASE}/{f}", dest))
    return plan


def _download(url: str, dest: Path, log: LogFn) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        log(f"Downloading {dest.name}{f' ({total / 1024 / 1024:.1f}MB)' if total else ''}...")
        written = 0
        last_logged_mb = 0
        with open(tmp, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                written_mb = written // (25 * 1024 * 1024)
                if written_mb != last_logged_mb:
                    last_logged_mb = written_mb
                    pct = f" ({written / total * 100:.0f}%)" if total else ""
                    log(f"  {dest.name}: {written / 1024 / 1024:.1f}MB{pct}")
    tmp.replace(dest)
    log(f"  {dest.name}: done ({written / 1024 / 1024:.1f}MB).")


def install(log: LogFn = print, update: bool = False) -> Path:  # noqa: ARG001 - `update` kept for CLI compat
    """Download every missing acestep.cpp binary/model file."""
    plan = _download_plan()
    if not plan:
        log("ACE-Step (acestep.cpp) already installed.")
        return dest_dir()
    log(f"Installing ACE-Step (acestep.cpp) — {len(plan)} file(s) to fetch.")
    for url, dest in plan:
        _download(url, dest, log)
    log("ACE-Step (acestep.cpp) ready.")
    return dest_dir()


def build_server_cmd(host: str = "127.0.0.1", port: int = 8080) -> list[str]:
    if not is_synced():
        raise AceStepError("ACE-Step (acestep.cpp) is not installed yet. Run `aisongtool install-tool ace-step` first.")
    return [str(server_exe()), "--models", str(models_dir()), "--host", host, "--port", str(port)]


def launch_blocking() -> int:
    """Run the server in the foreground, inheriting stdio — blocks until
    stopped (Ctrl+C)."""
    import subprocess

    cmd = build_server_cmd()
    proc = subprocess.run(cmd, cwd=str(bin_dir()))
    return proc.returncode
