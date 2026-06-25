/** Port of `aisongtool/syrex.py` — the "Syrex" video template, an
 * audio-reactive visualizer (curved baseline, tower-shaped frequency
 * spikes, panning background, bass-driven chromatic aberration), already
 * installed via the Setup view's "Install Syrex Visualizer" button. One-
 * shot subprocess, no server lifecycle, same shape as zimage.ts. */
import { existsSync } from 'fs'
import path from 'path'
import { envDir, venvPython, workersDir } from '../paths'

export class SyrexError extends Error {}

export function destDir(): string {
  return envDir('syrex-uv')
}

export function isSynced(): boolean {
  return existsSync(venvPython(destDir()))
}

export function buildRenderCmd(
  audioPath: string,
  backgroundPath: string,
  outPath: string,
  srtPath: string | null,
  title: string,
  width = 1920,
  height = 1080,
  fps = 30
): string[] {
  if (!isSynced()) {
    throw new SyrexError("The Syrex visualizer isn't installed yet. Install it from the Setup view first.")
  }
  const cmd = [
    venvPython(destDir()),
    path.join(workersDir(), 'syrex_visualizer.py'),
    '--audio',
    audioPath,
    '--background',
    backgroundPath,
    '--out',
    outPath,
    '--width',
    String(width),
    '--height',
    String(height),
    '--fps',
    String(fps)
  ]
  if (srtPath) cmd.push('--srt', srtPath)
  if (title) cmd.push('--title', title)
  return cmd
}
