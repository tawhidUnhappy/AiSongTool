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
//  - macOS: no equivalent prebuilt LGPL static build exists upstream that
//    could be license-verified here (third-party static-build sites
//    typically bundle GPL-licensed x264/x265) — instead this compiles a
//    minimal ffmpeg from its own official source tarball directly on the
//    macOS runner with `--disable-gpl --disable-nonfree`, so the license is
//    verifiably LGPL by construction rather than trusted from a download.
//    Slower (~10-15min) than just downloading a prebuilt binary, but it's a
//    one-time cost per release build.
import { createWriteStream, mkdirSync, chmodSync, rmSync, existsSync, copyFileSync } from 'fs'
import path from 'path'
import os from 'os'
import { fileURLToPath } from 'url'
import { pipeline } from 'stream/promises'
import { execFileSync } from 'child_process'

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
  // mac: handled separately by buildMacFromSource() below, not a prebuilt
  // download — see header comment.
}

const FFMPEG_SOURCE_VERSION = '7.1.1'

async function buildMacFromSource() {
  mkdirSync(OUT_DIR, { recursive: true })
  const buildDir = path.join(OUT_DIR, '_build')
  mkdirSync(buildDir, { recursive: true })

  console.log('Installing build dependencies via Homebrew (nasm, pkg-config, lame, opus, libvpx)...')
  execFileSync('brew', ['install', 'nasm', 'pkg-config', 'lame', 'opus', 'libvpx'], { stdio: 'inherit' })

  // Homebrew installs to /opt/homebrew (Apple Silicon) or /usr/local
  // (Intel) — neither is on the default compiler/pkg-config search path,
  // which is why `./configure` couldn't find libmp3lame even though brew
  // install succeeded. `brew --prefix` resolves to whichever applies here.
  const brewPrefix = execFileSync('brew', ['--prefix']).toString().trim()

  const tarPath = path.join(buildDir, 'ffmpeg.tar.xz')
  const srcUrl = `https://ffmpeg.org/releases/ffmpeg-${FFMPEG_SOURCE_VERSION}.tar.xz`
  console.log(`Downloading ffmpeg ${FFMPEG_SOURCE_VERSION} source from ${srcUrl} ...`)
  const resp = await fetch(srcUrl)
  if (!resp.ok) throw new Error(`Download failed: ${resp.status}`)
  await pipeline(resp.body, createWriteStream(tarPath))

  console.log('Extracting source...')
  execFileSync('tar', ['-xJf', tarPath, '-C', buildDir])
  const srcDir = path.join(buildDir, `ffmpeg-${FFMPEG_SOURCE_VERSION}`)

  console.log('Configuring (LGPL-only: --disable-gpl --disable-nonfree)...')
  execFileSync(
    './configure',
    [
      '--disable-gpl',
      '--disable-nonfree',
      '--enable-version3',
      '--disable-debug',
      '--disable-doc',
      '--disable-ffplay',
      '--enable-videotoolbox',
      '--enable-audiotoolbox',
      '--enable-libmp3lame',
      '--enable-libopus',
      '--enable-libvpx',
      '--enable-zlib',
      `--extra-cflags=-I${brewPrefix}/include`,
      `--extra-ldflags=-L${brewPrefix}/lib`,
      `--pkg-config-flags=--define-prefix`
    ],
    {
      cwd: srcDir,
      stdio: 'inherit',
      env: { ...process.env, PKG_CONFIG_PATH: `${brewPrefix}/lib/pkgconfig` }
    }
  )

  console.log('Building (make)...')
  execFileSync('make', [`-j${os.cpus().length}`], {
    cwd: srcDir,
    stdio: 'inherit',
    env: { ...process.env, PKG_CONFIG_PATH: `${brewPrefix}/lib/pkgconfig` }
  })

  for (const binName of ['ffmpeg', 'ffprobe']) {
    copyFileSync(path.join(srcDir, binName), path.join(OUT_DIR, binName))
    chmodSync(path.join(OUT_DIR, binName), 0o755)
  }
  rmSync(buildDir, { recursive: true, force: true })
  console.log(`ffmpeg/ffprobe built (LGPL-only) and ready in ${OUT_DIR}`)
}

async function main() {
  const target = process.argv[2] ?? { win32: 'win', linux: 'linux', darwin: 'mac' }[process.platform]
  if (target === 'mac') {
    await buildMacFromSource()
    return
  }
  const source = SOURCES[target]
  if (!source) {
    console.error(`No ffmpeg source configured for '${target}'. Known: ${Object.keys(SOURCES).join(', ')}, mac`)
    process.exit(1)
  }

  mkdirSync(OUT_DIR, { recursive: true })
  const archivePath = path.join(OUT_DIR, `_download.${source.archive === 'zip' ? 'zip' : 'tar.xz'}`)

  console.log(`Downloading ${source.url} ...`)
  const resp = await fetch(source.url)
  if (!resp.ok) throw new Error(`Download failed: ${resp.status}`)
  await pipeline(resp.body, createWriteStream(archivePath))

  console.log('Extracting...')
  if (source.archive === 'zip') {
    execFileSync('unzip', ['-o', archivePath, '-d', path.join(OUT_DIR, '_extract')])
  } else {
    mkdirSync(path.join(OUT_DIR, '_extract'), { recursive: true })
    execFileSync('tar', ['-xJf', archivePath, '-C', path.join(OUT_DIR, '_extract')])
  }

  // BtbN's archives nest a single top-level `ffmpeg-*-lgpl/bin/` directory —
  // find and copy just the two binaries we need, flat into OUT_DIR. No
  // `glob` dependency needed for a one-level-deep search like this.
  const { readdirSync, statSync } = await import('fs')
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
