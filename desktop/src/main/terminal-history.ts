/**
 * Buffers every chunk written to the Terminal pane's `terminal:data` channel
 * so a freshly-mounted `<Terminal>` (e.g. the user switches to the Terminal
 * tab after a job already started from the Setup view, or just navigates
 * away and back) can replay what already happened instead of showing
 * nothing — `event.sender.send(...)` is fire-and-forget; a renderer-side
 * listener that wasn't mounted yet when a chunk was sent never gets it,
 * which looked like "nothing is happening" and led to clicking an install
 * button a second time while the first install was still genuinely running.
 *
 * One continuous buffer for the whole app session (not reset per-job) —
 * the Terminal tab is meant to behave like a real persistent terminal, not
 * just "this one job's output". Capped so a very long/chatty job (e.g. a
 * tqdm-heavy model download) can't grow this unboundedly.
 */
const MAX_HISTORY_CHARS = 2_000_000

let history = ''

export function recordTerminalChunk(chunk: string): void {
  history += chunk
  if (history.length > MAX_HISTORY_CHARS) {
    history = history.slice(history.length - MAX_HISTORY_CHARS)
  }
}

export function getTerminalHistory(): string {
  return history
}
