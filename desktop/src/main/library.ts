/**
 * Persistent "generated songs" library — every song the Create page's own
 * generation form produces lands in `<outputDir>/audio/` so it can be
 * browsed and reused as a fresh input later, instead of only existing
 * buried in a per-run job temp dir. `<outputDir>/images/` and
 * `<outputDir>/videos/` are the matching destinations for generated
 * background images and rendered videos, kept separate so the output folder
 * stays organized instead of one flat pile.
 */
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, copyFileSync, writeFileSync } from 'fs'
import path from 'path'

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
