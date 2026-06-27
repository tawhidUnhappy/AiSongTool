/**
 * IPC handler registration — kept separate from index.ts (window/app
 * lifecycle) so each grows independently as more views get ported.
 */
import { app, ipcMain, dialog, shell, type IpcMainInvokeEvent } from 'electron'
import { copyFileSync, existsSync } from 'fs'
import path from 'path'
import { uniqueDestPath } from './unique-path'
import {
  isJobRunning,
  isNamedGuiRunning,
  runBlocking,
  runCapture,
  setTerminalSize,
  spawnDetached,
  stopNamedGui,
  terminateCurrentJob
} from './jobs'
import { mainVenvPython, dataDir } from './paths'
import { ensureMainEnv } from './bootstrap'
import { recordTerminalChunk, getTerminalHistory } from './terminal-history'
import { importAceStepUiOutputs, listAudioLibrary } from './library'
import * as aceStep from './tools/ace-step'
import * as zimage from './tools/zimage'
import * as createPipeline from './create-pipeline'
import type { RunAllParams } from './create-pipeline'
import { runTranscribe } from './transcribe-pipeline'
import { runNightcoreVideo } from './nightcore-video-pipeline'
import type { TranscribeParams, NightcoreVideoParams } from '../shared/types'
import {
  getSettings,
  setSetting,
  addImagePromptHistoryEntry,
  removeImagePromptHistoryEntry,
  clearImagePromptHistory,
  WHISPER_MODEL_OPTIONS,
  DEMUCS_MODEL_OPTIONS,
  DEMUCS_SHIFTS_OPTIONS,
  VAD_OPTIONS,
  type AppSettings
} from './settings'

function send(event: IpcMainInvokeEvent, chunk: string): void {
  recordTerminalChunk(chunk)
  event.sender.send('terminal:data', chunk)
}

const AUDIO_EXTENSIONS = ['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'opus']
const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'bmp']
const VIDEO_EXTENSIONS = ['mp4', 'mov', 'mkv', 'webm', 'avi', 'm4v']

// Mirrors create.py's `_SUBTITLE_OUTPUTS`.
const SUBTITLE_OUTPUTS = [
  { ext: 'srt', fname: 'final.srt', label: 'Subtitles (.srt)' },
  { ext: 'ass', fname: 'final.ass', label: 'Styled (.ass)' },
  { ext: 'vtt', fname: 'final.vtt', label: 'Web (.vtt)' },
  { ext: 'lrc', fname: 'final.lrc', label: 'Music player (.lrc)' },
  { ext: 'sbv', fname: 'final.sbv', label: 'YouTube (.sbv)' }
]

