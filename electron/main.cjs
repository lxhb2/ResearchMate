const { app, BrowserWindow, ipcMain, dialog, Notification, Tray, Menu, nativeImage, session, shell } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const fs = require('fs')
const http = require('http')
const { autoUpdater } = require('electron-updater')

autoUpdater.autoDownload = false
autoUpdater.autoInstallOnAppQuit = true

const APP_PORT = Number(process.env.RESEARCHMATE_PORT || 18080)
let mainWindow = null
let backendProc = null
let quitting = false
let tray = null
let updateChecked = false
let updateInfo = null
let downloadStarted = false

async function ensureChecked(force = false) {
  if (updateChecked && !force) return
  const result = await autoUpdater.checkForUpdates()
  updateInfo = result?.updateInfo || null
  updateChecked = true
  return result
}

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
      PDF2ZH_BRIDGE: path.join(process.resourcesPath, 'backend', 'scripts', 'pdf2zh_bridge.py'),
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
  mainWindow.loadURL(`http://127.0.0.1:${APP_PORT}/`).then(() => {
    // ResearchMate 是单页应用；外部页面必须交给系统浏览器，避免替换整个客户端。
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
      if (/^https?:\/\//i.test(url)) {
        shell.openExternal(url).catch(() => {})
      }
      return { action: 'deny' }
    })
    mainWindow.webContents.on('will-navigate', (event, url) => {
      try {
        const next = new URL(url)
        const origin = `http://127.0.0.1:${APP_PORT}`
        if (next.origin !== origin) {
          event.preventDefault()
          if (/^https?:$/i.test(next.protocol)) {
            shell.openExternal(url).catch(() => {})
          }
        }
      } catch {
        event.preventDefault()
      }
    })
  })
  // 关闭窗口时隐藏到托盘，而不是退出（托盘菜单可真正退出）
  mainWindow.on('close', (e) => {
    if (!quitting) {
      e.preventDefault()
      mainWindow.hide()
    }
  })
  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow()
    return
  }
  mainWindow.show()
  mainWindow.focus()
}

function createTray() {
  const icon = nativeImage.createFromDataURL(
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAIklEQVR4nGP48u33f0owA9UMSE77SBIeNWDUgOFqwIDlRgAyBzv+OHOwZAAAAABJRU5ErkJggg=='
  )
  tray = new Tray(icon)
  tray.setToolTip('ResearchMate')
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '打开 ResearchMate', click: showMainWindow },
      { type: 'separator' },
      {
        label: '退出',
        click: () => {
          quitting = true
          app.quit()
        },
      },
    ])
  )
  tray.on('click', showMainWindow)
}

function registerIpc() {
  ipcMain.handle('app:version', () => app.getVersion())

  ipcMain.handle('app:notify', (_event, payload) => {
    if (Notification.isSupported()) {
      new Notification({
        title: String(payload?.title || 'ResearchMate'),
        body: String(payload?.body || ''),
      }).show()
    }
    return { ok: true }
  })

  ipcMain.handle('update:check', async () => {
    try {
      await ensureChecked(true)
      return {
        ok: true,
        current: app.getVersion(),
        available: updateInfo?.version || null,
        releaseName: updateInfo?.releaseName || null,
        releaseDate: updateInfo?.releaseDate || null,
      }
    } catch (err) {
      return { ok: false, error: String(err?.message || err) }
    }
  })

  ipcMain.handle('update:download', async () => {
    try {
      await ensureChecked()
      if (!updateInfo) {
        return { ok: false, error: '未发现可用更新，请先点击「检查更新」' }
      }
      if (downloadStarted) {
        return { ok: true, already: true }
      }
      downloadStarted = true
      await autoUpdater.downloadUpdate()
      return { ok: true }
    } catch (err) {
      downloadStarted = false
      return { ok: false, error: String(err?.message || err) }
    }
  })

  ipcMain.handle('update:install', async () => {
    setImmediate(() => autoUpdater.quitAndInstall())
    return { ok: true }
  })
}

app.whenReady().then(async () => {
  app.setAppUserModelId('com.researchmate.desktop')
  // 关键修复：清掉旧页面缓存，并禁止缓存 index.html，避免用户更新后仍看到旧 UI
  await session.defaultSession.clearCache()
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const headers = { ...(details.responseHeaders || {}) }
    if (details.url.endsWith('/') || details.url.endsWith('/index.html') || details.url.endsWith('index.html')) {
      headers['Cache-Control'] = ['no-cache, no-store, must-revalidate']
      headers['Pragma'] = ['no-cache']
      headers['Expires'] = ['0']
    }
    callback({ responseHeaders: headers })
  })
  registerIpc()
  startBackend()
  autoUpdater.on('update-available', () => {
    if (Notification.isSupported()) {
      new Notification({
        title: 'ResearchMate 更新可用',
        body: '新版本已发布，可在应用内检查并下载。',
      }).show()
    }
  })
  try {
    await waitForServer()
  } catch (err) {
    console.error('[ResearchMate] backend startup failed:', err)
    dialog.showErrorBox('ResearchMate 启动失败', String(err?.message || err))
    app.quit()
    return
  }
  createWindow()
  createTray()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (!quitting) return
  stopBackend()
  app.quit()
})

app.on('before-quit', () => stopBackend())
