"""Ring-buffer log capture feeding the Terminal view's log pane.

Subprocess output is fed in explicitly via `append()` (see jobs.py); stdout/
stderr of the app process itself is also tee'd in via `install_tee()` so
in-process errors show up in the same place.

Backed by `pyte` — a real VT100/ANSI terminal emulator — instead of a
hand-rolled `\\r`/`\\n` state machine. That gets us, for free and correctly:
cursor-addressed overwrites (ffmpeg/tqdm-style `\\r` progress, including
multi-line cursor-up redraws our old regex-based ANSI stripper couldn't
handle), and actual ANSI color/bold/italic/underline rendering instead of
discarding every escape code. `pyte.HistoryScreen` is a fixed-size grid (like
a real terminal window) plus a bounded scrollback deque for everything that's
scrolled off the top — `render_spans()` stitches scrollback + the live screen
back into one logical, ever-growing log.
"""
from __future__ import annotations

import re
import sys
import threading

import pyte

_COLUMNS = 200
_LINES = 50
_HISTORY = 20_000

# Tools write Unix-style bare \n for "new line" (Python's print, ffmpeg,
# tqdm's own final newline, ...). A real terminal only gets that behavior
# because the pty's line discipline translates \n -> \r\n on the way out;
# piped (non-pty) stdout has no such translation, and pyte — being a
# faithful VT100 emulator — treats bare \n as "move down one row, same
# column" (no carriage return), which would stair-step every line. Insert
# the \r ourselves for any \n not already preceded by one.
_BARE_NL_RE = re.compile(r"(?<!\r)\n")

# Standard ANSI 16-color palette (Tango theme) — pyte names colors like
# "red"/"brightred"/"default"; truecolor/256-color codes resolve to a literal
# hex string already, so only the named ones need a lookup.
_NAMED_COLORS = {
    "black": "#000000", "red": "#CC0000", "green": "#4E9A06", "brown": "#C4A000",
    "blue": "#3465A4", "magenta": "#75507B", "cyan": "#06989A", "white": "#D3D7CF",
    "brightblack": "#555753", "brightred": "#EF2929", "brightgreen": "#8AE234",
    "brightbrown": "#FCE94F", "brightblue": "#729FCF", "brightmagenta": "#AD7FA8",
    "brightcyan": "#34E2E2", "brightwhite": "#EEEEEC",
}

_screen = pyte.HistoryScreen(_COLUMNS, _LINES, history=_HISTORY)
_stream = pyte.Stream(_screen)
_version = 0
_lock = threading.Lock()
_installed = False


def _sink(text: str) -> None:
    global _version
    if not text:
        return
    text = _BARE_NL_RE.sub("\r\n", text)
    with _lock:
        _stream.feed(text)
        _version += 1


def append(text: str) -> None:
    _sink(text)


def resolve_color(name: str) -> str | None:
    """pyte color name/hex -> a Flet-usable color string, or None for
    "default" (meaning: let the caller's own default text color apply)."""
    if name in (None, "default"):
        return None
    if name in _NAMED_COLORS:
        return _NAMED_COLORS[name]
    if re.fullmatch(r"[0-9a-fA-F]{6}", name):
        return f"#{name}"
    return None


def _row_plain(row, columns: int) -> str:
    return "".join(row[i].data for i in range(columns))


def _row_runs(row, columns: int) -> list[tuple[str, tuple]]:
    """One row -> runs of (text, (fg, bold, italics, underscore,
    strikethrough)) — merges consecutive same-style characters so the UI
    builds one TextSpan per *style change*, not one per character."""
    length = len(_row_plain(row, columns).rstrip())
    runs: list[tuple[str, tuple]] = []
    cur_chars: list[str] = []
    cur_attrs: tuple | None = None
    for i in range(length):
        ch = row[i]
        attrs = (ch.fg, ch.bold, ch.italics, ch.underscore, ch.strikethrough)
        if attrs != cur_attrs and cur_chars:
            runs.append(("".join(cur_chars), cur_attrs))
            cur_chars = []
        cur_attrs = attrs
        cur_chars.append(ch.data)
    if cur_chars:
        runs.append(("".join(cur_chars), cur_attrs))
    return runs


def render_spans() -> tuple[list[list[tuple[str, tuple]]], int]:
    """Scrollback + live screen as a list of lines, each a list of
    (text, attrs) runs — see _row_runs. `attrs` is None for a blank line."""
    with _lock:
        columns = _screen.columns
        lines = [_row_runs(row, columns) for row in _screen.history.top]

        screen_rows = [_screen.buffer[i] for i in range(_screen.lines)]
        while screen_rows and not _row_plain(screen_rows[-1], columns).strip():
            screen_rows.pop()
        lines.extend(_row_runs(row, columns) for row in screen_rows)

        return lines, _version


def render() -> tuple[str, int]:
    """Plain-text version of render_spans() — for anything that just wants
    the raw log text (e.g. "copy all" / saving to a file), no styling."""
    lines, version = render_spans()
    text = "\n".join("".join(t for t, _ in line) for line in lines)
    return text, version


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
