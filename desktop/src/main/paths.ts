/**
 * Path resolution into the existing Python side of the project — TS
 * equivalent of `aisongtool/paths.py` + `toolrunner.py`'s `find_uv`/
 * `venv_python`. `desktop/` sits as a sibling of `aisongtool/` at the repo
 * root.
 */
import { existsSync } from 'fs'
import os from 'os'
import path from 'path'

/** Repo root (`D:\AiSongTool`), one level up from `desktop/`. `__dirname` at
 * runtime is `desktop/out/main` (electron-vite's build output). */
export function repoRoot(): string {
  return path.resolve(__dirname, '../../..')
}

/** Matches `aisongtool.paths.data_dir()` in dev mode — same repo root, where
 * the isolated tool envs (demucs-uv/whisperx-uv/zimage-uv/gemma-uv/ace-step)
 * and `jobs/` already live. */
export function dataDir(): string {
  return repoRoot()
}

export function jobsDir(): string {
  return path.join(dataDir(), 'jobs')
}

/** Matches `aisongtool.paths.workers_dir()` — standalone scripts that run
 * inside an isolated tool's own venv (no `aisongtool` package import). */
export function workersDir(): string {
  return path.join(repoRoot(), 'workers')
}

/** The main project's own venv (has the `aisongtool` package installed,
 * `aisongtool = "aisongtool.cli:main"` per pyproject.toml) — NOT one of the
 * isolated per-tool envs. */
export function mainVenvPython(): string {
  return venvPython(repoRoot())
}

/** Matches `toolrunner.venv_python()` — the venv's own interpreter, invoked
 * directly rather than via `uv run` (which would re-sync to the lockfile's
 * CPU-default torch and undo the CUDA build `tools_install.ensure_env`
 * force-reinstalls afterward). */
export function venvPython(envDir: string): string {
  return path.join(envDir, '.venv', 'Scripts', 'python.exe')
}

export function envDir(name: string): string {
  return path.join(dataDir(), name)
}

/** Matches `toolrunner.find_uv()`. */
export function findUv(): string {
  const fromPath = whichSync('uv')
  if (fromPath) return fromPath
  const home = os.homedir()
  const candidates = [
    path.join(home, '.cargo', 'bin', 'uv.exe'),
    path.join(home, '.local', 'bin', 'uv.exe')
  ]
  for (const c of candidates) {
    if (existsSync(c)) return c
  }
  throw new Error('uv not found. Ensure `uv --version` works.')
}

/** Matches `toolrunner.find_ffmpeg()`. */
export function findFfmpeg(): string {
  const found = whichSync('ffmpeg')
  if (!found) throw new Error('ffmpeg not found. Install it and ensure `ffmpeg -version` works.')
  return found
}

/** Matches `nightcore._find_ffprobe()` — falls back to deriving it from
 * ffmpeg's own path (same install, same dir) if not separately on PATH. */
export function findFfprobe(): string {
  const found = whichSync('ffprobe')
  if (found) return found
  return findFfmpeg().replace(/ffmpeg(\.\w+)?$/i, (_m, ext) => `ffprobe${ext ?? ''}`)
}

/** Minimal PATH-search helper (Windows-only `;`-separated PATH, `.exe`/
 * `.cmd`/`.bat` suffix resolution) — avoids pulling in an extra npm package
 * for what's a handful of lines. */
function whichSync(name: string): string | null {
  const pathEnv = process.env.PATH ?? ''
  const exts = ['.exe', '.cmd', '.bat', '']
  for (const dir of pathEnv.split(path.delimiter)) {
    for (const ext of exts) {
      const candidate = path.join(dir, name + ext)
      if (existsSync(candidate)) return candidate
    }
  }
  return null
}
