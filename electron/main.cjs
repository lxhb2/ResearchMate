const { app, BrowserWindow, ipcMain, dialog } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const fs = require('fs')
const http = require('http')
const { autoUpdater } = require('electron-updater')

const APP_PORT = Number(process.env.RESEARCHMATE_PORT || 18080)
let mainWindow = null
let backendProc = null
let quitting = false

function resolveBackendExe() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend', 'ResearchMate.exe')
  }
  return path.join(__dirname, '..', 'backend', 'packaging', 'windows_sqlite', 'dist', 'ResearchMate.exe')
}

function waitForServer(timeoutMs = 60000) {
  const url = `http://127.0.0.1:${APP_PORT}/`
  const startedAt = Date.now()
  return new Promise((resolve, reject) => {
    const poll = () => {
      const req = http.get(url, (res) => {
        res.resume()
        resolve(true)
      })
      req.on('error', () => {
        if (Date.now() - startedAt > timeoutMs) {
          reject(new Error('backend server did not start in time'))
          return
        }
        setTimeout(poll, 800)
      })
      req.setTimeout(1500, () => req.destroy())
    }
    poll()
  })
}

function startBackend() {
  if (process.env.RESEARCHMATE_DEV === '1') return
  const exe = resolveBackendExe()
  if (!fs.existsSync(exe)) {
    console.warn('[ResearchMate] backend exe not found, expecting external server:', exe)
    return
  }
  const dataDir = app.getPath('userData')
  fs.mkdirSync(dataDir, { recursive: true })
  fs.mkdirSync(path.join(dataDir, 'storage', 'pdfs'), { recursive: true })
  backendProc = spawn(exe, [], {
    cwd: dataDir,
    env: {
      ...process.env,
      PORT: String(APP_PORT),
      PDF_DIR: path.join(dataDir, 'storage', 'pdfs'),
      STORAGE_DIR: path.join(dataDir, 'storage'),
      DATABASE_URL: `sqlite:///${path.join(dataDir, 'researchmate.db').replace(/\\/g, '/')}`,
    },
    windowsHide: true,
  })
  backendProc.stdout?.on('data', (d) => console.log('[backend]', String(d).trim()))
  backendProc.stderr?.on('data', (d) => console.error('[backend]', String(d).trim()))
  backendProc.on('exit', (code) => {
    if (!quitting && mainWindow) {
      mainWindow.webContents.send('backend:exited', code)
    }
  })
}

function stopBackend() {
  quitting = true
  if (backendProc && !backendProc.killed) {
    try {
      backendProc.kill()
    } catch {
      // ignore
    }
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 720,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#f4f6fb',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  mainWindow.once('ready-to-show', () => mainWindow.show())
  mainWindow.loadURL(`http://127.0.0.1:${APP_PORT}/`)
  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function registerIpc() {
  ipcMain.handle('app:version', () => app.getVersion())

  ipcMain.handle('update:check', async () => {
    try {
      const result = await autoUpdater.checkForUpdates()
      return {
        ok: true,
        current: app.getVersion(),
        available: result?.updateInfo?.version || null,
        releaseName: result?.updateInfo?.releaseName || null,
        releaseDate: result?.updateInfo?.releaseDate || null,
      }
    } catch (err) {
      return { ok: false, error: String(err?.message || err) }
    }
  })

  ipcMain.handle('update:download', async () => {
    try {
      await autoUpdater.downloadUpdate()
      return { ok: true }
    } catch (err) {
      return { ok: false, error: String(err?.message || err) }
    }
  })

  ipcMain.handle('update:install', async () => {
    setImmediate(() => autoUpdater.quitAndInstall())
    return { ok: true }
  })
}

app.whenReady().then(async () => {
  registerIpc()
  startBackend()
  try {
    await waitForServer()
  } catch (err) {
    console.error('[ResearchMate] backend startup failed:', err)
    dialog.showErrorBox('ResearchMate 启动失败', String(err?.message || err))
    app.quit()
    return
  }
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  stopBackend()
  app.quit()
})

app.on('before-quit', () => stopBackend())
