# AiSongTool

AI-powered song subtitle generator. Upload any audio file and get perfectly timed, line-by-line lyrics subtitles in SRT, VTT, ASS, LRC, and SBV formats.

**Pipeline:** Vocal separation (Demucs) → Speech-to-text (WhisperX) → Lyrics alignment → Subtitle output

---

## Quick Start

### CPU (works on any machine)

```bash
docker run -p 8000:8000 \
  -v aisongtool-hf:/root/.cache/huggingface \
  -v aisongtool-torch:/root/.cache/torch \
  yuzukilies/aisongtool:latest
```

Then open [http://localhost:8000](http://localhost:8000)

---

### GPU (faster — requires NVIDIA GPU + drivers)

```bash
docker run --gpus all -p 8000:8000 \
  -v aisongtool-hf:/root/.cache/huggingface \
  -v aisongtool-torch:/root/.cache/torch \
  yuzukilies/aisongtool:gpu
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

---

## Notes

- AI models (~3–6 GB) are downloaded on **first run** and cached in the mounted volumes. Subsequent runs are instant.
- Jobs are deleted automatically after download + ~1 hour TTL.
- Rate limit: 20 jobs/hour per IP.
- For private/gated HuggingFace models, set `HF_TOKEN` in your environment.

---

## Source

[github.com/tawhidUnhappy/AiSongTool](https://github.com/tawhidUnhappy/AiSongTool)
