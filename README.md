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

`aisongtool app` opens a native desktop window with four tabs:

- **Generate Subtitles** — upload a song (+ optional lyrics), run the pipeline, download SRT/ASS/VTT/LRC/SBV.
- **Make Video** — pick a completed job, supply a background image, render an MP4 with
  word-by-word karaoke-highlighted lyrics burned in.
- **Terminal** — live output from whatever's currently running (pipeline, ffmpeg, setup).
- **Setup** — GPU/uv/ffmpeg status and a button to (re)provision the isolated environments.

`aisongtool setup` auto-detects an NVIDIA GPU via `nvidia-smi` and installs the matching
CUDA or CPU torch build into two isolated `uv` environments (`demucs-uv/`, `whisperx-uv/`),
mirroring the Docker images' two-venv split so Demucs and WhisperX never fight over a
shared torch version. Re-run it with `--cpu` or `--cuda` to force a build, or `--force`
to rewrite the env definitions. `ffmpeg` (for the video feature) is a separate prerequisite
checked on the Setup tab — install it system-wide and ensure it's on `PATH`.

`aisongtool app` runs the provisioning step automatically on first launch if you skip it.

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

The **Make Video** tab takes a completed job's audio + word-level timing (only
available when lyrics were supplied without segment mode) and a background image
you upload, and burns in word-by-word karaoke-highlighted lyrics over the image with
`ffmpeg`. Requires `ffmpeg` on `PATH` — checked on the Setup tab.

---

## Notes

- AI models (~3–6 GB) are downloaded on **first run** and cached in the mounted volumes. Subsequent runs are instant.
- Only one job runs at a time (pipeline or video render) — the UI tells you if one's already in progress.
- For private/gated HuggingFace models, set `HF_TOKEN` in your environment.

---

## Source

[github.com/tawhidUnhappy/AiSongTool](https://github.com/tawhidUnhappy/AiSongTool)
