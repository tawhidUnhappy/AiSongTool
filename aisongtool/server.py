#!/usr/bin/env python3
"""AiSongTool FastAPI server — production-ready."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from collections import defaultdict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

# ── Paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "jobs"
JOBS.mkdir(exist_ok=True)

WEBUI_DIR = ROOT / "webui"
INDEX_HTML = WEBUI_DIR / "index.html"
STATIC_DIR = WEBUI_DIR / "static"

LIVE_LOG = JOBS / "live.log"
LIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
LIVE_LOG.touch(exist_ok=True)

LOG_TAIL_LINES = 300

# ── Production limits ──────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 200 * 1024 * 1024   # 200 MB
MAX_LYRICS_CHARS = 50_000
RATE_LIMIT_JOBS  = 20                  # per window per IP
RATE_LIMIT_WINDOW = 3600               # 1 hour

_ALLOWED_WHISPER_MODELS = {
    "tiny", "base", "small", "medium",
    "large-v2", "large-v3", "large-v3-turbo",
}

# Accepted audio magic bytes: (prefix_bytes, byte_offset)
_AUDIO_MAGIC: list[tuple[bytes, int]] = [
    (b"ID3",    0),   # MP3 with ID3 tag
    (b"\xff\xfb", 0), # MP3 frame sync
    (b"\xff\xf3", 0),
    (b"\xff\xf2", 0),
    (b"RIFF",   0),   # WAV
    (b"fLaC",   0),   # FLAC
    (b"OggS",   0),   # OGG / Opus
    (b"ftyp",   4),   # M4A / AAC (ISO base media file)
]
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

# ── Rate limiter (in-memory, resets on restart) ────────────────────────
_rate_data: dict[str, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        ts = [t for t in _rate_data[ip] if now - t < RATE_LIMIT_WINDOW]
        _rate_data[ip] = ts
        if len(ts) >= RATE_LIMIT_JOBS:
            return False
        _rate_data[ip].append(now)
        return True


def _mark_stale_jobs_failed() -> None:
    """On startup, any job still marked 'running' is orphaned (server crashed/restarted).
    Mark them failed so new jobs aren't blocked."""
    try:
        for d in JOBS.iterdir():
            if not d.is_dir():
                continue
            status_path = d / "out" / "status.json"
            if status_path.exists():
                try:
                    j = json.loads(status_path.read_text(encoding="utf-8"))
                    if j.get("status") == "running":
                        status_path.write_text(
                            json.dumps({"status": "failed", "reason": "server_restart"}),
                            encoding="utf-8",
                        )
                except Exception:
                    pass
    except Exception:
        pass

_mark_stale_jobs_failed()

# ── Current process tracking (for /stop) ──────────────────────────────
_current_process: "subprocess.Popen[str] | None" = None
_current_job_dir: Path | None = None
_process_lock = threading.Lock()

# ── App ────────────────────────────────────────────────────────────────
app = FastAPI(title="AiSongTool", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Security headers middleware ────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "media-src blob:;"
    )
    return response


# ── Helpers ────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "unknown")


def _safe_name(name: str | None) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "").strip())
    return name[:120] if name else "upload"


def _validate_audio(data: bytes, filename: str) -> None:
    ext = Path(filename).suffix.lower()
    if ext not in _AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Accepted: mp3, wav, m4a, aac, flac, ogg, opus.",
        )
    if len(data) < 12:
        raise HTTPException(status_code=400, detail="File is too small to be a valid audio file.")
    for magic, offset in _AUDIO_MAGIC:
        if data[offset : offset + len(magic)] == magic:
            return
    # No magic match — still allow; ffmpeg will reject invalid files later.


def _append_live(msg: str) -> None:
    with LIVE_LOG.open("a", encoding="utf-8", errors="replace") as f:
        f.write(msg.rstrip() + "\n")


