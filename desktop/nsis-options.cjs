const path = require('node:path')

// electron-builder 26 has no portable.include option. Include the same hooks
// through makensis so both NSIS targets prepare the directory before launch.
module.exports = ([, commands]) => {
  commands['!include'] = `"${path.join(__dirname, 'windows-access.nsh')}"`
  return false
}
