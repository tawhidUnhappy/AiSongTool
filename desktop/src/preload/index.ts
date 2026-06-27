import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'
import type {
  AppSettings,
  CreateFlow,
  CreateRunParams,
  DoctorStatus,
  LibrarySong,
  ModelOptions,
  NightcoreVideoParams,
  NightcoreVideoResult,
  TranscribeParams,
  TranscribeResult
} from '../shared/types'

// Custom APIs for renderer
const api = {
  runSetup: (): Promise<number> => ipcRenderer.invoke('run-setup'),
  installTool: (name: string): Promise<number> => ipcRenderer.invoke('install-tool', name),
  resetTool: (name: string): Promise<number> => ipcRenderer.invoke('reset-tool', name),
  launchAceStep: (): Promise<void> => ipcRenderer.invoke('launch-ace-step'),
  isAceStepUiUp: (): Promise<boolean> => ipcRenderer.invoke('is-ace-step-ui-up'),
  launchZimageGui: (): Promise<void> => ipcRenderer.invoke('launch-zimage-gui'),
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke('open-external', url),
  stopGui: (name: string): Promise<void> => ipcRenderer.invoke('stop-gui', name),
  isGuiRunning: (name: string): Promise<boolean> => ipcRenderer.invoke('is-gui-running', name),
  getDoctorStatus: (): Promise<DoctorStatus> => ipcRenderer.invoke('get-doctor-status'),
  getDataDir: (): Promise<string> => ipcRenderer.invoke('get-data-dir'),
  terminateJob: (): Promise<void> => ipcRenderer.invoke('terminate-job'),
  getTerminalHistory: (): Promise<string> => ipcRenderer.invoke('get-terminal-history'),
  isJobRunning: (): Promise<boolean> => ipcRenderer.invoke('is-job-running'),
  getSettings: (): Promise<AppSettings> => ipcRenderer.invoke('get-settings'),
  setSetting: <K extends Exclude<keyof AppSettings, 'imagePromptHistory'>>(
    key: K,
    value: AppSettings[K]
  ): Promise<void> => ipcRenderer.invoke('set-setting', key, value),
  getModelOptions: (): Promise<ModelOptions> => ipcRenderer.invoke('get-model-options'),
  downloadAceStepModels: (): Promise<number> => ipcRenderer.invoke('download-ace-step-models'),
  setPromptHistoryEnabled: (enabled: boolean): Promise<void> =>
    ipcRenderer.invoke('set-prompt-history-enabled', enabled),
  addImagePromptHistory: (prompt: string): Promise<void> => ipcRenderer.invoke('add-image-prompt-history', prompt),
  removeImagePromptHistory: (prompt: string): Promise<void> =>
    ipcRenderer.invoke('remove-image-prompt-history', prompt),
  clearImagePromptHistory: (): Promise<void> => ipcRenderer.invoke('clear-image-prompt-history'),
  onTerminalData: (callback: (chunk: string) => void): (() => void) => {
    const listener = (_event: Electron.IpcRendererEvent, chunk: string): void => callback(chunk)
    ipcRenderer.on('terminal:data', listener)
    return () => ipcRenderer.removeListener('terminal:data', listener)
  },
  resizeTerminal: (cols: number, rows: number): void => {
    ipcRenderer.send('terminal:resize', cols, rows)
  },

  // Create flow
  startCreateRun: (params: CreateRunParams): Promise<void> => ipcRenderer.invoke('create:start-run', params),
  getCreateStatus: (): Promise<CreateFlow> => ipcRenderer.invoke('create:get-status'),
  getDefaultBackground: (): Promise<string> => ipcRenderer.invoke('create:default-background'),
  getOutputDir: (): Promise<string> => ipcRenderer.invoke('create:get-output-dir'),
  pickOutputDir: (): Promise<string | null> => ipcRenderer.invoke('create:pick-output-dir'),
  pickSongFile: (): Promise<string | null> => ipcRenderer.invoke('create:pick-song-file'),
  pickImageFile: (): Promise<string | null> => ipcRenderer.invoke('create:pick-image-file'),
  listSubtitleOutputs: (jobDir: string): Promise<{ ext: string; label: string }[]> =>
    ipcRenderer.invoke('create:list-subtitle-outputs', jobDir),
  saveArtifact: (srcPath: string, suggestedName: string): Promise<string> =>
    ipcRenderer.invoke('create:save-artifact', srcPath, suggestedName),
  listAudioLibrary: (): Promise<LibrarySong[]> => ipcRenderer.invoke('create:list-audio-library'),

  // Tools view
  transcribeSong: (params: TranscribeParams): Promise<TranscribeResult> =>
    ipcRenderer.invoke('tools:transcribe', params),
  downloadArtifact: (srcPath: string, suggestedName: string): Promise<string> =>
    ipcRenderer.invoke('tools:download-artifact', srcPath, suggestedName),
  pickVideoFile: (): Promise<string | null> => ipcRenderer.invoke('tools:pick-video-file'),
  nightcoreVideo: (params: NightcoreVideoParams): Promise<NightcoreVideoResult> =>
    ipcRenderer.invoke('tools:nightcore-video', params)
}

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI)
    contextBridge.exposeInMainWorld('api', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = electronAPI
  // @ts-ignore (define in dts)
  window.api = api
}
