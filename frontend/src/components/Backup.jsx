import { useRef, useState } from 'react'
import { downloadAuthed, uploadRaw } from '../lib/api'
import { ask } from './Dialog.jsx'
import { Btn } from './ui.jsx'

// 一键导出 / 恢复全部数据：换电脑、升级前留一份
export default function Backup({ notify, reload, locked }) {
  const [busy, setBusy] = useState('')
  const [withFiles, setWithFiles] = useState(false)
  const fileRef = useRef(null)
  const run = async (kind, fn) => { setBusy(kind); try { await fn() } catch (e) { notify(e.message) } finally { setBusy('') } }

  const exportNow = () => run('export', () => downloadAuthed('/backup' + (withFiles ? '?workspace=true' : ''), 'baize-backup.zip'))
  const restore = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!(await ask(`用「${file.name}」恢复数据？\n现在的全部数据会被备份里的内容替换。替换前会自动把当前数据另存一份在 data 目录，恢复错了还能找回。`, { ok: '恢复', danger: true }))) return
    run('restore', async () => {
      const r = await uploadRaw('/backup/restore', file)
      await reload()
      notify(`已恢复${r.workspace_files ? `，并放回 ${r.workspace_files} 个工作区文件` : ''}。原来的数据另存为 data/${r.saved_current_as}`)
    })
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Btn kind="primary" icon="download" disabled={locked || !!busy} onClick={exportNow}>{busy === 'export' ? '正在打包…' : '导出备份'}</Btn>
        <input ref={fileRef} type="file" accept=".zip,application/zip" className="hidden" onChange={restore} />
        <Btn kind="outline" icon="upload" disabled={locked || !!busy} onClick={() => fileRef.current?.click()}>{busy === 'restore' ? '正在恢复…' : '从备份恢复'}</Btn>
        <label className="ml-1 flex cursor-pointer items-center gap-2 text-[13px] text-muted">
          <input type="checkbox" checked={withFiles} onChange={(e) => setWithFiles(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
          连同工作区里的文件
        </label>
      </div>
      <p className="text-xs leading-relaxed text-faint">备份是一个 zip，包含渠道、智能体、会话、记忆、经验、用量和设置。<b className="font-medium text-muted">里面有渠道密钥</b>，请像密码一样保管，不要放进网盘同步目录。</p>
    </div>
  )
}
