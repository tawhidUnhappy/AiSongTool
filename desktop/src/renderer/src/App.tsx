import { useState } from 'react'
import { Terminal } from './components/Terminal'
import { Setup } from './views/Setup'
import { Create } from './views/Create'
import { Tools } from './views/Tools'

const TABS = [
  ['setup', 'Setup'],
  ['create', 'Create'],
  ['tools', 'Tools']
] as const

function App(): React.JSX.Element {
  const [tab, setTab] = useState<'setup' | 'create' | 'tools'>('setup')

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
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{ fontWeight: tab === key ? 700 : 400 }}
          >
            {label}
          </button>
        ))}
      </div>

      <div style={{ flex: '1 1 60%', minHeight: 0, overflowY: 'auto' }}>
        {/* Both views stay mounted (just hidden) so a Create run in
            progress isn't torn down when switching to Setup and back —
            the same bug this rewrite's Flet predecessor had to fix by
            building views once and toggling visibility, not rebuilding. */}
        <div style={{ display: tab === 'setup' ? 'block' : 'none' }}>
          <Setup />
        </div>
        <div style={{ display: tab === 'create' ? 'block' : 'none' }}>
          <Create />
        </div>
        <div style={{ display: tab === 'tools' ? 'block' : 'none' }}>
          <Tools />
        </div>
      </div>

      <div style={{ flex: '1 1 40%', minHeight: 120, border: '1px solid #333', borderRadius: 4 }}>
        <Terminal />
      </div>
    </div>
  )
}

export default App
