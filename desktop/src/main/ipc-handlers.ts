/**
 * IPC handler registration — kept separate from index.ts (window/app
 * lifecycle) so each grows independently as more views get ported.
 */
import { app, ipcMain, dialog, shell, type IpcMainInvokeEvent } from 'electron'
import { copyFileSync, existsSync } from 'fs'
import path from 'path'
import { uniqueDestPath } from './unique-path'
import {
  isNamedGuiRunning,
  runBlocking,
  runCapture,
  setTerminalSize,
  spawnDetached,
  stopNamedGui,
  terminateCurrentJob
} from './jobs'
import { mainVenvPython, repoRoot } from './paths'
import * as aceStep from './tools/ace-step'
import * as zimage from './tools/zimage'
import * as gemmaWriter from './tools/gemma-writer'
import * as createPipeline from './create-pipeline'
import type { RunAllParams } from './create-pipeline'
import { runTranscribe } from './transcribe-pipeline'
import { runNightcoreVideo } from './nightcore-video-pipeline'
import type { TranscribeParams, NightcoreVideoParams } from '../shared/types'
import {
  getSettings,
  setSetting,
  addPromptHistoryEntry,
  removePromptHistoryEntry,
  clearPromptHistory,
  addImagePromptHistoryEntry,
  removeImagePromptHistoryEntry,
  clearImagePromptHistory,
  addReferenceSongHistoryEntry,
  removeReferenceSongHistoryEntry,
  clearReferenceSongHistory,
  WHISPER_MODEL_OPTIONS,
  GEMMA_MODEL_OPTIONS,
  DEMUCS_MODEL_OPTIONS,
  DEMUCS_SHIFTS_OPTIONS,
  VAD_OPTIONS,
  type AppSettings
} from './settings'

function send(event: IpcMainInvokeEvent, chunk: string): void {
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
    const cmd = [mainVenvPython(), '-m', 'aisongtool.cli', 'setup']
    return runBlocking(cmd, repoRoot(), (chunk) => send(event, chunk))
  })

  ipcMain.handle('install-tool', async (event, name: string) => {
    if (name === 'ace-step') {
      try {
        await aceStep.install((chunk) => send(event, chunk))
        return 0
      } catch (exc) {
        send(event, `${String(exc)}\r\n`)
        return 1
      }
    }
    const cmd = [mainVenvPython(), '-m', 'aisongtool.cli', 'install-tool', name]
    return runBlocking(cmd, repoRoot(), (chunk) => send(event, chunk))
  })

  ipcMain.handle('launch-ace-step', (event) => {
    const cmd = aceStep.buildServerCmd()
    spawnDetached(cmd, aceStep.binDir(), (chunk) => send(event, chunk), undefined, 'ace-step')
    // ace-server.exe serves its own WebUI at the same host:port — give it a
    // moment to come up before opening the browser (no /health endpoint
    // worth polling here; a fixed delay is fine for a local UI launch, unlike
    // the Create pipeline's server start which actually needs to know when
    // model loading finishes).
    setTimeout(() => shell.openExternal('http://127.0.0.1:8080'), 2000)
  })

  ipcMain.handle('stop-gui', (_event, name: string) => stopNamedGui(name))

  ipcMain.handle('is-gui-running', (_event, name: string) => isNamedGuiRunning(name))

  ipcMain.handle('launch-zimage-gui', (event) => {
    const cmd = zimage.buildGuiCmd()
    spawnDetached(cmd, zimage.destDir(), (chunk) => send(event, chunk), undefined, 'zimage')
  })

  ipcMain.handle('launch-gemma-gui', (event) => {
    const cmd = gemmaWriter.buildGuiCmd()
    spawnDetached(cmd, gemmaWriter.destDir(), (chunk) => send(event, chunk), undefined, 'gemma')
  })

  // Gemma's (and Z-Image's) Gradio server can take a while to come up —
  // unlike ace-server.exe's near-instant native binary start, model loading
  // makes a fixed post-launch delay unreliable — so the renderer offers an
  // explicit "open in browser" action instead of trying to auto-open it.
  ipcMain.handle('open-external', (_event, url: string) => shell.openExternal(url))

  ipcMain.handle('get-doctor-status', async () => {
    const cmd = [mainVenvPython(), '-m', 'aisongtool.cli', 'doctor']
    const stdout = await runCapture(cmd, repoRoot())
    return JSON.parse(stdout)
  })

  ipcMain.handle('terminate-job', () => {
    terminateCurrentJob()
  })

  ipcMain.handle('get-settings', () => getSettings())

  // Generic for every plain (string/boolean/number) setting — promptHistory
  // imagePromptHistory, and referenceSongHistory are the exceptions, since
  // they need add/remove/clear array mutation, not a flat replace. The
  // renderer's typed `window.api.setSetting` call site is what actually
  // keeps `key`/`value` correlated; this boundary just forwards whatever
  // already-validated pair it received.
  ipcMain.handle(
    'set-setting',
    (
      _event,
      key: Exclude<keyof AppSettings, 'promptHistory' | 'imagePromptHistory' | 'referenceSongHistory'>,
      value: AppSettings[typeof key]
    ) => {
      setSetting(key, value as never)
    }
  )

  ipcMain.handle('add-prompt-history', (_event, prompt: string) => addPromptHistoryEntry(prompt))

  ipcMain.handle('remove-prompt-history', (_event, prompt: string) => removePromptHistoryEntry(prompt))

  ipcMain.handle('clear-prompt-history', () => clearPromptHistory())

  ipcMain.handle('set-prompt-history-enabled', (_event, enabled: boolean) => setSetting('promptHistoryEnabled', enabled))

  ipcMain.handle('add-image-prompt-history', (_event, prompt: string) => addImagePromptHistoryEntry(prompt))

  ipcMain.handle('remove-image-prompt-history', (_event, prompt: string) => removeImagePromptHistoryEntry(prompt))

  ipcMain.handle('clear-image-prompt-history', () => clearImagePromptHistory())

  ipcMain.handle('add-reference-song-history', (_event, text: string) => addReferenceSongHistoryEntry(text))

  ipcMain.handle('remove-reference-song-history', (_event, text: string) => removeReferenceSongHistoryEntry(text))

  ipcMain.handle('clear-reference-song-history', () => clearReferenceSongHistory())

  ipcMain.handle('get-model-options', () => ({
    aceStepLm: aceStep.LM_MODEL_OPTIONS,
    aceStepDit: aceStep.DIT_MODEL_OPTIONS,
    whisper: WHISPER_MODEL_OPTIONS,
    gemma: GEMMA_MODEL_OPTIONS,
    demucs: DEMUCS_MODEL_OPTIONS,
    demucsShifts: DEMUCS_SHIFTS_OPTIONS,
    vad: VAD_OPTIONS
  }))

  // Lets the Setup view fetch a newly-selected ACE-Step LM/DiT variant
  // on demand (without re-running the whole install flow) — reuses
  // aceStep.install()'s downloadPlan, which already skips files already on
  // disk and only fetches whatever the current settings.ts selection needs.
  ipcMain.handle('download-ace-step-models', async (event) => {
    try {
      await aceStep.install((chunk) => send(event, chunk))
      return 0
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
