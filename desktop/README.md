# desktop

AiSongTool's Electron + React + TypeScript desktop app — see the
[root README](../README.md) for what the app actually does and how to download a
release. This one's the dev-setup doc for working on the app itself.

## Recommended IDE Setup

- [VSCode](https://code.visualstudio.com/) + [ESLint](https://marketplace.visualstudio.com/items?itemName=dbaeumer.vscode-eslint) + [Prettier](https://marketplace.visualstudio.com/items?itemName=esbenp.prettier-vscode)

## Project Setup

### Install

```bash
$ npm install
```

### Development

```bash
$ npm run dev
```

### Build

```bash
# For windows
$ npm run build:win

# For macOS
$ npm run build:mac

# For Linux
$ npm run build:linux
```

Each `build:*` script first runs `fetch-ffmpeg` (see `scripts/fetch-ffmpeg.mjs`), which
fetches a static LGPL ffmpeg/ffprobe build for that platform — on macOS this compiles
ffmpeg from its own source tarball with `--disable-gpl --disable-nonfree` instead of
downloading a prebuilt binary, since no license-verified prebuilt LGPL macOS build exists
upstream — into `resources/ffmpeg/` before packaging. Not committed to git (binary,
~100MB+, OS-specific).

The packaged app's one writable data root (every isolated tool env, job, cache, and
setting — see `src/main/paths.ts`'s `dataDir()`) is **not** inside the install directory:
dev mode uses the repo root (unchanged), a portable build uses the folder next to the
running `.exe`, and an installed build uses a per-user app-data directory. `src/main/
bootstrap.ts`'s `ensureMainEnv()` provisions the main `aisongtool` venv into it on first
run in a packaged build, since a venv can't be bundled (it bakes in the absolute path of
the interpreter that created it).