def _cleanup_job(job_dir: Path, delay_seconds: int = 10) -> None:
    try:
        time.sleep(delay_seconds)
        job_dir = job_dir.resolve()
        if JOBS.resolve() not in job_dir.parents:
            return
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
    except Exception:
        pass


def _any_running_job() -> bool:
    try:
        for d in JOBS.iterdir():
            if not d.is_dir():
                continue
            status = d / "out" / "status.json"
            if status.exists():
                try:
                    j = json.loads(status.read_text(encoding="utf-8", errors="replace"))
                    if j.get("status") == "running":
                        return True
                except Exception:
                    continue
    except Exception:
        return False
    return False


def _get_song_stem(job_dir: Path) -> str:
    inp = job_dir / "input"
    if not inp.exists():
        return "captions"
    for p in inp.iterdir():
        if p.is_file() and p.name.lower() != "lyrics.txt":
            return p.stem
    return "captions"


# ── Pipeline runner ────────────────────────────────────────────────────

def _run_pipeline(job_dir: Path, song_path: Path, lyrics_path: Path | None, out_dir: Path,
                  model: str = "large-v3", language_code: str = "",
                  segment_mode: bool = False, skip_demucs: bool = False,
                  has_lyrics: bool = True, vad: str = "silero") -> None:
    status_path = out_dir / "status.json"
    log_path = out_dir / "pipeline.log"

    status_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    log_path.write_text("", encoding="utf-8")

    _append_live("")
    _append_live(f"===== JOB {job_dir.name} started =====")

    cmd = [
        sys.executable, "-m", "aisongtool.cli",
        "--song", str(song_path),
        "--out", str(out_dir),
        "--whisper_model", model,
    ]
    if has_lyrics and lyrics_path is not None:
        cmd += ["--lyrics", str(lyrics_path)]
    if language_code:
        cmd += ["--language", language_code]
    if segment_mode:
        cmd += ["--segment_mode"]
    if skip_demucs:
        cmd += ["--skip_demucs"]
    cmd += ["--vad", vad]
    # Only pass env dirs when not in Docker mode (Docker uses DEMUCS_PYTHON etc.)
    if not os.environ.get("DEMUCS_PYTHON"):
        cmd += [
            "--demucs_env", str(ROOT / "demucs-uv"),
            "--whisperx_env", str(ROOT / "whisperx-uv"),
        ]

    global _current_process, _current_job_dir

    env = os.environ.copy()
    env["AISONGTOOL_LIVE_LOG"] = str(LIVE_LOG)

    p = subprocess.Popen(
        cmd, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", env=env,
    )

    with _process_lock:
        _current_process = p
        _current_job_dir = job_dir

    stdout_data, _ = p.communicate()
    rc = p.returncode

    with _process_lock:
        _current_process = None
        _current_job_dir = None

    if rc != 0:
        with log_path.open("a", encoding="utf-8", errors="replace") as f:
            if stdout_data:
                f.write("\n--- output ---\n" + stdout_data[-8000:])
        status_path.write_text(
            json.dumps({"status": "failed", "returncode": rc}), encoding="utf-8"
        )
        _append_live(f"===== JOB {job_dir.name} FAILED =====")
        threading.Thread(target=_cleanup_job, args=(job_dir, 3600), daemon=True).start()
        return

    status_path.write_text(json.dumps({"status": "done"}), encoding="utf-8")
    _append_live(f"===== JOB {job_dir.name} done =====")
    threading.Thread(target=_cleanup_job, args=(job_dir, 3600), daemon=True).start()


# ── Zip helper ─────────────────────────────────────────────────────────

def _zip_outputs(job_dir: Path) -> Path:
    out_dir = job_dir / "out"
    zip_path = out_dir / "outputs.zip"
    files = [
        out_dir / "final.srt",
        out_dir / "final.ass",
        out_dir / "final.vtt",
        out_dir / "final.lrc",
        out_dir / "final.sbv",
        out_dir / "lyrics_clean.txt",
        out_dir / "pipeline.log",
    ]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in files:
            if p.exists():
                z.write(p, arcname=p.name)
    return zip_path


