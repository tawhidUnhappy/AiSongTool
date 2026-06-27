import { useEffect, useRef, useState } from 'react'
import type { CreateFlow, LibrarySong } from '../../../shared/types'
import { STAGE_TEXT } from '../../../shared/types'
import templateSkyPreview from '../assets/template_sky.jpg'
import templateSyrexPreview from '../assets/template_syrex.jpg'

// Mirrors the language codes ACE-Step's own server recognizes (see its
// `acestep/api/server_utils.py`'s `language_mapping`) — '' lets its LM
// detect the language from the description itself (use_cot_language).
const VOCAL_LANGUAGES: [string, string][] = [
  ['', 'Auto-detect'],
  ['en', 'English'],
  ['zh', 'Chinese'],
  ['ja', 'Japanese'],
  ['ko', 'Korean'],
  ['es', 'Spanish'],
  ['fr', 'French'],
  ['de', 'German'],
  ['it', 'Italian'],
  ['pt', 'Portuguese'],
  ['ru', 'Russian'],
  ['bn', 'Bengali'],
  ['hi', 'Hindi'],
  ['ar', 'Arabic'],
  ['th', 'Thai'],
  ['vi', 'Vietnamese'],
  ['id', 'Indonesian'],
  ['tr', 'Turkish'],
  ['nl', 'Dutch'],
  ['pl', 'Polish']
]

