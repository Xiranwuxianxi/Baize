const path = require('node:path')
const { outputDirectory } = require('./release.cjs')

function applicationPaths() {
  const output = outputDirectory(path.resolve(__dirname, '..'))
  if (process.platform === 'darwin') {
    const app = path.join(output, process.arch === 'arm64' ? 'mac-arm64' : 'mac', 'Baize.app/Contents')
    return { executable: path.join(app, 'MacOS/Baize'), resources: path.join(app, 'Resources') }
  }
  const app = path.join(output, process.platform === 'win32' ? 'win-unpacked' : 'linux-unpacked')
  return { executable: path.join(app, process.platform === 'win32' ? 'Baize.exe' : 'Baize'), resources: path.join(app, 'resources') }
}

module.exports = { applicationPaths }
