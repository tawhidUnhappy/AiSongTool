/**
 * Path resolution into the existing Python side of the project — TS
 * equivalent of `aisongtool/paths.py` + `toolrunner.py`'s `find_uv`/
 * `venv_python`.
 *
 * Two distinct roots, conflated in earlier dev-only code because they
 * happened to be the same directory:
 *  - `appResourcesDir()`: bundled, read-only app files (workers/, the
 *    `aisongtool` package source + its pyproject.toml/uv.lock, font/) — in
 *    dev mode the repo root; in a packaged build, Electron's own bundled
 *    resources directory (electron-builder's `extraResources`/`files`).
 *  - `dataDir()`: the one writable root everything else lives under — every
 *    isolated tool env (including the main `aisongtool` venv itself now —
 *    see `mainVenvPython()`), `jobs/`, `output/`, settings, and every model/
 *    HF/torch/uv cache (see `cacheEnv()`). Dev mode: repo root (unchanged).
 *    Portable build: next to the running .exe (`PORTABLE_EXECUTABLE_DIR`,
 *    set by electron-builder's NSIS portable target). Installed build: one
 *    per-user app-data directory. Deleting this one directory removes
 *    everything this app has ever written, in every mode.
 */
import { existsSync, accessSync, constants } from 'fs'
import os from 'os'
import path from 'path'
import { app } from 'electron'

function isPortable(): boolean {
  return !!process.env.PORTABLE_EXECUTABLE_DIR
}

export function appResourcesDir(): string {
  if (!app.isPackaged) return path.resolve(__dirname, '../../..')
  return process.resourcesPath
}

export function dataDir(): string {
  if (!app.isPackaged) return path.resolve(__dirname, '../../..')
  if (isPortable()) return process.env.PORTABLE_EXECUTABLE_DIR as string
  return path.join(app.getPath('appData'), 'AiSongTool')
}

export function jobsDir(): string {
  return path.join(dataDir(), 'jobs')
}

/** Matches `aisongtool.paths.workers_dir()` — standalone scripts that run
 * inside an isolated tool's own venv (no `aisongtool` package import).
 * Bundled/read-only — never written to at runtime. */
export function workersDir(): string {
  return path.join(appResourcesDir(), 'workers')
}

/** Where the main `aisongtool` package's source + pyproject.toml/uv.lock
 * live (bundled, read-only) — what `uv sync` reads to build the main env. */
export function mainEnvProjectDir(): string {
  return appResourcesDir()
}

/** The main project's own venv (has the `aisongtool` package installed) —
 * NOT one of the isolated per-tool envs. In dev mode this is the developer's
 * own `uv sync`'d `.venv` next to pyproject.toml, same as before. In a
 * packaged build it lives in the writable data root instead of bundled: a
 * venv bakes in the absolute path of the interpreter that created it, so it
 * can't be relocated after the fact — `uv` has to create it locally on the
 * end user's own machine, same as every isolated tool env already does (see
 * `bootstrap.ts`'s `ensureMainEnv()` for the first-run `uv sync` that
 * populates it there). */
export function mainVenvPython(): string {
  if (!app.isPackaged) return venvPython(mainEnvProjectDir())
  return venvPython(dataDir())
}

/** Matches `toolrunner.venv_python()` — the venv's own interpreter, invoked
 * directly rather than via `uv run` (which would re-sync to the lockfile's
 * CPU-default torch and undo the CUDA build `tools_install.ensure_env`
 * force-reinstalls afterward). Branches Windows (`Scripts/python.exe`) vs.
 * POSIX (`bin/python`), matching the Python-side `venv_python()` this
 * mirrors. */
export function venvPython(envDir: string): string {
  return process.platform === 'win32'
    ? path.join(envDir, '.venv', 'Scripts', 'python.exe')
    : path.join(envDir, '.venv', 'bin', 'python')
}

export function envDir(name: string): string {
  return path.join(dataDir(), name)
}

