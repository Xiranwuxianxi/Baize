const fs = require('node:fs')
const path = require('node:path')
const { outputDirectory } = require('./release.cjs')

module.exports = {
  appId: 'com.xiranwuxianxi.baize',
  productName: 'Baize',
  executableName: 'Baize',
  extraMetadata: { version: process.env.BAIZE_BUILD_VERSION || fs.readFileSync(path.join(__dirname, '../VERSION'), 'utf8').trim() },
  directories: { output: outputDirectory(path.resolve(__dirname, '..')) },
  files: ['main.cjs', 'lib/**/*.cjs', 'assets/icon.png', 'loading.html', 'loading.css', 'package.json'],
  asar: true,
  extraResources: [{ from: '../.desktop-build/backend/baize-backend', to: 'backend', filter: ['**/*'] }],
  npmRebuild: false,
  electronDownload: { cache: path.join(__dirname, '../.desktop-build/cache/electron') },
  publish: null,
  win: { target: ['nsis', 'portable'], icon: 'assets/icon.ico', signAndEditExecutable: true },
  nsis: {
    artifactName: 'Baize-${version}-windows-${arch}-setup.${ext}',
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
    deleteAppDataOnUninstall: false,
    preCompressedFileExtensions: [],
    installerIcon: 'assets/icon.ico',
    uninstallerIcon: 'assets/icon.ico',
  },
  portable: {
    artifactName: 'Baize-${version}-windows-${arch}-portable.${ext}',
    // In electron-builder 26, true uses each launcher's unique $PLUGINSDIR.
    // A second click must not delete the first instance's program directory.
    unpackDirName: true,
    splashImage: 'assets/portable-splash.bmp',
  },
  mac: {
    target: ['dmg', 'zip'], category: 'public.app-category.developer-tools',
    icon: 'assets/icon.icns',
    artifactName: 'Baize-${version}-macos-${arch}.${ext}',
    identity: '-', hardenedRuntime: false, notarize: false,
  },
  linux: {
    target: ['AppImage', 'deb'], category: 'Development',
    syncDesktopName: true,
    icon: 'assets/icon.png',
    artifactName: 'Baize-${version}-linux-${arch}.${ext}',
    maintainer: 'Xiranwuxianxi',
  },
}
