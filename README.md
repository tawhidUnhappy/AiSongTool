# AiSongTool

Generate a full song — AI music generation, vocal separation, transcription/alignment,
and a finished lyric video — from one prompt, or just turn an existing song into
perfectly-timed subtitles. Desktop app for Windows, macOS, and Linux, fully self-contained.

**Pipeline:** Song generation (ACE-Step-1.5, optional) → Vocal separation (Demucs) →
Speech-to-text (WhisperX) → Lyrics alignment → Subtitles + lyric video

---

## Download (Windows / macOS / Linux)

Grab the latest build from the
[Releases page](https://github.com/tawhidUnhappy/AiSongTool/releases) — each release
ships both a portable build (no install, run from anywhere) and a system installer:

| Platform | Installer                          | Portable             |
| -------- | ----------------------------------- | --------------------- |
| Windows  | `*-setup.exe`                       | `*-portable.exe`       |
| macOS    | `*.dmg` (drag to Applications)      | `*.zip` (unzip and run) |
| Linux    | `*.deb` (`sudo apt install ./*.deb`) | `*.AppImage`           |

`ffmpeg`/`ffprobe` are bundled — no separate install needed. `git` and
[`uv`](https://docs.astral.sh/uv/) must already be on your system `PATH`; the app uses
them to provision everything else (the main environment, and any of WhisperX/Demucs/
Z-Image/ACE-Step-1.5 you choose to install) on first run.

Builds are unsigned (no paid code-signing certificate) — Windows SmartScreen / macOS
Gatekeeper will warn on first launch; that's expected, not a sign anything's wrong.

### First run

1. Open the **Setup** tab. It shows the app's one data folder (every model, cache, job,
   and setting this app ever writes lives there — see [Self-contained](#self-contained)
   below) and lets you provision the environments you need.
2. Click **Run setup**, then install whichever optional tools you want (ACE-Step-1.5 for
   song generation, Z-Image for background images). Each downloads its own models on
   first use — expect several GB and a real wait the first time.
3. Head to **Create** and generate a song, or **Tools** to just subtitle/edit an existing
   one.

### Self-contained

Every model, cache (Hugging Face, torch, `uv`), job, output file, and setting this app
writes lives under **one** data folder (shown at the top of the Setup tab) — never
`~/.cache`, `%LOCALAPPDATA%`, or any other shared system location. Deleting that one
folder, or uninstalling (Windows NSIS installer and Linux `.deb` both clean it up
automatically; macOS ships a small "Uninstall AiSongTool" helper in the DMG), removes
everything this app has ever written — no leftover caches, no orphaned models.

### Updating

Installing a newer version over an existing install upgrades in place and never touches
your data folder — every model you've already downloaded stays put, nothing re-downloads.
This works the same way on every platform, since the data folder always lives outside the
installed app's own files. A few notes depending on how you installed:

- **Windows installer** (`*-setup.exe`): running the *same* version's installer again
  detects this and asks before reinstalling, instead of silently doing it.
- **Linux `.deb`**: `sudo apt install ./AiSongTool-<version>.deb` already reports "is
  already the newest version" for a same-version reinstall, the normal `apt` behavior.
- **Portable builds** (`*-portable.exe`, `.AppImage`, `.zip`): there's no installer at
  all — "updating" just means replacing the file. Replace it **in the same folder** to
  keep using the same data folder; running a new download from a *different* folder
  starts a fresh, separate one (Windows portable's data folder is wherever the `.exe`
  itself sits).

---

## What it does

- **Create** — the main flow: generate a song with ACE-Step-1.5 (style prompt + optional
  lyrics — its own 5Hz LM expands that into full generation metadata automatically) or
  pick/upload an existing one. The generation form's "Advanced" section exposes ACE-Step's
  *entire* `/release_task` request model (bpm/key/inference steps/guidance scale/repaint
  & cover params/5Hz LM tuning, etc.) as native fields — parsed directly from ACE-Step's
  own request model on disk and regenerated after every install/update/reset, so it never
  goes stale even though it's not hand-maintained here. Either way (generate or pick
  existing) it automatically runs vocal separation (Demucs) and transcription/alignment
  (WhisperX) to produce SRT/ASS/VTT/LRC/SBV + karaoke timing, generates or lets you pick a
  background image, and renders the final lyric video — optionally with the nightcore
  speed/pitch edit, on by default. One guided flow, end to end.
- **Tools** — the single-purpose pieces, for when you don't want the full flow:
  *Subtitles* (song → SRT/ASS/VTT/LRC/SBV only), *Lyric Video* (existing job + image →
  plain-speed lyric video), *Nightcore* (any song + image → sped-up edit, no lyrics).
- **Terminal** — live output from whatever's currently running (pipeline, ffmpeg, setup,
  model installs).
