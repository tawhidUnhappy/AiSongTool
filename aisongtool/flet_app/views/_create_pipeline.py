"""Create flow's stage logic — split out of create.py (which stays UI-only:
building widgets and wiring callbacks). Each stage here mutates the shared
`flow` dict so create.py's poll loop can read status without any of this
module needing to know about Flet controls at all.

Each external tool (ACE-Step, Z-Image, Demucs/WhisperX via `aisongtool run`,
ffmpeg) runs to completion via `jobs.run_blocking`/explicit shutdown before
the next stage starts, freeing GPU/CPU between stages.
"""
from __future__ import annotations

import shutil
import sys
import time
import uuid
from pathlib import Path

from .. import jobs, terminal
from ..state import JOBS_DIR
from ... import ace_step, ace_step_api, gemma_writer, zimage
from ...karaoke import retime_karaoke_ass
from ...nightcore import DEFAULT_SPEED, build_nightcore_audio_cmd
from ...video import build_render_cmd

STAGE_TEXT = {
    "writing": "Writing song style, lyrics, and image prompt with Gemma 4...",
    "gen_checking": "Checking ACE-Step installation...",
    "gen_starting_server": "Starting ACE-Step API server (first start can take a couple "
                            "minutes while the model loads)...",
    "gen_generating": "Generating song with ACE-Step...",
    "gen_closing_server": "Song ready — shutting down the ACE-Step server to free the GPU...",
    "image_generating": "Generating background image...",
    "pipeline": "Running pipeline: separating vocals, transcribing, aligning, building subtitles...",
    "nightcore_audio": "Speeding up + pitching up the audio (nightcore)...",
    "retime": "Retiming lyrics to match the sped-up audio...",
    "video": "Rendering final video...",
}


def write_with_gemma(flow: dict, prompt: str) -> dict | None:
    """One-shot Gemma 4 generation — same shape as generate_image: a worker
    process loads the model, writes one JSON result, exits. Failure here
    aborts the whole run (unlike a bad image, a missing song style/lyrics
    means there's nothing for ACE-Step to generate from)."""
    flow["stage"] = "writing"
    flow["stage_started_at"] = time.monotonic()
    if not gemma_writer.is_synced():
        flow["error_message"] = ("Gemma 4 isn't installed yet. Go to the Setup tab and click "
                                  "\"Install Gemma 4\" first.")
        terminal.append(flow["error_message"] + "\n")
        flow["stage"] = "error"
        return None

    out_json = JOBS_DIR / "_gemma" / uuid.uuid4().hex[:12] / "result.json"
    try:
        cmd = gemma_writer.build_write_cmd(prompt, out_json)
    except gemma_writer.GemmaWriterError as exc:
        flow["error_message"] = str(exc)
        terminal.append(f"{exc}\n")
        flow["stage"] = "error"
        return None

    code = jobs.run_blocking(cmd, cwd=gemma_writer.dest_dir())
    if code != 0:
        flow["error_message"] = ("Gemma 4 failed to write the song style/lyrics/image prompt — "
                                  "check the Terminal tab.")
        flow["stage"] = "error"
        return None

    try:
        return gemma_writer.read_result(out_json)
    except gemma_writer.GemmaWriterError as exc:
        flow["error_message"] = str(exc)
        flow["stage"] = "error"
        return None


