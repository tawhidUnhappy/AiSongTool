import { useEffect, useState } from 'react'

interface GuiControlProps {
  name: string
  label: string
  disabled: boolean
  onLaunch: () => Promise<void>
}

/** "Open UI" / "Stop UI" pair for a long-lived background GUI process
 * (ACE-Step's or Z-Image's Gradio servers) — launching takes the single-job
 * lock for nothing (these are detached), so this is the only way to get
 * the GPU back without quitting the whole app. */
export function GuiControl({ name, label, disabled, onLaunch }: GuiControlProps): React.JSX.Element {
  const [running, setRunning] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    window.api.isGuiRunning(name).then(setRunning)
  }, [name])

  const launch = async (): Promise<void> => {
    setBusy(true)
    try {
      await onLaunch()
      setRunning(true)
    } finally {
      setBusy(false)
    }
  }

  const stop = async (): Promise<void> => {
    setBusy(true)
    try {
      await window.api.stopGui(name)
      setRunning(false)
    } finally {
      setBusy(false)
    }
  }

  return running ? (
    <button onClick={stop} disabled={busy}>
      Stop {label}
    </button>
  ) : (
    <button onClick={launch} disabled={disabled || busy}>
      Open {label}
    </button>
  )
}
