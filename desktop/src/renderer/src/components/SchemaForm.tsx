/**
 * Renders a generic form straight from an `AceStepSchema` (see
 * ace-step-schema.ts / ace_step_schema.py) — one control per field, picked
 * by its declared type (checkbox/select/number/textarea/text). This is
 * deliberately generic rather than a hand-built field list: when ACE-Step
 * adds, removes, or retypes a `/release_task` field, the next schema
 * regeneration (after an install/update/reset) changes what renders here
 * with no code change in this file.
 */
import type { CSSProperties, JSX } from 'react'
import type { AceStepSchemaField } from '../../../shared/types'

interface SchemaFormProps {
  fields: AceStepSchemaField[]
  values: Record<string, unknown>
  onChange: (name: string, value: unknown) => void
}

const labelStyle: CSSProperties = { fontSize: 13, display: 'flex', flexDirection: 'column', gap: 4 }
const inputStyle: CSSProperties = { width: '100%', boxSizing: 'border-box' }
const fieldWrapStyle: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4 }

function fieldLabel(name: string): string {
  return name.replace(/_/g, ' ')
}

export default function SchemaForm({ fields, values, onChange }: SchemaFormProps): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {fields.map((field) => {
        const value = values[field.name]
        return (
          <div key={field.name} style={fieldWrapStyle}>
            <label style={labelStyle}>
              <span>
                <strong>{fieldLabel(field.name)}</strong>
                {field.description && (
                  <span style={{ color: 'var(--ev-c-text-2)', fontWeight: 400 }}> — {field.description}</span>
                )}
              </span>
              <SchemaFieldControl field={field} value={value} onChange={(v) => onChange(field.name, v)} />
            </label>
          </div>
        )
      })}
    </div>
  )
}

function SchemaFieldControl({
  field,
  value,
  onChange
}: {
  field: AceStepSchemaField
  value: unknown
  onChange: (value: unknown) => void
}): JSX.Element {
  if (field.type === 'boolean') {
    return <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
  }

  if (field.type === 'enum' && field.enumValues) {
    return (
      <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} style={inputStyle}>
        {field.optional && <option value="">(default)</option>}
        {field.enumValues.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
    )
  }

  if (field.type === 'integer' || field.type === 'number') {
    return (
      <input
        type="number"
        value={value === null || value === undefined ? '' : String(value)}
        min={field.min ?? undefined}
        max={field.max ?? undefined}
        step={field.type === 'integer' ? 1 : 'any'}
        placeholder={field.optional ? '(default)' : undefined}
        onChange={(e) => {
          const text = e.target.value
          if (text === '') return onChange(field.optional ? null : 0)
          const n = field.type === 'integer' ? parseInt(text, 10) : parseFloat(text)
          if (!Number.isNaN(n)) onChange(n)
        }}
        style={inputStyle}
      />
    )
  }

  // ACE-Step's request model has no dedicated "this is a file path" type —
  // it's just `str`/`Optional[str]` like any other text field — but every
  // such field in practice is named `*_path` (reference_audio_path,
  // src_audio_path). A real native file dialog beats asking the user to
  // type/paste an absolute path by hand, which was the actual complaint
  // (Gradio's own upload widget vs. this being "just give the path").
  if (field.name.endsWith('_path')) {
    return (
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          type="text"
          value={String(value ?? '')}
          placeholder={field.optional ? '(none)' : undefined}
          onChange={(e) => onChange(e.target.value)}
          style={{ ...inputStyle, flex: 1 }}
        />
        <button
          type="button"
          onClick={async () => {
            const picked = await window.api.pickSongFile()
            if (picked) onChange(picked)
          }}
        >
          Browse...
        </button>
      </div>
    )
  }

  // 'string' / 'list' — a list-typed field (e.g. track_classes) still just
  // takes free text here rather than a dedicated multi-select widget; rare
  // enough in ACE-Step's request model that a plain text input (left as-is,
  // unsent, if the user never touches it) is the pragmatic choice over
  // building a one-off control for it.
  if (field.multiline) {
    return (
      <textarea
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        style={inputStyle}
      />
    )
  }
  return (
    <input
      type="text"
      value={String(value ?? '')}
      placeholder={field.optional ? '(default)' : undefined}
      onChange={(e) => onChange(e.target.value)}
      style={inputStyle}
    />
  )
}
