import { ElectronAPI } from '@electron-toolkit/preload'
import type {
  AppSettings,
  CreateFlow,
  CreateRunParams,
  DoctorStatus,
  ModelOptions,
  NightcoreVideoParams,
  NightcoreVideoResult,
  TranscribeParams,
  TranscribeResult
} from '../shared/types'

interface Api {
  runSetup: () => Promise<number>
  installTool: (name: string) => Promise<number>
  resetTool: (name: string) => Promise<number>
  launchAceStep: () => Promise<void>
  isAceStepUiUp: () => Promise<boolean>
  launchZimageGui: () => Promise<void>
  openExternal: (url: string) => Promise<void>
  stopGui: (name: string) => Promise<void>
  isGuiRunning: (name: string) => Promise<boolean>
  getDoctorStatus: () => Promise<DoctorStatus>
  getDataDir: () => Promise<string>
  terminateJob: () => Promise<void>
  getTerminalHistory: () => Promise<string>
  isJobRunning: () => Promise<boolean>
  getSettings: () => Promise<AppSettings>
  setSetting: <K extends Exclude<keyof AppSettings, 'promptHistory' | 'imagePromptHistory'>>(
    key: K,
    value: AppSettings[K]
  ) => Promise<void>
  getModelOptions: () => Promise<ModelOptions>
  downloadAceStepModels: () => Promise<number>
  addPromptHistory: (prompt: string) => Promise<void>
  removePromptHistory: (prompt: string) => Promise<void>
  clearPromptHistory: () => Promise<void>
  setPromptHistoryEnabled: (enabled: boolean) => Promise<void>
  addImagePromptHistory: (prompt: string) => Promise<void>
  removeImagePromptHistory: (prompt: string) => Promise<void>
  clearImagePromptHistory: () => Promise<void>
  onTerminalData: (callback: (chunk: string) => void) => () => void
  resizeTerminal: (cols: number, rows: number) => void

  startCreateRun: (params: CreateRunParams) => Promise<void>
  getCreateStatus: () => Promise<CreateFlow>
  getDefaultBackground: () => Promise<string>
  getOutputDir: () => Promise<string>
  pickOutputDir: () => Promise<string | null>
  pickSongFile: () => Promise<string | null>
  pickImageFile: () => Promise<string | null>
  listSubtitleOutputs: (jobDir: string) => Promise<{ ext: string; label: string }[]>
  saveArtifact: (srcPath: string, suggestedName: string) => Promise<string>

  transcribeSong: (params: TranscribeParams) => Promise<TranscribeResult>
  downloadArtifact: (srcPath: string, suggestedName: string) => Promise<string>
  pickVideoFile: () => Promise<string | null>
  nightcoreVideo: (params: NightcoreVideoParams) => Promise<NightcoreVideoResult>
}

declare global {
  interface Window {
    electron: ElectronAPI
    api: Api
  }
}
