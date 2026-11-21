const { spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
for (const [key, directory] of Object.entries({
  npm_config_cache: 'npm', ELECTRON_CACHE: 'electron', ELECTRON_BUILDER_CACHE: 'electron-builder',
  PYINSTALLER_CONFIG_DIR: 'pyinstaller', PYTHONUSERBASE: 'python-userbase',
})) process.env[key] ||= path.join(root, '.desktop-build/cache', directory)
process.env.PYTHONNOUSERSITE = '1'
const { build, Platform } = require('electron-builder')
function run(command, args, cwd = root) {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', env: process.env })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`${command} exited with ${result.status}`)
}

async function main() {
  const python = process.env.BAIZE_BUILD_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
  const npmCli = process.env.npm_execpath
  if (!npmCli || !fs.existsSync(npmCli)) throw new Error('Run this build through npm run build or npm run pack')
  run(process.execPath, [npmCli, 'ci', '--no-fund', '--no-audit'], path.join(root, 'frontend'))
  run(process.execPath, [npmCli, 'run', 'build'], path.join(root, 'frontend'))
  run(python, ['-m', 'PyInstaller', '--noconfirm', '--clean',
    '--distpath', path.join(root, '.desktop-build/backend'),
    '--workpath', path.join(root, '.desktop-build/pyinstaller'),
    path.join(__dirname, 'backend.spec')])
  const targets = process.argv.includes('--dir') ? Platform.current().createTarget('dir') : undefined
  await build({ projectDir: __dirname, config: require('./electron-builder.cjs'), targets,
    effectiveOptionComputed: require('./nsis-options.cjs'),
  })
}

main().catch(error => { console.error(error); process.exitCode = 1 })