def generate_song(flow: dict, prompt: str, lyrics: str, duration: float, options: dict) -> tuple[Path | None, str]:
    """Runs ACE-Step end to end: install check -> start its API server ->
    generate -> explicitly shut the server down again (frees the GPU before
    Demucs/WhisperX run next), all on the calling thread."""
    flow["stage"] = "gen_checking"
    if not ace_step.is_synced():
        flow["error_message"] = ("ACE-Step-1.5 isn't installed yet. Go to the Setup tab "
                                  "and click \"Install / update ACE-Step\" first.")
        terminal.append(flow["error_message"] + "\n")
        flow["stage"] = "error"
        return None, ""

    server_proc = None
    try:
        if not ace_step_api.is_server_up():
            flow["stage"] = "gen_starting_server"
            flow["stage_started_at"] = time.monotonic()
            cmd = ace_step.build_run_cmd("api")
            server_proc = jobs.spawn_background(cmd, cwd=ace_step.dest_dir())
            if not ace_step_api.wait_for_server(timeout=300, log=terminal.append):
                flow["error_message"] = "ACE-Step API server did not start in time."
                terminal.append(flow["error_message"] + "\n")
                flow["stage"] = "error"
                return None, ""

        flow["stage"] = "gen_generating"
        flow["stage_started_at"] = time.monotonic()
        gen_out_dir = JOBS_DIR / "_songgen" / uuid.uuid4().hex[:12]
        audio_path = ace_step_api.generate_song(
            prompt=prompt, lyrics=lyrics, duration=duration,
            out_dir=gen_out_dir, log=terminal.append,
            vocal_language=options["vocal_language"],
            instrumental=options["instrumental"],
            seed=options["seed"],
            on_progress=lambda text: flow.update(gen_progress_text=text),
        )
        returned_lyrics = "" if options["instrumental"] else lyrics
        return audio_path, returned_lyrics
    except ace_step_api.AceStepApiError as exc:
        flow["error_message"] = str(exc)
        flow["stage"] = "error"
        return None, ""
    except Exception as exc:  # noqa: BLE001
        flow["error_message"] = f"Unexpected error: {exc!r}"
        flow["stage"] = "error"
        return None, ""
    finally:
        if server_proc is not None:
            # Closing the server clobbers flow["stage"] while it runs, so
            # remember whether an error was already recorded above and
            # restore it afterwards — otherwise a failed generation gets
            # permanently stuck showing "shutting down the server" instead of
            # the actual error.
            had_error = flow.get("error_message") is not None
            flow["stage"] = "gen_closing_server"
            terminal.append("Closing ACE-Step API server to free the GPU...\n")
            # A plain proc.terminate() only kills the immediate child —
            # ACE-Step's server forks its own worker process(es) for model
            # serving, which would otherwise keep running and holding the GPU.
            jobs.terminate_tree(server_proc)
            if had_error:
                flow["stage"] = "error"


def generate_image(flow: dict, prompt: str) -> Path | None:
    """One-shot Z-Image-Turbo generation — no server lifecycle like ACE-Step
    needs: the worker process loads the model, makes one image, saves it, and
    exits, so a plain `jobs.run_blocking` call is the whole job. Failure here
    just logs a warning and falls back to the default background — a bad
    image generation shouldn't sink the whole run."""
    flow["stage"] = "image_generating"
    flow["stage_started_at"] = time.monotonic()
    if not zimage.is_synced():
        terminal.append("Z-Image-Turbo isn't installed — using the default background image. "
                         "(Install it from the Setup tab to generate one from the prompt.)\n")
        return None

    out_path = JOBS_DIR / "_imagegen" / uuid.uuid4().hex[:12] / "image.png"
    try:
        cmd = zimage.build_generate_cmd(prompt, out_path)
    except zimage.ZImageError as exc:
        terminal.append(f"{exc}\n")
        return None

    code = jobs.run_blocking(cmd, cwd=zimage.dest_dir())
    if code != 0 or not out_path.exists():
        terminal.append("Image generation failed — using the default background image instead.\n")
        return None
    return out_path


