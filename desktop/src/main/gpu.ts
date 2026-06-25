/**
 * Lightweight `nvidia-smi` polling — used after killing a GPU-heavy process
 * (ACE-Step's API server) to confirm the driver has actually reclaimed its
 * VRAM before the next GPU-heavy step starts, instead of guessing a fixed
 * sleep duration and hoping it was long enough.
 */
import { execFile } from 'child_process'

function queryFreeMb(): Promise<number | null> {
  return new Promise((resolve) => {
    execFile(
      'nvidia-smi',
      ['--query-gpu=memory.free', '--format=csv,noheader,nounits'],
      (error, stdout) => {
        if (error) {
          resolve(null)
          return
        }
        const value = Number(stdout.trim().split('\n')[0])
        resolve(Number.isFinite(value) ? value : null)
      }
    )
  })
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Polls until at least `thresholdMb` is free or `timeoutMs` elapses.
 * Falls back to a flat 3s wait if `nvidia-smi` isn't on PATH (e.g.
 * non-NVIDIA setups) or its output can't be parsed — same safety margin
 * the fixed-delay version used before this, just skipped immediately once
 * we can actually confirm the GPU is free instead of always paying it. */
export async function waitForGpuMemoryFree(
  thresholdMb = 2048,
  timeoutMs = 20_000,
  pollIntervalMs = 500
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let sawReading = false
  while (Date.now() < deadline) {
    const freeMb = await queryFreeMb()
    if (freeMb === null) break // nvidia-smi unavailable/unparseable — fall through to flat wait
    sawReading = true
    if (freeMb >= thresholdMb) return
    await sleep(pollIntervalMs)
  }
  if (!sawReading) {
    await sleep(3000)
  }
}