- **Setup** — GPU/`uv`/ffmpeg status, the data folder path, and buttons to (re)provision
  every environment.

### Optional tools, each in their own isolated environment

Demucs, WhisperX, Z-Image (background images), and
[ACE-Step-1.5](https://github.com/ACE-Step/ACE-Step-1.5) (song generation) each install
into their own `uv`-managed environment so their dependencies never conflict with each
other. ACE-Step-1.5 in particular ships its own `pyproject.toml`/`uv.lock` (a full `git
clone` + `uv sync`, not an environment AiSongTool authors itself) and picks the right
CUDA/MPS/ROCm/CPU `torch` build automatically. All of it installs from the **Setup** tab;
GPU (NVIDIA) is auto-detected and used when present, falling back to CPU otherwise.

---

## Running from source / headless (Docker)

The desktop app is the primary way to use AiSongTool. For a headless server deployment
(no GUI), a separate Docker image is also maintained — it exposes the core subtitle
pipeline (no Electron, no ACE-Step) over HTTP:

```bash
docker run -p 8000:8000 \
  -v aisongtool-hf:/root/.cache/huggingface \
  -v aisongtool-torch:/root/.cache/torch \
  tawhidunhappy/aisongtool:latest
```

Then open [http://localhost:8000](http://localhost:8000). GPU build (`:gpu`, needs
[nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)):

```bash
docker run --gpus all -p 8000:8000 \
  -v aisongtool-hf:/root/.cache/huggingface \
  -v aisongtool-torch:/root/.cache/torch \
  tawhidunhappy/aisongtool:gpu
```

Or with Docker Compose: `docker compose up` (CPU) / `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up` (GPU).

| Tag      | Size (pull) | GPU required | Description                |
| -------- | ----------- | ------------ | -------------------------- |
| `latest` | ~1.5 GB     | No           | CPU-only, works everywhere |
| `cpu`    | ~1.5 GB     | No           | Same as latest             |
| `gpu`    | ~10 GB      | Yes (NVIDIA) | CUDA, much faster          |

### Building the desktop app yourself

```bash
git clone https://github.com/tawhidUnhappy/AiSongTool.git
cd AiSongTool/desktop
npm install
npm run dev          # run in dev mode
npm run build:win    # or build:mac / build:linux — produces installers in desktop/dist/
```

`build:mac`/`build:linux`/`build:win` each fetch (or, on macOS, compile from source) a
static LGPL ffmpeg/ffprobe build into `desktop/resources/ffmpeg/` before packaging — see
`desktop/scripts/fetch-ffmpeg.mjs`.

---

## Output Formats

| Format | Use for                                      |
| ------ | --------------------------------------------- |
| `.srt` | Most video editors (Premiere, DaVinci, etc.)  |
| `.ass` | Styled karaoke subtitles                      |
| `.vtt` | Web / YouTube                                 |
| `.lrc` | Music players                                 |
| `.sbv` | YouTube captions                              |

---

## Notes

- AI models are downloaded on first use of each tool and cached in the app's one data
  folder (or the mounted Docker volumes, for the headless image). Subsequent runs are
  instant.
- Only one job runs at a time (generation, pipeline, or video render) — the UI tells you
  if one's already in progress.
- For private/gated Hugging Face models, set `HF_TOKEN` in your environment.

---

## Source

[github.com/tawhidUnhappy/AiSongTool](https://github.com/tawhidUnhappy/AiSongTool)
