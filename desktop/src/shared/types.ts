/** Mirrors `aisongtool.tools_install.doctor()`'s return shape exactly —
 * see `aisongtool/cli.py`'s `doctor` subcommand, which prints this as JSON. */
export interface EnvStatus {
  provisioned: boolean
  venv_python: string | null
}

export interface GpuStatus {
  nvidia_smi: boolean
  cuda_available_in_main_env: boolean
  cuda_device: string | null
}

export interface AceStepStatus {
  cloned: boolean
  synced: boolean
  dir: string
}

export interface DoctorStatus {
  uv: string | null
  ffmpeg: string | null
  nvidia_smi: string | null
  gpu: GpuStatus
  envs: Record<string, EnvStatus>
  ace_step: AceStepStatus
}

/** Mirrors `create-pipeline.ts`'s `Flow` / `_create_pipeline.py`'s `flow`
 * dict — the Create view polls this every second while a run is busy. */
export interface CreateFlow {
  stage: string | null
  stageStartedAt: number | null
  genProgressText: string | null
  busy: boolean
  errorMessage: string | null
  jobDir: string | null
  songPath: string | null
  pipelineReturncode: number | null
  renderReturncode: number | null
  videoOut: string | null
  audioOut: string | null
  // Whole-run timer, independent of any one stage's `stageStartedAt` —
  // `runStartedAt` is fixed for the run's lifetime, `elapsedSeconds` is
  // filled in once the run finishes (success or failure) so the UI can
  // show a final "took Xm Ys" instead of a live-ticking clock forever.
  runStartedAt: number | null
  elapsedSeconds: number | null
}

/** Song name/style/lyrics are always written by the user — ACE-Step's own
 * 5Hz LM already expands the style/lyrics into full generation metadata
 * (bpm/keyscale/timesignature/CoT caption) internally as part of generation
 * itself (Gemma 4 used to do an equivalent pre-step from a short
 * description, removed in favor of relying on that). */
export interface CreateGenOptions {
  vocalLanguage: string
  instrumental: boolean
  seed: number | null
  // The Create page's schema-driven "Advanced" section — every other
  // ACE-Step `/release_task` request field (bpm, key_scale, inference_steps,
  // guidance_scale, repaint/cover params, LM tuning, etc.), keyed by
  // ACE-Step's own field names exactly, straight from ace-step-schema.ts's
  // parse of its real request model (see ace_step_schema.py) — not a fixed
  // list maintained here. Merged into the /release_task body alongside
  // prompt/lyrics/duration/vocalLanguage/seed.
  advancedFields: Record<string, unknown>
}

/** Mirrors `desktop/src/main/ace-step-schema.ts` — the generation-form
 * schema parsed from ACE-Step's own request model, regenerated after every
 * install/update/reset. */
export interface AceStepSchemaField {
  name: string
  type: 'string' | 'boolean' | 'integer' | 'number' | 'enum' | 'list'
  enumValues: string[] | null
  optional: boolean
  multiline: boolean
  default: unknown
  description: string
  min: number | null
  max: number | null
}

export interface AceStepSchema {
  fields: AceStepSchemaField[]
}

export interface CreateRunParams {
  mode: 'generate' | 'existing'
  prompt: string
  songName: string
  genLyrics: string
  duration: number
  genOptions: CreateGenOptions
  existingSong: string | null
  existingLyrics: string
  // What the subtitles/lyric-video are actually built from. 'auto': lyrics
  // if any, else the WhisperX transcript (default). 'transcript': always
  // use the transcript, even if lyrics were given — more reliable when a
  // song skips/repeats lines vs the literal lyrics text, since aligning
  // mismatched lyrics to the wrong audio produces wrong timing. 'lyrics':
  // force lyrics-alignment.
  captionSource: 'auto' | 'transcript' | 'lyrics'
  // Video template, picked as a card in the UI — 'sky': the original
  // static-image + centered Edo-font captions (background image prompt
  // hardcoded to "Minimalistic red sky"). 'syrex': an audio-reactive
  // visualizer (curved baseline, tower spikes, panning background,
  // bass-driven chromatic aberration) instead of a static background.
  template: 'sky' | 'syrex'
  // Whether to speed up + pitch up the final video/audio (the genre-defining
  // nightcore edit) as the very last step — on by default (matches every
  // run before this option existed), off renders/saves the song at its
  // normal speed/pitch instead.
  nightcore: boolean
  imageSource: 'auto' | 'pick'
  imagePath: string
  // Only consulted when imageSource === 'auto' — 'song' reuses the song
  // style/description prompt as-is, 'manual' uses imagePromptText verbatim.
  imagePromptMode: 'song' | 'manual'
  imagePromptText: string
}

