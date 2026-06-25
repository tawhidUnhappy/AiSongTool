#!/usr/bin/env node
// Downloads a static, LGPL-licensed ffmpeg+ffprobe build for the current (or
// given) platform into desktop/resources/ffmpeg/ — picked up automatically
// by electron-builder's `resources/**` asarUnpack rule, and by
// paths.ts's findFfmpeg()/findFfprobe() (checked before falling back to a
// system PATH install). Run before `electron-builder` in CI (see
// .github/workflows/release.yml) — not committed to git; these binaries are
// ~80-150MB each and change independently of app source.
//
// LGPL (not GPL) builds specifically, so bundling/redistributing them
// carries no extra obligations beyond LGPL's own (dynamic linking + offering
// source on request, both satisfied by linking to the build's own published
// source/binaries).
//
// Sources:
//  - Windows/Linux: BtbN's `ffmpeg-master-latest-{win64,linux64}-lgpl` GitHub
//    Actions release builds (https://github.com/BtbN/FFmpeg-Builds).
//  - macOS: BtbN doesn't publish macOS builds; evermeet.cx's static builds
//    are the commonly-used alternative — verify license terms/build flags
//    there before shipping a real release (not independently confirmed
//    here).
import { createWriteStream, mkdirSync, chmodSync, rmSync, existsSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { pipeline } from 'stream/promises'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT_DIR = path.join(__dirname, '..', 'resources', 'ffmpeg')

const SOURCES = {
  win: {
    url: 'https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-lgpl.zip',
    archive: 'zip',
    binNames: ['ffmpeg.exe', 'ffprobe.exe']
  },
  linux: {
    url: 'https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-lgpl.tar.xz',
    archive: 'tar',
    binNames: ['ffmpeg', 'ffprobe']
  }
  // mac: intentionally omitted — see header comment. Add once a specific
  // verified LGPL build URL is picked.
}

async function main() {
  const target = process.argv[2] ?? { win32: 'win', linux: 'linux', darwin: 'mac' }[process.platform]
  const source = SOURCES[target]
  if (!source) {
    console.error(`No ffmpeg source configured for '${target}'. Known: ${Object.keys(SOURCES).join(', ')}`)
    process.exit(1)
  }

  mkdirSync(OUT_DIR, { recursive: true })
  const archivePath = path.join(OUT_DIR, `_download.${source.archive === 'zip' ? 'zip' : 'tar.xz'}`)

  console.log(`Downloading ${source.url} ...`)
  const resp = await fetch(source.url)
  if (!resp.ok) throw new Error(`Download failed: ${resp.status}`)
  await pipeline(resp.body, createWriteStream(archivePath))

  console.log('Extracting...')
  const { execFileSync } = await import('child_process')
  if (source.archive === 'zip') {
    execFileSync('unzip', ['-o', archivePath, '-d', path.join(OUT_DIR, '_extract')])
  } else {
    mkdirSync(path.join(OUT_DIR, '_extract'), { recursive: true })
    execFileSync('tar', ['-xJf', archivePath, '-C', path.join(OUT_DIR, '_extract')])
  }

  // BtbN's archives nest a single top-level `ffmpeg-*-lgpl/bin/` directory —
  // find and copy just the two binaries we need, flat into OUT_DIR. No
  // `glob` dependency needed for a one-level-deep search like this.
  const { copyFileSync, readdirSync, statSync } = await import('fs')
  function findFile(dir, name) {
    for (const entry of readdirSync(dir)) {
      const full = path.join(dir, entry)
      if (statSync(full).isDirectory()) {
        const found = findFile(full, name)
        if (found) return found
      } else if (entry === name) {
        return full
      }
    }
    return null
  }
  for (const binName of source.binNames) {
    const found = findFile(path.join(OUT_DIR, '_extract'), binName)
    if (!found) throw new Error(`Couldn't find ${binName} in the extracted archive.`)
    copyFileSync(found, path.join(OUT_DIR, binName))
    if (target !== 'win') chmodSync(path.join(OUT_DIR, binName), 0o755)
  }

  rmSync(archivePath, { force: true })
  rmSync(path.join(OUT_DIR, '_extract'), { recursive: true, force: true })
  console.log(`ffmpeg/ffprobe ready in ${OUT_DIR}`)
}

if (!existsSync(OUT_DIR) || process.argv.includes('--force')) {
  main().catch((err) => {
    console.error(err)
    process.exit(1)
  })
} else {
  console.log(`${OUT_DIR} already exists — pass --force to re-download.`)
}
