/**
 * Persistent "generated songs" library — every song this app produces (the
 * Create flow's own ACE-Step generation, and anything made in the embedded
 * ACE-Step UI tab) lands in `<outputDir>/audio/` so it can be browsed and
 * reused as a fresh input later, instead of only existing buried in a
 * per-run job temp dir or wherever ACE-Step's own Gradio app happens to save
 * it. `<outputDir>/images/` and `<outputDir>/videos/` are the matching
 * destinations for generated background images and rendered videos, kept
 * separate so the output folder stays organized instead of one flat pile.
 */
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, copyFileSync, writeFileSync } from 'fs'
import path from 'path'
import * as aceStep from './tools/ace-step'

export interface LibrarySong {
  name: string
  path: string
  mtimeMs: number
  sizeMb: number
  caption: string | null
  lyrics: string | null
}

function ensureDir(dir: string): string {
  mkdirSync(dir, { recursive: true })
  return dir
}

export function audioLibraryDir(outputDir: string): string {
  return ensureDir(path.join(outputDir, 'audio'))
}

export function imageLibraryDir(outputDir: string): string {
  return ensureDir(path.join(outputDir, 'images'))
}

export function videoLibraryDir(outputDir: string): string {
  return ensureDir(path.join(outputDir, 'videos'))
}

function writeMeta(destAudioPath: string, caption: string | null, lyrics: string | null): void {
  if (!caption && !lyrics) return
  const metaPath = `${destAudioPath}.meta.json`
  writeFileSync(metaPath, JSON.stringify({ caption, lyrics }, null, 2), 'utf-8')
}

/** Called right after a Create-flow generation succeeds, before the rest of
 * the pipeline (Demucs/WhisperX/render) runs — so the raw song shows up in
 * the library immediately even if a later pipeline step fails. */
export function saveGeneratedSong(
  outputDir: string,
  srcPath: string,
  songName: string,
  caption: string,
  lyrics: string,
  uniqueSuffix: string
): void {
  const base = sanitizeFilename(songName) || 'song'
  const destPath = path.join(audioLibraryDir(outputDir), `${base}_${uniqueSuffix}.mp3`)
  copyFileSync(srcPath, destPath)
  writeMeta(destPath, caption || null, lyrics || null)
}

function sanitizeFilename(name: string): string {
  return name
    .trim()
    .replace(/[\\/:*?"<>|]/g, '')
    .slice(0, 80)
}

const AUDIO_EXTENSIONS = new Set(['.mp3', '.wav', '.m4a', '.flac', '.ogg'])

/** ACE-Step's own Gradio UI (acestep_v15_pipeline.py) saves every generation
 * into `<ace-step repo>/gradio_outputs/batch_<timestamp>/<uuid>.mp3` (plus
 * sidecar `.json`/`.npy`/`.npz` files we don't want) — confirmed by reading
 * that script's own `output_dir` setup, not assumed. Copies any file not
 * already present in the library (checked by destination filename, derived
 * deterministically from the source — no separate "already imported"
 * manifest needed) into `<outputDir>/audio/`, reading the matching `.json`
 * sidecar for `caption`/`lyrics` if present. */
export function importAceStepUiOutputs(outputDir: string): void {
  const gradioOutputs = path.join(aceStep.destDir(), 'gradio_outputs')
  if (!existsSync(gradioOutputs)) return

  const destDir = audioLibraryDir(outputDir)
  for (const batchName of readdirSync(gradioOutputs)) {
    const batchDir = path.join(gradioOutputs, batchName)
    if (!statSync(batchDir).isDirectory()) continue
    for (const fname of readdirSync(batchDir)) {
      if (path.extname(fname).toLowerCase() !== '.mp3') continue
      const srcPath = path.join(batchDir, fname)
      const destPath = path.join(destDir, `acestep-ui_${fname}`)
      if (existsSync(destPath)) continue
      copyFileSync(srcPath, destPath)

      const sidecarJson = path.join(batchDir, `${path.basename(fname, '.mp3')}.json`)
      if (existsSync(sidecarJson)) {
        try {
          const data = JSON.parse(readFileSync(sidecarJson, 'utf-8'))
          writeMeta(destPath, data.caption || null, data.lyrics || null)
        } catch {
          // Sidecar JSON is just a nice-to-have for the card preview —
          // missing/malformed metadata shouldn't block importing the song.
        }
      }
    }
  }
}

export function listAudioLibrary(outputDir: string): LibrarySong[] {
  const dir = audioLibraryDir(outputDir)
  const songs: LibrarySong[] = []
  for (const fname of readdirSync(dir)) {
    if (!AUDIO_EXTENSIONS.has(path.extname(fname).toLowerCase())) continue
    const fullPath = path.join(dir, fname)
    const stat = statSync(fullPath)
    let caption: string | null = null
    let lyrics: string | null = null
    const metaPath = `${fullPath}.meta.json`
    if (existsSync(metaPath)) {
      try {
        const meta = JSON.parse(readFileSync(metaPath, 'utf-8'))
        caption = meta.caption ?? null
        lyrics = meta.lyrics ?? null
      } catch {
        // Ignore unreadable metadata — the song itself is still usable.
      }
    }
    songs.push({ name: fname, path: fullPath, mtimeMs: stat.mtimeMs, sizeMb: stat.size / (1024 * 1024), caption, lyrics })
  }
  songs.sort((a, b) => b.mtimeMs - a.mtimeMs)
  return songs
}