/** Mirrors `desktop/src/main/settings.ts`'s `AppSettings` — which model
 * variant each tool currently uses, set via the Setup view's dropdowns. */
export interface AppSettings {
  aceStepLmModel: string
  aceStepDitModel: string
  whisperModel: string
  promptHistoryEnabled: boolean
  imagePromptHistory: string[]

  createMode: 'generate' | 'existing'
  createCaptionSource: 'auto' | 'transcript' | 'lyrics'
  createImageSource: 'auto' | 'pick'
  createImagePromptMode: 'song' | 'manual'
  createTemplate: 'sky' | 'syrex'
  createNightcore: boolean

  // Vocal separation (Demucs) + WhisperX's voice-activity-detection backend
  // — configured once in Setup (same pattern as the other model pickers),
  // used as the default by both the Create flow and the Tools view.
  demucsModel: string
  demucsShifts: number
  vad: 'silero' | 'pyannote'

  // Whether to separate vocals at all is a per-run, per-song call, so it
  // stays scoped to the Tools view rather than living with the rest above.
  toolsSeparateVocals: boolean
}

export interface ModelOption {
  value: string
  label: string
  sizeMb?: number
}

export interface ModelOptions {
  aceStepLm: ModelOption[]
  aceStepDit: ModelOption[]
  whisper: ModelOption[]
  demucs: ModelOption[]
  demucsShifts: ModelOption[]
  vad: ModelOption[]
}

/** Tools view's standalone "Transcribe to .srt" utility — just WhisperX,
 * no nightcore/video steps from the Create flow. */
export interface TranscribeParams {
  songPath: string
  whisperModel: string
  skipDemucs: boolean
  // Demucs random-shift ensembling passes — 0 (default) is a single fast
  // pass; each extra shift re-runs separation on a time-shifted copy and
  // averages the results, measurably improving vocal isolation on a
  // heavily blended mix at a proportional cost in time. Only relevant when
  // skipDemucs is false.
  demucsShifts: number
  // WhisperX's voice-activity-detection backend — 'silero' (default) is
  // fast; 'pyannote' tends to find speech more reliably under loud
  // instrumentation, at the cost of a one-time model download and being
  // slower per run.
  vad: 'silero' | 'pyannote'
  // Optional literal lyrics text — when given, enables aligning the actual
  // lyrics against the transcript instead of being transcript-only (same
  // captionSource semantics as the Create flow). Empty string = no lyrics
  // given, always transcript-only.
  lyricsText: string
  captionSource: 'auto' | 'transcript' | 'lyrics'
}

export interface TranscribeResult {
  returncode: number
  srtPath: string | null
}

/** Tools view's standalone "Nightcore a video" utility — just the audio
 * speed+pitch edit (and a matching video speed-up to stay in sync), no
 * other visual change. */
export interface NightcoreVideoParams {
  videoPath: string
  speed: number
  // Adds a subtle echo for a dreamier/echoey feel — some nightcore edits
  // use this, many don't, so it's opt-in. Bass/treble boost + loudness
  // normalization are always applied (they're close to universal in actual
  // nightcore edits, not just the speed/pitch resample).
  reverb: boolean
}

export interface NightcoreVideoResult {
  returncode: number
  videoPath: string | null
}

/** A previously-generated song available to reuse as a fresh input —
 * mirrors `desktop/src/main/library.ts`'s `LibrarySong`. */
export interface LibrarySong {
  name: string
  path: string
  mtimeMs: number
  sizeMb: number
  caption: string | null
  lyrics: string | null
}

export const STAGE_TEXT: Record<string, string> = {
  gen_checking: 'Checking ACE-Step installation...',
  gen_starting_server:
    'Starting ACE-Step API server (first start can take a couple minutes while the model loads)...',
  gen_generating: 'Generating song with ACE-Step...',
  gen_closing_server: 'Song ready — shutting down the ACE-Step server to free the GPU...',
  image_generating: 'Generating background image...',
  pipeline: 'Running pipeline: separating vocals, transcribing, aligning, building subtitles...',
  video: 'Rendering lyric video at normal speed...',
  nightcore_audio: 'Speeding up + pitching up the standalone audio file (nightcore)...',
  nightcore_video: 'Speeding up + pitching up the finished video (nightcore)...'
}
