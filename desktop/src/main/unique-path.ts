import { existsSync } from 'fs'
import path from 'path'

/** Chrome-download-manager-style collision handling: if `dir/filename`
 * already exists, try `name (1).ext`, `name (2).ext`, etc. instead of
 * overwriting or throwing. */
export function uniqueDestPath(dir: string, filename: string): string {
  const ext = path.extname(filename)
  const base = filename.slice(0, filename.length - ext.length)
  let candidate = path.join(dir, filename)
  let n = 1
  while (existsSync(candidate)) {
    candidate = path.join(dir, `${base} (${n})${ext}`)
    n += 1
  }
  return candidate
}
