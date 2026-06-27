import { useRef, useState } from 'react'
import { Terminal } from './components/Terminal'
import { Setup } from './views/Setup'
import { Create } from './views/Create'
import { Tools } from './views/Tools'

const TABS = [
  ['setup', 'Setup'],
  ['create', 'Create'],
  ['tools', 'Tools']
] as const

const MIN_TERMINAL_HEIGHT = 100
const MIN_CONTENT_HEIGHT = 200

function App(): React.JSX.Element {
  const [tab, setTab] = useState<'setup' | 'create' | 'tools'>('setup')
  const [terminalHeight, setTerminalHeight] = useState(280)
  const dragState = useRef<{ startY: number; startHeight: number } | null>(null)

  const onDragStart = (e: React.MouseEvent): void => {
    dragState.current = { startY: e.clientY, startHeight: terminalHeight }
    const onMove = (ev: MouseEvent): void => {
      if (!dragState.current) return
      // Dragging the handle up (cursor moves toward the top of the window)
      // grows the Terminal pane — same direction a user dragging a
      // bottom-docked panel's top edge expects.
      const delta = dragState.current.startY - ev.clientY
      const next = dragState.current.startHeight + delta
      const max = window.innerHeight - MIN_CONTENT_HEIGHT
      setTerminalHeight(Math.max(MIN_TERMINAL_HEIGHT, Math.min(max, next)))
    }
    const onUp = (): void => {
      dragState.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: 16,
        gap: 12,
        boxSizing: 'border-box'
      }}
    >
      <div style={{ display: 'flex', gap: 8 }}>
        {TABS.map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} style={{ fontWeight: tab === key ? 700 : 400 }}>
            {label}
          </button>
        ))}
      </div>

      <div style={{ flex: '1 1 auto', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {/* Both views stay mounted (just hidden) so a Create run in
            progress isn't torn down when switching to Setup and back —
            the same bug this rewrite's Flet predecessor had to fix by
            building views once and toggling visibility, not rebuilding. */}
        <div
          style={{
            display: tab === 'setup' ? 'block' : 'none',
            flex: 1,
            minHeight: 0,
            overflowY: 'auto'
          }}
        >
          <Setup />
        </div>
        <div
          style={{
            display: tab === 'create' ? 'flex' : 'none',
            flexDirection: 'column',
            flex: 1,
            minHeight: 0
          }}
        >
          <Create />
        </div>
        <div
          style={{
            display: tab === 'tools' ? 'block' : 'none',
            flex: 1,
            minHeight: 0,
            overflowY: 'auto'
          }}
        >
          <Tools />
        </div>
      </div>

      <div
        onMouseDown={onDragStart}
        title="Drag to resize"
        style={{
          height: 6,
          flexShrink: 0,
          cursor: 'row-resize',
          background: '#333',
          borderRadius: 3
        }}
      />

      <div
        style={{
          height: terminalHeight,
          flexShrink: 0,
          minHeight: MIN_TERMINAL_HEIGHT,
          border: '1px solid #333',
          borderRadius: 4,
          overflow: 'hidden'
        }}
      >
        <Terminal />
      </div>
    </div>
  )
}

export default App
