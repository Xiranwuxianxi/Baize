const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const net = require('node:net')
const path = require('node:path')
const { applicationPaths } = require('./locations.cjs')

const executable = process.env.BAIZE_SMOKE_EXECUTABLE || applicationPaths().executable
if (!fs.existsSync(executable)) throw new Error(`Build the desktop app first: ${executable}`)
const args = ['--smoke-test']
const smokeHome = fs.mkdtempSync(path.join(os.tmpdir(), 'baize-desktop-smoke-'))
const child = spawn(executable, args, { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true, env: { ...process.env, BAIZE_SMOKE_HOME: smokeHome } })
let passed = false
child.stdout.on('data', data => { process.stdout.write(data); if (data.toString().includes('BAIZE_DESKTOP_SMOKE_OK')) passed = true })
child.stderr.on('data', data => process.stderr.write(data))
const timer = setTimeout(() => { child.kill('SIGKILL'); process.exitCode = 1 }, 180000)
child.on('error', error => { console.error(error); clearTimeout(timer); process.exitCode = 1 })
child.on('close', async code => {
  clearTimeout(timer)
  // A portable NSIS launcher does not forward its child's stdout, so read the
  // result from this invocation's isolated data directory as well.
  const resultFile = path.join(smokeHome, 'smoke-result.json')
  if (fs.existsSync(resultFile)) passed = JSON.parse(fs.readFileSync(resultFile, 'utf8')).passed === true
  const portFile = path.join(smokeHome, 'electron', 'backend-port.json')
  if (fs.existsSync(portFile)) {
    const { port } = JSON.parse(fs.readFileSync(portFile, 'utf8'))
    const listening = await new Promise(resolve => {
      const socket = net.createConnection({ host: '127.0.0.1', port })
      const finish = open => { socket.destroy(); resolve(open) }
      socket.once('connect', () => finish(true))
      socket.once('error', () => finish(false))
      socket.setTimeout(1000, () => finish(false))
    })
    if (listening) { console.error('The backend was still running after the application exited'); passed = false }
  }
  if (!path.resolve(smokeHome).startsWith(path.resolve(os.tmpdir()) + path.sep)) throw new Error('Invalid smoke test directory')
  fs.rmSync(smokeHome, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 })
  process.exitCode = passed && code === 0 ? 0 : 1
  if (process.exitCode) console.error(`Desktop smoke test failed: exit=${code}, rendered=${passed}`)
})
