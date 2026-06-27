/**
 * HTTP client for ACE-Step-1.5's own `acestep-api` REST server
 * (https://github.com/ACE-Step/ACE-Step-1.5) — replaces the earlier client
 * for `acestep.cpp`'s `ace-server` (a two-stage `/lm` + `/synth` + `/job?id=`
 * job protocol). ACE-Step-1.5's API is a single async job queue instead:
 * `POST /release_task` submits one task (caption+lyrics -> a finished song
 * in one step, no separate codes-then-audio stages), `POST /query_result`
 * polls it by `task_id`, and the finished file is fetched via a plain
 * `GET /v1/audio?path=...` download — no multipart response to parse.
 */
import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'

export type LogFn = (line: string) => void

const DEFAULT_HOST = '127.0.0.1'
const DEFAULT_PORT = 8001

export class AceStepApiError extends Error {}

function baseUrl(host: string, port: number): string {
  return `http://${host}:${port}`
}

export async function isServerUp(host = DEFAULT_HOST, port = DEFAULT_PORT): Promise<boolean> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 3000)
    const resp = await fetch(`${baseUrl(host, port)}/health`, { signal: controller.signal })
    clearTimeout(timer)
    return resp.status === 200
  } catch {
    return false
  }
}

/** Poll /health until it responds or `timeoutMs` passes (model loading on
 * first start can take a while). */
export async function waitForServer(
  host = DEFAULT_HOST,
  port = DEFAULT_PORT,
  timeoutMs = 300_000,
  log: LogFn = console.log
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await isServerUp(host, port)) return true
    await sleep(2000)
  }
  log(`ACE-Step server did not become healthy within ${Math.round(timeoutMs / 1000)}s.`)
  return false
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

type AceRequest = Record<string, unknown>

export interface GenerateSongOptions {
  /** The full `/release_task` request body, built by the caller
   * (create-pipeline.ts) by merging the Create page's schema-driven
   * generation form values — see ace-step-schema.ts/ace_step_schema.py —
   * straight into one object, field-for-field. Deliberately untyped here:
   * the whole point of driving the form from ACE-Step's own request model
   * is that this app never hand-maintains a fixed list of accepted fields,
   * so a fixed TS interface for the body would defeat that. */
  requestBody: AceRequest
  outDir: string
  log?: LogFn
  host?: string
  port?: number
  pollIntervalMs?: number
  timeoutMs?: number
  onProgress?: LogFn
}

interface ReleaseTaskResponse {
  data?: { task_id?: string }
  code?: number
  error?: string | null
}

interface QueryResultItem {
  task_id: string
  status: number // 0 = queued/running, 1 = succeeded, 2 = failed
  result?: string // JSON string: { file, metas, ... }
}

/** Submit one `/release_task` (caption+lyrics -> a finished song in a single
 * job, no separate codes/audio stages like acestep.cpp's `/lm`+`/synth`),
 * poll `/query_result` until done, then download the finished file from
 * `/v1/audio?path=...`. */
export async function generateSong(opts: GenerateSongOptions): Promise<string> {
  const {
    requestBody,
    outDir,
    log = console.log,
    host = DEFAULT_HOST,
    port = DEFAULT_PORT,
    pollIntervalMs = 2000,
    timeoutMs = 600_000,
    onProgress
  } = opts

  const base = baseUrl(host, port)
  const taskBody: AceRequest = { task_type: 'text2music', batch_size: 1, ...requestBody }

  log(`POST ${base}/release_task ${JSON.stringify(taskBody)}\r\n`)
  try {
    const taskId = await releaseTask(base, taskBody, log)
    const resultJson = await pollResult(base, taskId, log, pollIntervalMs, timeoutMs, onProgress)
    const filePath = resultJson.file
    if (!filePath) throw new AceStepApiError(`Task ${taskId} succeeded but returned no file path: ${JSON.stringify(resultJson)}`)

    log(`GET ${base}${filePath}\r\n`)
    const audioResp = await fetch(`${base}${filePath}`)
    if (!audioResp.ok) {
      throw new AceStepApiError(`Downloading result audio failed (${audioResp.status})`)
    }
    const audioBuffer = Buffer.from(await audioResp.arrayBuffer())

    mkdirSync(outDir, { recursive: true })
    const outPath = path.join(outDir, 'generated.mp3')
    writeFileSync(outPath, audioBuffer)
    log(`Saved generated song to ${outPath}\r\n`)
    return outPath
  } catch (exc) {
    log(`Generation failed: ${String(exc)}\r\n`)
    throw exc
  }
}

async function releaseTask(base: string, body: AceRequest, log: LogFn): Promise<string> {
  const resp = await fetch(`${base}/release_task`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  const text = await resp.text()
  if (!resp.ok) {
    throw new AceStepApiError(`/release_task failed (${resp.status}): ${text}`)
  }
  const parsed = JSON.parse(text) as ReleaseTaskResponse
  const taskId = parsed.data?.task_id
  if (!taskId) throw new AceStepApiError(`/release_task returned no task_id: ${text}`)
  log(`task submitted: ${taskId}\r\n`)
  return taskId
}

interface ParsedResultItem {
  file?: string
  metas?: Record<string, unknown>
}

async function pollResult(
  base: string,
  taskId: string,
  log: LogFn,
  pollIntervalMs: number,
  timeoutMs: number,
  onProgress: LogFn | undefined
): Promise<ParsedResultItem> {
  const deadline = Date.now() + timeoutMs
  let lastStatus: number | null = null
  while (Date.now() < deadline) {
    await sleep(pollIntervalMs)
    let resp: Response
    try {
      resp = await fetch(`${base}/query_result`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id_list: [taskId] })
      })
    } catch (exc) {
      log(`Poll request failed (${String(exc)}) — server may still be loading models, retrying...\r\n`)
      continue
    }
    if (resp.status !== 200) {
      log(`/query_result returned ${resp.status}, retrying...\r\n`)
      continue
    }
    const payload = (await resp.json()) as { data?: QueryResultItem[] }
    const item = payload.data?.find((i) => i.task_id === taskId)
    if (!item) {
      log(`/query_result didn't include task ${taskId} yet, retrying...\r\n`)
      continue
    }
    if (item.status !== lastStatus) {
      const label = item.status === 0 ? 'running' : item.status === 1 ? 'succeeded' : 'failed'
      log(`task ${taskId}: ${label}\r\n`)
      lastStatus = item.status
      onProgress?.(`generating: ${label}`)
    }
    if (item.status === 1) {
      // `result` decodes to an array (one entry per `batch_size`, even when
      // batch_size is 1 — confirmed against a real server response, which
      // came back as `[{file, metas, ...}]`, not a flat object).
      if (!item.result) return {}
      const parsed = JSON.parse(item.result) as ParsedResultItem[]
      return parsed[0] ?? {}
    }
    if (item.status === 2) {
      throw new AceStepApiError(`task ${taskId} failed: ${item.result ?? '(no detail)'}`)
    }
  }
  throw new AceStepApiError(`task ${taskId} timed out after ${Math.round(timeoutMs / 1000)}s.`)
}