/** Every model/package cache this app's child processes can produce,
 * centralized under one `caches/` subdirectory of the one data root instead
 * of each tool's own default (`~/.cache`, `%LOCALAPPDATA%`, etc.) — the
 * actual mechanism behind the "delete the app folder, nothing is left
 * anywhere else" requirement. Merged into every spawned process's env in
 * `jobs.ts`'s `trackedSpawn()`, so no individual worker script or tool
 * installer needs to set these itself. `AISONGTOOL_DATA_DIR` lets the Python
 * side (`aisongtool.paths.data_dir()`) resolve the very same root without
 * re-deriving dev/portable/installed logic on its own. */
export function cacheEnv(): Record<string, string> {
  const root = path.join(dataDir(), 'caches')
  const hfHome = path.join(root, 'huggingface')
  return {
    AISONGTOOL_DATA_DIR: dataDir(),
    XDG_CACHE_HOME: root,
    HF_HOME: hfHome,
    HF_HUB_CACHE: path.join(hfHome, 'hub'),
    TRANSFORMERS_CACHE: hfHome,
    TORCH_HOME: path.join(root, 'torch'),
    UV_CACHE_DIR: path.join(root, 'uv'),
    HF_HUB_DISABLE_TELEMETRY: '1'
  }
}

/** Matches `toolrunner.find_uv()`. */
export function findUv(): string {
  const fromPath = whichSync('uv')
  if (fromPath) return fromPath
  const home = os.homedir()
  const candidates =
    process.platform === 'win32'
      ? [path.join(home, '.cargo', 'bin', 'uv.exe'), path.join(home, '.local', 'bin', 'uv.exe')]
      : [path.join(home, '.cargo', 'bin', 'uv'), path.join(home, '.local', 'bin', 'uv')]
  for (const c of candidates) {
    if (existsSync(c)) return c
  }
  throw new Error('uv not found. Ensure `uv --version` works.')
}

/** Matches `toolrunner.find_ffmpeg()`. Checks the bundled static build
 * (electron-builder `extraResources`, see resources/ffmpeg/) before falling
 * back to a system PATH install. */
export function findFfmpeg(): string {
  const bundled = bundledFfBinary('ffmpeg')
  if (bundled) return bundled
  const found = whichSync('ffmpeg')
  if (!found) throw new Error('ffmpeg not found. Install it and ensure `ffmpeg -version` works.')
  return found
}

/** Matches `nightcore._find_ffprobe()` — falls back to deriving it from
 * ffmpeg's own path (same install, same dir) if not separately on PATH. */
export function findFfprobe(): string {
  const bundled = bundledFfBinary('ffprobe')
  if (bundled) return bundled
  const found = whichSync('ffprobe')
  if (found) return found
  return findFfmpeg().replace(/ffmpeg(\.\w+)?$/i, (_m, ext) => `ffprobe${ext ?? ''}`)
}

function bundledFfBinary(name: 'ffmpeg' | 'ffprobe'): string | null {
  const exe = process.platform === 'win32' ? `${name}.exe` : name
  const candidate = path.join(appResourcesDir(), 'ffmpeg', exe)
  return existsSync(candidate) ? candidate : null
}

/** Minimal PATH-search helper — Windows: `;`-separated `PATH`, `.exe`/
 * `.cmd`/`.bat` suffix resolution. POSIX: `:`-separated `PATH`, no suffix,
 * executable-bit check (avoids matching a same-named non-executable file). */
function whichSync(name: string): string | null {
  const pathEnv = process.env.PATH ?? ''
  const exts = process.platform === 'win32' ? ['.exe', '.cmd', '.bat', ''] : ['']
  for (const dir of pathEnv.split(path.delimiter)) {
    for (const ext of exts) {
      const candidate = path.join(dir, name + ext)
      if (!existsSync(candidate)) continue
      if (process.platform === 'win32') return candidate
      try {
        accessSync(candidate, constants.X_OK)
        return candidate
      } catch {
        continue
      }
    }
  }
  return null
}
