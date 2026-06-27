/** Small persisted user-preference store — which model variant each tool
 * should use. Stored as plain JSON next to the repo (gitignored), read by
 * create-pipeline.ts at generation time and written by the Setup view's
 * model dropdowns. */
import { existsSync, readFileSync, writeFileSync } from 'fs'
import path from 'path'
import { dataDir } from './paths'

export interface AppSettings {
  aceStepLmModel: string
  aceStepDitModel: string
  whisperModel: string
  promptHistoryEnabled: boolean
  imagePromptHistory: string[]

  // Create view — every dropdown/checkbox/radio remembered across restarts,
  // so reopening the app doesn't reset them to defaults. Song generation
  // itself happens in ACE-Step's own embedded Gradio UI, which keeps its
  // own state — nothing about it is persisted here.
  createMode: 'generate' | 'existing'
  createCaptionSource: 'auto' | 'transcript' | 'lyrics'
  createImageSource: 'auto' | 'pick'
  // Video template — 'sky' is the original static-image + centered Edo-font
  // captions look (background image prompt hardcoded to "Minimalistic red
  // sky"); 'syrex' is the audio-reactive visualizer (curved baseline, tower
  // spikes, panning background, bass-driven chromatic aberration).
  createTemplate: 'sky' | 'syrex'
  // Whether to speed up + pitch up the final video/audio (the genre-
  // defining nightcore edit) as the very last Create-flow step — on by
  // default (matches every run before this option existed).
  createNightcore: boolean

  // Vocal separation (Demucs) + WhisperX's voice-activity-detection backend
  // — configured once in the Setup view (same pattern as the WhisperX/
  // ACE-Step model pickers above) and used as the default by both the
  // Create flow's pipeline and the Tools view's "Transcribe to .srt".
  demucsModel: string
  demucsShifts: number
  vad: 'silero' | 'pyannote'

  // Tools view's "Transcribe to .srt" — whether to separate vocals at all
  // is a per-run, per-song call (see Tools.tsx's warning text), so it stays
  // scoped here rather than living in Setup with the rest.
  toolsSeparateVocals: boolean
}

// ACE-Step-1.5 (the original diffusers/vLLM model, replacing the earlier
// GGUF-quantized acestep.cpp port — see ace-step.ts) needs noticeably more
// VRAM per component unquantized. Per its own README's hardware matrix, the
// 2B DiT (turbo or sft) + a 0.6-1.7B LM fits comfortably in the 8-16GB tier
// most consumer GPUs are in; the XL (4B) DiT + 4B LM combo needs 20GB+. This
// app can't assume a specific card the way the old default tuned for the
// dev machine's 12GB 3060 — default to the smaller, broadly-compatible tier
// and let Setup's dropdowns opt up on bigger hardware.
export const DEFAULT_SETTINGS: AppSettings = {
  aceStepLmModel: 'acestep-5Hz-lm-1.7B',
  aceStepDitModel: 'acestep-v15-turbo',
  whisperModel: 'large-v3',
  promptHistoryEnabled: true,
  imagePromptHistory: [],

  createMode: 'generate',
  // Defaults to the WhisperX-transcript path (same as the Tools view's
  // "Transcribe to .srt", which always uses this when no lyrics are
  // pasted) rather than aligning literal lyrics text against the audio —
  // a song generated/sourced with lyrics can still skip or repeat lines
  // vs. that literal text, and the transcript-only path's pattern-aware
  // line splitter (see pipeline_core.py's _split_segment_into_lines)
  // produces more reliable, comfortable-to-read timing either way.
  createCaptionSource: 'transcript',
  createImageSource: 'auto',
  createTemplate: 'sky',
  createNightcore: true,

  demucsModel: 'htdemucs',
  demucsShifts: 0,
  vad: 'silero',

  toolsSeparateVocals: false
}

function settingsPath(): string {
  return path.join(dataDir(), 'desktop-settings.json')
}

export function getSettings(): AppSettings {
  if (!existsSync(settingsPath())) return { ...DEFAULT_SETTINGS }
  try {
    const raw = JSON.parse(readFileSync(settingsPath(), 'utf-8'))
    return { ...DEFAULT_SETTINGS, ...raw }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

export function setSetting<K extends keyof AppSettings>(key: K, value: AppSettings[K]): void {
  const current = getSettings()
  current[key] = value
  writeFileSync(settingsPath(), JSON.stringify(current, null, 2), 'utf-8')
}

const MAX_PROMPT_HISTORY = 20

/** Records a description for the image-prompt field right when a Create run
 * actually starts (not on every keystroke) — a no-op if the user has turned
 * history off (promptHistoryEnabled). Most-recent-first, de-duped, capped at
 * MAX_PROMPT_HISTORY. */
export function addImagePromptHistoryEntry(prompt: string): void {
  const trimmed = prompt.trim()
  const current = getSettings()
  if (!current.promptHistoryEnabled || !trimmed) return
  const next = [trimmed, ...current.imagePromptHistory.filter((p) => p !== trimmed)].slice(0, MAX_PROMPT_HISTORY)
  setSetting('imagePromptHistory', next)
}

export function removeImagePromptHistoryEntry(prompt: string): void {
  const current = getSettings()
  setSetting(
    'imagePromptHistory',
    current.imagePromptHistory.filter((p) => p !== prompt)
  )
}

export function clearImagePromptHistory(): void {
  setSetting('imagePromptHistory', [])
}

export const DEMUCS_MODEL_OPTIONS = [
  { value: 'htdemucs', label: 'htdemucs — fast/default' },
  { value: 'htdemucs_ft', label: 'htdemucs_ft — fine-tuned, better isolation, ~4x slower' },
  { value: 'htdemucs_6s', label: 'htdemucs_6s — 6-stem (adds guitar/piano separation)' }
]

export const DEMUCS_SHIFTS_OPTIONS = [
  { value: '0', label: 'Fast (single pass)' },
  { value: '2', label: 'Better (3x slower)' },
  { value: '5', label: 'Best (6x slower)' }
]

export const VAD_OPTIONS = [
  { value: 'silero', label: 'Fast (silero, default)' },
  { value: 'pyannote', label: 'More accurate under loud instrumentation (pyannote, slower)' }
]

export const WHISPER_MODEL_OPTIONS = [
  { value: 'tiny', label: 'tiny — fastest' },
  { value: 'base', label: 'base' },
  { value: 'small', label: 'small' },
  { value: 'medium', label: 'medium' },
  { value: 'large-v2', label: 'large-v2' },
  { value: 'large-v3', label: 'large-v3 — best accuracy' },
  { value: 'large-v3-turbo', label: 'large-v3-turbo — fast + accurate' }
]
