const fs = require('node:fs')
const path = require('node:path')

module.exports = {
  appId: 'com.xiranwuxianxi.baize',
  productName: 'Baize',
  executableName: 'Baize',
  extraMetadata: { version: fs.readFileSync(path.join(__dirname, '../VERSION'), 'utf8').trim() },
  directories: { output: process.env.BAIZE_DESKTOP_OUTPUT || '../release' },
  files: ['main.cjs', 'lib/**/*.cjs', 'package.json'],
  asar: true,
  extraResources: [{ from: '../.desktop-build/backend/baize-backend', to: 'backend', filter: ['**/*'] }],
  npmRebuild: false,
  electronDownload: { cache: path.join(__dirname, '../.desktop-build/cache/electron') },
  publish: null,
  win: { target: ['nsis', 'portable'], signAndEditExecutable: false },
  nsis: {
    artifactName: 'Baize-${version}-windows-${arch}-setup.${ext}',
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
    deleteAppDataOnUninstall: false,
    preCompressedFileExtensions: [],
  },
  portable: { artifactName: 'Baize-${version}-windows-${arch}-portable.${ext}' },
  mac: {
    target: ['dmg', 'zip'], category: 'public.app-category.developer-tools',
    artifactName: 'Baize-${version}-macos-${arch}.${ext}',
    identity: '-', hardenedRuntime: false, notarize: false,
  },
  linux: {
    target: ['AppImage', 'deb'], category: 'Development',
    artifactName: 'Baize-${version}-linux-${arch}.${ext}',
    maintainer: 'Xiranwuxianxi',
  },
}
