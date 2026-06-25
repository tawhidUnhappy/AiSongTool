/**
 * First-run provisioning of the main `aisongtool` venv itself.
 *
 * In dev mode the developer already ran `uv sync` once at the repo root, so
 * `mainVenvPython()` (paths.ts) just works. In a packaged build there is no
 * such venv yet — `aisongtool/`'s source + pyproject.toml/uv.lock ship as a
 * read-only bundled resource (see electron-builder.yml's `extraResources`),
 * but the venv itself can't be bundled: it bakes in the absolute path of the
 * interpreter that created it, so it has to be created locally on the end
 * user's own machine, exactly like every isolated tool env already is. This
 * is the one-time `uv sync` that does that, run automatically before the
 * first `aisongtool.cli` invocation in a packaged build.
 */
import { existsSync } from 'fs'
import { findUv, mainEnvProjectDir, mainVenvPython, dataDir } from './paths'
import { runBlocking, type OnData } from './jobs'
import { app } from 'electron'

let synced = false

/** No-op once the main venv already exists (dev mode: always, since the
 * developer's own `.venv` is already there) or after the first successful
 * sync this process session. `uv sync --project <bundled source dir>` reads
 * pyproject.toml/uv.lock from the read-only bundled resources, but
 * `UV_PROJECT_ENVIRONMENT` redirects the actual `.venv` it creates into the
 * writable data root instead of next to that bundled source. */
export async function ensureMainEnv(onData: OnData): Promise<void> {
  if (!app.isPackaged) return
  if (synced || existsSync(mainVenvPython())) {
    synced = true
    return
  }
  const uv = findUv()
  onData('First run: setting up the main AiSongTool environment (one-time)...\r\n')
  const code = await runBlocking(
    [uv, 'sync', '--project', mainEnvProjectDir()],
    mainEnvProjectDir(),
    onData,
    { UV_PROJECT_ENVIRONMENT: `${dataDir()}/.venv` }
  )
  if (code !== 0) {
    throw new Error(`Setting up the main environment failed (uv sync exit ${code}).`)
  }
  synced = true
}
