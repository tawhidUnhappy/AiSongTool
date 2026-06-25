"""HTTP client for acestep.cpp's `ace-server` (https://github.com/ServeurpersoCom/acestep.cpp).

Mirrors `desktop/src/main/tools/ace-step-api.ts` (the actively-used,
live-tested Electron client) — see that file's docstring for the full
protocol explanation. This Python copy backs the (currently lower-priority,
kept-running-in-parallel) Flet app's "Song Generation" view and has not
itself been exercised against a live server yet.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import httpx

from .ace_step import selected_model_files

LogFn = Callable[[str], None]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


class AceStepApiError(RuntimeError):
    pass


def _base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def is_server_up(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    try:
        resp = httpx.get(f"{_base_url(host, port)}/health", timeout=3.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def wait_for_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 300.0,
    log: LogFn = print,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_server_up(host, port):
            return True
        time.sleep(2.0)
    log(f"ACE-Step server did not become healthy within {timeout:.0f}s.")
    return False


def generate_song(
    prompt: str,
    lyrics: str,
    duration: float,
    out_dir: Path,
    log: LogFn = print,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    song_name: str = "",
    vocal_language: str = "en",
    instrumental: bool = False,
    seed: int | None = None,
    poll_interval: float = 2.0,
    timeout: float = 600.0,
    on_progress: LogFn | None = None,
) -> Path:
    """Submit caption(+lyrics) -> /lm for audio codes -> /synth for audio,
    polling each job, then save the result.

    `prompt`/`lyrics` are always treated as literal — the caller has already
    resolved who wrote them (manual text or Gemma 4) before this is called.
    `instrumental=True` forces `lyrics="[Instrumental]"` (acestep.cpp's
    documented convention). `vocal_language` should already be resolved to a
    real code (e.g. via Gemma 4 language detection) rather than left as
    "unknown" — see ace-step-api.ts for the full explanation of why leaving
    it blank is unsafe."""
    models = selected_model_files()
    base = _base_url(host, port)
    lm_body: dict = {
        "duration": duration,
        "vocal_language": "en" if vocal_language == "unknown" else vocal_language,
        "seed": -1 if seed is None else seed,
        "lm_model": models["lm"],
        "use_cot_caption": False,
        "caption": prompt,
        "lyrics": "[Instrumental]" if instrumental else lyrics,
    }
    if song_name.strip():
        lm_body["track"] = song_name.strip()

    log(f"POST {base}/lm {lm_body}")
    try:
        with httpx.Client(timeout=30.0) as client:
            lm_result = _run_job(client, base, "/lm", lm_body, log, poll_interval, timeout, on_progress, "lm")
            synth_body = {**lm_result, "synth_model": models["dit"], "output_format": "mp3"}
            log(f"POST {base}/synth")
            audio_bytes = _run_synth_job(client, base, synth_body, log, poll_interval, timeout, on_progress)
    except Exception as exc:  # noqa: BLE001
        log(f"Generation failed: {exc!r}")
        raise

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "generated.mp3"
    out_path.write_bytes(audio_bytes)
    log(f"Saved generated song to {out_path}")
    return out_path


def _post_json(client: httpx.Client, url: str, body: dict, timeout: float) -> httpx.Response:
    return client.post(url, json=body, timeout=timeout)


def _poll_job(
    client: httpx.Client, base: str, job_id: str, log: LogFn, poll_interval: float, timeout: float,
    on_progress: LogFn | None, label: str,
) -> None:
    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        try:
            resp = client.get(f"{base}/job", params={"id": job_id}, timeout=30.0)
        except httpx.HTTPError as exc:
            log(f"Poll request failed ({exc!r}) — server may still be loading models, retrying...")
            continue
        if resp.status_code != 200:
            log(f"/job?id={job_id} returned {resp.status_code}, retrying...")
            continue
        status = (resp.json() or {}).get("status", "unknown")
        if status != last_status:
            log(f"{label} job {job_id}: {status}")
            last_status = status
            if on_progress:
                on_progress(f"{label}: {status}")
        if status == "done":
            return
        if status in ("failed", "cancelled"):
            raise AceStepApiError(f"{label} job {job_id} {status}")
    raise AceStepApiError(f"{label} job {job_id} timed out after {timeout:.0f}s.")


def _run_job(
    client: httpx.Client, base: str, endpoint: str, body: dict, log: LogFn, poll_interval: float,
    timeout: float, on_progress: LogFn | None, label: str,
) -> dict:
    resp = _post_json(client, f"{base}{endpoint}", body, 120.0)
    if resp.status_code != 200:
        raise AceStepApiError(f"{endpoint} failed ({resp.status_code}): {resp.text}")
    job_id = resp.json().get("id")
    if not job_id:
        raise AceStepApiError(f"{endpoint} returned no job id: {resp.text}")
    log(f"{label} job submitted: {job_id}")
    _poll_job(client, base, job_id, log, poll_interval, timeout, on_progress, label)

    result_resp = client.get(f"{base}/job", params={"id": job_id, "result": 1}, timeout=60.0)
    if result_resp.status_code != 200:
        raise AceStepApiError(f"Fetching {label} result failed ({result_resp.status_code}): {result_resp.text}")
    items = result_resp.json()
    if not items:
        raise AceStepApiError(f"{label} job {job_id} returned no result items.")
    return items[0]


def _run_synth_job(
    client: httpx.Client, base: str, body: dict, log: LogFn, poll_interval: float, timeout: float,
    on_progress: LogFn | None,
) -> bytes:
    resp = _post_json(client, f"{base}/synth", body, 120.0)
    if resp.status_code != 200:
        raise AceStepApiError(f"/synth failed ({resp.status_code}): {resp.text}")
    job_id = resp.json().get("id")
    if not job_id:
        raise AceStepApiError(f"/synth returned no job id: {resp.text}")
    log(f"synth job submitted: {job_id}")
    _poll_job(client, base, job_id, log, poll_interval, timeout, on_progress, "synth")

    result_resp = client.get(f"{base}/job", params={"id": job_id, "result": 1}, timeout=60.0)
    if result_resp.status_code != 200:
        raise AceStepApiError(f"Fetching synth result failed ({result_resp.status_code}): {result_resp.text}")
    content_type = result_resp.headers.get("content-type", "")
    if "boundary=" not in content_type:
        raise AceStepApiError(f"/synth result wasn't multipart (content-type: {content_type})")
    boundary = content_type.split("boundary=")[1].strip('"').split(";")[0]
    for content_type_part, part_body in _split_multipart(result_resp.content, boundary):
        if content_type_part.lower().startswith("audio/"):
            return part_body
    raise AceStepApiError("/synth multipart result had no audio part")


def _split_multipart(buffer: bytes, boundary: str) -> list[tuple[str, bytes]]:
    """Minimal multipart/mixed parser — see ace-step-api.ts's `splitMultipart`
    for the matching implementation/rationale."""
    delimiter = f"--{boundary}".encode()
    parts: list[tuple[str, bytes]] = []
    search_from = 0
    while True:
        start = buffer.find(delimiter, search_from)
        if start == -1:
            break
        after_delim = start + len(delimiter)
        if buffer[after_delim:after_delim + 2] == b"--":
            break
        next_delim = buffer.find(delimiter, after_delim)
        if next_delim == -1:
            break
        part = buffer[after_delim:next_delim]
        header_end = part.find(b"\r\n\r\n")
        if header_end != -1:
            header_text = part[:header_end].decode("utf-8", errors="replace")
            content_type = ""
            for line in header_text.splitlines():
                if line.lower().startswith("content-type:"):
                    content_type = line.split(":", 1)[1].strip()
            body = part[header_end + 4:len(part) - 2]
            parts.append((content_type, body))
        search_from = next_delim
    return parts
