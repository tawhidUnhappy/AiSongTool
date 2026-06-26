import { ReactNode, useState } from 'react'

interface ToolCardProps {
  title: string
  description: string
  installLabel: string
  onInstall: () => Promise<number>
  statusText: string
  extra?: ReactNode
  // True while *any* job is running elsewhere in the app (Setup polls the
  // main process's single authoritative job lock — see jobs.ts's
  // isJobRunning()). Disables the button even across this component
  // remounting (e.g. navigating away and back resets `running` below to
  // false, but the job that button started may still genuinely be in
  // progress) — without this, a confused user re-clicking an apparently-
  // enabled button while a job is still running hit a raw "a job is
  // already running" error instead of just staying disabled.
  blockedByOtherJob?: boolean
}

/** Shared "optional tool" card — title/description/install button/status,
 * used for ACE-Step/Z-Image/Syrex so none of them duplicate the same
 * button-click/error-handling boilerplate. Mirrors the Flet app's
 * `_tool_card.py`'s `tool_install_card`. */
export function ToolCard({
  title,
  description,
  installLabel,
  onInstall,
  statusText,
  extra,
  blockedByOtherJob = false
}: ToolCardProps): React.JSX.Element {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleClick = async (): Promise<void> => {
    setRunning(true)
    setError(null)
    try {
      await onInstall()
    } catch (err) {
      setError(String(err))
    } finally {
      setRunning(false)
    }
  }

  const disabled = running || blockedByOtherJob

  return (
    <div style={{ border: '1px solid #333', borderRadius: 6, padding: 16 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 12, color: 'var(--ev-c-text-2)', marginBottom: 12 }}>{description}</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={handleClick} disabled={disabled}>
          {running ? 'Working…' : installLabel}
        </button>
        {extra}
      </div>
      <div style={{ fontSize: 12, color: error ? '#e88' : 'var(--ev-c-text-2)', marginTop: 8 }}>
        {error ?? (!running && blockedByOtherJob ? 'Another job is running — wait for it to finish.' : statusText)}
      </div>
    </div>
  )
}
