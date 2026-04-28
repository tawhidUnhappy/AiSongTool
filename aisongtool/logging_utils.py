from __future__ import annotations
import os
from pathlib import Path

def log(msg: str, log_path: Path) -> None:
    line = msg.rstrip()
    print(line)

    # Always append to the per-job log file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as f:
        f.write(line + "\n")

    # If WebUI is running, also tee into the shared live log so the tail terminal updates.
    live = os.environ.get("AISONGTOOL_LIVE_LOG")
    if live:
        try:
            p = Path(live)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("ab", buffering=0) as fb:
                fb.write((line + "\n").encode("utf-8", errors="replace"))
        except Exception:
            pass
