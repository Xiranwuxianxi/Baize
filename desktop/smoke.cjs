const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { applicationPaths } = require('./locations.cjs')

const { executable } = applicationPaths()
if (!fs.existsSync(executable)) throw new Error(`Build the desktop app first: ${executable}`)
const args = ['--smoke-test', ...(process.env.CI && process.platform === 'linux' ? ['--no-sandbox'] : [])]
const smokeHome = fs.mkdtempSync(path.join(os.tmpdir(), 'baize-desktop-smoke-'))
const child = spawn(executable, args, { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true, env: { ...process.env, BAIZE_SMOKE_HOME: smokeHome } })
let passed = false
child.stdout.on('data', data => { process.stdout.write(data); if (data.toString().includes('BAIZE_DESKTOP_SMOKE_OK')) passed = true })
child.stderr.on('data', data => process.stderr.write(data))
const timer = setTimeout(() => { child.kill('SIGKILL'); process.exitCode = 1 }, 180000)
child.on('error', error => { console.error(error); clearTimeout(timer); process.exitCode = 1 })
child.on('exit', code => {
  clearTimeout(timer)
  if (!path.resolve(smokeHome).startsWith(path.resolve(os.tmpdir()) + path.sep)) throw new Error('Invalid smoke test directory')
  fs.rmSync(smokeHome, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 })
  process.exitCode = passed && code === 0 ? 0 : 1
})