# ── Routes ─────────────────────────────────────────────────────────────

@app.get("/")
def index():
    if not INDEX_HTML.exists():
        return PlainTextResponse("Missing webui/index.html", status_code=500)
    return FileResponse(path=str(INDEX_HTML), media_type="text/html")


@app.post("/start")
async def start_job(
    request: Request,
    background_tasks: BackgroundTasks,
    song: UploadFile = File(...),
    lyrics: str = Form(...),
    model: str = Form("large-v3"),
    language: str = Form(""),
    cue_mode: str = Form("line"),
    skip_demucs: str = Form(""),
    vad: str = Form("silero"),
):
    ip = _client_ip(request)

    if not _check_rate_limit(ip):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit: max {RATE_LIMIT_JOBS} jobs per hour. Please wait.",
        )

    if _any_running_job():
        return PlainTextResponse("A job is already running. Please wait.", status_code=409)

    # Validate model
    model = model.strip() or "large-v3"
    if model not in _ALLOWED_WHISPER_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'.")

    # Validate language (letters only, max 8 chars)
    language_code = re.sub(r"[^a-z]", "", language.strip().lower())[:8]

    # Validate lyrics
    if len(lyrics) > MAX_LYRICS_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Lyrics too long (max {MAX_LYRICS_CHARS:,} characters).",
        )

    # Read + validate audio
    data = await song.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB).",
        )
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    _validate_audio(data, song.filename or "upload.mp3")

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS / job_id
    inp_dir = job_dir / "input"
    out_dir = job_dir / "out"
    inp_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    song_name = _safe_name(song.filename)
    song_path = inp_dir / song_name
    song_path.write_bytes(data)

    lyrics_path: Path | None = None
    if lyrics.strip():
        lyrics_path = inp_dir / "lyrics.txt"
        lyrics_path.write_text(lyrics, encoding="utf-8")

    (out_dir / "pipeline.log").write_text("", encoding="utf-8")
    (out_dir / "status.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    LIVE_LOG.write_text("", encoding="utf-8")

    seg_mode = cue_mode.strip().lower() == "segment"
    skip_demucs_flag = skip_demucs.strip() in ("1", "true", "yes")
    vad_backend = vad.strip() if vad.strip() in ("silero", "pyannote") else "silero"
    background_tasks.add_task(_run_pipeline, job_dir, song_path, lyrics_path, out_dir,
                              model=model, language_code=language_code,
                              segment_mode=seg_mode, skip_demucs=skip_demucs_flag,
                              has_lyrics=lyrics_path is not None, vad=vad_backend)
    return JSONResponse({"job_id": job_id})


@app.get("/job/{job_id}/status")
def job_status(job_id: str):
    if not re.fullmatch(r"[a-f0-9]{12}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")
    status_path = JOBS / job_id / "out" / "status.json"
    if not status_path.exists():
        return JSONResponse({"status": "unknown"})
    try:
        return JSONResponse(json.loads(status_path.read_text(encoding="utf-8")))
    except Exception:
        return JSONResponse({"status": "unknown"})


@app.get("/gpu-info")
def gpu_info():
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            row = r.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in row.split(",")]
            raw_name = parts[0] if len(parts) > 0 else "GPU"
            mem_mb   = parts[1] if len(parts) > 1 else None
            driver   = parts[2] if len(parts) > 2 else None
            temp_c   = parts[3] if len(parts) > 3 else None
            util_pct = parts[4] if len(parts) > 4 else None
            name = raw_name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")
            mem_gb = f"{round(int(mem_mb) / 1024)} GB" if (mem_mb and mem_mb.isdigit()) else None
            return JSONResponse({
                "available": True,
                "name": name,
                "mem_gb": mem_gb,
                "driver": driver,
                "temp_c":   None if (not temp_c   or temp_c   == "N/A") else temp_c,
                "util_pct": None if (not util_pct or util_pct == "N/A") else util_pct,
            })
    except Exception:
        pass
    return JSONResponse({"available": False})


