import { randomUUID } from 'crypto'

/** Short id for per-run job subdirectories (`jobs/_create/<id>/`,
 * `jobs/_gemma/<id>/`, etc.) — just needs to be unique enough to not collide
 * within one session, not cryptographically unguessable. */
export function shortId(): string {
  return randomUUID().replace(/-/g, '').slice(0, 12)
}
