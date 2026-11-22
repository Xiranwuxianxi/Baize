// Packaging helpers stay outside the application file inclusion list.
const fs = require('node:fs')
const path = require('node:path')
const readline = require('node:readline/promises')

const BUILD_TIME_ZONE = 'Asia/Shanghai'

function parseVersion(version) {
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.[0-9]$/.test(version)) {
    throw new Error(`Invalid version ${JSON.stringify(version)}; use three numbers with a last component from 0 to 9`)
  }
  const parts = version.split('.').map(Number)
  if (parts.some(number => !Number.isSafeInteger(number))) throw new Error('Version component is too large')
  return parts
}

function bumpVersion(version, updateType) {
  let [major, middle, last] = parseVersion(version)
  if (updateType === 'big') { major += 1; middle = 0; last = 0 }
  else if (updateType === 'small') {
    last += 1
    if (last === 10) { last = 0; middle += 1 }
  } else throw new Error('Choose an update type: small or big')
  const result = `${major}.${middle}.${last}`
  parseVersion(result)
  return result
}

function readVersion(root) {
  const version = fs.readFileSync(path.join(root, 'VERSION'), 'utf8').trim()
  parseVersion(version)
  return version
}

function buildTimestamp(date = new Date()) {
  const values = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: BUILD_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map(part => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}_${values.hour}-${values.minute}-${values.second}`
}

function releasePlan(baseVersion, updateType, timestamp = buildTimestamp()) {
  if (!/^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$/.test(timestamp)) throw new Error('Invalid build timestamp')
  const version = bumpVersion(baseVersion, updateType)
  return { baseVersion, updateType, version, timestamp, timeZone: BUILD_TIME_ZONE, folder: `Baize-${version}_${timestamp}` }
}

async function askUpdateType(version, input = process.stdin, output = process.stdout) {
  if (!input.isTTY || !output.isTTY) {
    throw new Error('Before packaging, ask the user to choose small or big, then pass --update small or --update big; no update type is selected automatically')
  }
  const prompt = readline.createInterface({ input, output })
  try {
    while (true) {
      const choice = (await prompt.question(`当前版本 ${version}。本次是小更新还是大更新？\n1. 小更新 → ${bumpVersion(version, 'small')}\n2. 大更新 → ${bumpVersion(version, 'big')}\n请选择 1 / 2（输入 q 取消）：`)).trim().toLowerCase()
      if (['1', 'small', '小更新'].includes(choice)) return 'small'
      if (['2', 'big', '大更新'].includes(choice)) return 'big'
      if (['q', 'quit', '取消'].includes(choice)) throw new Error('Packaging cancelled')
      output.write('请输入 1 或 2；不会自动选择更新类型。\n')
    }
  } finally { prompt.close() }
}

function reserveOutput(root, plan, outputBase) {
  const base = outputBase ? path.resolve(root, 'desktop', outputBase) : path.join(root, 'release')
  fs.mkdirSync(base, { recursive: true })
  for (let attempt = 1; ; attempt += 1) {
    const output = path.join(base, `${plan.folder}${attempt === 1 ? '' : `-${attempt}`}`)
    try { fs.mkdirSync(output); return output }
    catch (error) { if (error.code !== 'EEXIST') throw error }
  }
}

function outputDirectory(root, env = process.env) {
  if (env.BAIZE_DESKTOP_OUTPUT) return path.resolve(root, 'desktop', env.BAIZE_DESKTOP_OUTPUT)
  const latest = path.join(root, '.desktop-build/latest-build.json')
  if (fs.existsSync(latest)) {
    const receipt = JSON.parse(fs.readFileSync(latest, 'utf8'))
    return path.resolve(root, receipt.output)
  }
  // Keep checks for previously built packages usable until the first new build.
  return path.join(root, 'release')
}

function recordSuccessfulBuild(root, plan, output, updateSourceVersion = true) {
  const receipt = { ...plan, output: path.relative(root, output), completedAt: new Date().toISOString() }
  fs.writeFileSync(path.join(output, 'BUILD.json'), `${JSON.stringify(receipt, null, 2)}\n`)
  fs.mkdirSync(path.join(root, '.desktop-build'), { recursive: true })
  fs.writeFileSync(path.join(root, '.desktop-build/latest-build.json'), `${JSON.stringify(receipt, null, 2)}\n`)
  if (updateSourceVersion) {
    fs.writeFileSync(path.join(root, 'VERSION'), `${plan.version}\n`)
    for (const relative of ['desktop/package.json', 'desktop/package-lock.json', 'frontend/package.json', 'frontend/package-lock.json']) {
      const filename = path.join(root, relative)
      if (!fs.existsSync(filename)) continue
      const document = JSON.parse(fs.readFileSync(filename, 'utf8'))
      document.version = plan.version
      if (document.packages?.['']) document.packages[''].version = plan.version
      fs.writeFileSync(filename, `${JSON.stringify(document, null, 2)}\n`)
    }
  }
  return receipt
}

module.exports = { BUILD_TIME_ZONE, parseVersion, bumpVersion, readVersion, buildTimestamp, releasePlan, askUpdateType, reserveOutput, outputDirectory, recordSuccessfulBuild }
