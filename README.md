# AiSongTool

AI-powered song subtitle generator. Upload any audio file and get perfectly timed, line-by-line lyrics subtitles in SRT, VTT, ASS, LRC, and SBV formats.

**Pipeline:** Vocal separation (Demucs) → Speech-to-text (WhisperX) → Lyrics alignment → Subtitle output

---

## Quick Start

### Native, with uv (no Docker)

```bash
cd AiSongTool
uv tool install --editable .   # installs the `aisongtool` command, uv's own Python
aisongtool setup                # provisions demucs-uv/ + whisperx-uv/ (auto-detects your GPU)
aisongtool app                  # opens the AiSongTool desktop app
```

`aisongtool app` opens a native desktop window — built with [Flet](https://flet.dev), so
the UI is genuine Material 3 (the design language Android 15 ships), with a bottom
navigation bar and four destinations:

- **Create** — the main flow: generate a song with ACE-Step-1.5 (or pick/upload an
  existing one), which automatically runs vocal separation (Demucs) + transcription/
  alignment (WhisperX) to produce SRT/ASS/VTT/LRC/SBV + karaoke timing, then pick a
  background image and confirm which processed song to use, and generate the final
  **lyrics nightcore video** (sped-up/pitched-up audio with the karaoke lyrics retimed to
  match, burned in over your image) — one guided flow, fully automated end to end. Every
  uploaded/generated song and image along the way is selectable from a dropdown, not just
  the one you just made. Lets you choose an output folder up front so the final files land
  exactly where you want.
- **Tools** — the single-purpose pieces, for when you don't want the full flow:
  *Subtitles* (song → SRT/ASS/VTT/LRC/SBV only), *Lyric Video* (existing job + image →
  plain-speed lyric video), *Nightcore* (any song + image → sped-up edit, no lyrics).
- **Terminal** — live output from whatever's currently running (pipeline, ffmpeg, setup).
- **Setup** — GPU/uv/ffmpeg status and buttons to (re)provision the isolated environments.

`aisongtool setup` auto-detects an NVIDIA GPU via `nvidia-smi` and installs the matching
CUDA or CPU torch build into two isolated `uv` environments (`demucs-uv/`, `whisperx-uv/`),
mirroring the Docker images' two-venv split so Demucs and WhisperX never fight over a
shared torch version. Re-run it with `--cpu` or `--cuda` to force a build, or `--force`
to rewrite the env definitions. `ffmpeg` (for the video feature) is a separate prerequisite
checked on the Setup view — install it system-wide and ensure it's on `PATH`.

`aisongtool app` runs the provisioning step automatically on first launch if you skip it.

#### Optional: ACE-Step-1.5 (music generation)

[ACE-Step-1.5](https://github.com/ACE-Step/ACE-Step-1.5) is a separate, optional music
generation model. It has a large, fast-moving dependency set of its own (vLLM, diffusers,
its own pinned CUDA torch build) that would conflict with AiSongTool's main env and with
demucs-uv/whisperx-uv, so it's installed the same isolated-`uv`-env way, but as a full git
clone of its own project (it ships its own `pyproject.toml`/`uv.lock`, unlike demucs-uv/
whisperx-uv, which AiSongTool authors itself):

```bash
aisongtool install-tool ace-step   # clones https://github.com/ACE-Step/ACE-Step-1.5 + `uv sync`
aisongtool ace-step app            # Gradio UI (uv run acestep)
aisongtool ace-step api            # REST API server (uv run acestep-api)
aisongtool ace-step download       # pre-fetch model checkpoints (uv run acestep-download)
```

Installing it is also available from the **Setup** view; once installed, the **Create**
flow drives it directly. `aisongtool install-tool
ace-step --update` pulls the latest changes and re-syncs. Requires `git` and `uv` on `PATH`;
downloads several GB on first install.

---

### CPU (works on any machine)

```bash
docker run -p 8000:8000 \
  -v aisongtool-hf:/root/.cache/huggingface \
  -v aisongtool-torch:/root/.cache/torch \
  tawhidunhappy/aisongtool:latest
```

Then open [http://localhost:8000](http://localhost:8000)

---

### GPU (faster — requires NVIDIA GPU + drivers)

```bash
docker run --gpus all -p 8000:8000 \
  -v aisongtool-hf:/root/.cache/huggingface \
  -v aisongtool-torch:/root/.cache/torch \
  tawhidunhappy/aisongtool:gpu
```

---

### Docker Compose

**CPU:**

```bash
docker compose up
```

**GPU:**

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
```

---

## Tags

| Tag      | Size (pull) | GPU required | Description                |
| -------- | ----------- | ------------ | -------------------------- |
| `latest` | ~1.5 GB     | No           | CPU-only, works everywhere |
| `cpu`    | ~1.5 GB     | No           | Same as latest             |
| `gpu`    | ~10 GB      | Yes (NVIDIA) | CUDA 12.1, much faster     |

---

## GPU Requirements

To use the `:gpu` image you need:

1. NVIDIA GPU (any CUDA 12.1 compatible card)
2. Up-to-date NVIDIA drivers installed on your machine
3. [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed

On Windows, Docker Desktop handles GPU passthrough automatically once drivers are installed.

---

## How It Works

1. **Upload** an audio file (MP3, WAV, M4A, AAC, FLAC, OGG, Opus) and paste your lyrics
2. **Demucs** separates vocals from the music
3. **WhisperX** transcribes and timestamps every word
4. **Alignment** matches your lyrics to the transcribed words
5. **Download** your subtitles in any format

### Output Formats

| Format | Use for                                      |
| ------ | -------------------------------------------- |
| `.srt` | Most video editors (Premiere, DaVinci, etc.) |
| `.ass` | Styled karaoke subtitles                     |
| `.vtt` | Web / YouTube                                |
| `.lrc` | Music players                                |
| `.sbv` | YouTube captions                             |

### Lyric Video

Both rely on a completed job's word-level timing (only available when lyrics were
supplied without segment mode) and a background image, burning in word-by-word
karaoke-highlighted lyrics with `ffmpeg`. Requires `ffmpeg` on `PATH` — checked on the
Setup view.

- The **Create** flow's final step additionally speeds up + pitches up the audio (the
  classic nightcore edit) and retimes the lyrics to match, so they stay in sync.
- The **Tools → Lyric Video** sub-tab does the plain-speed version only.

---

## Notes

- AI models (~3–6 GB) are downloaded on **first run** and cached in the mounted volumes. Subsequent runs are instant.
- Only one job runs at a time (pipeline or video render) — the UI tells you if one's already in progress.
- For private/gated HuggingFace models, set `HF_TOKEN` in your environment.

---

## Source

[github.com/tawhidUnhappy/AiSongTool](https://github.com/tawhidUnhappy/AiSongTool)
