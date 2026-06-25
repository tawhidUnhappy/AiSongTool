/** Standalone "Transcribe to .srt" tool (Tools view) — runs just WhisperX
 * transcription via the same `aisongtool.cli run` pipeline the Create flow
 * uses, with no nightcore/video/image steps after it. Defaults to
 * `--caption_source transcript` (always use what was actually sung, no
 * lyrics needed); if the user pastes lyrics text, that gets written to a
 * file and passed through `--lyrics`/`--caption_source` instead, same as
 * the Create flow's lyrics-alignment path. */
import { copyFileSync, existsSync, mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { jobsDir, mainVenvPython } from './paths'
import { runBlocking, type OnData } from './jobs'
import { shortId } from './short-id'
import { getSettings } from './settings'
import type { TranscribeParams, TranscribeResult } from '../shared/types'

export type { TranscribeParams, TranscribeResult }

export async function runTranscribe(params: TranscribeParams, onData: OnData): Promise<TranscribeResult> {
  const jobDir = path.join(jobsDir(), '_transcribe', shortId())
  mkdirSync(path.join(jobDir, 'input'), { recursive: true })
  const localSong = path.join(jobDir, 'input', path.basename(params.songPath))
  copyFileSync(params.songPath, localSong)

  const outDir = path.join(jobDir, 'out')
  const hasLyrics = params.lyricsText.trim().length > 0
  const cmd = [
    mainVenvPython(),
    '-m',
    'aisongtool.cli',
    'run',
    '--song',
    localSong,
    '--out',
    outDir,
    '--whisper_model',
    params.whisperModel,
    '--caption_source',
    hasLyrics ? params.captionSource : 'transcript',
    '--vad',
    params.vad,
    '--demucs_model',
    getSettings().demucsModel
  ]
  if (hasLyrics) {
    const lyricsPath = path.join(jobDir, 'input', 'lyrics.txt')
    writeFileSync(lyricsPath, params.lyricsText, 'utf-8')
    cmd.push('--lyrics', lyricsPath)
  }
  if (params.skipDemucs) {
    cmd.push('--skip_demucs')
  } else if (params.demucsShifts > 0) {
    cmd.push('--demucs_shifts', String(params.demucsShifts))
  }

  const returncode = await runBlocking(cmd, jobDir, onData)
  const srtPath = path.join(outDir, 'final.srt')
  return { returncode, srtPath: returncode === 0 && existsSync(srtPath) ? srtPath : null }
}
