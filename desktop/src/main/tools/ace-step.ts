/** Port of `aisongtool/ace_step.py` — ACE-Step, now via the GGUF-quantized
 * `acestep.cpp` port (https://github.com/ServeurpersoCom/acestep.cpp)
 * instead of the original diffusers/vLLM-based ACE-Step-1.5 clone. Prebuilt
 * binaries + GGUF models downloaded into `acestep-cpp/` — no git clone /
 * `uv sync` step, just file downloads. Which LM/DiT variant is active comes
 * from `settings.ts` (the Setup view's model dropdowns), not a fixed
 * constant — see LM_MODEL_OPTIONS/DIT_MODEL_OPTIONS for the curated set of
 * variants offered. */
import { existsSync, mkdirSync, renameSync } from 'fs'
import { open, type FileHandle } from 'fs/promises'
import path from 'path'
import { dataDir } from '../paths'
import { getSettings } from '../settings'

export type LogFn = (line: string) => void

export class AceStepError extends Error {}

const DIR_NAME = 'acestep-cpp'

const BIN_FILES = [
  'ace-server.exe',
  'ace-lm.exe',
  'ace-synth.exe',
  'ggml.dll',
  'ggml-base.dll',
  'ggml-cuda.dll',
  'ggml-cpu-alderlake.dll',
  'ggml-cpu-cannonlake.dll',
  'ggml-cpu-cascadelake.dll',
  'ggml-cpu-haswell.dll',
  'ggml-cpu-icelake.dll',
  'ggml-cpu-sandybridge.dll',
  'ggml-cpu-skylakex.dll',
  'ggml-cpu-sse42.dll',
  'ggml-cpu-x64.dll'
]

// Only one published choice each (Q8_0 embedding, BF16 VAE — no quantized
// VAE variant exists), so these aren't user-selectable like LM/DiT are.
const FIXED_FILES = {
  embedding: 'Qwen3-Embedding-0.6B-Q8_0.gguf',
  vae: 'vae-BF16.gguf'
}

export interface ModelOption {
  value: string
  label: string
  sizeMb: number
}

// acestep.cpp loads one component at a time (LM, then text/lyric encoders,
// then DiT, then VAE — never all simultaneously, confirmed from its own
// server logs), so peak VRAM is bounded by whichever single component is
// largest, not the sum of all of them. That means even the largest options
// below comfortably fit a 12GB card with room to spare for KV-cache/
// activations — a curated subset of the full ~50-combination catalog
// (https://www.serveurperso.com/temp/acestep.cpp-win64/models/), not
// exhaustive.
export const LM_MODEL_OPTIONS: ModelOption[] = [
  { value: 'acestep-5Hz-lm-0.6B-Q8_0.gguf', label: '0.6B — fastest', sizeMb: 677 },
  { value: 'acestep-5Hz-lm-1.7B-Q8_0.gguf', label: '1.7B', sizeMb: 1800 },
  { value: 'acestep-5Hz-lm-4B-Q8_0.gguf', label: '4B — best quality', sizeMb: 4200 }
]

export const DIT_MODEL_OPTIONS: ModelOption[] = [
  { value: 'acestep-v15-turbo-Q8_0.gguf', label: '2B Turbo — fast (8 steps)', sizeMb: 2400 },
  { value: 'acestep-v15-sft-Q8_0.gguf', label: '2B SFT — better quality (50 steps)', sizeMb: 2400 },
  { value: 'acestep-v15-xl-turbo-Q8_0.gguf', label: 'XL (4B) Turbo — fast (8 steps)', sizeMb: 4900 },
  { value: 'acestep-v15-xl-sft-Q8_0.gguf', label: 'XL (4B) SFT — best quality (50 steps)', sizeMb: 4900 }
]

const BINARIES_BASE = 'https://www.serveurperso.com/temp/acestep.cpp-win64/build/Release'
const MODELS_BASE = 'https://www.serveurperso.com/temp/acestep.cpp-win64/models'

export function destDir(): string {
  return path.join(dataDir(), DIR_NAME)
}

export function binDir(): string {
  return path.join(destDir(), 'bin')
}

export function modelsDir(): string {
  return path.join(destDir(), 'models')
}

export function serverExe(): string {
  return path.join(binDir(), 'ace-server.exe')
}

