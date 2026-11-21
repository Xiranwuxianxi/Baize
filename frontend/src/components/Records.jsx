import { ask } from './Dialog.jsx'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Btn } from './ui.jsx'

const size = (n) => (n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB')
const day = (ts) => { const d = new Date(ts * 1000); return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}` }

// 设置页里的「聊天记录」：勾选会话后删除，可选同时删除会话文件夹
export default function Records({ notify, reload, locked }) {
  const [r, setR] = useState(null)
  const [picked, setPicked] = useState([])
  const [files, setFiles] = useState(false)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => api('GET', '/records').then(setR).catch((e) => notify(e.message)), [notify])
  useEffect(() => { load() }, [load])
  if (!r) return <div className="skeleton h-3 w-40" />

  const all = r.conversations.length > 0 && picked.length === r.conversations.length
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const remove = async () => {
    if (!await ask(`删除选中的 ${picked.length} 个会话及其全部聊天记录？${files ? '会话文件夹里的文件也会一起删除。' : ''}此操作无法撤销。`)) return
    setBusy(true)
    try {
      const res = await api('POST', '/records/delete', { ids: picked, files })
      notify(`已删除 ${res.removed} 个会话`)
      setPicked([])
      await load()
      reload()
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-[13px] leading-relaxed text-muted">
        所有数据只保存在这台电脑的 SQLite 文件里，不上传任何地方：<span className="font-mono text-xs text-ink [overflow-wrap:anywhere]">{r.db_path}</span>（{size(r.db_bytes)}）
      </p>
      {r.conversations.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line-strong px-4 py-5 text-[13px] text-faint">还没有聊天记录。</p>
      ) : (
        <>
          <div className="max-h-80 overflow-y-auto scroll rounded-xl border border-line bg-raised">
            <label className="sticky top-0 flex items-center gap-3 border-b border-line bg-raised px-3.5 py-2 text-xs text-muted">
              <input type="checkbox" checked={all} onChange={() => setPicked(all ? [] : r.conversations.map((c) => c.id))} className="h-4 w-4 accent-[var(--accent)]" />
              全选（{r.conversations.length} 个会话）
            </label>
            {r.conversations.map((c) => (
              <label key={c.id} className="flex cursor-pointer items-center gap-3 border-b border-line px-3.5 py-2 text-[13px] last:border-0 hover:bg-sunken/60">
                <input type="checkbox" checked={picked.includes(c.id)} onChange={() => toggle(c.id)} className="h-4 w-4 accent-[var(--accent)]" />
                <span className="min-w-0 flex-1 truncate text-ink">{c.title}</span>
                <span className="shrink-0 font-mono text-[11px] text-faint">{c.messages} 条 · {size(c.bytes)} · {day(c.last)}</span>
              </label>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Btn kind="danger" icon="trash" disabled={locked || busy || !picked.length} onClick={remove}>删除选中的会话</Btn>
            <label className="flex items-center gap-2 text-[13px] text-muted">
              <input type="checkbox" checked={files} onChange={(e) => setFiles(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
              同时删除这些会话的文件夹
            </label>
          </div>
        </>
      )}
    </div>
  )
}
