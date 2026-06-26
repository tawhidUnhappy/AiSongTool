import { useCallback, useEffect, useState } from 'react'
import type { AppSettings, DoctorStatus, ModelOptions } from '../../../shared/types'
import { ToolCard } from '../components/ToolCard'
import { GuiControl } from '../components/GuiControl'

function ModelSelect({
  label,
  value,
  options,
  onChange
}: {
  label: string
  value: string
  options: { value: string; label: string; sizeMb?: number }[]
  onChange: (v: string) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
            {o.sizeMb ? ` (~${(o.sizeMb / 1024).toFixed(1)}GB)` : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

function StatusRow({ label, ok, detail }: { label: string; ok: boolean; detail?: string }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
      <span style={{ color: ok ? '#8f8' : '#e88' }}>{ok ? '✓' : '✗'}</span>
      <span>{label}</span>
      {detail && <span style={{ color: 'var(--ev-c-text-2)', fontSize: 12 }}>{detail}</span>}
    </div>
  )
}

export function Setup(): React.JSX.Element {
  const [status, setStatus] = useState<DoctorStatus | null>(null)
  const [runningSetup, setRunningSetup] = useState(false)
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [modelOptions, setModelOptions] = useState<ModelOptions | null>(null)
  const [downloadingAceStep, setDownloadingAceStep] = useState(false)
  const [dataDir, setDataDir] = useState<string | null>(null)
  const [jobRunning, setJobRunning] = useState(false)

  const refresh = useCallback(async () => {
    setStatus(await window.api.getDoctorStatus())
  }, [])

  useEffect(() => {
    refresh()
    window.api.getSettings().then(setSettings)
    window.api.getModelOptions().then(setModelOptions)
    window.api.getDataDir().then(setDataDir)
  }, [refresh])

  // Polls the main process's single authoritative job lock so every
  // install/setup button here stays disabled while ANY of them is running
  // — even across this view (or just one ToolCard) remounting, which
  // resets component-local "running" state but not the actual job.
  useEffect(() => {
    const poll = (): void => {
      window.api.isJobRunning().then(setJobRunning)
    }
    poll()
    const interval = setInterval(poll, 1000)
    return () => clearInterval(interval)
  }, [])

  const updateSetting = async <
    K extends Exclude<
      keyof AppSettings,
      'promptHistory' | 'promptHistoryEnabled' | 'imagePromptHistory' | 'referenceSongHistory'
    >
  >(
    key: K,
    value: AppSettings[K]
  ): Promise<void> => {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev))
    await window.api.setSetting(key, value)
  }

  const downloadAceStepModels = async (): Promise<void> => {
    setDownloadingAceStep(true)
    try {
      await window.api.downloadAceStepModels()
    } finally {
      setDownloadingAceStep(false)
      refresh()
    }
  }

  const runSetup = async (): Promise<void> => {
    setRunningSetup(true)
    try {
      await window.api.runSetup()
    } finally {
      setRunningSetup(false)
      refresh()
    }
  }

  const installAndRefresh = async (name: string): Promise<number> => {
    const code = await window.api.installTool(name)
    await refresh()
    return code
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}>
      {dataDir && (
        <div style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>
          Data folder: <code>{dataDir}</code> — every model, cache, job, and setting this app writes lives here.
          Delete it (or uninstall) to fully reset.
        </div>
      )}
      <div style={{ border: '1px solid #333', borderRadius: 6, padding: 16 }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <button onClick={runSetup} disabled={runningSetup || jobRunning}>
            {runningSetup ? 'Running setup…' : 'Run setup'}
          </button>
          <button onClick={refresh}>Refresh status</button>
        </div>

        {status && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>Prerequisites</div>
            <StatusRow label="uv" ok={status.uv !== null} detail={status.uv ?? 'not found — required'} />
            <StatusRow
              label="ffmpeg"
              ok={status.ffmpeg !== null}
              detail={status.ffmpeg ?? 'not found — needed for video export'}
            />
            <StatusRow
              label="NVIDIA GPU"
              ok={status.nvidia_smi !== null}
              detail={status.nvidia_smi ?? 'none detected — CPU mode'}
            />
            {status.gpu.cuda_available_in_main_env && (
              <div style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>
                CUDA available in this process: {status.gpu.cuda_device}
              </div>
            )}

            <div style={{ fontWeight: 600, fontSize: 13, marginTop: 8 }}>Isolated environments</div>
            {Object.entries(status.envs).map(([name, info]) => (
              <StatusRow
                key={name}
                label={name}
                ok={info.provisioned && info.venv_python !== null}
                detail={info.provisioned && info.venv_python !== null ? 'ready' : 'not provisioned — click Run setup'}
              />
            ))}
          </div>
        )}
      </div>

      <ToolCard
        title="Optional: ACE-Step-1.5 (music generation)"
        description="Clones github.com/ACE-Step/ACE-Step-1.5 and runs its own `uv sync` into an isolated
          env — model checkpoints download from Hugging Face on first use, not from this app."
        installLabel="Install / update ACE-Step"
        onInstall={() => installAndRefresh('ace-step')}
        blockedByOtherJob={jobRunning}
        statusText={
          status?.ace_step.synced
            ? `Installed at ${status.ace_step.dir}`
            : status?.ace_step.cloned
              ? 'Cloned, but not yet synced — click Install / update.'
              : 'Not installed yet.'
        }
        extra={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {settings && modelOptions && (
              <>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  <ModelSelect
                    label="Lyrics/audio-codes LM"
                    value={settings.aceStepLmModel}
                    options={modelOptions.aceStepLm}
                    onChange={(v) => updateSetting('aceStepLmModel', v)}
                  />
                  <ModelSelect
                    label="Music synthesis (DiT)"
                    value={settings.aceStepDitModel}
                    options={modelOptions.aceStepDit}
                    onChange={(v) => updateSetting('aceStepDitModel', v)}
                  />
                </div>
                <button onClick={downloadAceStepModels} disabled={downloadingAceStep || jobRunning}>
                  {downloadingAceStep ? 'Downloading…' : 'Download selected models'}
                </button>
              </>
            )}
            <GuiControl
              name="ace-step"
              label="ACE-Step UI"
              disabled={!status?.ace_step.synced}
              onLaunch={() => window.api.launchAceStep()}
            />
          </div>
        }
      />

      <ToolCard
        title="Optional: Z-Image-Turbo (image generation)"
        description="An isolated `uv` env (like demucs-uv/whisperx-uv) — lets the Create flow generate a
          background image straight from the song's prompt instead of needing one uploaded by hand."
        installLabel="Install Z-Image Turbo"
        onInstall={() => installAndRefresh('z-image')}
        blockedByOtherJob={jobRunning}
        statusText={
          status?.envs['zimage-uv']?.provisioned && status.envs['zimage-uv'].venv_python
            ? 'Installed.'
            : 'Not installed yet.'
        }
        extra={
          <GuiControl
            name="zimage"
            label="Z-Image UI (Gradio)"
            disabled={!(status?.envs['zimage-uv']?.provisioned && status.envs['zimage-uv'].venv_python)}
            onLaunch={() => window.api.launchZimageGui()}
          />
        }
      />

      <ToolCard
        title="Optional: Gemma 4 (prompt writing + chat)"
        description="An isolated `uv` env — lets the Create flow turn one short description into a song
          style caption, full lyrics, and an image prompt. Its Gradio UI also has a normal multi-turn
          Chat tab for using Gemma 4 like any other chatbot."
        installLabel="Install Gemma 4"
        onInstall={() => installAndRefresh('gemma')}
        blockedByOtherJob={jobRunning}
        statusText={
          status?.envs['gemma-uv']?.provisioned && status.envs['gemma-uv'].venv_python
            ? 'Installed.'
            : 'Not installed yet.'
        }
        extra={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {settings && modelOptions && (
              <ModelSelect
                label="Gemma model"
                value={settings.gemmaModel}
                options={modelOptions.gemma}
                onChange={(v) => updateSetting('gemmaModel', v)}
              />
            )}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <GuiControl
                name="gemma"
                label="Gemma 4 UI (Gradio)"
                disabled={!(status?.envs['gemma-uv']?.provisioned && status.envs['gemma-uv'].venv_python)}
                onLaunch={() => window.api.launchGemmaGui()}
              />
              <button onClick={() => window.api.openExternal('http://127.0.0.1:7862')}>
                Open in browser ↗
              </button>
            </div>
            <span style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>
              The first model load (after clicking "Open Gemma 4 UI") can take a while — once it's
              ready, the link above opens the UI, which has both the writer form and a Chat tab.
            </span>
          </div>
        }
      />

      <ToolCard
        title="Optional: Syrex Visualizer (video template)"
        description="An isolated `uv` env (CPU-only: numpy/scipy/opencv/pillow, no torch) — lets the Create
          flow's 'Syrex Visualizer' template render an audio-reactive video (curved spectrum spikes, panning
          background, bass-driven chromatic aberration) instead of the default static-image template."
        installLabel="Install Syrex Visualizer"
        onInstall={() => installAndRefresh('syrex')}
        blockedByOtherJob={jobRunning}
        statusText={
          status?.envs['syrex-uv']?.provisioned && status.envs['syrex-uv'].venv_python
            ? 'Installed.'
            : 'Not installed yet.'
        }
      />

      <div style={{ border: '1px solid #333', borderRadius: 6, padding: 16 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Transcription (WhisperX)</div>
        <div style={{ fontSize: 13, color: 'var(--ev-c-text-2)', marginBottom: 8 }}>
          Larger models transcribe lyrics more accurately but take longer — affects the Create flow's lyric
          timing.
        </div>
        {settings && modelOptions && (
          <ModelSelect
            label="WhisperX model"
            value={settings.whisperModel}
            options={modelOptions.whisper}
            onChange={(v) => updateSetting('whisperModel', v)}
          />
        )}
      </div>

      <div style={{ border: '1px solid #333', borderRadius: 6, padding: 16 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Vocal separation (Demucs)</div>
        <div style={{ fontSize: 13, color: 'var(--ev-c-text-2)', marginBottom: 8 }}>
          Defaults used by the Create flow and the Tools view's "Transcribe to .srt" — higher isolation
          quality and pyannote both trade time for accuracy on a heavily blended mix.
        </div>
        {settings && modelOptions && (
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <ModelSelect
              label="Demucs model"
              value={settings.demucsModel}
              options={modelOptions.demucs}
              onChange={(v) => updateSetting('demucsModel', v)}
            />
            <ModelSelect
              label="Vocal isolation quality"
              value={String(settings.demucsShifts)}
              options={modelOptions.demucsShifts}
              onChange={(v) => updateSetting('demucsShifts', Number(v))}
            />
            <ModelSelect
              label="Voice detector (VAD)"
              value={settings.vad}
              options={modelOptions.vad}
              onChange={(v) => updateSetting('vad', v as AppSettings['vad'])}
            />
          </div>
        )}
      </div>
    </div>
  )
}
