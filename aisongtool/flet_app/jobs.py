"""Subprocess spawning + output streaming, shared by every view that runs an
external command (the pipeline CLI, ffmpeg, `aisongtool setup`).

Every spawned process is also assigned to this app's Windows Job Object
(see win_job.py) so it — and anything it spawns in turn — is guaranteed to
be killed if this app's own process ever exits, including a force-close
(Task Manager "End Task", `taskkill /F`, a crash), where no Python cleanup
code gets a chance to run at all."""
from __future__ import annotations

import codecs
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from . import terminal, win_job
from .state import set_current_job

OnExit = Callable[[int], None]


def _stream_to_terminal(stream) -> None:
    """Reads in raw chunks, not line-by-line — `for line in stream` only
    yields once a `\\n` arrives, so a `\\r`-only progress bar (huggingface_hub
    model downloads, tqdm, ffmpeg) that doesn't print a newline until it's
    100% done would buffer completely silently for the whole download/run,
    looking indistinguishable from a hang. Matches the read1()-loop the
    legacy `toolrunner.run_cmd` already used for the same reason.

    Decodes with a stateful incremental decoder (not a fresh `.decode()` per
    chunk) since an arbitrary 4096-byte read can land mid multi-byte UTF-8
    character — a one-shot decode would mangle it into a replacement char."""
    read_fn = getattr(stream, "read1", None) or stream.read
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while True:
        chunk = read_fn(4096)
        if not chunk:
            terminal.append(decoder.decode(b"", final=True))
            break
        terminal.append(decoder.decode(chunk))


def spawn_cli(cmd: list[str], cwd: Path | None = None, on_exit: OnExit | None = None) -> subprocess.Popen:
    """Run `cmd`, streaming combined stdout/stderr into the terminal ring
    buffer line-by-line, and report the exit code via `on_exit`.

    `on_exit` runs on a background thread. Flet's `page.update()`/
    `control.update()` are safe to call from a background thread, but views
    still poll plain state via a timer for consistency with the rest of the
    app (see flet_app/views/generate.py)."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd is not None else None, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        # Binary, not text=True: Popen's text mode hardcodes universal-newline
        # translation (collapses \r to \n) with no way to opt out, which would
        # destroy tqdm/ffmpeg-style \r-only progress updates before
        # terminal.py ever sees them. Decode manually in the pump loop instead.
    )
    win_job.assign(proc.pid)
    set_current_job(proc, cwd)
    terminal.append(f"$ (cwd={cwd}) {' '.join(cmd)}\n")

    def _pump() -> None:
        assert proc.stdout is not None
        _stream_to_terminal(proc.stdout)
        proc.wait()
        set_current_job(None, None)
        if on_exit:
            on_exit(proc.returncode or 0)

    threading.Thread(target=_pump, daemon=True).start()
    return proc


def run_blocking(cmd: list[str], cwd: Path | None = None) -> int:
    """Run `cmd` to completion on the *calling* thread — for orchestration
    code that's already running on its own background thread (see
    views/create.py) and wants each tool to fully start, run, and exit before
    the next one starts (so GPU/CPU is freed in between), rather than the
    fire-and-chain-via-on_exit style `spawn_cli` is meant for from the UI
    thread. Still takes the single-job lock and streams into the Terminal
    ring buffer, same as `spawn_cli`."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd is not None else None, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        # Binary, not text=True: Popen's text mode hardcodes universal-newline
        # translation (collapses \r to \n) with no way to opt out, which would
        # destroy tqdm/ffmpeg-style \r-only progress updates before
        # terminal.py ever sees them. Decode manually in the pump loop instead.
    )
    win_job.assign(proc.pid)
    set_current_job(proc, cwd)
    terminal.append(f"$ (cwd={cwd}) {' '.join(cmd)}\n")
    try:
        assert proc.stdout is not None
        _stream_to_terminal(proc.stdout)
        proc.wait()
        return proc.returncode or 0
    finally:
        set_current_job(None, None)


def spawn_background(cmd: list[str], cwd: Path | None = None, extra_env: dict | None = None) -> subprocess.Popen:
    """Like `spawn_cli`, but does NOT touch the single-job lock — for
    long-lived background services (the ACE-Step API server) that must keep
    running while one-shot jobs (pipeline runs, ffmpeg conversions) come and
    go independently. Still streams into the Terminal ring buffer.

    Started in its own session/process group (POSIX) so `terminate_tree` can
    reach every descendant it spawns — `uv run <entry>` and ACE-Step's own
    multiprocess model-serving workers both fork several layers deep, and a
    plain `proc.terminate()` only kills the immediate child, leaving the rest
    running and still holding the GPU."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    if extra_env:
        env.update(extra_env)

    proc = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd is not None else None, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=(sys.platform != "win32"),
    )
    win_job.assign(proc.pid)
    terminal.append(f"$ (cwd={cwd}) {' '.join(cmd)}\n")

    def _pump() -> None:
        assert proc.stdout is not None
        _stream_to_terminal(proc.stdout)

    threading.Thread(target=_pump, daemon=True).start()
    return proc


def terminate_tree(proc: subprocess.Popen, timeout: float = 15.0) -> None:
    """Kill `proc` and every process it spawned (children, grandchildren,
    ...), not just the immediate child. A plain `proc.terminate()` only
    signals the direct child — for something launched via `uv run <entry>`
    that itself forks worker processes (ACE-Step's API server spawns its LM
    engine as a separate process), that leaves the real GPU-holding process
    orphaned and running. Best-effort: swallows errors from processes that
    already exited."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=timeout)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
