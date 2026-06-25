/** Port of `aisongtool/nightcore.py`'s audio edit, plus a video-in-place
 * variant for the Tools tab's standalone "Nightcore a video" utility (the
 * Create flow's own nightcore+render path stays in create-pipeline.ts). */
import { execFile } from 'child_process'
import { findFfmpeg, findFfprobe } from '../paths'
import { runBlocking, type OnData } from '../jobs'

export const DEFAULT_SPEED = 1.25

// The genre's actual sound is more than the resample trick — community
// nightcore edits near-universally also push a "smile curve" EQ (boosted
// bass + treble, since raising pitch via resample alone can sound thin/
// brittle) and normalize loudness for that punchier, more energetic feel.
// Applied by default; reverb is the one stylistic addition left optional
// (some edits add it for a dreamier/echoey feel, many don't).
const NIGHTCORE_ENHANCE_FILTERS = 'bass=g=6,treble=g=3,loudnorm=I=-14:TP=-1.5:LRA=11'
const NIGHTCORE_REVERB_FILTER = 'aecho=0.8:0.7:40:0.25'

function probeSampleRate(audioPath: string): Promise<number> {
  const ffprobe = findFfprobe()
  return new Promise((resolve, reject) => {
    execFile(
      ffprobe,
      ['-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=sample_rate', '-of', 'json', audioPath],
      (error, stdout) => {
        if (error) {
          reject(error)
          return
        }
        const data = JSON.parse(stdout)
        const streams = data.streams ?? []
        if (streams.length === 0 || !streams[0].sample_rate) {
          reject(new Error(`Could not determine sample rate of ${audioPath}`))
          return
        }
        resolve(Number(streams[0].sample_rate))
      }
    )
  })
}

/** The classic nightcore edit: resample as if the track played faster
 * (raises pitch and speed together, not an independent tempo stretch),
 * plus the EQ/loudness treatment that's actually typical of nightcore
 * edits — see NIGHTCORE_ENHANCE_FILTERS. */
export async function buildNightcoreAudioCmd(
  inPath: string,
  outPath: string,
  speed: number = DEFAULT_SPEED,
  reverb: boolean = false
): Promise<string[]> {
  const ffmpeg = findFfmpeg()
  const rate = await probeSampleRate(inPath)
  const newRate = Math.round(rate * speed)
  const af = [`asetrate=${newRate}`, `aresample=${rate}`, NIGHTCORE_ENHANCE_FILTERS]
  if (reverb) af.push(NIGHTCORE_REVERB_FILTER)
  return [ffmpeg, '-y', '-i', inPath, '-af', af.join(','), '-c:a', 'libmp3lame', '-b:a', '192k', outPath]
}

/** Same nightcore audio edit applied to a video file in place — the video
 * stream is sped up by the same factor (`setpts=PTS/speed`) so it stays in
 * sync with the now-faster audio, with no other visual change. Net result
 * runs `speed`x faster end-to-end, so the output is shorter than the input.
 *
 * `useGpu` switches decode (`-hwaccel cuda`) and encode (`h264_nvenc`,
 * fastest preset) onto the NVIDIA GPU instead of CPU x264 — a full
 * re-encode is the slow part of this tool, and NVENC is dramatically
 * faster than libx264 on a machine with an NVIDIA GPU. The caller is
 * expected to fall back to the CPU build (useGpu=false) if the GPU
 * attempt fails (no GPU, or an ffmpeg build without NVENC support). */
export async function buildNightcoreVideoCmd(
  inPath: string,
  outPath: string,
  speed: number = DEFAULT_SPEED,
  reverb: boolean = false,
  useGpu: boolean = true
): Promise<string[]> {
  const ffmpeg = findFfmpeg()
  const rate = await probeSampleRate(inPath)
  const newRate = Math.round(rate * speed)
  const af = [`asetrate=${newRate}`, `aresample=${rate}`, NIGHTCORE_ENHANCE_FILTERS]
  if (reverb) af.push(NIGHTCORE_REVERB_FILTER)

  const videoArgs = useGpu
    ? ['-c:v', 'h264_nvenc', '-preset', 'p1', '-tune', 'hq', '-rc', 'vbr', '-cq', '19']
    : ['-c:v', 'libx264', '-preset', 'veryfast']
  const hwaccelArgs = useGpu ? ['-hwaccel', 'cuda'] : []

  return [
    ffmpeg,
    '-y',
    ...hwaccelArgs,
    '-i',
    inPath,
    '-vf',
    `setpts=PTS/${speed}`,
    '-af',
    af.join(','),
    ...videoArgs,
    '-pix_fmt',
    'yuv420p',
    '-c:a',
    'aac',
    '-b:a',
    '192k',
    outPath
  ]
}

/** Runs the video-in-place nightcore edit, trying the GPU build first and
 * transparently re-running on CPU if that fails (no NVIDIA GPU, or an
 * ffmpeg build without NVENC support) — shared by the Tools tab's
 * standalone tool and the Create flow's own nightcore step. */
export async function nightcoreVideoInPlace(
  inPath: string,
  outPath: string,
  speed: number,
  reverb: boolean,
  cwd: string,
  onData: OnData
): Promise<number> {
  const gpuCmd = await buildNightcoreVideoCmd(inPath, outPath, speed, reverb, true)
  let returncode = await runBlocking(gpuCmd, cwd, onData)

  if (returncode !== 0) {
    onData('\n[nightcore] GPU encode failed — falling back to CPU encoding…\n')
    const cpuCmd = await buildNightcoreVideoCmd(inPath, outPath, speed, reverb, false)
    returncode = await runBlocking(cpuCmd, cwd, onData)
  }
  return returncode
}
