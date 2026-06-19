"""Ring-buffer log capture feeding the Terminal view's log pane.

Subprocess output is fed in explicitly via `append()` (see jobs.py); stdout/
stderr of the app process itself is also tee'd in via `install_tee()` so
in-process errors show up in the same place.
"""
from __future__ import annotations

import re
import sys
import threading

_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

_MAX_CHARS = 2_000_000

_buffer = ""
_dropped = 0
_lock = threading.Lock()
_installed = False


def _sink(text: str) -> None:
    global _buffer, _dropped
    if not text:
        return
    text = _ANSI_RE.sub("", text).replace("\r\n", "\n")
    with _lock:
        _buffer += text
        if len(_buffer) > _MAX_CHARS:
            excess = len(_buffer) - _MAX_CHARS
            _buffer = _buffer[excess:]
            _dropped += excess


def append(text: str) -> None:
    _sink(text)


def drain(cursor: int) -> tuple[str, int]:
    """Return text appended since `cursor`, and the new cursor position."""
    with _lock:
        pos = max(0, cursor - _dropped)
        new = _buffer[pos:]
        return new, _dropped + len(_buffer)


class _Tee:
    def __init__(self, original):
        self._original = original

    def write(self, text: str) -> int:
        self._original.write(text)
        _sink(text)
        return len(text)

    def flush(self) -> None:
        self._original.flush()

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name):
        return getattr(self._original, name)


def install_tee() -> None:
    global _installed
    if _installed:
        return
    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)
    _installed = True
