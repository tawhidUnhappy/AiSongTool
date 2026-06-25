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

/** Each of song name/style/lyrics can independently be written by the user
 * or by Gemma 4 — any combination, instead of one all-or-nothing mode.
 * `prompt` (the "describe the song" field) doubles as the literal style
 * caption when songStyleSource is 'manual', or as Gemma's seed description
 * when any of the three is 'gemma'. */
export interface CreateGenOptions {
  songNameSource: 'manual' | 'gemma'
  songStyleSource: 'manual' | 'gemma'
  lyricsSource: 'manual' | 'gemma'
  vocalLanguage: string
  instrumental: boolean
  seed: number | null
}

export interface CreateRunParams {
  mode: 'generate' | 'existing'
  prompt: string
  songName: string
  genLyrics: string
  duration: number
  genOptions: CreateGenOptions
  // A pasted reference song (lyrics and/or a description of one), used as
  // pure style inspiration — when non-empty, overrides genOptions' three
  // name/style/lyrics sources and writes a new, original song in the
  // reference's style via Gemma's 'reference' mode instead of 'full'.
  // Empty string = not using a reference.
  referenceSong: string
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
  // Only consulted when imageSource === 'auto' and genOptions.songStyleSource
  // is 'manual' (when Gemma already wrote the style, it writes a matching
  // image prompt in the same call) — 'song' reuses the song style/
  // description prompt as before, 'manual' uses imagePromptText verbatim,
  // 'gemma' asks Gemma 4 to write just an image prompt from imagePromptText.
  imagePromptMode: 'song' | 'manual' | 'gemma'
  imagePromptText: string
}

/** Mirrors `desktop/src/main/settings.ts`'s `AppSettings` — which model
 * variant each tool currently uses, set via the Setup view's dropdowns. */
export interface AppSettings {
  aceStepLmModel: string
  aceStepDitModel: string
  whisperModel: string
  gemmaModel: string
  promptHistory: string[]
  promptHistoryEnabled: boolean
  imagePromptHistory: string[]
  referenceSongHistory: string[]

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
  gemma: ModelOption[]
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

export const STAGE_TEXT: Record<string, string> = {
  writing: 'Writing song name, style, lyrics, and image prompt with Gemma 4...',
  gen_checking: 'Checking ACE-Step installation...',
  gen_starting_server:
    'Starting ACE-Step API server (first start can take a couple minutes while the model loads)...',
  gen_generating: 'Generating song with ACE-Step...',
  gen_closing_server: 'Song ready — shutting down the ACE-Step server to free the GPU...',
  writing_image_prompt: 'Writing image prompt with Gemma 4...',
  detecting_language: 'Detecting lyrics language with Gemma 4...',
  image_generating: 'Generating background image...',
  pipeline: 'Running pipeline: separating vocals, transcribing, aligning, building subtitles...',
  video: 'Rendering lyric video at normal speed...',
  nightcore_audio: 'Speeding up + pitching up the standalone audio file (nightcore)...',
  nightcore_video: 'Speeding up + pitching up the finished video (nightcore)...'
}
