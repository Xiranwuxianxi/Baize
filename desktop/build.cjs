const { spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const { readVersion, releasePlan, askUpdateType, reserveOutput, recordSuccessfulBuild } = require('./release.cjs')

const root = path.resolve(__dirname, '..')
for (const [key, directory] of Object.entries({
  npm_config_cache: 'npm', ELECTRON_CACHE: 'electron', ELECTRON_BUILDER_CACHE: 'electron-builder',
  PYINSTALLER_CONFIG_DIR: 'pyinstaller', PYTHONUSERBASE: 'python-userbase',
})) process.env[key] ||= path.join(root, '.desktop-build/cache', directory)
process.env.PYTHONNOUSERSITE = '1'
function run(command, args, cwd = root) {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', env: process.env })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`${command} exited with ${result.status}`)
}

async function main() {
  const python = process.env.BAIZE_BUILD_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
  const npmCli = process.env.npm_execpath
  if (!npmCli || !fs.existsSync(npmCli)) throw new Error('Run this build through npm run build or npm run pack')
  const updateIndex = process.argv.indexOf('--update')
  const baseVersion = process.env.BAIZE_BASE_VERSION || readVersion(root)
  const updateType = updateIndex === -1 ? process.env.BAIZE_UPDATE_TYPE || await askUpdateType(baseVersion) : process.argv[updateIndex + 1]
  const plan = releasePlan(baseVersion, updateType, process.env.BAIZE_BUILD_TIMESTAMP)
  if (process.env.BAIZE_BUILD_VERSION && process.env.BAIZE_BUILD_VERSION !== plan.version) {
    throw new Error('The selected version does not match the update type and base version')
  }
  const { build, Platform } = require('electron-builder')
  const output = reserveOutput(root, plan, process.env.BAIZE_DESKTOP_OUTPUT)
  process.env.BAIZE_DESKTOP_OUTPUT = output
  process.env.BAIZE_BUILD_VERSION = plan.version
  const versionDirectory = path.join(root, '.desktop-build/build-version')
  fs.mkdirSync(versionDirectory, { recursive: true })
  process.env.BAIZE_BUILD_VERSION_FILE = path.join(versionDirectory, 'VERSION')
  fs.writeFileSync(process.env.BAIZE_BUILD_VERSION_FILE, `${plan.version}\n`)
  console.log(`Packaging ${plan.baseVersion} → ${plan.version} (${plan.updateType}); output: ${output}`)
  run(process.execPath, [npmCli, 'ci', '--no-fund', '--no-audit'], path.join(root, 'frontend'))
  run(process.execPath, [npmCli, 'run', 'build'], path.join(root, 'frontend'))
  run(python, ['-m', 'PyInstaller', '--noconfirm', '--clean',
    '--distpath', path.join(root, '.desktop-build/backend'),
    '--workpath', path.join(root, '.desktop-build/pyinstaller'),
    path.join(__dirname, 'backend.spec')])
  const targets = process.argv.includes('--dir') ? Platform.current().createTarget('dir') : undefined
  await build({ projectDir: __dirname, config: require('./electron-builder.cjs'), targets, publish: 'never',
    effectiveOptionComputed: process.platform === 'win32' ? require('./nsis-options.cjs') : undefined,
  })
  if (!process.argv.includes('--dir')) {
    const files = fs.readdirSync(output)
    const suffixes = process.platform === 'win32' ? ['-setup.exe', '-portable.exe']
      : process.platform === 'darwin' ? ['.dmg', '.zip'] : ['.AppImage', '.deb']
    for (const suffix of suffixes) {
      if (!files.some(file => file.endsWith(suffix))) throw new Error(`Missing desktop package: ${suffix}`)
    }
  }
  recordSuccessfulBuild(root, plan, output, !process.env.CI)
  console.log(`Packaging completed: ${output}\nUpload installers to GitHub Releases manually.`)
}

main().catch(error => { console.error(error); process.exit(1) })
