/**
 * HTTP client for acestep.cpp's `ace-server` (https://github.com/ServeurpersoCom/acestep.cpp).
 * Replaces the old client for the original diffusers-based ACE-Step-1.5
 * REST API (`/release_task` + `/query_result`) — acestep.cpp's `ace-server`
 * speaks a different, simpler job protocol: `POST /lm` (caption+lyrics ->
 * audio codes), `POST /synth` (codes -> audio), both returning `{id}` and
 * polled via `GET /job?id=`. See acestep.cpp's docs/ARCHITECTURE.md for the
 * full AceRequest field reference.
 */
import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { selectedModelFiles } from './ace-step'

export type LogFn = (line: string) => void

const DEFAULT_HOST = '127.0.0.1'
const DEFAULT_PORT = 8080

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

export interface GenerateSongOptions {
  prompt: string
  lyrics: string
  duration: number
  outDir: string
  log?: LogFn
  host?: string
  port?: number
  /** Song title — maps to AceRequest's `track` field. */
  songName?: string
  vocalLanguage?: string
  instrumental?: boolean
  seed?: number | null
  pollIntervalMs?: number
  timeoutMs?: number
  onProgress?: LogFn
}

type AceRequest = Record<string, unknown>

/** Submit caption(+lyrics) -> /lm for audio codes -> /synth for audio,
 * polling each job, then save the result.
 *
 * `prompt`/`lyrics` are always treated as literal — the caller (create-
 * pipeline.ts) has already resolved who wrote them (manual text or Gemma 4)
 * before this is called, so there's no "let acestep.cpp's own LM expand a
 * short description" mode here anymore (that's `use_cot_caption`, kept off
 * unconditionally to avoid the model silently rewriting a caption the
 * caller already finalized). `instrumental=true` forces
 * `lyrics="[Instrumental]"` (acestep.cpp's documented convention — there's
 * no separate boolean field for it). `seed=null` means random
 * (`seed: -1`). `vocalLanguage` should already be resolved to a real code by
 * the caller (e.g. via Gemma 4 language detection) rather than left as
 * "unknown" — acestep.cpp's own metadata-fill guesses from the caption alone
 * when left blank, and has been observed guessing a wrong language entirely,
 * which then mismatches the literal lyric text and produces weak/garbled
 * vocals easy to mistake for "instrumental only". */
export async function generateSong(opts: GenerateSongOptions): Promise<string> {
  const {
    prompt,
    lyrics,
    duration,
    outDir,
    log = console.log,
    host = DEFAULT_HOST,
    port = DEFAULT_PORT,
    songName = '',
    vocalLanguage = 'en',
    instrumental = false,
    seed = null,
    pollIntervalMs = 2000,
    timeoutMs = 600_000,
    onProgress
  } = opts

  const models = selectedModelFiles()
  const base = baseUrl(host, port)
  const lmBody: AceRequest = {
    duration,
    vocal_language: vocalLanguage === 'unknown' ? 'en' : vocalLanguage,
    seed: seed === null ? -1 : seed,
    lm_model: models.lm,
    use_cot_caption: false,
    caption: prompt,
    lyrics: instrumental ? '[Instrumental]' : lyrics
  }
  if (songName.trim()) lmBody.track = songName.trim()

  log(`POST ${base}/lm ${JSON.stringify(lmBody)}\r\n`)
  try {
    const lmResult = await runJob(base, '/lm', lmBody, log, pollIntervalMs, timeoutMs, onProgress, 'lm')
    const synthBody: AceRequest = {
      ...(lmResult as AceRequest),
      synth_model: models.dit,
      output_format: 'mp3'
    }
    // Previously logged only the URL, not the body — unlike the /lm log
    // line below, which prints `lm_model` — so there was no way to
    // visually confirm from the Terminal pane which DiT/synth model a run
    // actually used; echoing `synth_model` here closes that gap.
    log(`POST ${base}/synth synth_model=${synthBody.synth_model}\r\n`)
    const audioBuffer = await runSynthJob(base, synthBody, log, pollIntervalMs, timeoutMs, onProgress)

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

async function postJson(url: string, body: unknown, timeoutMs: number): Promise<{ status: number; text: string }> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal
    })
    return { status: resp.status, text: await resp.text() }
  } finally {
    clearTimeout(timer)
  }
}

/** Submit a job, poll `GET /job?id=` until done/failed/cancelled. */
async function pollJob(
  base: string,
  jobId: string,
  log: LogFn,
  pollIntervalMs: number,
  timeoutMs: number,
  onProgress: LogFn | undefined,
  label: string
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let lastStatus: string | null = null
  while (Date.now() < deadline) {
    await sleep(pollIntervalMs)
    let resp: Response
    try {
      resp = await fetch(`${base}/job?id=${jobId}`)
    } catch (exc) {
      log(`Poll request failed (${String(exc)}) — server may still be loading models, retrying...\r\n`)
      continue
    }
    if (resp.status !== 200) {
      log(`/job?id=${jobId} returned ${resp.status}, retrying...\r\n`)
      continue
    }
    const payload = (await resp.json()) as { status?: string }
    const status = payload.status ?? 'unknown'
    if (status !== lastStatus) {
      log(`${label} job ${jobId}: ${status}\r\n`)
      lastStatus = status
      onProgress?.(`${label}: ${status}`)
    }
    if (status === 'done') return
    if (status === 'failed' || status === 'cancelled') {
      throw new AceStepApiError(`${label} job ${jobId} ${status}`)
    }
  }
  throw new AceStepApiError(`${label} job ${jobId} timed out after ${Math.round(timeoutMs / 1000)}s.`)
}

