const path = require('node:path')

// electron-builder 26 has no portable.include option. Include the same hooks
// through makensis so both NSIS targets prepare the directory before launch.
module.exports = options => {
  // The hook is also used for non-NSIS packaging with a different argument.
  if (!Array.isArray(options)) return false
  const [, commands] = options
  commands['!include'] = `"${path.join(__dirname, 'windows-access.nsh')}"`
  return false
}
