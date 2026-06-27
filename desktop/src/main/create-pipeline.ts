/**
 * Port of `aisongtool/flet_app/views/_create_pipeline.py` — the Create
 * flow's stage logic. Mutates a single module-level `flow` object (this app
 * only ever runs one Create job at a time, same as the single-job lock in
 * jobs.ts) instead of Python's per-build closure dict; the renderer gets it
 * pushed after every change instead of polling.
 */
import { appendFileSync, copyFileSync, existsSync, mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { app } from 'electron'
import { shortId } from './short-id'
import * as zimage from './tools/zimage'
import * as syrex from './tools/syrex'
import { audioLibraryDir, imageLibraryDir, videoLibraryDir } from './library'
import { buildNightcoreAudioCmd, nightcoreVideoInPlace, DEFAULT_SPEED } from './tools/nightcore'
import { renderVideoWithFallback } from './tools/video'
import { jobsDir, mainVenvPython, dataDir, appResourcesDir } from './paths'
import { runBlocking, type OnData } from './jobs'
import { getSettings } from './settings'
import type { CreateFlow, CreateRunParams } from '../shared/types'

export type Flow = CreateFlow
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
// Defaults to `<dataDir>/output` so saved artifacts go somewhere predictable
// out of the box instead of always prompting a save dialog — still
// overridable via the Create view's "Choose folder" button.
let outputDir: string = path.join(dataDir(), 'output')

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

/** Resolves what prompt to hand to Z-Image for the background image —
 * either the song prompt as-is, or literal manual text. */
function resolveImagePrompt(
  fallbackPrompt: string,
  imagePromptMode: RunAllParams['imagePromptMode'],
  imagePromptText: string
): string {
  if (imagePromptMode === 'manual') {
    return imagePromptText.trim() || fallbackPrompt
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
    let { prompt, songName, imagePath } = params
    const {
      existingSong,
      existingLyrics,
      captionSource,
      template,
      nightcore,
      imageSource,
      imagePromptMode,
      imagePromptText
    } = params
    const songPath: string | null = existingSong
    const lyricsText: string = existingLyrics

    if (songPath === null) {
      flow.errorMessage = 'No song to work with.'
      flow.stage = 'error'
      return
    }

    if (imageSource === 'auto') {
      if (template === 'sky') {
        // The "Minimalistic Sky" template hardcodes the image-generation
        // prompt outright — every other source (song style, manual text)
        // is ignored so this template's look stays exactly the same
        // regardless of the song.
        const generatedImage = await generateImage(SKY_TEMPLATE_PROMPT, onData, true)
        if (generatedImage !== null) imagePath = generatedImage
      } else {
        const imagePrompt = resolveImagePrompt(prompt, imagePromptMode, imagePromptText)
        const generatedImage = await generateImage(imagePrompt, onData)
        if (generatedImage !== null) imagePath = generatedImage
      }
      if (imagePath !== params.imagePath) {
        try {
          copyFileSync(imagePath, path.join(imageLibraryDir(getOutputDir()), `${sanitizeFilename(songName) || 'image'}_${shortId()}${path.extname(imagePath)}`))
        } catch (exc) {
          onData(`Could not save the generated image to the library: ${String(exc)}\r\n`)
        }
      }
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
      const baseName = sanitizeFilename(songName) || `song_${path.basename(jobDir)}`
      const videoDestDir = videoLibraryDir(getOutputDir())
      const audioDestDir = audioLibraryDir(getOutputDir())
      copyFileSync(videoOut, path.join(videoDestDir, `${baseName}.mp4`))
      copyFileSync(audioOut, path.join(audioDestDir, `${baseName}_audio.mp3`))
      onData(`Saved video to ${videoDestDir} and audio to ${audioDestDir}\r\n`)
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
  // electron-builder auto-bundles desktop/resources/* straight into
  // process.resourcesPath (no extra `to:` mapping needed, unlike the
  // explicit aisongtool/workers/font extraResources entries) — dev mode has
  // no such flattening, so it reads the file at its actual repo location.
  return app.isPackaged
    ? path.join(process.resourcesPath, 'nightcore_default_bg.png')
    : path.join(appResourcesDir(), 'desktop', 'resources', 'nightcore_default_bg.png')
}
