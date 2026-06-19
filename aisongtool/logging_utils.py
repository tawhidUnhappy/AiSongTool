from __future__ import annotations
from pathlib import Path

def log(msg: str, log_path: Path) -> None:
    line = msg.rstrip()
    print(line)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as f:
        f.write(line + "\n")