async function runJob(
  base: string,
  endpoint: string,
  body: AceRequest,
  log: LogFn,
  pollIntervalMs: number,
  timeoutMs: number,
  onProgress: LogFn | undefined,
  label: string
): Promise<AceRequest> {
  const resp = await postJson(`${base}${endpoint}`, body, 120_000)
  if (resp.status !== 200) {
    throw new AceStepApiError(`${endpoint} failed (${resp.status}): ${resp.text}`)
  }
  const jobId = (JSON.parse(resp.text) as { id?: string }).id
  if (!jobId) throw new AceStepApiError(`${endpoint} returned no job id: ${resp.text}`)
  log(`${label} job submitted: ${jobId}\r\n`)
  await pollJob(base, jobId, log, pollIntervalMs, timeoutMs, onProgress, label)

  const resultResp = await fetch(`${base}/job?id=${jobId}&result=1`)
  if (resultResp.status !== 200) {
    throw new AceStepApiError(`Fetching ${label} result failed (${resultResp.status}): ${await resultResp.text()}`)
  }
  const items = (await resultResp.json()) as AceRequest[]
  if (!items || items.length === 0) {
    throw new AceStepApiError(`${label} job ${jobId} returned no result items.`)
  }
  return items[0]
}

/** Same job lifecycle as `runJob`, but `/synth`'s result is `multipart/mixed`
 * (audio + latents) rather than JSON — pull out just the audio part. */
async function runSynthJob(
  base: string,
  body: AceRequest,
  log: LogFn,
  pollIntervalMs: number,
  timeoutMs: number,
  onProgress: LogFn | undefined
): Promise<Buffer> {
  const resp = await postJson(`${base}/synth`, body, 120_000)
  if (resp.status !== 200) {
    throw new AceStepApiError(`/synth failed (${resp.status}): ${resp.text}`)
  }
  const jobId = (JSON.parse(resp.text) as { id?: string }).id
  if (!jobId) throw new AceStepApiError(`/synth returned no job id: ${resp.text}`)
  log(`synth job submitted: ${jobId}\r\n`)
  await pollJob(base, jobId, log, pollIntervalMs, timeoutMs, onProgress, 'synth')

  const resultResp = await fetch(`${base}/job?id=${jobId}&result=1`)
  if (resultResp.status !== 200) {
    throw new AceStepApiError(`Fetching synth result failed (${resultResp.status}): ${await resultResp.text()}`)
  }
  const contentType = resultResp.headers.get('content-type') ?? ''
  const boundaryMatch = contentType.match(/boundary=("?)([^;"]+)\1/)
  if (!boundaryMatch) {
    throw new AceStepApiError(`/synth result wasn't multipart (content-type: ${contentType})`)
  }
  const buffer = Buffer.from(await resultResp.arrayBuffer())
  const parts = splitMultipart(buffer, boundaryMatch[2])
  const audioPart = parts.find((p) => /^audio\//i.test(p.contentType))
  if (!audioPart) {
    throw new AceStepApiError(
      `/synth multipart result had no audio part (found: ${parts.map((p) => p.contentType).join(', ')})`
    )
  }
  return audioPart.body
}

interface MultipartPart {
  contentType: string
  body: Buffer
}

/** Minimal `multipart/mixed` parser — just enough to split a response body
 * into its parts and read each one's Content-Type + raw bytes, since Node's
 * `fetch` has no built-in multipart decoder for response bodies (only for
 * constructing outgoing `FormData`). */
function splitMultipart(buffer: Buffer, boundary: string): MultipartPart[] {
  const delimiter = Buffer.from(`--${boundary}`)
  const parts: MultipartPart[] = []
  let searchFrom = 0
  for (;;) {
    const start = buffer.indexOf(delimiter, searchFrom)
    if (start === -1) break
    const afterDelim = start + delimiter.length
    if (buffer.slice(afterDelim, afterDelim + 2).toString() === '--') break // closing boundary
    const next = buffer.indexOf(delimiter, afterDelim)
    if (next === -1) break
    const partBuffer = buffer.slice(afterDelim, next)
    const headerEnd = partBuffer.indexOf('\r\n\r\n')
    if (headerEnd !== -1) {
      const headerText = partBuffer.slice(0, headerEnd).toString('utf8')
      const ctMatch = headerText.match(/Content-Type:\s*([^\r\n]+)/i)
      // Trailing \r\n before the next boundary delimiter belongs to the
      // delimiter line, not the part body.
      const body = partBuffer.slice(headerEnd + 4, partBuffer.length - 2)
      parts.push({ contentType: ctMatch ? ctMatch[1].trim() : '', body })
    }
    searchFrom = next
  }
  return parts
}
