'use strict'

/**
 * TeterAI CA — Electron main process
 *
 * Responsibilities:
 *  1. Spawn the FastAPI backend (uvicorn) as a child process
 *  2. Wait for the API to become ready, then open the BrowserWindow
 *  3. Handle app lifecycle (quit / crash recovery)
 *  4. Expose IPC handlers for native dialogs (folder picker)
 */

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const http = require('http')

const API_PORT = 8000
const API_URL = `http://127.0.0.1:${API_PORT}`
const MAX_STARTUP_WAIT_MS = 30000
const STARTUP_POLL_INTERVAL_MS = 500

let mainWindow = null
let apiProcess = null

// ---------------------------------------------------------------------------
// FastAPI backend
// ---------------------------------------------------------------------------

function getPythonExe() {
  if (app.isPackaged) {
    // Bundled Python interpreter (produced by PyInstaller)
    const ext = process.platform === 'win32' ? '.exe' : ''
    return path.join(process.resourcesPath, 'backend', 'teterai-backend' + ext)
  }
  // Development: use system python / uv
  return process.platform === 'win32' ? 'python' : 'python3'
}

function getBackendDir() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend')
  }
  // Three levels up from src/ui/desktop/ → repo root
  return path.resolve(__dirname, '..', '..', '..')
}

function spawnFastAPI() {
  const pythonExe = getPythonExe()
  const backendDir = getBackendDir()

  let args, cwd, env

  if (app.isPackaged) {
    // Packaged: run the PyInstaller bundle
    args = []
    cwd = backendDir
    env = { ...process.env, DESKTOP_MODE: 'true' }
  } else {
    // Development: uv run uvicorn
    args = [
      'run', 'uvicorn',
      'ui.api.server:app',
      '--host', '127.0.0.1',
      '--port', String(API_PORT),
      '--no-access-log',
    ]
    cwd = backendDir
    env = {
      ...process.env,
      DESKTOP_MODE: 'true',
      PYTHONPATH: path.join(backendDir, 'src'),
    }
  }

  console.log(`[main] Starting FastAPI: ${pythonExe} ${args.join(' ')}`)

  apiProcess = spawn(
    app.isPackaged ? pythonExe : 'uv',
    args,
    { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] }
  )

  apiProcess.stdout.on('data', d => console.log('[API]', d.toString().trimEnd()))
  apiProcess.stderr.on('data', d => console.error('[API]', d.toString().trimEnd()))

  apiProcess.on('exit', (code, signal) => {
    console.warn(`[main] FastAPI exited (code=${code}, signal=${signal})`)
    apiProcess = null
  })
}

// ---------------------------------------------------------------------------
// Wait for API to be ready
// ---------------------------------------------------------------------------

function waitForAPI(timeoutMs = MAX_STARTUP_WAIT_MS) {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    function check() {
      http.get(`${API_URL}/api/docs`, res => {
        if (res.statusCode < 500) {
          resolve()
        } else {
          retry()
        }
      }).on('error', retry)
    }
    function retry() {
      if (Date.now() - start > timeoutMs) {
        reject(new Error('FastAPI did not start in time'))
        return
      }
      setTimeout(check, STARTUP_POLL_INTERVAL_MS)
    }
    check()
  })
}

// ---------------------------------------------------------------------------
// BrowserWindow
// ---------------------------------------------------------------------------

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 600,
    title: 'TeterAI CA',
    backgroundColor: '#313131',
    show: false,  // revealed on 'ready-to-show' to avoid white flash
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  // Show branded splash immediately while FastAPI starts
  mainWindow.loadFile(path.join(__dirname, 'loading.html'))

  mainWindow.once('ready-to-show', () => mainWindow.show())

  // Open external links in the default browser, not in Electron
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(API_URL)) {
      shell.openExternal(url)
      return { action: 'deny' }
    }
    return { action: 'allow' }
  })

  mainWindow.on('closed', () => { mainWindow = null })
}

// ---------------------------------------------------------------------------
// IPC handlers
// ---------------------------------------------------------------------------

ipcMain.handle('select-folder', async () => {
  if (!mainWindow) return null
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select Folder',
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('get-app-version', () => app.getVersion())

ipcMain.handle('open-folder', async (_event, folderPath) => {
  if (!folderPath) return
  await shell.openPath(folderPath)
})

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  spawnFastAPI()

  // Show splash immediately — don't wait for the API
  createWindow()

  try {
    await waitForAPI()
    // Transition from splash to the app
    if (mainWindow) mainWindow.loadURL(API_URL)
  } catch (err) {
    console.error('[main] Failed to start backend:', err)
    dialog.showErrorBox(
      'TeterAI CA — Startup Error',
      `The backend server failed to start.\n\n${err.message}\n\nPlease reinstall the application.`
    )
    app.quit()
  }

  app.on('activate', () => {
    // macOS: re-create window when dock icon is clicked
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (apiProcess) {
    console.log('[main] Stopping FastAPI…')
    apiProcess.kill()
    apiProcess = null
  }
})

app.on('will-quit', () => {
  if (apiProcess) {
    apiProcess.kill()
    apiProcess = null
  }
})
