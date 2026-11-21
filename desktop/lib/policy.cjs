function isAppUrl(value, origin) {
  if (value === 'about:blank') return true
  try {
    if (value.startsWith('blob:')) return new URL(value.slice(5)).origin === origin
    return new URL(value).origin === origin
  } catch {
    return false
  }
}

function externalUrl(value) {
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null
  } catch {
    return null
  }
}

module.exports = { isAppUrl, externalUrl }
