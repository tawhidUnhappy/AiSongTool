import { useEffect, useRef, useState } from 'react'

const ACE_STEP_UI_URL = 'http://127.0.0.1:7860'

/** Embeds ACE-Step-1.5's own Gradio demo UI directly in the app (a
 * <webview> pointed at its locally-running server) instead of opening it in
 * the system browser — same Gradio app ACE-Step itself ships, untouched, so
 * every feature it has (including its own settings/preferences, which live
 * in its own `acestep/ui/gradio/interfaces/*.js`) keeps working exactly as
 * upstream built it. */
export function AceStepUI(): React.JSX.Element {
  const [running, setRunning] = useState(false)
  const [starting, setStarting] = useState(false)
  const [up, setUp] = useState(false)
  const [busy, setBusy] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    window.api.isGuiRunning('ace-step').then(setRunning)
  }, [])

  useEffect(() => {
    if (!running) {
      setUp(false)
      return
    }
    const poll = (): void => {
      window.api.isAceStepUiUp().then(setUp)
    }
    poll()
    pollRef.current = setInterval(poll, 1500)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [running])

  const launch = async (): Promise<void> => {
    setBusy(true)
    setStarting(true)
    try {
      await window.api.launchAceStep()
      setRunning(true)
    } finally {
      setBusy(false)
    }
  }

  const stop = async (): Promise<void> => {
    setBusy(true)
    try {
      await window.api.stopGui('ace-step')
      setRunning(false)
      setUp(false)
      setStarting(false)
    } finally {
      setBusy(false)
    }
  }

  if (!running) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: 16 }}>
        <div style={{ fontSize: 13, color: 'var(--ev-c-text-2)' }}>
          ACE-Step-1.5&apos;s own Gradio UI — generate, edit, and remix songs directly with its full feature
          set (not just the Create flow&apos;s simplified options). Requires ACE-Step to be installed from
          the Setup view first.
        </div>
        <div>
          <button onClick={launch} disabled={busy}>
            {busy ? 'Starting…' : 'Launch ACE-Step UI'}
          </button>
        </div>
      </div>
    )
  }

  if (!up) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: 16 }}>
        <div style={{ fontSize: 13, color: 'var(--ev-c-text-2)' }}>
          {starting
            ? 'Starting ACE-Step UI — first start loads the model and can take a couple minutes...'
            : 'Connecting to ACE-Step UI...'}
        </div>
        <div>
          <button onClick={stop} disabled={busy}>
            Cancel / stop
          </button>
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={stop} disabled={busy}>
          Stop ACE-Step UI
        </button>
        <span style={{ fontSize: 12, color: 'var(--ev-c-text-2)', alignSelf: 'center' }}>
          Running at {ACE_STEP_UI_URL}
        </span>
      </div>
      <webview src={ACE_STEP_UI_URL} style={{ flex: 1, minHeight: 0 }} />
    </div>
  )
}
