const { app, BrowserWindow, dialog, Menu, session, shell } = require('electron')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { startBackend } = require('./lib/backend.cjs')
const { isAppUrl, externalUrl } = require('./lib/policy.cjs')

const smoke = process.argv.includes('--smoke-test')
const root = path.resolve(__dirname, '..')
let backend
let quitting = false
let stopped = false
let smokeHome
let startupWindow

app.setName('Baize')
// Chromium must not create files in Baize's data home before legacy migration.
if (!smoke) {
  const profile = path.join(app.getPath('appData'), 'BaizeDesktop')
  fs.mkdirSync(profile, { recursive: true })
  app.setPath('userData', profile)
}
if (smoke) {
  smokeHome = process.env.BAIZE_SMOKE_HOME || fs.mkdtempSync(path.join(os.tmpdir(), 'baize-desktop-smoke-'))
  fs.mkdirSync(path.join(smokeHome, 'electron'), { recursive: true })
  app.setPath('userData', path.join(smokeHome, 'electron'))
  for (const key of Object.keys(process.env)) if (key.startsWith('MAC_')) delete process.env[key]
  process.env.MAC_HOME = path.join(smokeHome, 'home')
  process.env.MAC_HOST = '127.0.0.1'
  app.disableHardwareAcceleration()
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const window = BrowserWindow.getAllWindows()[0]
    if (window) { if (window.isMinimized()) window.restore(); window.show(); window.focus() }
  })

  const preferences = { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true }
  const openExternal = value => { const safe = externalUrl(value); if (safe) shell.openExternal(safe).catch(() => {}) }
  app.on('web-contents-created', (_, contents) => {
    contents.on('will-navigate', (event, url) => {
      if (!backend || !isAppUrl(url, backend.origin)) { event.preventDefault(); openExternal(url) }
    })
    contents.setWindowOpenHandler(({ url }) => {
      if (backend && isAppUrl(url, backend.origin)) return { action: 'allow', overrideBrowserWindowOptions: { webPreferences: preferences } }
      openExternal(url)
      return { action: 'deny' }
    })
    contents.on('will-attach-webview', event => event.preventDefault())
  })

  function newWindow() {
    return new BrowserWindow({
      title: '白泽 Baize', width: 1320, height: 900, minWidth: 900, minHeight: 640,
      icon: path.join(__dirname, 'assets/icon.png'),
      show: false, backgroundColor: '#111827', webPreferences: preferences,
    })
  }

  async function createWindow() {
    const window = startupWindow && !startupWindow.isDestroyed() ? startupWindow : newWindow()
    startupWindow = undefined
    await window.loadURL(backend.origin)
    if (smoke) {
      const rendered = await window.webContents.executeJavaScript(`new Promise(resolve => {
        const root = document.querySelector('#root')
        if (root?.childElementCount) return resolve(true)
        if (!root) return resolve(false)
        const observer = new MutationObserver(() => {
          if (root.childElementCount) { observer.disconnect(); resolve(true) }
        })
        observer.observe(root, { childList: true })
        setTimeout(() => { observer.disconnect(); resolve(false) }, 10000)
      })`)
      if (!rendered) throw new Error('The desktop interface did not render')
      fs.writeFileSync(path.join(smokeHome, 'smoke-result.json'), JSON.stringify({ passed: true }))
      console.log('BAIZE_DESKTOP_SMOKE_OK')
      app.quit()
    } else window.show()
  }

  app.whenReady().then(async () => {
    app.setAppUserModelId('com.xiranwuxianxi.baize')
    if (smoke) app.setAppLogsPath(path.join(smokeHome, 'logs'))
    else app.setAppLogsPath()
    session.defaultSession.setPermissionRequestHandler((contents, permission, callback) => {
      callback(Boolean(backend && isAppUrl(contents.getURL(), backend.origin) && permission === 'clipboard-sanitized-write'))
    })
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      ...(process.platform === 'darwin' ? [{ role: 'appMenu' }] : [{ label: 'File', submenu: [{ role: 'quit' }] }]),
      { role: 'editMenu' }, { role: 'viewMenu' }, { role: 'windowMenu' },
    ]))
    startupWindow = newWindow()
    await startupWindow.loadFile(path.join(__dirname, 'loading.html'))
    if (!smoke) startupWindow.show()
    backend = await startBackend({ packaged: app.isPackaged, resourcesPath: process.resourcesPath, root,
      logPath: path.join(app.getPath('logs'), 'desktop-backend.log'),
      portFile: path.join(app.getPath('userData'), 'backend-port.json'),
    })
    backend.child.once('exit', () => {
      if (!quitting) {
        if (smoke) { console.error('Backend stopped unexpectedly'); process.exitCode = 1 }
        else dialog.showErrorBox('白泽服务已停止', '请重新打开白泽。详细信息可在应用日志中查看。')
        app.quit()
      }
    })
    await createWindow()
    app.on('activate', () => { if (!BrowserWindow.getAllWindows().length) createWindow().catch(fail) })
  }).catch(fail)

  app.on('window-all-closed', () => { if (process.platform !== 'darwin' || smoke) app.quit() })
  app.on('before-quit', event => {
    if (stopped) return
    event.preventDefault()
    if (quitting) return
    quitting = true
    for (const window of BrowserWindow.getAllWindows()) window.destroy()
    Promise.resolve(backend?.stop()).catch(console.error).finally(() => {
      stopped = true
      app.quit()
    })
  })
}

function fail(error) {
  console.error(error)
  if (smoke) process.exitCode = 1
  else dialog.showErrorBox('白泽无法启动', '请重新打开白泽，或查看应用日志了解详细原因。')
  app.quit()
}
