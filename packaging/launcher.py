"""PyInstaller entry point for the standalone AiSongTool executable.

The frozen exe *is* the CLI: ``AiSongTool.exe <command> [args...]`` behaves
exactly like ``aisongtool <command>``. Double-clicking it (no arguments)
opens the desktop app instead of dumping CLI help into a console.

Built with console=False so the exe runs in the Windows GUI subsystem: no
terminal window appears. In app mode, stdout/stderr are redirected to
devnull since all log output is shown in the app's own Terminal tab.
"""
import multiprocessing
import os
import sys


def _redirect_stdio_to_devnull() -> None:
    try:
        devnull = open(os.devnull, "w")
        sys.stdout = devnull
        sys.stderr = devnull
    except Exception:
        pass


from aisongtool.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) == 1:
        sys.argv.append("app")
    if sys.argv[1] == "app" and getattr(sys, "frozen", False):
        _redirect_stdio_to_devnull()
    sys.exit(main())
