/** Small persisted user-preference store — which model variant each tool
 * should use. Stored as plain JSON next to the repo (gitignored), read by
 * create-pipeline.ts at generation time and written by the Setup view's
 * model dropdowns. */
import { existsSync, readFileSync, writeFileSync } from 'fs'
import path from 'path'
import { repoRoot } from './paths'

export interface AppSettings {
  aceStepLmModel: string
  aceStepDitModel: string
  whisperModel: string
  gemmaModel: string
  promptHistory: string[]
  promptHistoryEnabled: boolean
  imagePromptHistory: string[]
  referenceSongHistory: string[]

  // Create view — every dropdown/checkbox/radio remembered across restarts,
  // so reopening the app doesn't reset them to defaults. Free-text fields
  // (prompt/lyrics/seed) aren't included here; prompt text already has its
  // own history feature, and a remembered seed would silently make every
  // future "random" run reproduce the same output.
  createMode: 'generate' | 'existing'
  createSongNameSource: 'manual' | 'gemma'
  createSongStyleSource: 'manual' | 'gemma'
  createLyricsSource: 'manual' | 'gemma'
  createInstrumental: boolean
  createVocalLanguage: string
  createDuration: number
  createCaptionSource: 'auto' | 'transcript' | 'lyrics'
  createImageSource: 'auto' | 'pick'
  createImagePromptMode: 'song' | 'manual' | 'gemma'
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
  // — configured once in the Setup view (same pattern as the WhisperX/Gemma/
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

// Defaults picked to fit comfortably in 12GB VRAM while maximizing quality:
// acestep.cpp loads one component at a time (LM, then text/lyric encoders,
// then DiT, then VAE — never all at once, confirmed from its own server
// logs), so peak VRAM is bounded by the single largest component, not the
// sum. The XL DiT's largest single component (Q8_0) is ~4.9GB and the 4B LM
// Q8_0 is ~4.2GB — both far under 12GB with room for KV-cache/activations.
//
// DiT defaults to the *turbo* (8-step, distilled) XL variant rather than
// *sft* (50-step full diffusion) — confirmed reports of glitchy audio with
// the sft variant, and a 50-step full-diffusion run has much more room for
// numerical drift to compound in a GGUF-quantized reimplementation than an
// 8-step distilled model does. Turbo at XL (4B) size is still a large
// quality upgrade over the original 2B turbo default.
export const DEFAULT_SETTINGS: AppSettings = {
  aceStepLmModel: 'acestep-5Hz-lm-4B-Q8_0.gguf',
  aceStepDitModel: 'acestep-v15-xl-turbo-Q8_0.gguf',
  whisperModel: 'large-v3',
  gemmaModel: 'google/gemma-4-E4B-it',
  promptHistory: [],
  promptHistoryEnabled: true,
  imagePromptHistory: [],
  referenceSongHistory: [],

  createMode: 'generate',
  createSongNameSource: 'manual',
  createSongStyleSource: 'manual',
  createLyricsSource: 'manual',
  createInstrumental: false,
  createVocalLanguage: 'unknown',
  // 3m20s — long enough for a full verse/chorus/verse/chorus/bridge
  // structure rather than just a short clip.
  createDuration: 200,
  // Defaults to the WhisperX-transcript path (same as the Tools view's
  // "Transcribe to .srt", which always uses this when no lyrics are
  // pasted) rather than aligning literal lyrics text against the audio —
  // a song generated/sourced with lyrics can still skip or repeat lines
  // vs. that literal text, and the transcript-only path's pattern-aware
  // line splitter (see pipeline_core.py's _split_segment_into_lines)
  // produces more reliable, comfortable-to-read timing either way.
  createCaptionSource: 'transcript',
  createImageSource: 'auto',
  createImagePromptMode: 'song',
  createTemplate: 'sky',
  createNightcore: true,

  demucsModel: 'htdemucs',
  demucsShifts: 0,
  vad: 'silero',

  toolsSeparateVocals: false
}

function settingsPath(): string {
  return path.join(repoRoot(), 'desktop-settings.json')
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

/** Records a "describe the song" prompt right when a Create run actually
 * starts (not on every keystroke) — a no-op if the user has turned history
 * off. Most-recent-first, de-duped, capped at MAX_PROMPT_HISTORY. */
export function addPromptHistoryEntry(prompt: string): void {
  const trimmed = prompt.trim()
  const current = getSettings()
  if (!current.promptHistoryEnabled || !trimmed) return
  const next = [trimmed, ...current.promptHistory.filter((p) => p !== trimmed)].slice(0, MAX_PROMPT_HISTORY)
  setSetting('promptHistory', next)
}

export function removePromptHistoryEntry(prompt: string): void {
  const current = getSettings()
  setSetting(
    'promptHistory',
    current.promptHistory.filter((p) => p !== prompt)
  )
}

export function clearPromptHistory(): void {
  setSetting('promptHistory', [])
}

/** Same idea as the "describe the song" history above, for the image
 * prompt field — shares the same on/off toggle (promptHistoryEnabled),
 * separate list since the two prompts mean different things. */
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

/** Same idea again, for the "reference song" field — pasted reference
 * lyrics/descriptions are remembered so a previous reference can be reused,
 * same on/off toggle as the other two. Deliberately separate from any
 * per-run seed (seed is never persisted) since the point of a reference
 * run is a fresh, newly-generated song every time, not a reproducible one. */
export function addReferenceSongHistoryEntry(text: string): void {
  const trimmed = text.trim()
  const current = getSettings()
  if (!current.promptHistoryEnabled || !trimmed) return
  const next = [trimmed, ...current.referenceSongHistory.filter((p) => p !== trimmed)].slice(0, MAX_PROMPT_HISTORY)
  setSetting('referenceSongHistory', next)
}

export function removeReferenceSongHistoryEntry(text: string): void {
  const current = getSettings()
  setSetting(
    'referenceSongHistory',
    current.referenceSongHistory.filter((p) => p !== text)
  )
}

export function clearReferenceSongHistory(): void {
  setSetting('referenceSongHistory', [])
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

// "E2B"/"E4B" = Gemma's elastic-parameter naming (effective ~2B/~4B compute
// from one model family), matching the E4B id already used by gemma_write.py.
export const GEMMA_MODEL_OPTIONS = [
  { value: 'google/gemma-4-E2B-it', label: 'E2B — faster' },
  { value: 'google/gemma-4-E4B-it', label: 'E4B — best quality' }
]
