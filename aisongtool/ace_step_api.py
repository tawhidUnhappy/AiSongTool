"""HTTP client for ACE-Step-1.5's own `acestep-api` REST server
(https://github.com/ACE-Step/ACE-Step-1.5) — replaces the earlier client for
acestep.cpp's `ace-server` (a two-stage `/lm` + `/synth` + `/job?id=` job
protocol). ACE-Step-1.5's API is a single async job queue instead:
`POST /release_task` submits one task (caption+lyrics -> a finished song in
one step), `POST /query_result` polls it by `task_id`, and the finished file
is fetched via a plain `GET /v1/audio?path=...` download.

Mirrors `desktop/src/main/tools/ace-step-api.ts` — see that file's docstring
for the same protocol explanation. This Python copy backs the Flet app's
Docker-only "Song Generation" view (see `flet_app/views/_create_pipeline.py`)
and has not itself been exercised against a live server yet, same caveat as
the TS client it mirrors.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import httpx

from .ace_step import DEFAULT_DIT_MODEL

LogFn = Callable[[str], None]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8001


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
    model: str = DEFAULT_DIT_MODEL,
    vocal_language: str = "en",
    instrumental: bool = False,
    seed: int | None = None,
    poll_interval: float = 2.0,
    timeout: float = 600.0,
    on_progress: LogFn | None = None,
) -> Path:
    """Submit one `/release_task` (caption+lyrics -> a finished song in a
    single job, no separate codes/audio stages like acestep.cpp's
    `/lm`+`/synth`), poll `/query_result` until done, then download the
    finished file from `/v1/audio?path=...`.

    `prompt`/`lyrics` are always treated as literal — the caller has already
    resolved who wrote them (manual text or Gemma 4). `instrumental=True`
    sends empty lyrics (no separate "[Instrumental]" convention confirmed for
    this API, unlike acestep.cpp's documented one). `vocal_language` should
    already be resolved to a real code rather than left as "unknown"."""
    base = _base_url(host, port)
    task_body: dict = {
        "task_type": "text2music",
        "prompt": prompt,
        "lyrics": "" if instrumental else lyrics,
        "audio_duration": duration,
        "vocal_language": "en" if vocal_language == "unknown" else vocal_language,
        "seed": -1 if seed is None else seed,
        "batch_size": 1,
        "model": model,
    }

    log(f"POST {base}/release_task {task_body}")
    try:
        with httpx.Client(timeout=30.0) as client:
            task_id = _release_task(client, base, task_body, log)
            result = _poll_result(client, base, task_id, log, poll_interval, timeout, on_progress)
            file_path = result.get("file")
            if not file_path:
                raise AceStepApiError(f"task {task_id} succeeded but returned no file path: {result}")

            log(f"GET {base}{file_path}")
            audio_resp = client.get(f"{base}{file_path}", timeout=120.0)
            if audio_resp.status_code != 200:
                raise AceStepApiError(f"Downloading result audio failed ({audio_resp.status_code})")
            audio_bytes = audio_resp.content
    except Exception as exc:  # noqa: BLE001
        log(f"Generation failed: {exc!r}")
        raise

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "generated.mp3"
    out_path.write_bytes(audio_bytes)
    log(f"Saved generated song to {out_path}")
    return out_path


def _release_task(client: httpx.Client, base: str, body: dict, log: LogFn) -> str:
    resp = client.post(f"{base}/release_task", json=body, timeout=30.0)
    if resp.status_code != 200:
        raise AceStepApiError(f"/release_task failed ({resp.status_code}): {resp.text}")
    task_id = (resp.json() or {}).get("data", {}).get("task_id")
    if not task_id:
        raise AceStepApiError(f"/release_task returned no task_id: {resp.text}")
    log(f"task submitted: {task_id}")
    return task_id


def _poll_result(
    client: httpx.Client, base: str, task_id: str, log: LogFn, poll_interval: float, timeout: float,
    on_progress: LogFn | None,
) -> dict:
    import json as _json

    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        try:
            resp = client.post(f"{base}/query_result", json={"task_id_list": [task_id]}, timeout=30.0)
        except httpx.HTTPError as exc:
            log(f"Poll request failed ({exc!r}) — server may still be loading models, retrying...")
            continue
        if resp.status_code != 200:
            log(f"/query_result returned {resp.status_code}, retrying...")
            continue
        items = (resp.json() or {}).get("data", [])
        item = next((i for i in items if i.get("task_id") == task_id), None)
        if item is None:
            log(f"/query_result didn't include task {task_id} yet, retrying...")
            continue
        status = item.get("status")
        if status != last_status:
            label = {0: "running", 1: "succeeded", 2: "failed"}.get(status, str(status))
            log(f"task {task_id}: {label}")
            last_status = status
            if on_progress:
                on_progress(f"generating: {label}")
        if status == 1:
            # `result` decodes to an array (one entry per `batch_size`, even
            # when batch_size is 1 — confirmed against a real server
            # response: `[{"file": ..., "metas": ..., ...}]`, not a flat
            # object), mirroring the same fix in ace-step-api.ts.
            result = item.get("result")
            if not result:
                return {}
            parsed = _json.loads(result)
            return parsed[0] if parsed else {}
        if status == 2:
            raise AceStepApiError(f"task {task_id} failed: {item.get('result') or '(no detail)'}")
    raise AceStepApiError(f"task {task_id} timed out after {timeout:.0f}s.")
