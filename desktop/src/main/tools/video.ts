/** Port of `aisongtool/video.py`'s `build_render_cmd` — renders an MP4 from
 * a still background image + audio + karaoke ASS track. */
import path from 'path'
import { findFfmpeg } from '../paths'
import { runBlocking, type OnData } from '../jobs'

/** Escape a path for use inside ffmpeg's `ass=...` filter argument, where
 * `:` and `\` are filter-syntax metacharacters. */
function escapeForAssFilter(p: string): string {
  const s = path.resolve(p).replace(/\\/g, '/')
  return s.replace(/:/g, '\\:')
}

export function buildRenderCmd(
  backgroundImage: string,
  audioPath: string,
  karaokeAssPath: string,
  outPath: string,
  resolution: [number, number] = [1920, 1080],
  useGpu: boolean = false
): string[] {
  const ffmpeg = findFfmpeg()
  const [width, height] = resolution
  const vf =
    `scale=${width}:${height}:force_original_aspect_ratio=increase,` +
    `crop=${width}:${height},` +
    `ass='${escapeForAssFilter(karaokeAssPath)}'`
  // `-tune stillimage` is an x264-only knob (it's still the right call for
  // the CPU fallback, where it measurably tightens up an unchanging-image
  // encode) — NVENC has no equivalent flag, but the same near-zero motion
  // already makes the encode cheap, and `-cq 19` at NVENC's p4 preset (a
  // quality-leaning preset, not the fastest one — this is a one-shot full
  // render, not a per-frame interactive cost) keeps quality on par with the
  // CPU build while running on the GPU instead of pegging a CPU core for
  // the song's full duration.
  const videoArgs = useGpu
    ? ['-c:v', 'h264_nvenc', '-preset', 'p4', '-tune', 'hq', '-rc', 'vbr', '-cq', '19']
    : ['-c:v', 'libx264', '-tune', 'stillimage', '-preset', 'medium', '-crf', '18']
  return [
    ffmpeg,
    '-y',
    '-loop',
    '1',
    '-i',
    backgroundImage,
    '-i',
    audioPath,
    '-vf',
    vf,
    ...videoArgs,
    '-pix_fmt',
    'yuv420p',
    '-c:a',
    'aac',
    '-b:a',
    '192k',
    '-shortest',
    outPath
  ]
}

/** Runs the static-image lyric-video render, trying GPU NVENC first and
 * transparently falling back to the CPU x264 build if that fails (no
 * NVIDIA GPU, or an ffmpeg build without NVENC support) — same
 * try-GPU-then-CPU pattern as `nightcore.ts`'s `nightcoreVideoInPlace`. */
export async function renderVideoWithFallback(
  backgroundImage: string,
  audioPath: string,
  karaokeAssPath: string,
  outPath: string,
  cwd: string,
  onData: OnData,
  resolution: [number, number] = [1920, 1080]
): Promise<number> {
  const gpuCmd = buildRenderCmd(backgroundImage, audioPath, karaokeAssPath, outPath, resolution, true)
  let returncode = await runBlocking(gpuCmd, cwd, onData)

  if (returncode !== 0) {
    onData('\n[video] GPU encode failed — falling back to CPU encoding…\n')
    const cpuCmd = buildRenderCmd(backgroundImage, audioPath, karaokeAssPath, outPath, resolution, false)
    returncode = await runBlocking(cpuCmd, cwd, onData)
  }
  return returncode
}
