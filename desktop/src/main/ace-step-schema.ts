/**
 * Reads the generation-form schema written by
 * `aisongtool/ace_step_schema.py` (an AST-based parse of ACE-Step-1.5's own
 * `GenerateMusicRequest` Pydantic model — its real `/release_task` request
 * contract) — regenerated automatically after every install/update/reset of
 * ACE-Step (see `ace_step.py`'s `_regenerate_schema()`), not hand-maintained
 * here. The Create page's generation form renders itself from this instead
 * of a fixed set of fields we'd have to keep in sync by hand.
 */
import { existsSync, readFileSync } from 'fs'
import path from 'path'
import { dataDir } from './paths'

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

export function readAceStepSchema(): AceStepSchema | null {
  const p = schemaPath()
  if (!existsSync(p)) return null
  try {
    return JSON.parse(readFileSync(p, 'utf-8')) as AceStepSchema
  } catch {
    return null
  }
}
