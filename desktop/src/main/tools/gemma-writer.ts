/** Port of `aisongtool/gemma_writer.py` — Gemma 4 prompt writer, a one-shot
 * subprocess for the Create flow's per-field "let Gemma write it" options
 * (song name/style/lyrics/image prompt, plus language detection), already
 * installed via the Setup view's "Install Gemma 4" button. */
import { existsSync, readFileSync } from 'fs'
import path from 'path'
import { envDir, venvPython, workersDir } from '../paths'
import { getSettings } from '../settings'

export class GemmaWriterError extends Error {}

export interface GemmaResult {
  song_name: string
  song_style: string
  lyrics: string
  image_prompt: string
}

export function destDir(): string {
  return envDir('gemma-uv')
}

export function isSynced(): boolean {
  return existsSync(venvPython(destDir()))
}

function buildModeCmd(prompt: string, outJson: string, mode: string, duration?: number): string[] {
  if (!isSynced()) {
    throw new GemmaWriterError("Gemma 4 isn't installed yet. Install it from the Setup view first.")
  }
  const durationArgs = duration != null ? ['--duration', String(duration)] : []
  return [
    venvPython(destDir()),
    path.join(workersDir(), 'gemma_write.py'),
    '--prompt',
    prompt,
    '--out',
    outJson,
    '--mode',
    mode,
    '--model',
    getSettings().gemmaModel,
    ...durationArgs
  ]
}

/** `duration` (seconds) tells Gemma roughly how long the song will be, so
 * it writes a proportional amount of lyrics instead of a fixed length
 * regardless of the actual target — see gemma_write.py's
 * `_duration_guidance`. */
export function buildWriteCmd(prompt: string, outJson: string, duration?: number): string[] {
  return buildModeCmd(prompt, outJson, 'full', duration)
}

/** Same worker script, `--mode reference` — `referenceSong` is a pasted
 * reference song's lyrics and/or description, used purely as style
 * inspiration. The mode's instructions explicitly forbid reusing the
 * reference's actual lines/title/imagery — the result is a new, original
 * song in a similar style, not a reworded copy of the reference. */
export function buildWriteFromReferenceCmd(referenceSong: string, outJson: string, duration?: number): string[] {
  return buildModeCmd(referenceSong, outJson, 'reference', duration)
}

/** Same worker script, `--mode image_prompt` — for flows that want Gemma's
 * help with just the background image, without writing song
 * name/style/lyrics too. */
export function buildWriteImagePromptCmd(prompt: string, outJson: string): string[] {
  return buildModeCmd(prompt, outJson, 'image_prompt')
}

/** Same worker script, `--mode detect_language` — `lyrics` should be the
 * literal lyrics text (not a description). Used instead of leaving
 * vocal_language on "Auto" and letting acestep.cpp guess from the caption
 * alone, which has been observed picking a wrong language entirely. */
export function buildDetectLanguageCmd(lyrics: string, outJson: string): string[] {
  return buildModeCmd(lyrics, outJson, 'detect_language')
}

/** Validates the worker's JSON output has the keys the Create flow needs —
 * raises with a clear message rather than a confusing crash deep in the
 * orchestration code. */
export function readResult(outJson: string): GemmaResult {
  if (!existsSync(outJson)) {
    throw new GemmaWriterError('Gemma did not produce an output file.')
  }
  const data = JSON.parse(readFileSync(outJson, 'utf-8'))
  const missing = (['song_name', 'song_style', 'lyrics', 'image_prompt'] as const).filter((k) => !data[k])
  if (missing.length > 0) {
    throw new GemmaWriterError(`Gemma's output is missing: ${missing.join(', ')}`)
  }
  return data
}

export function readImagePromptResult(outJson: string): string {
  if (!existsSync(outJson)) {
    throw new GemmaWriterError('Gemma did not produce an output file.')
  }
  const data = JSON.parse(readFileSync(outJson, 'utf-8'))
  if (!data.image_prompt) {
    throw new GemmaWriterError("Gemma's output is missing: image_prompt")
  }
  return data.image_prompt
}

export function readDetectLanguageResult(outJson: string): string {
  if (!existsSync(outJson)) {
    throw new GemmaWriterError('Gemma did not produce an output file.')
  }
  const data = JSON.parse(readFileSync(outJson, 'utf-8'))
  if (!data.language) {
    throw new GemmaWriterError("Gemma's output is missing: language")
  }
  return data.language
}

/** `gemma_gradio.py` — a standalone Gradio UI that loads the model once and
 * serves repeated writes, same shape as Z-Image's/ACE-Step's own GUI entry
 * points. */
export function buildGuiCmd(port = 7862): string[] {
  if (!isSynced()) {
    throw new GemmaWriterError("Gemma 4 isn't installed yet. Install it from the Setup view first.")
  }
  return [venvPython(destDir()), path.join(workersDir(), 'gemma_gradio.py'), '--port', String(port)]
}
