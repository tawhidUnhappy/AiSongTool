import { useEffect, useRef, useState } from 'react'
import type { ModelOptions } from '../../../shared/types'

function path_basename(p: string): string {
  return p.replace(/\\/g, '/').split('/').pop() ?? p
}

export function Tools(): React.JSX.Element {
  const [modelOptions, setModelOptions] = useState<ModelOptions | null>(null)
  const [songPath, setSongPath] = useState<string | null>(null)
  const [whisperModel, setWhisperModel] = useState('large-v3')
  // Defaults to the full mix — vocal separation can introduce its own
  // artifacts on a mix where vocals and instrumental are tightly blended,
  // which sometimes hurts WhisperX more than it helps. Opt-in, not opt-out.
  const [separateVocals, setSeparateVocals] = useState(false)
  const [demucsShifts, setDemucsShifts] = useState(0)
  const [vad, setVad] = useState<'silero' | 'pyannote'>('silero')
  const [lyricsText, setLyricsText] = useState('')
  const [captionSource, setCaptionSource] = useState<'auto' | 'transcript' | 'lyrics'>('auto')
  const [running, setRunning] = useState(false)
  const [statusText, setStatusText] = useState('Pick a song, then click Transcribe.')
  const [srtPath, setSrtPath] = useState<string | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    window.api.getModelOptions().then((opts) => {
      setModelOptions(opts)
      if (opts.whisper.length > 0) setWhisperModel((prev) => prev || opts.whisper[opts.whisper.length - 1].value)
    })
    window.api.getSettings().then((s) => {
      setWhisperModel(s.whisperModel)
      setSeparateVocals(s.toolsSeparateVocals)
      setDemucsShifts(s.demucsShifts)
      setVad(s.vad)
    })
  }, [])

  const onWhisperModelChange = (v: string): void => {
    setWhisperModel(v)
    window.api.setSetting('whisperModel', v)
  }
  const onSeparateVocalsChange = (v: boolean): void => {
    setSeparateVocals(v)
    window.api.setSetting('toolsSeparateVocals', v)
  }
  const onDemucsShiftsChange = (v: number): void => {
    setDemucsShifts(v)
    window.api.setSetting('demucsShifts', v)
  }
  const onVadChange = (v: 'silero' | 'pyannote'): void => {
    setVad(v)
    window.api.setSetting('vad', v)
  }

  const pickSong = async (): Promise<void> => {
    const p = await window.api.pickSongFile()
    if (p) setSongPath(p)
  }

  const transcribe = async (): Promise<void> => {
    if (running || !songPath) return
    setRunning(true)
    setSrtPath(null)
    setStatusText('Transcribing… this can take a while for long songs.')
    try {
      const result = await window.api.transcribeSong({
        songPath,
        whisperModel,
        skipDemucs: !separateVocals,
        demucsShifts,
        vad,
        lyricsText,
        captionSource
      })
      if (result.returncode === 0 && result.srtPath) {
        setSrtPath(result.srtPath)
        setStatusText('Done.')
        setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
      } else {
        setStatusText('Transcription failed — check the Terminal pane for details.')
      }
    } finally {
      setRunning(false)
    }
  }

  const saveSrt = async (): Promise<void> => {
    if (!srtPath || !songPath) return
    const stem = path_basename(songPath).replace(/\.[^.]+$/, '')
    await window.api.saveArtifact(srtPath, `${stem}.srt`)
  }

  const downloadSrt = async (): Promise<void> => {
    if (!srtPath || !songPath) return
    const stem = path_basename(songPath).replace(/\.[^.]+$/, '')
    const dest = await window.api.downloadArtifact(srtPath, `${stem}.srt`)
    setStatusText(`Downloaded to ${dest}`)
  }

  const [ncVideoPath, setNcVideoPath] = useState<string | null>(null)
  const [ncSpeed, setNcSpeed] = useState(1.25)
  const [ncReverb, setNcReverb] = useState(false)
  const [ncRunning, setNcRunning] = useState(false)
  const [ncStatusText, setNcStatusText] = useState('Pick a video, then click Nightcore.')
  const [ncOutPath, setNcOutPath] = useState<string | null>(null)
  const ncResultRef = useRef<HTMLDivElement>(null)

  const pickNcVideo = async (): Promise<void> => {
    const p = await window.api.pickVideoFile()
    if (p) setNcVideoPath(p)
  }

  const runNightcoreVideo = async (): Promise<void> => {
    if (ncRunning || !ncVideoPath) return
    setNcRunning(true)
    setNcOutPath(null)
    setNcStatusText('Rendering… speed and length depend on the source video.')
    try {
      const result = await window.api.nightcoreVideo({ videoPath: ncVideoPath, speed: ncSpeed, reverb: ncReverb })
      if (result.returncode === 0 && result.videoPath) {
        setNcOutPath(result.videoPath)
        setNcStatusText('Done.')
        setTimeout(() => ncResultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
      } else {
        setNcStatusText('Nightcore render failed — check the Terminal pane for details.')
      }
    } finally {
      setNcRunning(false)
    }
  }

  const saveNcVideo = async (): Promise<void> => {
    if (!ncOutPath || !ncVideoPath) return
    const stem = path_basename(ncVideoPath).replace(/\.[^.]+$/, '')
    const ext = path_basename(ncOutPath).match(/\.[^.]+$/)?.[0] ?? '.mp4'
    await window.api.saveArtifact(ncOutPath, `${stem}_nightcore${ext}`)
  }

  const downloadNcVideo = async (): Promise<void> => {
    if (!ncOutPath || !ncVideoPath) return
    const stem = path_basename(ncVideoPath).replace(/\.[^.]+$/, '')
    const ext = path_basename(ncOutPath).match(/\.[^.]+$/)?.[0] ?? '.mp4'
    const dest = await window.api.downloadArtifact(ncOutPath, `${stem}_nightcore${ext}`)
    setNcStatusText(`Downloaded to ${dest}`)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}>
      <Card title="Transcribe to .srt">
        <div style={muted}>
          Runs just WhisperX on a song and saves a plain .srt of what's actually sung — no lyrics text needed,
          no video/image generation.
        </div>

        <div style={row}>
          <button onClick={pickSong}>Pick song file…</button>
          <span style={muted}>{songPath ? `Using: ${path_basename(songPath)}` : 'No song selected.'}</span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>Lyrics (optional)</span>
          <textarea
            value={lyricsText}
            onChange={(e) => setLyricsText(e.target.value)}
            placeholder="Paste the song's lyrics here to align them against the transcript instead of transcript-only…"
            rows={6}
            style={{ resize: 'vertical', fontFamily: 'inherit', fontSize: 13 }}
          />
        </div>

        {lyricsText.trim().length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Caption source</span>
            <Radio
              name="captionSource"
              value={captionSource}
              onChange={(v) => setCaptionSource(v as typeof captionSource)}
              options={[
                ['auto', 'Auto (lyrics + transcript)'],
                ['transcript', 'Whisper transcript only'],
                ['lyrics', 'My lyrics + transcript']
              ]}
            />
            <span style={muted}>
              A song can skip or repeat lines vs the literal lyrics — "Whisper transcript only" shows exactly
              what's actually sung instead of forcing mismatched lyrics onto the wrong timing.
            </span>
          </div>
        )}

        {modelOptions && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 320 }}>
            <span style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>WhisperX model</span>
            <select value={whisperModel} onChange={(e) => onWhisperModelChange(e.target.value)}>
              {modelOptions.whisper.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        )}

        <label style={{ fontSize: 13 }}>
          <input type="checkbox" checked={separateVocals} onChange={(e) => onSeparateVocalsChange(e.target.checked)} />{' '}
          Separate vocals first (Demucs)
        </label>
        <div style={muted}>
          Transcribes the full song by default. Try checking this only if the transcript comes back empty or
          wrong — on some mixes, separating vocals from a tightly-blended instrumental introduces its own
          artifacts and makes WhisperX worse, not better.
        </div>

        {separateVocals && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 320 }}>
            <span style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>Vocal isolation quality</span>
            <select value={demucsShifts} onChange={(e) => onDemucsShiftsChange(Number(e.target.value))}>
              <option value={0}>Fast (single pass)</option>
              <option value={2}>Better (3x slower)</option>
              <option value={5}>Best (6x slower)</option>
            </select>
            <span style={muted}>
              Higher settings re-run separation on shifted copies of the audio and average the results —
              cleaner vocals out of a heavily blended mix, at a proportional cost in time.
            </span>
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 320 }}>
          <span style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>Voice detector</span>
          <select value={vad} onChange={(e) => onVadChange(e.target.value as typeof vad)}>
            <option value="silero">Fast (silero, default)</option>
            <option value="pyannote">More accurate under loud instrumentation (pyannote, slower)</option>
          </select>
          {vad === 'pyannote' && (
            <span style={muted}>
              First use downloads a model from Hugging Face — can take a moment.
            </span>
          )}
        </div>

        <div style={row}>
          <button onClick={transcribe} disabled={running || !songPath}>
            {running ? 'Transcribing…' : 'Transcribe'}
          </button>
        </div>
        <div style={muted}>{statusText}</div>
      </Card>

      <div ref={resultRef} />
      {srtPath && (
        <Card title="Result">
          <div style={{ color: '#8f8' }}>✓ Done — transcript ready.</div>
          <div style={row}>
            <button onClick={saveSrt}>Save to output folder</button>
            <button onClick={downloadSrt}>Download</button>
          </div>
          <div style={muted}>
            "Download" saves to your Downloads folder, Chrome-style — a name collision adds "(1)", "(2)",
            etc. instead of overwriting.
          </div>
        </Card>
      )}

      <Card title="Nightcore a video">
        <div style={muted}>
          Speeds up and pitches up a video's audio (the classic nightcore edit) and speeds up the video by the
          same amount to stay in sync — no other visual change. The output runs faster end-to-end, so it comes
          out shorter than the source.
        </div>
        <div style={muted}>
          Also boosts bass/treble and normalizes loudness, like real nightcore edits do — raising the pitch
          via the speed trick alone tends to sound thin without it.
        </div>

        <div style={row}>
          <button onClick={pickNcVideo}>Pick video file…</button>
          <span style={muted}>{ncVideoPath ? `Using: ${path_basename(ncVideoPath)}` : 'No video selected.'}</span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 320 }}>
          <span style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>Speed: {ncSpeed.toFixed(2)}x</span>
          <input
            type="range"
            min={1.05}
            max={1.5}
            step={0.05}
            value={ncSpeed}
            onChange={(e) => setNcSpeed(Number(e.target.value))}
          />
        </div>

        <label style={{ fontSize: 13 }}>
          <input type="checkbox" checked={ncReverb} onChange={(e) => setNcReverb(e.target.checked)} /> Add
          subtle reverb (dreamier/echoey style some nightcore edits use)
        </label>

        <div style={row}>
          <button onClick={runNightcoreVideo} disabled={ncRunning || !ncVideoPath}>
            {ncRunning ? 'Rendering…' : 'Nightcore'}
          </button>
        </div>
        <div style={muted}>{ncStatusText}</div>
      </Card>

      <div ref={ncResultRef} />
      {ncOutPath && (
        <Card title="Result">
          <div style={{ color: '#8f8' }}>✓ Done — nightcore video ready.</div>
          <div style={row}>
            <button onClick={saveNcVideo}>Save to output folder</button>
            <button onClick={downloadNcVideo}>Download</button>
          </div>
        </Card>
      )}
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ border: '1px solid #333', borderRadius: 6, padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
      {title && <div style={{ fontWeight: 600 }}>{title}</div>}
      {children}
    </div>
  )
}

function Radio({
  name,
  value,
  onChange,
  options
}: {
  name: string
  value: string
  onChange: (v: string) => void
  options: [string, string][]
}): React.JSX.Element {
  return (
    <div style={row}>
      {options.map(([v, label]) => (
        <label key={v} style={{ fontSize: 13 }}>
          <input type="radio" name={name} checked={value === v} onChange={() => onChange(v)} /> {label}
        </label>
      ))}
    </div>
  )
}

const row: React.CSSProperties = { display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }
const muted: React.CSSProperties = { fontSize: 12, color: 'var(--ev-c-text-2)' }
