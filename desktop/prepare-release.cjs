const fs = require('node:fs')
const path = require('node:path')
const { readVersion, releasePlan } = require('./release.cjs')

const root = path.resolve(__dirname, '..')
const updateType = process.env.BAIZE_UPDATE_TYPE
if (process.env.GITHUB_ACTIONS && !process.env.BAIZE_BASE_VERSION) throw new Error('Enter the previous packaging version before starting this batch')
const baseVersion = process.env.BAIZE_BASE_VERSION || readVersion(root)
const plan = releasePlan(baseVersion, updateType)
if (process.env.GITHUB_OUTPUT) {
  fs.appendFileSync(process.env.GITHUB_OUTPUT,
    `base_version=${plan.baseVersion}\nversion=${plan.version}\ntimestamp=${plan.timestamp}\nfolder=${plan.folder}\n`)
}
console.log(JSON.stringify(plan, null, 2))
