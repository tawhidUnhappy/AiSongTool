/**
 * Reads the generation-form schema written by
 * `aisongtool/ace_step_schema.py` (an AST-based parse of ACE-Step-1.5's own
 * `GenerateMusicRequest` Pydantic model — its real `/release_task` request
 * contract). Regenerated fresh, on the spot, every time the Create page
 * actually asks for it (see `getAceStepSchema()` below) — not just at
 * install/update/reset time — so it always reflects whatever's literally on
 * disk in the cloned ACE-Step repo right now, including changes made
 * outside this app (e.g. a manual `git pull` in that repo). Re-running the
 * AST parse is a near-instant, file-only operation (no model loading, no
 * heavy imports), so doing it on every fetch costs nothing noticeable.
 */
import { existsSync, readFileSync } from 'fs'
import path from 'path'
import { dataDir, mainVenvPython } from './paths'
import { runCapture } from './jobs'

const GENERATE_SCHEMA_CMD = ['-m', 'aisongtool.cli', 'generate-ace-step-schema']

export interface AceStepSchemaField {
  name: string
  type: 'string' | 'boolean' | 'integer' | 'number' | 'enum' | 'list'
  enumValues: string[] | null
  optional: boolean
  multiline: boolean
  default: unknown
  description: string
  min: number | null
  max: number | null
}

export interface AceStepSchema {
  fields: AceStepSchemaField[]
}

function schemaPath(): string {
  return path.join(dataDir(), 'ace-step-schema.json')
}

function readSchemaFile(): AceStepSchema | null {
  const p = schemaPath()
  if (!existsSync(p)) return null
  try {
    return JSON.parse(readFileSync(p, 'utf-8')) as AceStepSchema
  } catch {
    return null
  }
}

export async function getAceStepSchema(): Promise<AceStepSchema | null> {
  try {
    await runCapture([mainVenvPython(), ...GENERATE_SCHEMA_CMD], dataDir())
  } catch {
    // ACE-Step not installed, or its request model changed shape — fall
    // back to whatever was last successfully written (possibly null), so a
    // transient failure here doesn't blank out a form that was working.
  }
  return readSchemaFile()
}