function fmtDuration(totalSeconds: number): string {
  const s = Math.floor(totalSeconds)
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

function fmtElapsed(startedAt: number | null): string {
  if (startedAt === null) return ''
  const elapsed = Math.floor((Date.now() - startedAt) / 1000)
  return ` (${fmtDuration(elapsed)} elapsed)`
}

export function Create(): React.JSX.Element {
  const [outputDir, setOutputDir] = useState<string | null>(null)

  useEffect(() => {
    window.api.getOutputDir().then(setOutputDir)
  }, [])

  const [mode, setMode] = useState<'generate' | 'existing'>('generate')
  const [songName, setSongName] = useState('')

  const [existingSongPath, setExistingSongPath] = useState<string | null>(null)
  const [existingLyrics, setExistingLyrics] = useState('')
  const [captionSource, setCaptionSource] = useState<'auto' | 'transcript' | 'lyrics'>('transcript')
  const [librarySongs, setLibrarySongs] = useState<LibrarySong[]>([])

  // Auto-detects new songs from this page's own generations while the card
  // picker below is actually visible; no point polling a directory listing
  // nobody's looking at.
  useEffect(() => {
    if (mode !== 'existing') return
    const poll = (): void => {
      window.api.listAudioLibrary().then(setLibrarySongs)
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [mode])

  const [template, setTemplate] = useState<'sky' | 'syrex'>('sky')
  const [nightcore, setNightcore] = useState(true)

  const [imageSource, setImageSource] = useState<'auto' | 'pick'>('auto')
  const [imagePath, setImagePath] = useState<string | null>(null)
  const [imagePromptText, setImagePromptText] = useState('')

  // 'generate' mode's only input — ACE-Step's own sample mode auto-generates
  // the caption/lyrics/bpm/key/everything else from this one description via
  // its 5Hz LM (see create-pipeline.ts's generateSong()). Doubles as the
  // background-image prompt's fallback below.
  const [songDescription, setSongDescription] = useState('')
  // '' = let ACE-Step's own LM detect the language from the description.
  const [vocalLanguage, setVocalLanguage] = useState('')

  const [promptHistoryEnabled, setPromptHistoryEnabled] = useState(true)
  const [imagePromptHistory, setImagePromptHistory] = useState<string[]>([])

  // Remembers every dropdown/checkbox choice below across restarts (not
  // free-text fields like prompt/lyrics/seed — see settings.ts). Loaded once
  // on mount; a `loadedSettings` gate stops the persist-effects further down
  // from immediately re-writing defaults over what was just loaded.
  const [loadedSettings, setLoadedSettings] = useState(false)

  useEffect(() => {
    window.api.getSettings().then((s) => {
      setPromptHistoryEnabled(s.promptHistoryEnabled)
      setImagePromptHistory(s.imagePromptHistory)
      setMode(s.createMode)
      setVocalLanguage(s.createVocalLanguage)
      setCaptionSource(s.createCaptionSource)
      setTemplate(s.createTemplate)
      setNightcore(s.createNightcore)
      setImageSource(s.createImageSource)
      setLoadedSettings(true)
    })
  }, [])

  useEffect(() => {
    if (loadedSettings) window.api.setSetting('createMode', mode)
  }, [loadedSettings, mode])
  useEffect(() => {
    if (loadedSettings) window.api.setSetting('createVocalLanguage', vocalLanguage)
  }, [loadedSettings, vocalLanguage])
  useEffect(() => {
    if (loadedSettings) window.api.setSetting('createCaptionSource', captionSource)
  }, [loadedSettings, captionSource])
  useEffect(() => {
    if (loadedSettings) window.api.setSetting('createTemplate', template)
  }, [loadedSettings, template])
  useEffect(() => {
    if (loadedSettings) window.api.setSetting('createNightcore', nightcore)
  }, [loadedSettings, nightcore])
  useEffect(() => {
    if (loadedSettings) window.api.setSetting('createImageSource', imageSource)
  }, [loadedSettings, imageSource])

  const toggleHistoryEnabled = async (enabled: boolean): Promise<void> => {
    setPromptHistoryEnabled(enabled)
    await window.api.setPromptHistoryEnabled(enabled)
  }

  const removeImagePromptHistoryEntry = async (entry: string): Promise<void> => {
    setImagePromptHistory((prev) => prev.filter((p) => p !== entry))
    await window.api.removeImagePromptHistory(entry)
  }

  const clearImagePromptHistory = async (): Promise<void> => {
    setImagePromptHistory([])
    await window.api.clearImagePromptHistory()
  }

  const [running, setRunning] = useState(false)
  const [statusText, setStatusText] = useState('Set everything up, then click Run.')
  const [flow, setFlow] = useState<CreateFlow | null>(null)
  const [subtitleOutputs, setSubtitleOutputs] = useState<{ ext: string; label: string }[]>([])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    window.api.getDefaultBackground().then(setImagePath)
  }, [])


  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const poll = async (): Promise<void> => {
    const f = await window.api.getCreateStatus()
    setFlow(f)
    if (f.stage && f.stage in STAGE_TEXT) {
      let text = STAGE_TEXT[f.stage]
      if (f.stage === 'gen_generating' && f.genProgressText) {
        text = `${text} — ${f.genProgressText}`
      }
      setStatusText(text + fmtElapsed(f.stageStartedAt))
    } else if (f.stage === 'done') {
      setStatusText(`Done.${f.elapsedSeconds !== null ? ` (took ${fmtDuration(f.elapsedSeconds)})` : ''}`)
      if (f.jobDir) {
        window.api.listSubtitleOutputs(f.jobDir).then(setSubtitleOutputs)
      }
    } else if (f.stage === 'error') {
      const failed = f.errorMessage ?? 'Failed.'
      setStatusText(f.elapsedSeconds !== null ? `${failed} (after ${fmtDuration(f.elapsedSeconds)})` : failed)
    }
    if (!f.busy && pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
      setRunning(false)
      // The result card renders below the Run button, which can be
      // scrolled out of view in a long-running session (lots of song/lyrics
      // text above it) — jump to it instead of leaving "Done." sitting
      // there with no visible sign anything was produced.
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
    }
  }

  const pickOutputDir = async (): Promise<void> => {
    const dir = await window.api.pickOutputDir()
    if (dir) setOutputDir(dir)
  }

  const pickSong = async (): Promise<void> => {
    const p = await window.api.pickSongFile()
    if (p) setExistingSongPath(p)
  }

  const useLibrarySong = (song: LibrarySong): void => {
    setExistingSongPath(song.path)
    if (song.lyrics && !existingLyrics.trim()) setExistingLyrics(song.lyrics)
  }

  const pickImage = async (): Promise<void> => {
    const p = await window.api.pickImageFile()
    if (p) setImagePath(p)
  }

  const run = async (): Promise<void> => {
    if (running) return
    if (mode === 'generate' && !songDescription.trim()) {
      setStatusText('Describe the song you want first.')
      return
    }
    if (mode === 'existing' && !existingSongPath) {
      setStatusText('Pick a song first.')
      return
    }
    if (imagePath === null) return

    if (promptHistoryEnabled) {
      const trimmed = imagePromptText.trim()
      if (trimmed) {
        setImagePromptHistory((prev) => [trimmed, ...prev.filter((p) => p !== trimmed)].slice(0, 20))
        await window.api.addImagePromptHistory(trimmed)
      }
    }
    setRunning(true)
    setFlow(null)
    setSubtitleOutputs([])
    setStatusText('Starting...')

    await window.api.startCreateRun({
      mode,
      prompt: mode === 'generate' ? songDescription.trim() : '',
      vocalLanguage: mode === 'generate' ? vocalLanguage : '',
      songName: songName.trim(),
      existingSong: existingSongPath,
      existingLyrics: existingLyrics.trim(),
      captionSource,
      template,
      nightcore,
      imageSource,
      imagePath,
      imagePromptText: imagePromptText.trim()
    })

    pollRef.current = setInterval(poll, 1000)
    poll()
  }

  const saveVideo = async (): Promise<void> => {
    if (flow?.videoOut) await window.api.saveArtifact(flow.videoOut, path_basename(flow.videoOut))
  }
  const saveAudio = async (): Promise<void> => {
    if (flow?.audioOut) await window.api.saveArtifact(flow.audioOut, path_basename(flow.audioOut))
  }
  const saveSubtitle = async (ext: string): Promise<void> => {
    if (!flow?.jobDir || !flow?.songPath) return
    const stem = path_basename(flow.songPath).replace(/\.[^.]+$/, '')
    const src = `${flow.jobDir}\\out\\final.${ext}`
    await window.api.saveArtifact(src, `${stem}.${ext}`)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto', height: '100%' }}>
      <Card title="Output folder">
        <button onClick={pickOutputDir}>Choose folder</button>
        <div style={muted}>
          {outputDir
            ? `Saving to: ${outputDir} (audio/, images/, and videos/ subfolders)`
            : 'Loading…'}
        </div>
      </Card>

      <Card title="1. Song">
        <Radio
          name="mode"
          value={mode}
          onChange={(v) => setMode(v as typeof mode)}
          options={[
            ['generate', 'Generate a new song'],
            ['existing', 'Use an existing song']
          ]}
        />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>Lyrics for subtitles/video</span>
          <Radio
            name="captionSource"
            value={captionSource}
            onChange={(v) => setCaptionSource(v as typeof captionSource)}
            options={[
              ['auto', 'Auto (lyrics if given, else transcript)'],
              ['transcript', 'Whisper transcript only'],
              ['lyrics', 'My lyrics + transcript']
            ]}
          />
          <span style={muted}>
            A song can skip or repeat lines vs the literal lyrics — "Whisper transcript only" shows exactly
            what's actually sung instead of forcing mismatched lyrics onto the wrong timing.
          </span>
        </div>

        <hr style={hr} />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 13 }}>
            <strong>Song name</strong>
            <span style={muted}> — just for this app's own filenames/library</span>
          </span>
          <input
            placeholder="e.g. Neon Heartbreak"
            value={songName}
            onChange={(e) => setSongName(e.target.value)}
            style={{ width: '100%', boxSizing: 'border-box' }}
          />
        </div>

        <hr style={hr} />

        {mode === 'generate' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Song description</span>
            <textarea
              placeholder="e.g. an upbeat synth-pop love song with a driving beat and dreamy female vocals"
              value={songDescription}
              onChange={(e) => setSongDescription(e.target.value)}
              rows={3}
              style={textareaStyle}
            />
            <span style={muted}>
              ACE-Step's sample mode generates the caption, lyrics, and everything else from this description on
              its own — no other input needed.
            </span>
            <div style={{ ...row, marginTop: 4 }}>
              <label style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
                Lyrics language
                <select value={vocalLanguage} onChange={(e) => setVocalLanguage(e.target.value)}>
                  {VOCAL_LANGUAGES.map(([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        ) : (
          <>
            {librarySongs.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>
                  Previously generated songs — pick one to use as this run's input
                </span>
                <SongLibraryGrid songs={librarySongs} selected={existingSongPath} onPick={useLibrarySong} />
              </div>
            )}
            <div style={row}>
              <button onClick={pickSong}>Pick song file from disk…</button>
              <span style={muted}>{existingSongPath ? `Using: ${path_basename(existingSongPath)}` : 'No song selected.'}</span>
            </div>
            <textarea
              placeholder="Lyrics for this song (optional, improves alignment)"
              value={existingLyrics}
              onChange={(e) => setExistingLyrics(e.target.value)}
              rows={3}
              style={textareaStyle}
            />
          </>
        )}
      </Card>

      <Card title="2. Template">
        <TemplateCards
          value={template}
          onChange={(v) => setTemplate(v as typeof template)}
          options={[
            {
              value: 'sky',
              title: 'Minimalistic Sky',
              description: "Centered Edo-font lyrics over a generated sky background ('Minimalistic red sky').",
              preview: templateSkyPreview
            },
            {
              value: 'syrex',
              title: 'Syrex Visualizer',
              description:
                'Audio-reactive: curved spectrum spikes, panning background, bass-driven chromatic aberration.',
              preview: templateSyrexPreview
            }
          ]}
        />
        {template === 'syrex' && (
          <div style={muted}>
            Renders with the isolated Syrex visualizer env — install it from the Setup view first if you
            haven&apos;t already.
          </div>
        )}
      </Card>

      <Card title="3. Background image">
        <Radio
          name="imageSource"
          value={imageSource}
          onChange={(v) => setImageSource(v as typeof imageSource)}
          options={[
            ['auto', 'Generate from a description (Z-Image-Turbo)'],
            ['pick', 'Pick an image']
          ]}
        />
        {imageSource === 'pick' && (
          <div style={row}>
            <button onClick={pickImage}>Pick image…</button>
            <span style={muted}>{imagePath ? path_basename(imagePath) : 'Using default background.'}</span>
          </div>
        )}
        {imageSource === 'auto' && template === 'sky' && (
          <div style={muted}>
            The Minimalistic Sky template always generates from a fixed prompt ("Minimalistic red sky") —
            no need to write one.
          </div>
        )}
        {imageSource === 'auto' && template === 'syrex' && (
          <>
            <hr style={hr} />
            <textarea
              placeholder="e.g. a neon-lit city skyline at night, cinematic, rain-soaked streets"
              value={imagePromptText}
              onChange={(e) => setImagePromptText(e.target.value)}
              rows={2}
              style={textareaStyle}
            />
            <PromptHistory
              entries={imagePromptHistory}
              enabled={promptHistoryEnabled}
              onPick={setImagePromptText}
              onRemove={removeImagePromptHistoryEntry}
              onClear={clearImagePromptHistory}
              onToggleEnabled={toggleHistoryEnabled}
            />
          </>
        )}
      </Card>

      <Card title="4. Output">
        <label style={row}>
          <input type="checkbox" checked={nightcore} onChange={(e) => setNightcore(e.target.checked)} />
          Speed up + pitch up the final video/audio (nightcore)
        </label>
        {!nightcore && (
          <div style={muted}>Off: the video/audio are saved at the song&apos;s normal speed and pitch.</div>
        )}
      </Card>

      <Card title="">
        <div style={row}>
          <button onClick={run} disabled={running}>
            {running ? 'Running…' : 'Run'}
          </button>
        </div>
        <div style={muted}>{statusText}</div>
        {flow?.runStartedAt != null && (
          <div style={muted}>
            Total time: {fmtDuration(flow.elapsedSeconds ?? (Date.now() - flow.runStartedAt) / 1000)}
          </div>
        )}
      </Card>

      <div ref={resultRef} />
      {flow?.stage === 'done' && (
        <Card title="Generated">
          <div style={muted}>Vocals separated (Demucs) + transcribed/aligned (WhisperX).</div>
          <div style={row}>
            {subtitleOutputs.map(({ ext, label }) => (
              <button key={ext} onClick={() => saveSubtitle(ext)}>
                {label}
              </button>
            ))}
          </div>
        </Card>
      )}

      {flow?.stage === 'done' && flow.videoOut && (
        <Card title="Result">
          <div style={{ color: '#8f8' }}>✓ Done — video and audio saved to the output folder.</div>
          <div style={row}>
            <button onClick={saveVideo}>Save video</button>
            <button onClick={saveAudio}>Save audio only</button>
          </div>
        </Card>
      )}

      {flow?.stage === 'error' && (
        <Card title="Failed">
          <div style={{ color: '#e88' }}>{flow.errorMessage ?? 'Failed.'}</div>
        </Card>
      )}
    </div>
  )
}

function path_basename(p: string): string {
  return p.replace(/\\/g, '/').split('/').pop() ?? p
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

function fmtLibraryDate(mtimeMs: number): string {
  return new Date(mtimeMs).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  })
}