@app.post("/stop")
def stop_job():
    global _current_process, _current_job_dir
    with _process_lock:
        if _current_process is None:
            return JSONResponse({"status": "no_job"})
        try:
            import os as _os, signal as _sig
            try:
                _os.killpg(_os.getpgid(_current_process.pid), _sig.SIGTERM)
            except Exception:
                _current_process.kill()
        except Exception:
            pass
        if _current_job_dir:
            sp = _current_job_dir / "out" / "status.json"
            try:
                sp.write_text(json.dumps({"status": "failed", "reason": "cancelled"}), encoding="utf-8")
                _append_live(f"===== JOB {_current_job_dir.name} CANCELLED =====")
            except Exception:
                pass
        _current_process = None
        _current_job_dir = None
    return JSONResponse({"status": "stopped"})


_PROGRESS_RE = re.compile(r"^\s*\d+%\|")


@app.get("/log/tail")
def log_tail(lines: int = 300):
    n = min(lines, LOG_TAIL_LINES)
    if not LIVE_LOG.exists():
        return PlainTextResponse("")
    try:
        raw = LIVE_LOG.read_text(encoding="utf-8", errors="replace")
        # Strip ANSI escape codes
        raw = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", raw)
        # Split on real newlines; collapse \r overwrites within each line
        out_lines: list[str] = []
        for segment in re.split(r"\r?\n", raw):
            parts = segment.split("\r")
            out_lines.append(parts[-1].rstrip())
        # Collapse consecutive tqdm progress-bar frames to just the last one
        collapsed: list[str] = []
        i = 0
        while i < len(out_lines):
            if _PROGRESS_RE.match(out_lines[i]):
                j = i + 1
                while j < len(out_lines) and _PROGRESS_RE.match(out_lines[j]):
                    j += 1
                collapsed.append(out_lines[j - 1])
                i = j
            else:
                collapsed.append(out_lines[i])
                i += 1
        tail = collapsed[-n:]
        return PlainTextResponse("\n".join(tail))
    except Exception:
        return PlainTextResponse("")


@app.get("/job/{job_id}/download/{fmt}")
def download(job_id: str, fmt: str, background_tasks: BackgroundTasks):
    if not re.fullmatch(r"[a-f0-9]{12}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")

    job_dir = JOBS / job_id
    out_dir = job_dir / "out"
    song_stem = _get_song_stem(job_dir)

    fmt = fmt.lower().strip()
    allowed = {"srt", "ass", "vtt", "lrc", "sbv", "lyrics", "zip"}
    if fmt not in allowed:
        return PlainTextResponse("Unsupported format.", status_code=400)

    if fmt == "zip":
        zip_path = _zip_outputs(job_dir)
        if not zip_path.exists():
            return PlainTextResponse("Outputs not ready.", status_code=404)
        background_tasks.add_task(_cleanup_job, job_dir, 10)
        return FileResponse(
            path=str(zip_path), filename=f"{song_stem}_outputs.zip", media_type="application/zip"
        )

    mapping = {
        "srt":    ("final.srt",        f"{song_stem}.srt",         "application/x-subrip"),
        "ass":    ("final.ass",        f"{song_stem}.ass",         "text/plain"),
        "vtt":    ("final.vtt",        f"{song_stem}.vtt",         "text/vtt"),
        "lrc":    ("final.lrc",        f"{song_stem}.lrc",         "text/plain"),
        "sbv":    ("final.sbv",        f"{song_stem}.sbv",         "text/plain"),
        "lyrics": ("lyrics_clean.txt", f"{song_stem}_lyrics.txt",  "text/plain"),
    }
    fname, dlname, mime = mapping[fmt]
    path = out_dir / fname
    if not path.exists():
        return PlainTextResponse("Output not ready.", status_code=404)

    background_tasks.add_task(_cleanup_job, job_dir, 10)
    return FileResponse(path=str(path), filename=dlname, media_type=mime)
