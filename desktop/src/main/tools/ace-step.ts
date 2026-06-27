/** Port of `aisongtool/ace_step.py` — ACE-Step-1.5
 * (https://github.com/ACE-Step/ACE-Step-1.5), installed via `git clone` +
 * `uv sync` into its own isolated env, same as every other non-trivial tool
 * here. Replaces the earlier `acestep.cpp` (GGUF/C++) backend: that one only
 * shipped prebuilt Windows binaries with no Mac/Linux release or working
 * upstream CI, which would have meant compiling a C++ engine from source
 * per-OS in our own release pipeline. The original ACE-Step-1.5 installs the
 * same way Z-Image/Syrex already do here, and gets CUDA/MPS/ROCm/CPU device
 * selection for free from `torch` — no per-OS binary at all.
 *
 * Unlike those other tools, installation itself (`git clone` + `uv sync`)
 * stays on the Python side (`aisongtool/ace_step.py`, via `aisongtool.cli
 * install-tool ace-step`) rather than being reimplemented here — see
 * `ipc-handlers.ts`'s `install-tool` handler, which no longer special-cases
 * ace-step now that it's a real clone+sync install like the rest. This file
 * only builds the server launch command and the curated model option lists
 * for the Setup view. */
import path from 'path'
import { existsSync } from 'fs'
import { dataDir, findUv, venvPython } from '../paths'

export class AceStepError extends Error {}

const DIR_NAME = 'ace-step'

export interface ModelOption {
  value: string
  label: string
  sizeMb: number
}

// Plain model names (no file paths/quantization suffixes like the old GGUF
// builds) — ACE-Step-1.5's API takes these as its `model` field and
// resolves/downloads the right Hugging Face checkpoint itself, lazily, on
// first use of that variant.
export const LM_MODEL_OPTIONS: ModelOption[] = [
  { value: 'acestep-5Hz-lm-0.6B', label: '0.6B — fastest', sizeMb: 1300 },
  { value: 'acestep-5Hz-lm-1.7B', label: '1.7B', sizeMb: 3500 },
  { value: 'acestep-5Hz-lm-4B', label: '4B — best quality', sizeMb: 8200 }
]

export const DIT_MODEL_OPTIONS: ModelOption[] = [
  { value: 'acestep-v15-turbo', label: '2B Turbo — fast (8 steps)', sizeMb: 4800 },
  { value: 'acestep-v15-sft', label: '2B SFT — better quality (50 steps)', sizeMb: 4800 },
  { value: 'acestep-v15-xl-turbo', label: 'XL (4B) Turbo — fast (8 steps)', sizeMb: 9600 },
  { value: 'acestep-v15-xl-sft', label: 'XL (4B) SFT — best quality (50 steps)', sizeMb: 9600 }
]

export function destDir(): string {
  return path.join(dataDir(), DIR_NAME)
}

export function isCloned(): boolean {
  const d = destDir()
  return existsSync(path.join(d, '.git')) && existsSync(path.join(d, 'pyproject.toml'))
}

export function isSynced(): boolean {
  return isCloned() && existsSync(venvPython(destDir()))
}

/** `uv run acestep` — ACE-Step-1.5's Gradio demo UI `[project.scripts]`
 * entry point (`acestep.acestep_v15_pipeline:main`), embedded directly in
 * the Create page's generate mode via a `<webview>`, defaulting to port
 * 7860. (The headless REST server, `acestep-api`/port 8001, is used by the
 * separate Python/Docker pipeline — see `aisongtool/ace_step_api.py` — not
 * by this Electron app.) */
export function buildGuiCmd(): string[] {
  if (!isSynced()) {
    throw new AceStepError("ACE-Step-1.5 isn't installed yet. Install it from the Setup view first.")
  }
  return [findUv(), 'run', 'acestep']
}

/** `uv run acestep-download` — ACE-Step-1.5's own pre-download entry point
 * (fetches checkpoints from Hugging Face directly, not from this app). No
 * per-model-variant flags confirmed upstream yet, so this currently just
 * runs the tool's own default behavior; the Setup view's "pre-download
 * models" button otherwise relies on the server lazily fetching whichever
 * variant is selected the first time it's actually used for generation. */
export function buildDownloadModelsCmd(): string[] {
  if (!isSynced()) {
    throw new AceStepError("ACE-Step-1.5 isn't installed yet. Install it from the Setup view first.")
  }
  return [findUv(), 'run', 'acestep-download']
}
