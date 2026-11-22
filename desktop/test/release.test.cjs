const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const { PassThrough, Writable } = require('node:stream')
const { bumpVersion, buildTimestamp, releasePlan, askUpdateType, reserveOutput, outputDirectory, recordSuccessfulBuild } = require('../release.cjs')

test('small updates carry the last digit at nine; the middle number has no artificial limit', () => {
  assert.equal(bumpVersion('1.0.1', 'small'), '1.0.2')
  assert.equal(bumpVersion('1.2.8', 'small'), '1.2.9')
  assert.equal(bumpVersion('1.2.9', 'small'), '1.3.0')
  assert.equal(bumpVersion('1.9.9', 'small'), '1.10.0')
})

test('big updates increment the first number and reset the rest', () => {
  assert.equal(bumpVersion('1.0.1', 'big'), '2.0.0')
  assert.equal(bumpVersion('1.8.9', 'big'), '2.0.0')
  for (const invalid of ['v1.0.1', '1.0', '1.0.10', '1.02.3', '../1.0.1']) {
    assert.throws(() => bumpVersion(invalid, 'small'), /Invalid version/)
  }
  assert.throws(() => bumpVersion('1.0.1'), /Choose an update type/)
})

test('build folder times use Beijing time with a fixed UTC+8 offset and date rollover', () => {
  assert.equal(buildTimestamp(new Date('2026-11-22T09:35:40Z')), '2026-11-22_17-35-40')
  assert.equal(buildTimestamp(new Date('2026-07-22T09:35:40Z')), '2026-07-22_17-35-40')
  assert.equal(buildTimestamp(new Date('2026-07-22T23:35:40Z')), '2026-07-23_07-35-40')
  const plan = releasePlan('1.0.1', 'small', '2026-11-22_17-35-40')
  assert.equal(plan.folder, 'Baize-1.0.2_2026-11-22_17-35-40')
  assert.equal(plan.timeZone, 'Asia/Shanghai')
  assert.throws(() => releasePlan('1.0.1', 'small', '../old-output'), /Invalid build timestamp/)
})

test('non-interactive builds never assume an update type or start the build', async () => {
  await assert.rejects(askUpdateType('1.0.1', { isTTY: false }, { isTTY: false }), /ask the user/)
  const env = { ...process.env, npm_execpath: path.resolve(__dirname, '../package.json') }
  for (const name of Object.keys(env)) if (name.startsWith('BAIZE_')) delete env[name]
  const result = spawnSync(process.execPath, [path.resolve(__dirname, '../build.cjs')], { env, encoding: 'utf8', timeout: 10000 })
  assert.equal(result.status, 1, result.stderr)
  assert.match(result.stderr, /ask the user/)
  assert.doesNotMatch(result.stdout, /Packaging .*→/)
})

test('the interactive prompt waits for a choice and shows both proposed versions', { timeout: 2000 }, async () => {
  for (const [answer, expected] of [['1', 'small'], ['2', 'big'], ['q', null]]) {
    const input = new PassThrough()
    input.isTTY = true
    let text = ''
    const output = new Writable({ write(chunk, encoding, callback) { text += chunk.toString(); callback() } })
    output.isTTY = true
    try {
      const selection = askUpdateType('1.0.1', input, output)
      setImmediate(() => input.write(`${answer}\n`))
      if (expected) assert.equal(await selection, expected)
      else await assert.rejects(selection, /cancelled/)
      assert.match(text, /1\.0\.2/)
      assert.match(text, /2\.0\.0/)
    } finally { input.destroy(); output.destroy() }
  }
})

test('each batch gets a distinct timestamped directory and leaves older files intact', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'baize-release-test-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  const plan = releasePlan('1.0.1', 'small', '2026-11-22_09-35-40')
  const first = reserveOutput(root, plan)
  fs.writeFileSync(path.join(first, 'previous.exe'), 'previous package')
  const second = reserveOutput(root, plan)
  assert.equal(path.basename(first), plan.folder)
  assert.equal(path.basename(second), `${plan.folder}-2`)
  assert.equal(fs.readFileSync(path.join(first, 'previous.exe'), 'utf8'), 'previous package')
  assert.equal(path.basename(reserveOutput(root, plan, '../custom-output')), plan.folder)
})

test('completed builds synchronize application versions and keep subsequent checks on that batch', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'baize-release-test-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  fs.writeFileSync(path.join(root, 'VERSION'), '1.0.1\n')
  fs.writeFileSync(path.join(root, 'CHANGELOG.md'), '# 更新日志\n\n## [未发布]\n\n## [1.0.1] - 2026-11-22\n')
  for (const folder of ['desktop', 'frontend']) {
    fs.mkdirSync(path.join(root, folder))
    fs.writeFileSync(path.join(root, folder, 'package.json'), JSON.stringify({ version: '1.0.1', scripts: { check: 'unchanged' } }))
    fs.writeFileSync(path.join(root, folder, 'package-lock.json'), JSON.stringify({ version: '1.0.1', packages: { '': { version: '1.0.1' }, dependency: { version: '5.0.0' } } }))
  }
  const plan = releasePlan('1.0.1', 'small', '2026-11-22_09-35-40')
  const output = reserveOutput(root, plan)
  assert.equal(outputDirectory(root, {}), path.join(root, 'release'))
  recordSuccessfulBuild(root, plan, output)
  assert.equal(outputDirectory(root, {}), output)
  assert.equal(outputDirectory(root, { BAIZE_DESKTOP_OUTPUT: '../custom-output' }), path.join(root, 'custom-output'))
  assert.equal(fs.readFileSync(path.join(root, 'VERSION'), 'utf8').trim(), '1.0.2')
  const changelog = fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8')
  assert.equal(changelog.match(/^## \[(\d+\.\d+\.\d+)\]/m)[1], '1.0.2')
  assert.match(changelog, /## \[1\.0\.2\] - 2026-11-22/)
  for (const folder of ['desktop', 'frontend']) {
    const pkg = JSON.parse(fs.readFileSync(path.join(root, folder, 'package.json')))
    const lock = JSON.parse(fs.readFileSync(path.join(root, folder, 'package-lock.json')))
    assert.equal(pkg.version, plan.version)
    assert.equal(pkg.scripts.check, 'unchanged')
    assert.equal(lock.version, plan.version)
    assert.equal(lock.packages[''].version, plan.version)
    assert.equal(lock.packages.dependency.version, '5.0.0')
  }
  const next = releasePlan('1.0.2', 'small', '2026-11-22_10-35-40')
  const nextOutput = reserveOutput(root, next)
  recordSuccessfulBuild(root, next, nextOutput, false)
  assert.equal(fs.readFileSync(path.join(root, 'VERSION'), 'utf8').trim(), '1.0.2', 'CI must leave tracked version files untouched')
  assert.equal(outputDirectory(root, {}), nextOutput)
  assert.equal(fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8'), changelog, 'CI must preserve the source changelog')
  assert.equal(JSON.parse(fs.readFileSync(path.join(nextOutput, 'BUILD.json'))).version, '1.0.3')
})
