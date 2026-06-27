import { app, shell, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'
import { mkdirSync } from 'fs'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
import { registerIpcHandlers } from './ipc-handlers'
import { terminateAllJobs } from './jobs'
import { dataDir } from './paths'

function createWindow(): void {
  // Create the browser window.
  const mainWindow = new BrowserWindow({
    width: 1320,
    height: 880,
    show: false,
    autoHideMenuBar: true,
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  // HMR for renderer base on electron-vite cli.
  // Load the remote URL for development or the local html file for production.
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.whenReady().then(() => {
  // Set app user model id for windows
  electronApp.setAppUserModelId('com.aisongtool.app')

  // The one writable data root (see paths.ts's dataDir()) — every isolated
  // env, job, output, cache, and setting this app ever writes lives under
  // it. Create it up front so a fresh packaged install's very first run
  // (before Setup has provisioned anything) doesn't hit ENOENT writing
  // settings/jobs into a directory that doesn't exist yet.
  mkdirSync(dataDir(), { recursive: true })

  // Default open or close DevTools by F12 in development
  // and ignore CommandOrControl + R in production.
  // see https://github.com/alex8088/electron-toolkit/tree/master/packages/utils
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // IPC test
  ipcMain.on('ping', () => console.log('pong'))

  registerIpcHandlers()

  createWindow()

  app.on('activate', function () {
    // On macOS it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// Graceful-quit cleanup (v1) — kills whatever job is still running so it
// doesn't keep holding the GPU after the window closes. Does NOT cover a
// force-kill of the Electron process itself (Task Manager "End Task"); that
// guarantee needs a native Job Object addon (see the plan's Phase 5), same
// as win_job.py provides on the Python/Flet side today.
app.on('before-quit', () => {
  terminateAllJobs()
})

// In this file you can include the rest of your app's specific main process
// code. You can also put them in separate files and require them here.
