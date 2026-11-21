const { spawnSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

// Install/uninstall tests belong on disposable native CI runners.
if (!process.env.CI) throw new Error('Run package installation checks on a disposable CI runner')
const root = path.resolve(__dirname, '..')
const output = path.resolve(__dirname, process.env.BAIZE_DESKTOP_OUTPUT || '../release')
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'baize-package-test-'))
function run(command, args, env = {}) {
  console.log(`Package check: ${path.basename(command)} ${args.join(' ')}`)
  const result = spawnSync(command, args, {
    cwd: root, stdio: 'inherit', windowsHide: true, timeout: 240000,
    env: { ...process.env, ...env },
  })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`${command} failed (${result.status})`)
}
function artifact(extension) {
  const files = fs.readdirSync(output).filter(file => file.endsWith(extension))
  if (files.length !== 1) throw new Error(`Expected one ${extension} package, found ${files.length}`)
  return path.join(output, files[0])
}
function smoke(executable, env = {}) {
  run(process.execPath, [path.join(__dirname, 'smoke.cjs')], { BAIZE_SMOKE_EXECUTABLE: executable, ...env })
}

if (process.platform === 'win32') {
  run('powershell.exe', ['-NoProfile', '-NonInteractive', '-File', path.join(__dirname, 'test-windows-packages.ps1')], {
    BAIZE_PACKAGE_TEST_TEMP: temporary, BAIZE_PACKAGE_OUTPUT: output,
  })
} else if (process.platform === 'darwin') {
  const mount = path.join(temporary, 'mount')
  const installed = path.join(temporary, 'from-dmg', 'Baize.app')
  fs.mkdirSync(mount)
  fs.mkdirSync(path.dirname(installed))
  run('hdiutil', ['attach', '-nobrowse', '-readonly', '-mountpoint', mount, artifact('.dmg')])
  try { run('ditto', [path.join(mount, 'Baize.app'), installed]) }
  finally { run('hdiutil', ['detach', mount]) }
  run('codesign', ['--verify', '--deep', '--strict', installed])
  smoke(path.join(installed, 'Contents/MacOS/Baize'))
  const unzipped = path.join(temporary, 'from-zip')
  run('ditto', ['-x', '-k', artifact('.zip'), unzipped])
  const zipApp = path.join(unzipped, 'Baize.app')
  run('codesign', ['--verify', '--deep', '--strict', zipApp])
  smoke(path.join(zipApp, 'Contents/MacOS/Baize'))
} else if (process.platform === 'linux') {
  const appImage = artifact('.AppImage')
  fs.chmodSync(appImage, 0o755)
  smoke(appImage, { APPIMAGE_EXTRACT_AND_RUN: '1' })
  const deb = artifact('.deb')
  run('sudo', ['apt-get', 'install', '-y', deb])
  try { smoke('/opt/Baize/Baize') }
  finally { run('sudo', ['apt-get', 'remove', '-y', 'baize-desktop']) }
} else throw new Error(`Unsupported package test platform: ${process.platform}`)
console.log('All final package formats installed, rendered the interface and exited successfully')
