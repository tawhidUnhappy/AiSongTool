"""Entry point `flet build` looks for (the packaged native bundle just runs
this script directly — there's no `aisongtool app` CLI invocation involved).
`aisongtool app` (dev/uv mode) instead calls `app.main()` itself; see cli.py."""
from __future__ import annotations

from aisongtool.flet_app.app import main

main()
