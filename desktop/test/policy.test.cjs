const { test } = require('node:test')
const assert = require('node:assert/strict')
const { isAppUrl, externalUrl } = require('../lib/policy.cjs')
const origin = 'http://127.0.0.1:18760'

test('only application pages and application blobs stay inside Electron', () => {
  for (const value of [origin, `${origin}/api/state`, `blob:${origin}/file`, 'about:blank']) assert.equal(isAppUrl(value, origin), true)
  for (const value of ['https://example.com', 'file:///etc/passwd', 'javascript:alert(1)', 'blob:https://example.com/file', 'http://127.0.0.1:18761', 'invalid']) assert.equal(isAppUrl(value, origin), false)
})

test('external links cannot invoke file handlers or include credentials', () => {
  assert.equal(externalUrl('https://github.com/Xiranwuxianxi/Baize'), 'https://github.com/Xiranwuxianxi/Baize')
  for (const value of ['file:///etc/passwd', 'javascript:alert(1)', 'cmd:calc.exe', 'https://user:secret@example.com', 'invalid']) assert.equal(externalUrl(value), null)
})
