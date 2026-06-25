/** Port of `aisongtool/zimage.py` — Z-Image-Turbo, a one-shot subprocess
 * (no server lifecycle like ACE-Step), already installed via the Setup
 * view's "Install Z-Image Turbo" button. */
import { existsSync } from 'fs'
import path from 'path'
import { envDir, venvPython, workersDir } from '../paths'

export class ZImageError extends Error {}

export function destDir(): string {
  return envDir('zimage-uv')
}

export function isSynced(): boolean {
  return existsSync(venvPython(destDir()))
}

// Backgrounds sit behind centered lyric text, so a busy/photorealistic
// image fights for attention with the subtitles — a consistent minimalist
// sky/cloud aesthetic (think 7CLOUD album-cover style art) keeps every
// generated background calm and legible regardless of the song's own prompt.
const STYLE_SUFFIX =
  ', minimalistic red sky, soft gradient clouds, dreamy pastel sky background, 7cloud album cover aesthetic'

function buildGenerateCmdRaw(
  prompt: string,
  outPath: string,
  width: number,
  height: number,
  seed: number | null
): string[] {
  if (!isSynced()) {
    throw new ZImageError(
      "Z-Image-Turbo isn't installed yet. Install it from the Setup view first."
    )
  }
  const cmd = [
    venvPython(destDir()),
    path.join(workersDir(), 'zimage_generate.py'),
    '--prompt',
    prompt,
    '--out',
    outPath,
    '--width',
    String(width),
    '--height',
    String(height)
  ]
  if (seed !== null) cmd.push('--seed', String(seed))
  return cmd
}

export function buildGenerateCmd(
  prompt: string,
  outPath: string,
  width = 1280,
  height = 720,
  seed: number | null = null
): string[] {
  return buildGenerateCmdRaw(prompt + STYLE_SUFFIX, outPath, width, height, seed)
}

/** Same generation, but the prompt is used exactly as given — no style
 * suffix appended. Used by the "Minimalistic Sky" template's hardcoded
 * "Minimalistic red sky" prompt, which is already the whole point. */
export function buildGenerateCmdLiteral(
  prompt: string,
  outPath: string,
  width = 1280,
  height = 720,
  seed: number | null = null
): string[] {
  return buildGenerateCmdRaw(prompt, outPath, width, height, seed)
}

/** `zimage_gradio.py` — a standalone Gradio UI that loads the model once
 * and serves repeated generations, the same shape as ACE-Step's own
 * `acestep` entry point. */
export function buildGuiCmd(port = 7861): string[] {
  if (!isSynced()) {
    throw new ZImageError("Z-Image-Turbo isn't installed yet. Install it from the Setup view first.")
  }
  return [venvPython(destDir()), path.join(workersDir(), 'zimage_gradio.py'), '--port', String(port)]
}
