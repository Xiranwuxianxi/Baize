const fs = require('node:fs')
const path = require('node:path')
const { listPackage } = require('@electron/asar')
const { applicationPaths } = require('./locations.cjs')

const { resources } = applicationPaths()
const allowed = new Set(['package.json', 'main.cjs', 'lib', 'lib/backend.cjs', 'lib/policy.cjs', 'assets', 'assets/icon.png', 'loading.html', 'loading.css'])
for (const entry of listPackage(path.join(resources, 'app.asar'))) {
  const name = entry.replaceAll('\\', '/').replace(/^\//, '')
  if (!allowed.has(name)) throw new Error(`Unexpected desktop application file: ${name}`)
}
const backend = path.join(resources, 'backend')
const forbidden = new Set(['.env', 'config.yaml', 'mac.db', 'node_modules', '.venv', '.git'])
function inspect(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (forbidden.has(entry.name)) throw new Error(`Personal or development file in backend: ${entry.name}`)
    if (entry.isDirectory()) inspect(path.join(directory, entry.name))
  }
}
inspect(backend)
for (const relative of ['_internal/VERSION', '_internal/frontend/dist/index.html']) {
  if (!fs.existsSync(path.join(backend, relative))) throw new Error(`Missing bundled resource: ${relative}`)
}
console.log('Package audit passed: runtime files only; no personal data or build dependencies')
