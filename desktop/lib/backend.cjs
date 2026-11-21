const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const readline = require('node:readline')
const { setTimeout: delay } = require('node:timers/promises')

async function startBackend({ packaged, resourcesPath, root, logPath, portFile }) {
  const executable = process.platform === 'win32' ? 'baize-backend.exe' : 'baize-backend'
  const command = packaged
    ? path.join(resourcesPath, 'backend', executable)
    : (process.env.BAIZE_DEV_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'))
  const args = packaged ? [] : [path.join(root, 'backend/desktop_entry.py')]
  const env = { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }
  let preferredPort = 0
  try {
    const saved = JSON.parse(fs.readFileSync(portFile, 'utf8')).port
    if (Number.isInteger(saved) && saved > 1024 && saved <= 65535) preferredPort = saved
  } catch { /* First launch or an invalid preference starts with an allocated port. */ }
  env.BAIZE_DESKTOP_PORT = String(preferredPort)
  delete env.ELECTRON_RUN_AS_NODE
  delete env.PYTHONHOME
  delete env.PYTHONPATH
  fs.mkdirSync(path.dirname(logPath), { recursive: true })
  const output = fs.createWriteStream(logPath, { flags: 'a' })
  const child = spawn(command, args, { cwd: packaged ? resourcesPath : root, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  child.stdout.pipe(output, { end: false })
  child.stderr.pipe(output, { end: false })
  let closed = false
  const exited = new Promise(resolve => child.once('close', code => { closed = true; resolve(code) }))
  child.once('close', () => output.end())
  child.stdin.on('error', () => {})
  const lines = readline.createInterface({ input: child.stdout })
  let stopping = false

  async function stop() {
    if (stopping) return exited
    stopping = true
    if (closed || !child.pid || child.exitCode !== null || child.signalCode !== null) return
    child.stdin.end('shutdown\n')
    await Promise.race([exited, delay(8000)])
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
    await exited
  }

  try {
    const ready = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Backend startup timed out')), 90000)
      const finish = (fn, value) => { clearTimeout(timeout); fn(value) }
      child.once('error', error => finish(reject, error))
      child.once('exit', code => finish(reject, new Error(`Backend exited during startup (${code})`)))
      lines.on('line', line => {
        if (!line.startsWith('BAIZE_DESKTOP_READY ')) return
        try { finish(resolve, JSON.parse(line.slice('BAIZE_DESKTOP_READY '.length))) }
        catch (error) { finish(reject, error) }
      })
    })
    if (!Number.isInteger(ready.port) || ready.port < 1 || ready.port > 65535) throw new Error('Invalid backend port')
    const host = ready.host === '::' ? '[::1]' : ready.host === '0.0.0.0' ? '127.0.0.1' : ready.host
    const origin = new URL(`http://${host.includes(':') && !host.startsWith('[') ? `[${host}]` : host}:${ready.port}`).origin
    const deadline = Date.now() + 90000
    while (true) {
      if (child.exitCode !== null) throw new Error('Backend stopped before its web interface was ready')
      try {
        const response = await fetch(origin, { signal: AbortSignal.timeout(1500) })
        if (response.ok && response.headers.get('content-type')?.includes('text/html')) break
      } catch { /* Server may still be starting. */ }
      if (Date.now() > deadline) throw new Error('The packaged web interface is not available')
      await delay(150)
    }
    fs.writeFileSync(portFile, JSON.stringify({ port: ready.port }), { mode: 0o600 })
    return { child, origin, stop }
  } catch (error) {
    await stop()
    throw error
  } finally {
    lines.close()
    child.stdout.resume()
  }
}

module.exports = { startBackend }
