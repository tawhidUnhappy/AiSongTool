/** Standalone "Nightcore a video" tool (Tools view) — speeds up + pitches up
 * a video's audio (the classic nightcore resample trick) and speeds up its
 * video stream by the same factor to stay in sync. No other visual change;
 * the output just runs faster end-to-end, so it's shorter than the input. */
import { existsSync, mkdirSync } from 'fs'
import path from 'path'
import { jobsDir } from './paths'
import type { OnData } from './jobs'
import { shortId } from './short-id'
import { nightcoreVideoInPlace, DEFAULT_SPEED } from './tools/nightcore'
import type { NightcoreVideoParams, NightcoreVideoResult } from '../shared/types'

export type { NightcoreVideoParams, NightcoreVideoResult }

export async function runNightcoreVideo(
  params: NightcoreVideoParams,
  onData: OnData
): Promise<NightcoreVideoResult> {
  const jobDir = path.join(jobsDir(), '_nightcore_video', shortId())
  mkdirSync(jobDir, { recursive: true })

  const ext = path.extname(params.videoPath) || '.mp4'
  const outPath = path.join(jobDir, `nightcore${ext}`)
  const speed = params.speed || DEFAULT_SPEED

  const returncode = await nightcoreVideoInPlace(params.videoPath, outPath, speed, params.reverb, jobDir, onData)
  return { returncode, videoPath: returncode === 0 && existsSync(outPath) ? outPath : null }
}
