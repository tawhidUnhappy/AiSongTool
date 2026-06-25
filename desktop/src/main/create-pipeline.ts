/**
 * Port of `aisongtool/flet_app/views/_create_pipeline.py` — the Create
 * flow's stage logic. Mutates a single module-level `flow` object (this app
 * only ever runs one Create job at a time, same as the single-job lock in
 * jobs.ts) instead of Python's per-build closure dict; the renderer gets it
 * pushed after every change instead of polling.
 */
import { appendFileSync, copyFileSync, existsSync, mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { shortId } from './short-id'
import * as aceStep from './tools/ace-step'
import * as aceStepApi from './tools/ace-step-api'
import * as gemmaWriter from './tools/gemma-writer'
import * as zimage from './tools/zimage'
import * as syrex from './tools/syrex'
import { buildNightcoreAudioCmd, nightcoreVideoInPlace, DEFAULT_SPEED } from './tools/nightcore'
import { renderVideoWithFallback } from './tools/video'
import { jobsDir, mainVenvPython, repoRoot } from './paths'
import { killProcessTree, runBlocking, spawnDetached, type OnData } from './jobs'
import { waitForGpuMemoryFree } from './gpu'
import { getSettings } from './settings'
import type { CreateFlow, CreateGenOptions, CreateRunParams } from '../shared/types'

export type Flow = CreateFlow
export type GenOptions = CreateGenOptions
export type RunAllParams = CreateRunParams

// Writes straight to disk, independent of the Terminal pane / xterm buffer
// — temporary diagnostic for tracking down why the ACE-Step server-shutdown
// log lines weren't showing up in the terminal despite the code looking
// correct: this confirms (or disproves) that the code path actually runs,
// without relying on what did or didn't survive a manual terminal copy.
function debugLog(line: string): void {
  try {
    mkdirSync(jobsDir(), { recursive: true })
    appendFileSync(path.join(jobsDir(), '_debug.log'), `[${new Date().toISOString()}] ${line}\n`)
  } catch {
    // best-effort only
  }
}

function freshFlow(): Flow {
  return {
    stage: null,
    stageStartedAt: null,
    genProgressText: null,
    busy: false,
    errorMessage: null,
    jobDir: null,
    songPath: null,
    pipelineReturncode: null,
    renderReturncode: null,
    videoOut: null,
    audioOut: null,
    runStartedAt: null,
    elapsedSeconds: null
  }
}

// Hardcoded per the "Minimalistic Sky" template card — see generateImage's
// `literal` call site below, which skips zimage's usual song-style-derived
// prompt entirely for this template.
const SKY_TEMPLATE_PROMPT = 'Minimalistic red sky'

let flow: Flow = freshFlow()
// Defaults to `<repoRoot>/output` so saved artifacts go somewhere
// predictable out of the box instead of always prompting a save dialog —
// still overridable via the Create view's "Choose folder" button.
let outputDir: string = path.join(repoRoot(), 'output')

export function getFlow(): Flow {
  return flow
}

export function setOutputDir(dir: string): void {
  outputDir = dir
}

export function getOutputDir(): string {
  mkdirSync(outputDir, { recursive: true })
  return outputDir
}

/** One-shot Gemma 4 generation — a worker process loads the model, writes
 * one JSON result, exits. Failure here aborts the whole run (unlike a bad
 * image, a missing song style/lyrics means there's nothing for ACE-Step to
 * generate from). Called once whenever ANY of song name/style/lyrics is set
 * to 'gemma' — the caller picks out only the fields it actually asked for,
 * discarding the rest, rather than this function only writing a subset.
 * `referenceSong`, when non-empty, switches to Gemma's 'reference' mode —
 * write a new, original song inspired by the pasted reference's style,
 * not a copy of it (see gemma_write.py's _REFERENCE_INSTRUCTIONS). */
async function writeWithGemma(
  prompt: string,
  onData: OnData,
  referenceSong: string = '',
  duration?: number
): Promise<{ song_name: string; song_style: string; lyrics: string; image_prompt: string } | null> {
  flow.stage = 'writing'
  flow.stageStartedAt = Date.now()
  if (!gemmaWriter.isSynced()) {
    flow.errorMessage = 'Gemma 4 isn\'t installed yet. Go to the Setup view and click "Install Gemma 4" first.'
    onData(flow.errorMessage + '\r\n')
    flow.stage = 'error'
    return null
  }

  const outJson = path.join(jobsDir(), '_gemma', shortId(), 'result.json')
  let cmd: string[]
  try {
    cmd = referenceSong.trim()
      ? gemmaWriter.buildWriteFromReferenceCmd(referenceSong, outJson, duration)
      : gemmaWriter.buildWriteCmd(prompt, outJson, duration)
  } catch (exc) {
    flow.errorMessage = String((exc as Error).message)
    onData(flow.errorMessage + '\r\n')
    flow.stage = 'error'
    return null
  }

  const code = await runBlocking(cmd, gemmaWriter.destDir(), onData)
  if (code !== 0) {
    flow.errorMessage = 'Gemma 4 failed to write the song name/style/lyrics/image prompt — check the Terminal pane.'
    flow.stage = 'error'
    return null
  }

  try {
    return gemmaWriter.readResult(outJson)
  } catch (exc) {
    flow.errorMessage = String((exc as Error).message)
    flow.stage = 'error'
    return null
  }
}

/** Resolves vocal_language when left on "Auto" — asks Gemma 4 to detect it
 * from the literal lyrics text instead of leaving it blank for acestep.cpp
 * to guess from the caption alone (see ace-step-api.ts's generateSong docs
 * for why that guess has been observed picking a wrong language entirely).
 * Falls back to English on any failure (missing Gemma 4, no lyrics text to
 * detect from, etc.) rather than aborting the run. */
async function detectLanguage(lyrics: string, onData: OnData): Promise<string> {
  if (!lyrics.trim() || !gemmaWriter.isSynced()) return 'en'
  flow.stage = 'detecting_language'
  flow.stageStartedAt = Date.now()
  const outJson = path.join(jobsDir(), '_gemma_lang', shortId(), 'result.json')
  try {
    const cmd = gemmaWriter.buildDetectLanguageCmd(lyrics, outJson)
    const code = await runBlocking(cmd, gemmaWriter.destDir(), onData)
    if (code !== 0) {
      onData("Gemma 4 failed to detect the lyrics' language — defaulting to English.\r\n")
      return 'en'
    }
    return gemmaWriter.readDetectLanguageResult(outJson)
  } catch (exc) {
    onData(String((exc as Error).message) + '\r\n')
    return 'en'
  }
}

/** Runs ACE-Step end to end: install check -> start its API server ->
 * generate -> explicitly shut the server down again (frees the GPU before
 * Demucs/WhisperX run next). `vocalLanguage` and `songName` are passed in
 * already resolved (manual text, or Gemma 4's output) by the caller. */
async function generateSong(
  prompt: string,
  lyrics: string,
  duration: number,
  songName: string,
  vocalLanguage: string,
  instrumental: boolean,
  seed: number | null,
  onData: OnData
): Promise<{ songPath: string | null; lyricsText: string }> {
  debugLog('generateSong: entered')
  flow.stage = 'gen_checking'
  if (!aceStep.isSynced()) {
    flow.errorMessage =
      'ACE-Step-1.5 isn\'t installed yet. Go to the Setup view and click "Install / update ACE-Step" first.'
    onData(flow.errorMessage + '\r\n')
    flow.stage = 'error'
    return { songPath: null, lyricsText: '' }
  }

  let serverPid: number | null = null
  try {
    if (!(await aceStepApi.isServerUp())) {
      flow.stage = 'gen_starting_server'
      flow.stageStartedAt = Date.now()
      const cmd = aceStep.buildServerCmd()
      serverPid = spawnDetached(cmd, aceStep.binDir(), onData)
      if (!(await aceStepApi.waitForServer(undefined, undefined, 300_000, onData))) {
        flow.errorMessage = 'ACE-Step API server did not start in time.'
        onData(flow.errorMessage + '\r\n')
        flow.stage = 'error'
        return { songPath: null, lyricsText: '' }
      }
    }

    flow.stage = 'gen_generating'
    flow.stageStartedAt = Date.now()
    const genOutDir = path.join(jobsDir(), '_songgen', shortId())
    const audioPath = await aceStepApi.generateSong({
      prompt,
      lyrics,
      duration,
      outDir: genOutDir,
      log: onData,
      songName,
      vocalLanguage,
      instrumental,
      seed,
      onProgress: (text) => (flow.genProgressText = text)
    })
    const returnedLyrics = instrumental ? '' : lyrics
    return { songPath: audioPath, lyricsText: returnedLyrics }
  } catch (exc) {
    flow.errorMessage = String((exc as Error).message ?? exc)
    flow.stage = 'error'
    return { songPath: null, lyricsText: '' }
  } finally {
    debugLog(`generateSong finally: serverPid=${serverPid}`)
    if (serverPid !== null) {
      // Closing the server clobbers flow.stage while it runs, so remember
      // whether an error was already recorded above and restore it
      // afterwards — otherwise a failed generation gets permanently stuck
      // showing "shutting down the server" instead of the actual error.
      const hadError = flow.errorMessage !== null
      flow.stage = 'gen_closing_server'
      onData('Closing ACE-Step API server to free the GPU...\r\n')
      debugLog('Closing ACE-Step API server: onData call made, starting kill...')
      // A plain kill only hits the immediate child — ACE-Step's server
      // forks its own worker process(es) for model serving, which would
      // otherwise keep running and holding the GPU. Await the kill itself
      // finishing (not just being requested), then actually confirm the GPU
      // driver has reclaimed the dead process's VRAM (rather than guessing
      // a fixed delay was long enough) before the next step (Z-Image-Turbo,
      // if image_source is "auto") tries to load its own model onto the
      // same GPU — ACE-Step's server alone holds ~8GB on a 12GB card, so a
      // race here reliably OOMs the very next load.
      await killProcessTree(serverPid)
      debugLog('killProcessTree resolved')
      onData('Waiting for the GPU to free up...\r\n')
      await waitForGpuMemoryFree()
      debugLog('waitForGpuMemoryFree resolved — server shutdown complete')
      if (hadError) flow.stage = 'error'
    }
  }
}

/** One-shot Z-Image-Turbo generation — no server lifecycle like ACE-Step
 * needs. Failure here just logs a warning and falls back to the default
 * background — a bad image generation shouldn't sink the whole run. */
async function generateImage(prompt: string, onData: OnData, literal: boolean = false): Promise<string | null> {
  debugLog('generateImage: entered')
  flow.stage = 'image_generating'
  flow.stageStartedAt = Date.now()
  if (!zimage.isSynced()) {
    onData(
      "Z-Image-Turbo isn't installed — using the default background image. " +
        '(Install it from the Setup view to generate one from the prompt.)\r\n'
    )
    return null
  }

  const outPath = path.join(jobsDir(), '_imagegen', shortId(), 'image.png')
  let cmd: string[]
  try {
    cmd = literal ? zimage.buildGenerateCmdLiteral(prompt, outPath) : zimage.buildGenerateCmd(prompt, outPath)
  } catch (exc) {
    onData(String((exc as Error).message) + '\r\n')
    return null
  }

  const code = await runBlocking(cmd, zimage.destDir(), onData)
  if (code !== 0 || !existsSync(outPath)) {
    onData('Image generation failed — using the default background image instead.\r\n')
    return null
  }
  return outPath
}

/** Resolves what prompt to hand to Z-Image for the background image, when
 * not already covered by the "let Gemma 4 write everything" path above —
 * either the song prompt as-is, literal manual text, or Gemma 4 asked to
 * write just an image prompt (no song style/lyrics). Falls back to
 * `fallbackPrompt` on any failure rather than aborting the whole run over a
 * background image. */
async function resolveImagePrompt(
  fallbackPrompt: string,
  imagePromptMode: RunAllParams['imagePromptMode'],
  imagePromptText: string,
  onData: OnData
): Promise<string> {
  if (imagePromptMode === 'manual') {
    return imagePromptText.trim() || fallbackPrompt
  }
  if (imagePromptMode === 'gemma') {
    flow.stage = 'writing_image_prompt'
    flow.stageStartedAt = Date.now()
    if (!gemmaWriter.isSynced()) {
      onData("Gemma 4 isn't installed — using the song prompt for the image instead.\r\n")
      return fallbackPrompt
    }
    const outJson = path.join(jobsDir(), '_gemma_image', shortId(), 'result.json')
    try {
      const cmd = gemmaWriter.buildWriteImagePromptCmd(imagePromptText.trim() || fallbackPrompt, outJson)
      const code = await runBlocking(cmd, gemmaWriter.destDir(), onData)
      if (code !== 0) {
        onData('Gemma 4 failed to write an image prompt — using the song prompt instead.\r\n')
        return fallbackPrompt
      }
      return gemmaWriter.readImagePromptResult(outJson)
    } catch (exc) {
      onData(String((exc as Error).message) + '\r\n')
      return fallbackPrompt
    }
  }
  return fallbackPrompt // 'song'
}

function sanitizeFilename(name: string): string {
  return name
    .trim()
    .replace(/[\\/:*?"<>|]/g, '')
    .slice(0, 80)
}

export async function runAll(params: RunAllParams, onData: OnData): Promise<void> {
  try {
    let { prompt, songName, genLyrics: lyrics, imagePath, duration } = params
    const {
      mode,
      existingSong,
      existingLyrics,
      captionSource,
      template,
      nightcore,
      imageSource,
      imagePromptMode,
      imagePromptText,
      referenceSong
    } = params
    const genOptions = params.genOptions
    const useReference = referenceSong.trim().length > 0
    let songPath: string | null
    let lyricsText: string

    if (mode === 'generate') {
      // Each of song name/style/lyrics is independently 'manual' or
      // 'gemma' — call Gemma 4 at most once if ANY of them need it, then
      // pick out only the fields actually asked for. A pasted reference
      // song always writes all three together (it's one inspired-by call),
      // overriding the per-field source pickers.
      const needsGemma =
        useReference ||
        genOptions.songNameSource === 'gemma' ||
        genOptions.songStyleSource === 'gemma' ||
        (!genOptions.instrumental && genOptions.lyricsSource === 'gemma')
      let written: Awaited<ReturnType<typeof writeWithGemma>> = null
      if (needsGemma) {
        written = await writeWithGemma(prompt, onData, useReference ? referenceSong : '', duration)
        if (written === null) return // flow.errorMessage/stage already set
      }

      if ((useReference || genOptions.songNameSource === 'gemma') && written) songName = written.song_name
      if ((useReference || genOptions.songStyleSource === 'gemma') && written) prompt = written.song_style
      if (!genOptions.instrumental && (useReference || genOptions.lyricsSource === 'gemma') && written) {
        lyrics = written.lyrics
        // Gemma was already told this exact `duration` (see the
        // writeWithGemma call above) and sizes its lyrics for it, so the
        // user's selected duration stays in force here too instead of being
        // overridden to -1/auto-fit — previously, before Gemma had any
        // duration awareness at all, -1 was the only way to get audio
        // length that didn't fight an arbitrarily-sized lyrics block; now
        // that the lyrics are already roughly sized to match, asking
        // ACE-Step for the literal target duration keeps the final song
        // actually matching what was selected, with Gemma's lyrics doing
        // most of the work of making that not require much pacing
        // compression/stretching.
      }

      let vocalLanguage = genOptions.vocalLanguage
      if (vocalLanguage === 'unknown' && !genOptions.instrumental) {
        vocalLanguage = await detectLanguage(lyrics, onData)
      }

      const result = await generateSong(
        prompt,
        lyrics,
        duration,
        songName,
        vocalLanguage,
        genOptions.instrumental,
        genOptions.seed,
        onData
      )
      songPath = result.songPath
      lyricsText = result.lyricsText
      if (songPath === null) return // flow.errorMessage/stage already set

      if (imageSource === 'auto') {
        if (template === 'sky') {
          // The "Minimalistic Sky" template hardcodes the image-generation
          // prompt outright — every other source (song style, Gemma's own
          // image prompt, manual text) is ignored so this template's look
          // stays exactly the same regardless of the song.
          const generatedImage = await generateImage(SKY_TEMPLATE_PROMPT, onData, true)
          if (generatedImage !== null) imagePath = generatedImage
        } else {
          // 'song' mode reuses Gemma's image prompt if it already ran for
          // name/style/lyrics (no point asking twice), else the literal
          // style prompt.
          const songPromptForImage = written?.image_prompt ?? prompt
          const imagePrompt = await resolveImagePrompt(songPromptForImage, imagePromptMode, imagePromptText, onData)
          const generatedImage = await generateImage(imagePrompt, onData)
          if (generatedImage !== null) imagePath = generatedImage
        }
      }
    } else {
      songPath = existingSong
      lyricsText = existingLyrics
    }

    if (songPath === null) {
      flow.errorMessage = 'No song to work with.'
      flow.stage = 'error'
      return
    }

    const jobDir = path.join(jobsDir(), '_create', shortId())
    mkdirSync(path.join(jobDir, 'input'), { recursive: true })
    mkdirSync(path.join(jobDir, 'out'), { recursive: true })
    const localSong = path.join(jobDir, 'input', path.basename(songPath))
    copyFileSync(songPath, localSong)
    flow.jobDir = jobDir
    flow.songPath = localSong

    let lyricsPath: string | null = null
    if (lyricsText.trim()) {
      lyricsPath = path.join(jobDir, 'input', 'lyrics.txt')
      writeFileSync(lyricsPath, lyricsText, 'utf-8')
    }

    // Transcribe the *original*-pitch song first — Whisper's accuracy drops
    // sharply on nightcore's pitch-shifted vocals (confirmed: captions came
    // out "wrong and unsync" when transcription ran on the sped-up audio
    // instead). Retiming the resulting timestamps by dividing by `speed`
    // afterwards is an exact linear transform, not an approximation, so
    // there's no accuracy lost by doing it this way round.
    flow.stage = 'pipeline'
    flow.stageStartedAt = Date.now()
    const pipelineSettings = getSettings()
    const pipelineCmd = [
      mainVenvPython(),
      '-m',
      'aisongtool.cli',
      'run',
      '--song',
      localSong,
      '--out',
      path.join(jobDir, 'out'),
      '--whisper_model',
      pipelineSettings.whisperModel,
      '--caption_source',
      captionSource,
      '--demucs_model',
      pipelineSettings.demucsModel,
      '--vad',
      pipelineSettings.vad
    ]
    if (pipelineSettings.demucsShifts > 0) pipelineCmd.push('--demucs_shifts', String(pipelineSettings.demucsShifts))
    if (lyricsPath !== null) pipelineCmd.push('--lyrics', lyricsPath)
    const pipelineCode = await runBlocking(pipelineCmd, jobDir, onData)
    flow.pipelineReturncode = pipelineCode
    if (pipelineCode !== 0) {
      flow.errorMessage = 'Pipeline failed — check the Terminal pane for details.'
      flow.stage = 'error'
      return
    }

    const assPath = path.join(jobDir, 'out', 'karaoke.ass')
    const srtPath = path.join(jobDir, 'out', 'final.srt')
    if (template === 'sky' && !existsSync(assPath)) {
      flow.errorMessage =
        'Pipeline finished, but no lyrics were supplied so there\'s no karaoke timing — the Minimalistic ' +
        'Sky template\'s lyric video needs lyrics. Add lyrics and run again.'
      flow.stage = 'error'
      return
    }

    const outDir = path.join(jobDir, 'out')
    const videoNormalOut = path.join(outDir, 'lyrics_video.mp4')
    // When nightcore is off, the "final" video/audio just *are* the
    // normal-speed render and the original song audio — no separate file
    // to produce, so both outputs point straight at what already exists.
    const videoOut = nightcore ? path.join(outDir, 'lyrics_nightcore_video.mp4') : videoNormalOut
    const audioOut = nightcore ? path.join(outDir, 'nightcore_audio.mp3') : localSong
    flow.audioOut = audioOut
    flow.videoOut = videoOut

    // Render the lyric video at the song's *normal* speed first — original
    // audio, original-timed captions, no retiming math involved at all —
    // then nightcore the finished video as a single whole-file edit. This
    // is strictly less work than the old order (nightcore the audio, retime
    // every caption timestamp by the same factor, render from those two
    // derived files): Demucs/WhisperX were already running on the original
    // audio either way, so accuracy there doesn't change, but skipping the
    // separate retime step removes a whole class of timing bugs since the
    // captions are simply burned into the video before anything gets sped
    // up — speeding up the finished video automatically keeps them in sync.
    flow.stage = 'video'
    flow.stageStartedAt = Date.now()
    let renderCode: number
    try {
      if (template === 'syrex') {
        const renderCmd = syrex.buildRenderCmd(
          localSong,
          imagePath,
          videoNormalOut,
          existsSync(srtPath) ? srtPath : null,
          songName
        )
        renderCode = await runBlocking(renderCmd, outDir, onData)
      } else {
        // GPU NVENC first (falls back to CPU x264 internally if that
        // fails) — the static-image render used to be a CPU-only libx264
        // encode for the song's full duration regardless of GPU
        // availability, a large chunk of total Create-run time for no
        // reason on a machine that already has an NVIDIA GPU doing
        // everything else in this pipeline.
        renderCode = await renderVideoWithFallback(imagePath, localSong, assPath, videoNormalOut, outDir, onData)
      }
    } catch (exc) {
      flow.errorMessage = String((exc as Error).message)
      flow.stage = 'error'
      return
    }
    flow.renderReturncode = renderCode
    if (renderCode !== 0) {
      flow.errorMessage = 'Video render failed — check the Terminal pane.'
      flow.stage = 'error'
      return
    }

    if (nightcore) {
      flow.stage = 'nightcore_video'
      flow.stageStartedAt = Date.now()
      const nightcoreVideoCode = await nightcoreVideoInPlace(videoNormalOut, videoOut, DEFAULT_SPEED, false, outDir, onData)
      flow.renderReturncode = nightcoreVideoCode
      if (nightcoreVideoCode !== 0) {
        flow.errorMessage = 'Nightcore video step failed — check the Terminal pane.'
        flow.stage = 'error'
        return
      }

      flow.stage = 'nightcore_audio'
      flow.stageStartedAt = Date.now()
      const nightcoreCmd = await buildNightcoreAudioCmd(localSong, audioOut, DEFAULT_SPEED)
      const nightcoreCode = await runBlocking(nightcoreCmd, outDir, onData)
      if (nightcoreCode !== 0) {
        flow.errorMessage = 'Nightcore audio step failed — check the Terminal pane.'
        flow.stage = 'error'
        return
      }
    }

    // Copy the result into the output folder automatically — previously
    // this only happened if the user noticed and clicked "Save video"/"Save
    // audio only" below, which looked like nothing had been produced at all
    // when they checked the output folder directly without clicking those.
    try {
      const destDir = getOutputDir()
      const baseName = sanitizeFilename(songName) || `song_${path.basename(jobDir)}`
      copyFileSync(videoOut, path.join(destDir, `${baseName}.mp4`))
      copyFileSync(audioOut, path.join(destDir, `${baseName}_audio.mp3`))
      onData(`Saved video + audio to ${destDir}\r\n`)
    } catch (exc) {
      onData(`Could not auto-save to the output folder: ${String(exc)}\r\n`)
    }

    flow.stage = 'done'
  } finally {
    flow.busy = false
    if (flow.runStartedAt !== null) flow.elapsedSeconds = (Date.now() - flow.runStartedAt) / 1000
  }
}

export function startRun(params: RunAllParams, onData: OnData): void {
  if (flow.busy) {
    throw new Error('Something is already running.')
  }
  flow = freshFlow()
  flow.busy = true
  flow.runStartedAt = Date.now()
  // Fire-and-forget — the renderer polls `getFlow()` for progress. Guard
  // against an unhandled rejection (e.g. a filesystem error outside the
  // per-stage try/catches below) taking down the main process.
  runAll(params, onData).catch((exc) => {
    flow.errorMessage = `Unexpected error: ${String(exc)}`
    flow.stage = 'error'
    flow.busy = false
    if (flow.runStartedAt !== null) flow.elapsedSeconds = (Date.now() - flow.runStartedAt) / 1000
    onData(`${flow.errorMessage}\r\n`)
  })
}

export function defaultBackgroundImage(): string {
  return path.join(repoRoot(), 'aisongtool', 'flet_app', 'assets', 'nightcore_default_bg.png')
}
