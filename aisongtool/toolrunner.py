from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .logging_utils import log


def find_uv() -> str:
    uv = shutil.which("uv")
    if uv:
        return uv
    home = Path.home()
    for c in [
        home / ".cargo" / "bin" / "uv.exe",
        home / ".cargo" / "bin" / "uv",
        home / ".local" / "bin" / "uv.exe",
        home / ".local" / "bin" / "uv.EXE",
    ]:
        if c.exists():
            return str(c)
    raise RuntimeError("uv not found. Ensure `uv --version` works.")


def run_cmd(cmd: list[str], cwd: Path, log_path: Path) -> None:
    """Run a command and stream output live to console, pipeline.log, and the
    WebUI live-log terminal.

    On Linux/Docker the subprocess is spawned inside a PTY so that tools like
    tqdm detect a real terminal and emit \\r (in-place) progress updates rather
    than \\n (one new line per frame).  On Windows we fall back to a regular
    pipe because pty is unavailable there.
    """
    log(f"$ (cwd={cwd}) " + " ".join(cmd), log_path)

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLUMNS", "120")
    env.setdefault("LINES", "50")

    live_log_path = env.get("AISONGTOOL_LIVE_LOG")
    live_bin = None
    if live_log_path:
        try:
            Path(live_log_path).parent.mkdir(parents=True, exist_ok=True)
            live_bin = open(live_log_path, "ab", buffering=0)
        except Exception:
            live_bin = None

    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write(chunk: bytes, fbin) -> None:
        try:
            if hasattr(sys.stdout, "buffer"):
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            else:
                sys.stdout.write(chunk.decode("utf-8", errors="replace"))
                sys.stdout.flush()
        except Exception:
            pass
        try:
            fbin.write(chunk)
        except Exception:
            pass
        if live_bin is not None:
            try:
                live_bin.write(chunk)
            except Exception:
                pass

    with open(log_path, "ab", buffering=0) as fbin:
        if sys.platform != "win32":
            # ── Linux / Docker: use a PTY ─────────────────────────────────────
            # Spawning inside a PTY makes the child think stdout is a real
            # terminal, so tqdm writes \r updates in-place instead of \n.
            import pty
            import select as _sel

            master_fd, slave_fd = pty.openpty()
            p = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=slave_fd,
                stderr=slave_fd,
                bufsize=0,
                env=env,
            )
            os.close(slave_fd)

            try:
                while True:
                    try:
                        r, _, _ = _sel.select([master_fd], [], [], 0.05)
                    except (ValueError, OSError):
                        break
                    if r:
                        try:
                            chunk = os.read(master_fd, 4096)
                        except OSError:
                            break
                        if not chunk:
                            break
                        _write(chunk, fbin)
                    elif p.poll() is not None:
                        # Process done — drain any remaining output
                        try:
                            while True:
                                r2, _, _ = _sel.select([master_fd], [], [], 0)
                                if not r2:
                                    break
                                chunk = os.read(master_fd, 4096)
                                if not chunk:
                                    break
                                _write(chunk, fbin)
                        except OSError:
                            pass
                        break
            finally:
                try:
                    os.close(master_fd)
                except OSError:
                    pass

        else:
            # ── Windows: regular pipe (PTY not available) ─────────────────────
            p = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                env=env,
            )
            assert p.stdout is not None
            read_fn = getattr(p.stdout, "read1", None) or p.stdout.read
            while True:
                chunk = read_fn(4096)
                if not chunk:
                    break
                _write(chunk, fbin)

    rc = p.wait()

    if live_bin is not None:
        try:
            live_bin.flush()
            live_bin.close()
        except Exception:
            pass

    if rc != 0:
        raise RuntimeError(f"Command failed ({rc}): {' '.join(cmd)}")