export function registerIpcHandlers(): void {
  ipcMain.handle('run-setup', async (event) => {
    const onData = (chunk: string): void => send(event, chunk)
    await ensureMainEnv(onData)
    const cmd = [mainVenvPython(), '-m', 'aisongtool.cli', 'setup']
    return runBlocking(cmd, dataDir(), onData)
  })

  ipcMain.handle('install-tool', async (event, name: string) => {
    // ace-step is now a real `git clone` + `uv sync` install (ACE-Step-1.5,
    // replacing the old acestep.cpp binary downloads), same shape as
    // z-image/syrex — no more special-casing it here, it goes through the
    // same `aisongtool.cli install-tool` path as everything else.
    const onData = (chunk: string): void => send(event, chunk)
    await ensureMainEnv(onData)
    const cmd = [mainVenvPython(), '-m', 'aisongtool.cli', 'install-tool', name]
    return runBlocking(cmd, dataDir(), onData)
  })

  // "Reset to default" for ACE-Step — discards any local modifications to
  // the cloned repo (git reset --hard + clean) and pulls the latest official
  // commit, same as a fresh clone would have, without re-downloading the
  // already-synced env or any model checkpoints (both gitignored inside that
  // repo — see ace_step.py's update_to_official()).
  ipcMain.handle('reset-tool', async (event, name: string) => {
    const onData = (chunk: string): void => send(event, chunk)
    await ensureMainEnv(onData)
    const cmd = [mainVenvPython(), '-m', 'aisongtool.cli', 'reset-tool', name]
    return runBlocking(cmd, dataDir(), onData)
  })

  ipcMain.handle('launch-ace-step', (event) => {
    // `uv run acestep` — the actual Gradio demo UI (port 7860), embedded
    // directly into the Create page's generate mode via a <webview> (see
    // is-ace-step-ui-up below, which that view polls before pointing the
    // webview at the URL).
    const cmd = aceStep.buildGuiCmd()
    spawnDetached(cmd, aceStep.destDir(), (chunk) => send(event, chunk), undefined, 'ace-step')
  })

  // Polled by the renderer's embedded webview to know when the Gradio UI is
  // actually ready to load — model/UI startup can take a while, so a fixed
  // post-launch delay isn't reliable.
  ipcMain.handle('is-ace-step-ui-up', async () => {
    try {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), 2000)
      const resp = await fetch('http://127.0.0.1:7860', { signal: controller.signal })
      clearTimeout(timer)
      return resp.status < 500
    } catch {
      return false
    }
  })

  ipcMain.handle('stop-gui', (_event, name: string) => stopNamedGui(name))

  ipcMain.handle('is-gui-running', (_event, name: string) => isNamedGuiRunning(name))

  ipcMain.handle('launch-zimage-gui', (event) => {
    const cmd = zimage.buildGuiCmd()
    spawnDetached(cmd, zimage.destDir(), (chunk) => send(event, chunk), undefined, 'zimage')
  })

  // Z-Image's Gradio server can take a while to come up — model loading
  // makes a fixed post-launch delay unreliable — so the renderer offers an
  // explicit "open in browser" action instead of trying to auto-open it.
  ipcMain.handle('open-external', (_event, url: string) => shell.openExternal(url))

  ipcMain.handle('get-doctor-status', async () => {
    // First call after a fresh packaged install has no main venv yet —
    // silent here (no terminal pane open at this point) but only runs once
    // per app launch (ensureMainEnv no-ops immediately after).
    await ensureMainEnv(() => {})
    const cmd = [mainVenvPython(), '-m', 'aisongtool.cli', 'doctor']
    const stdout = await runCapture(cmd, dataDir())
    return JSON.parse(stdout)
  })

  ipcMain.handle('terminate-job', () => {
    terminateCurrentJob()
  })

  // Lets a freshly-mounted Terminal pane catch up on output from a job that
  // started before it was on screen (see terminal-history.ts) instead of
  // showing nothing and leaving the user to guess whether anything is
  // actually happening.
  ipcMain.handle('get-terminal-history', () => getTerminalHistory())

  // Lets views (Setup) disable their own install/setup buttons based on the
  // single authoritative job lock (jobs.ts) rather than only their own
  // component-local "running" state, which resets to false on remount (e.g.
  // navigating away and back) even while the job they started is still
  // genuinely in progress — clicking again then hit the job lock and surfaced
  // a raw "A job is already running" error instead of just staying disabled.
  ipcMain.handle('is-job-running', () => isJobRunning())

  // Setup view's "Data folder: <path>" line — the one directory everything
  // this app writes lives under (see paths.ts's dataDir()); deleting it (or
  // uninstalling, which does this automatically — see electron-builder.yml's
  // deleteAppDataOnUninstall/deb-after-remove.sh/Uninstall .command) resets
  // the app to a completely clean state.
  ipcMain.handle('get-data-dir', () => dataDir())

  ipcMain.handle('get-settings', () => getSettings())

  // Generic for every plain (string/boolean/number) setting — promptHistory
  // and imagePromptHistory are the exceptions, since they need
  // add/remove/clear array mutation, not a flat replace. The renderer's
  // typed `window.api.setSetting` call site is what actually keeps
  // `key`/`value` correlated; this boundary just forwards whatever
  // already-validated pair it received.
  ipcMain.handle(
    'set-setting',
    (
      _event,
      key: Exclude<keyof AppSettings, 'promptHistory' | 'imagePromptHistory'>,
      value: AppSettings[typeof key]
    ) => {
      setSetting(key, value as never)
    }
  )

  ipcMain.handle('set-prompt-history-enabled', (_event, enabled: boolean) => setSetting('promptHistoryEnabled', enabled))

  ipcMain.handle('add-image-prompt-history', (_event, prompt: string) => addImagePromptHistoryEntry(prompt))

  ipcMain.handle('remove-image-prompt-history', (_event, prompt: string) => removeImagePromptHistoryEntry(prompt))

  ipcMain.handle('clear-image-prompt-history', () => clearImagePromptHistory())

  ipcMain.handle('get-model-options', () => ({
    aceStepLm: aceStep.LM_MODEL_OPTIONS,
    aceStepDit: aceStep.DIT_MODEL_OPTIONS,
    whisper: WHISPER_MODEL_OPTIONS,
    demucs: DEMUCS_MODEL_OPTIONS,
    demucsShifts: DEMUCS_SHIFTS_OPTIONS,
    vad: VAD_OPTIONS
  }))

  // Lets the Setup view pre-fetch ACE-Step-1.5's checkpoints on demand,
  // without waiting for the first real generation request to trigger the
  // download lazily.
  ipcMain.handle('download-ace-step-models', async (event) => {
    try {
      const cmd = aceStep.buildDownloadModelsCmd()
      const code = await runBlocking(cmd, aceStep.destDir(), (chunk) => send(event, chunk))
      return code
    } catch (exc) {
      send(event, `${String(exc)}\r\n`)
      return 1
    }
  })

  ipcMain.on('terminal:resize', (_event, cols: number, rows: number) => {
    setTerminalSize(cols, rows)
  })

  // ---- Create flow --------------------------------------------------------

  ipcMain.handle('create:start-run', (event, params: RunAllParams) => {
    createPipeline.startRun(params, (chunk) => send(event, chunk))
  })

  ipcMain.handle('create:get-status', () => createPipeline.getFlow())

  ipcMain.handle('create:default-background', () => createPipeline.defaultBackgroundImage())

  ipcMain.handle('create:pick-output-dir', async () => {
    const result = await dialog.showOpenDialog({
      title: 'Choose output folder',
      properties: ['openDirectory']
    })
    if (result.canceled || result.filePaths.length === 0) return null
    createPipeline.setOutputDir(result.filePaths[0])
    return result.filePaths[0]
  })

  ipcMain.handle('create:pick-song-file', async () => {
    const result = await dialog.showOpenDialog({
      title: 'Pick a song',
      properties: ['openFile'],
      filters: [{ name: 'Audio', extensions: AUDIO_EXTENSIONS }]
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  ipcMain.handle('create:pick-image-file', async () => {
    const result = await dialog.showOpenDialog({
      title: 'Pick a background image',
      properties: ['openFile'],
      filters: [{ name: 'Images', extensions: IMAGE_EXTENSIONS }]
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  ipcMain.handle('tools:pick-video-file', async () => {
    const result = await dialog.showOpenDialog({
      title: 'Pick a video',
      properties: ['openFile'],
      filters: [{ name: 'Video', extensions: VIDEO_EXTENSIONS }]
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  ipcMain.handle('create:list-subtitle-outputs', (_event, jobDir: string) => {
    const outDir = path.join(jobDir, 'out')
    return SUBTITLE_OUTPUTS.filter(({ fname }) => existsSync(path.join(outDir, fname))).map(
      ({ ext, label }) => ({ ext, label })
    )
  })

  ipcMain.handle('create:save-artifact', (_event, srcPath: string, suggestedName: string) => {
    const dest = path.join(createPipeline.getOutputDir(), suggestedName)
    copyFileSync(srcPath, dest)
    return dest
  })

  ipcMain.handle('create:get-output-dir', () => createPipeline.getOutputDir())

  // Generated-songs library (output/audio/) — also sweeps in any new song
  // from the embedded ACE-Step Gradio UI (its own `gradio_outputs/` folder,
  // inside the cloned ace-step repo) before listing, so the Create view's
  // "existing song" card picker picks up songs made there with no extra
  // import step.
  ipcMain.handle('create:list-audio-library', () => {
    const outputDir = createPipeline.getOutputDir()
    importAceStepUiOutputs(outputDir)
    return listAudioLibrary(outputDir)
  })

  // ---- Tools (standalone single-tool utilities) ---------------------------

  ipcMain.handle('tools:transcribe', (event, params: TranscribeParams) => {
    return runTranscribe(params, (chunk) => send(event, chunk))
  })

  ipcMain.handle('tools:nightcore-video', (event, params: NightcoreVideoParams) => {
    return runNightcoreVideo(params, (chunk) => send(event, chunk))
  })

  // Downloads to the OS Downloads folder instead of the configured output
  // folder, Chrome-style: a name collision gets " (1)", " (2)", etc.
  // appended rather than overwriting or erroring.
  ipcMain.handle('tools:download-artifact', (_event, srcPath: string, suggestedName: string) => {
    const dest = uniqueDestPath(app.getPath('downloads'), suggestedName)
    copyFileSync(srcPath, dest)
    return dest
  })
}