/** The LM/DiT filenames currently selected in settings (Setup view's
 * dropdowns), plus the two fixed ones — what generation actually uses. */
export function selectedModelFiles(): { lm: string; dit: string; embedding: string; vae: string } {
  const settings = getSettings()
  return { lm: settings.aceStepLmModel, dit: settings.aceStepDitModel, ...FIXED_FILES }
}

/** Binaries downloaded (matches the old `isCloned` name so callers/IPC
 * handlers that check this before letting other actions proceed don't need
 * updating). */
export function isCloned(): boolean {
  return BIN_FILES.every((f) => existsSync(path.join(binDir(), f)))
}

/** Binaries + the currently-selected LM/DiT + the fixed embedding/VAE all
 * present — ready to actually run (matches the old `isSynced` name). */
export function isSynced(): boolean {
  if (!isCloned()) return false
  const files = selectedModelFiles()
  return Object.values(files).every((f) => existsSync(path.join(modelsDir(), f)))
}

export interface DownloadPlanEntry {
  url: string
  destPath: string
  label: string
}

/** Every file install() needs to fetch, skipping ones already on disk —
 * the actual downloading happens in ipc-handlers.ts (streamed with progress
 * over the same onData channel as everything else in the Terminal pane). */
export function downloadPlan(): DownloadPlanEntry[] {
  const plan: DownloadPlanEntry[] = []
  for (const f of BIN_FILES) {
    const destPath = path.join(binDir(), f)
    if (!existsSync(destPath)) plan.push({ url: `${BINARIES_BASE}/${f}`, destPath, label: `bin/${f}` })
  }
  for (const f of Object.values(selectedModelFiles())) {
    const destPath = path.join(modelsDir(), f)
    if (!existsSync(destPath)) plan.push({ url: `${MODELS_BASE}/${f}`, destPath, label: `models/${f}` })
  }
  return plan
}

export function buildServerCmd(host = '127.0.0.1', port = 8080): string[] {
  if (!isSynced()) {
    throw new AceStepError('ACE-Step (acestep.cpp) is not installed yet. Install it from the Setup view first.')
  }
  return [serverExe(), '--models', modelsDir(), '--host', host, '--port', String(port)]
}

function fmtMb(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

async function downloadOne(url: string, destPath: string, label: string, log: LogFn): Promise<void> {
  mkdirSync(path.dirname(destPath), { recursive: true })
  const resp = await fetch(url)
  if (!resp.ok || !resp.body) {
    throw new AceStepError(`Download failed (${resp.status}) for ${label}: ${url}`)
  }
  const totalBytes = Number(resp.headers.get('content-length') ?? 0)
  log(`Downloading ${label}${totalBytes ? ` (${fmtMb(totalBytes)})` : ''}...\r\n`)

  const tmpPath = `${destPath}.part`
  const handle: FileHandle = await open(tmpPath, 'w')
  let written = 0
  let lastLoggedMb = 0
  try {
    const reader = resp.body.getReader()
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      await handle.write(value)
      written += value.byteLength
      const writtenMb = Math.floor(written / (25 * 1024 * 1024))
      if (writtenMb !== lastLoggedMb) {
        lastLoggedMb = writtenMb
        const pct = totalBytes ? ` (${Math.round((written / totalBytes) * 100)}%)` : ''
        log(`  ${label}: ${fmtMb(written)}${pct}\r\n`)
      }
    }
  } finally {
    await handle.close()
  }
  renameSync(tmpPath, destPath)
  log(`  ${label}: done (${fmtMb(written)}).\r\n`)
}

/** Download every missing binary/model file for the currently-selected
 * LM/DiT (resumable in the sense that already-complete files are skipped on
 * the next call — partial downloads are left as `.part` files and redone
 * from scratch, no byte-range resume). Switching the LM/DiT dropdown to a
 * variant not yet on disk and calling this again fetches just that file. */
export async function install(log: LogFn = console.log): Promise<void> {
  const plan = downloadPlan()
  if (plan.length === 0) {
    log('ACE-Step (acestep.cpp) already installed.\r\n')
    return
  }
  log(`Installing ACE-Step (acestep.cpp) — ${plan.length} file(s) to fetch.\r\n`)
  for (const entry of plan) {
    await downloadOne(entry.url, entry.destPath, entry.label, log)
  }
  log('ACE-Step (acestep.cpp) ready.\r\n')
}