/** Card grid for picking a previously-generated song (library.ts's
 * `output/audio/`) as this run's input, instead of only a raw file-picker
 * dialog — each card shows whatever the song's own caption/lyrics metadata
 * has (from either a past sample-mode generation or an existing-song pick)
 * so songs are recognizable without having to remember filenames. */
function SongLibraryGrid({
  songs,
  selected,
  onPick
}: {
  songs: LibrarySong[]
  selected: string | null
  onPick: (song: LibrarySong) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', maxHeight: 280, overflowY: 'auto' }}>
      {songs.map((song) => {
        const isSelected = song.path === selected
        return (
          <div
            key={song.path}
            onClick={() => onPick(song)}
            style={{
              flex: '1 1 220px',
              minWidth: 200,
              maxWidth: 260,
              cursor: 'pointer',
              border: isSelected ? '2px solid #6ab0ff' : '1px solid #333',
              borderRadius: 6,
              padding: 10,
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              background: isSelected ? 'rgba(106, 176, 255, 0.08)' : 'transparent'
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
              <span style={{ fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {song.name.replace(/\.[^.]+$/, '')}
              </span>
              {isSelected && <span style={{ fontSize: 11, color: '#6ab0ff', flexShrink: 0 }}>✓ selected</span>}
            </div>
            <span style={muted}>
              {fmtLibraryDate(song.mtimeMs)} — {song.sizeMb.toFixed(1)}MB
            </span>
            {song.caption && (
              <span style={{ ...muted, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                {song.caption}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Video template picker — rendered as a row of selectable cards rather
 * than a dropdown/radio, since each option has a name + description worth
 * showing side by side instead of squeezed into one line. */
function TemplateCards({
  value,
  onChange,
  options
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; title: string; description: string; preview: string }[]
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      {options.map((o) => {
        const selected = o.value === value
        return (
          <div
            key={o.value}
            onClick={() => onChange(o.value)}
            style={{
              flex: '1 1 220px',
              minWidth: 200,
              cursor: 'pointer',
              border: selected ? '2px solid #6ab0ff' : '1px solid #333',
              borderRadius: 6,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              background: selected ? 'rgba(106, 176, 255, 0.08)' : 'transparent'
            }}
          >
            <img
              src={o.preview}
              alt={`${o.title} example`}
              style={{ width: '100%', aspectRatio: '16 / 9', objectFit: 'cover', display: 'block' }}
            />
            <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>{o.title}</span>
                {selected && <span style={{ fontSize: 12, color: '#6ab0ff' }}>✓ selected</span>}
              </div>
              <span style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>{o.description}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Recently-used "describe the song" prompts — recorded each time a Create
 * run actually starts, not on every keystroke. Each entry can be removed
 * individually, and history can be cleared or turned off entirely. */
function PromptHistory({
  entries,
  enabled,
  onPick,
  onRemove,
  onClear,
  onToggleEnabled
}: {
  entries: string[]
  enabled: boolean
  onPick: (prompt: string) => void
  onRemove: (prompt: string) => void
  onClear: () => void
  onToggleEnabled: (enabled: boolean) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <label style={{ fontSize: 12, color: 'var(--ev-c-text-2)' }}>
          <input type="checkbox" checked={enabled} onChange={(e) => onToggleEnabled(e.target.checked)} /> Remember
          prompts I use
        </label>
        {entries.length > 0 && (
          <button onClick={onClear} style={{ fontSize: 12 }}>
            Clear history
          </button>
        )}
      </div>
      {entries.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 140, overflowY: 'auto' }}>
          {entries.map((entry) => (
            <div
              key={entry}
              style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '2px 0' }}
            >
              <button
                onClick={() => onPick(entry)}
                title="Use this prompt"
                style={{ flex: 1, textAlign: 'left', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                {entry}
              </button>
              <button onClick={() => onRemove(entry)} title="Remove from history" style={{ fontSize: 12 }}>
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const row: React.CSSProperties = { display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }
const muted: React.CSSProperties = { fontSize: 12, color: 'var(--ev-c-text-2)' }
const hr: React.CSSProperties = { border: 'none', borderTop: '1px solid #333', width: '100%' }
const textareaStyle: React.CSSProperties = { width: '100%', resize: 'vertical', fontFamily: 'inherit', boxSizing: 'border-box' }