def run_all(
    flow: dict, mode: str, prompt: str, gen_lyrics: str, duration: float, gen_options: dict,
    existing_song: Path | None, existing_lyrics: str, image_source: str, image_path: Path,
) -> None:
    try:
        if mode == "generate":
            image_prompt = prompt
            if gen_options.get("write_with_gemma"):
                written = write_with_gemma(flow, prompt)
                if written is None:
                    return  # flow["error_message"]/stage already set
                prompt = written["song_style"]
                gen_lyrics = written["lyrics"]
                image_prompt = written["image_prompt"]
                # Gemma already wrote a literal style caption + lyrics, so
                # ACE-Step should use them as-is, not its own sample_mode LM.
                gen_options = {**gen_options, "sample_mode": False, "instrumental": False}

            song_path, lyrics_text = generate_song(flow, prompt, gen_lyrics, duration, gen_options)
            if song_path is None:
                return  # flow["error_message"]/stage already set

            if image_source == "auto":
                generated_image = generate_image(flow, image_prompt)
                if generated_image is not None:
                    image_path = generated_image
        else:
            song_path = existing_song
            lyrics_text = existing_lyrics

        job_dir = JOBS_DIR / "_create" / uuid.uuid4().hex[:12]
        (job_dir / "input").mkdir(parents=True, exist_ok=True)
        (job_dir / "out").mkdir(parents=True, exist_ok=True)
        local_song = job_dir / "input" / song_path.name
        shutil.copy(song_path, local_song)
        flow["job_dir"] = job_dir
        flow["song_path"] = local_song

        lyrics_path = None
        if lyrics_text.strip():
            lyrics_path = job_dir / "input" / "lyrics.txt"
            lyrics_path.write_text(lyrics_text, encoding="utf-8")

        # Transcribe the *original*-pitch song first — Whisper's accuracy
        # drops sharply on nightcore's pitch-shifted vocals. Retiming the
        # resulting timestamps by dividing by `speed` afterwards is an exact
        # linear transform, not an approximation, so nothing is lost by doing
        # it this way round.
        flow["stage"] = "pipeline"
        flow["stage_started_at"] = time.monotonic()
        cmd = [sys.executable, "-m", "aisongtool.cli", "run",
               "--song", str(local_song), "--out", str(job_dir / "out")]
        if lyrics_path is not None:
            cmd += ["--lyrics", str(lyrics_path)]
        code = jobs.run_blocking(cmd, cwd=job_dir)
        flow["pipeline_returncode"] = code
        if code != 0:
            flow["error_message"] = "Pipeline failed — check the Terminal tab for details."
            flow["stage"] = "error"
            return

        ass_path = job_dir / "out" / "karaoke.ass"
        if not ass_path.exists():
            flow["error_message"] = ("Pipeline finished, but no lyrics were supplied so "
                                      "there's no karaoke timing — the lyrics nightcore video "
                                      "needs lyrics. Add lyrics and run again.")
            flow["stage"] = "error"
            return

        out_dir = job_dir / "out"
        audio_out = out_dir / "nightcore_audio.mp3"
        ass_out = out_dir / "nightcore_karaoke.ass"
        video_out = out_dir / "lyrics_nightcore_video.mp4"
        flow["audio_out"] = audio_out
        flow["video_out"] = video_out

        flow["stage"] = "nightcore_audio"
        flow["stage_started_at"] = time.monotonic()
        cmd = build_nightcore_audio_cmd(local_song, audio_out, DEFAULT_SPEED)
        code = jobs.run_blocking(cmd, cwd=out_dir)
        if code != 0:
            flow["render_returncode"] = code
            flow["error_message"] = "Nightcore audio step failed — check the Terminal tab."
            flow["stage"] = "error"
            return

        flow["stage"] = "retime"
        retime_karaoke_ass(ass_path, ass_out, DEFAULT_SPEED)

        flow["stage"] = "video"
        flow["stage_started_at"] = time.monotonic()
        cmd = build_render_cmd(image_path, audio_out, ass_out, video_out)
        code = jobs.run_blocking(cmd, cwd=out_dir)
        flow["render_returncode"] = code
        if code != 0:
            flow["error_message"] = "Video render failed — check the Terminal tab."
            flow["stage"] = "error"
            return

        flow["stage"] = "done"
    finally:
        flow["busy"] = False
