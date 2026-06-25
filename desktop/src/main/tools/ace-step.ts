/** Port of `aisongtool/ace_step.py` — ACE-Step-1.5
 * (https://github.com/ACE-Step/ACE-Step-1.5), installed via `git clone` +
 * `uv sync` into its own isolated env, same as every other non-trivial tool
 * here. Replaces the earlier `acestep.cpp` (GGUF/C++) backend: that one only
 * shipped prebuilt Windows binaries with no Mac/Linux release or working
 * upstream CI, which would have meant compiling a C++ engine from source
 * per-OS in our own release pipeline. The original ACE-Step-1.5 installs the
 * same way Z-Image/Gemma/Syrex already do here, and gets CUDA/MPS/ROCm/CPU
 * device selection for free from `torch` — no per-OS binary at all.
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

/** `uv run acestep-api` inside the cloned repo — its own `[project.scripts]`
 * entry point for the REST server this app's `ace-step-api.ts` talks to. */
export function buildServerCmd(): string[] {
  if (!isSynced()) {
    throw new AceStepError("ACE-Step-1.5 isn't installed yet. Install it from the Setup view first.")
  }
  return [findUv(), 'run', 'acestep-api']
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
