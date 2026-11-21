import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { ask } from './Dialog.jsx'
import { Btn, Icon, IconBtn, inputCls } from './ui.jsx'

const MAX = 300

// 一个智能体自己的记忆：看得到、改得了、删得掉
export default function Memories({ agentId, notify, onCount }) {
  const [list, setList] = useState(null)
  const [q, setQ] = useState('')
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState(null) // { id, text }
  const load = useCallback(() => api('GET', `/agents/${agentId}/memories`).then((r) => { setList(r.memories); onCount?.(r.memories.length) }).catch((e) => notify(e.message)), [agentId, notify, onCount])
  useEffect(() => { load() }, [load])
  const run = async (fn) => { try { await fn() } catch (e) { notify(e.message) } load() }

  if (!list) return <div className="skeleton h-12 w-full rounded-xl" />
  const shown = list.filter((m) => !q.trim() || m.text.toLowerCase().includes(q.trim().toLowerCase()))
  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2">
        {list.length > 4 && (
          <label className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-xl border border-line bg-raised px-3 text-faint focus-within:border-accent">
            <Icon name="search" size={15} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索记忆" aria-label="搜索记忆" className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-faint" />
          </label>
        )}
        {list.length > 0 && (
          <button type="button" className="ml-auto shrink-0 rounded-md px-2 py-1 text-xs text-muted hover:bg-sunken hover:text-danger"
            onClick={async () => { if (await ask(`清空它的全部 ${list.length} 条记忆？`)) run(() => api('DELETE', `/agents/${agentId}/memories`)) }}>清空</button>
        )}
      </div>
      {shown.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line-strong px-4 py-4 text-[13px] leading-relaxed text-faint">
          {list.length ? '没有符合的记忆。' : '还没有记忆。聊天中遇到以后用得上的信息（你的偏好、项目背景、定下的决定），它会自己记下来；你也可以在下面手动添加。'}
        </p>
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-raised">
          {shown.map((m) => (
            <li key={m.id} className="flex items-start gap-2.5 px-3.5 py-2.5 text-[13px]">
              <button type="button" aria-label={m.pinned ? '取消置顶' : '置顶'} title={m.pinned ? '取消置顶' : '置顶：每次都带上这一条'}
                onClick={() => run(() => api('PUT', '/memories/' + m.id, { ...m, pinned: !m.pinned }))}
                className={'mt-0.5 shrink-0 ' + (m.pinned ? 'text-accent' : 'text-line-strong hover:text-muted')}><Icon name="star" size={15} weight={m.pinned ? 'fill' : 'regular'} /></button>
              {editing?.id === m.id ? (
                <form className="flex min-w-0 flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => { await api('PUT', '/memories/' + m.id, { ...m, text: editing.text }); setEditing(null) }) }}>
                  <input autoFocus maxLength={MAX} className={inputCls + ' h-8 min-w-0 flex-1 py-1 text-[13px]'} value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
                  <Btn kind="primary" type="submit" className="h-8 px-3 text-xs">保存</Btn>
                  <Btn kind="ghost" onClick={() => setEditing(null)} className="h-8 px-2 text-xs">取消</Btn>
                </form>
              ) : (
                <>
                  <span className="min-w-0 flex-1 leading-relaxed text-ink [overflow-wrap:anywhere]">{m.text}</span>
                  <IconBtn icon="edit" label="编辑" size={28} onClick={() => setEditing({ id: m.id, text: m.text })} />
                  <IconBtn icon="trash" label="删除" kind="danger" size={28} onClick={() => run(() => api('DELETE', '/memories/' + m.id))} />
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (draft.trim()) run(async () => { await api('POST', `/agents/${agentId}/memories`, { text: draft }); setDraft('') }) }}>
        <input className={inputCls + ' h-9 min-w-0 flex-1 py-1.5 text-[13px]'} value={draft} maxLength={MAX} onChange={(e) => setDraft(e.target.value)} placeholder="手动加一条，例如：我的项目都用 TypeScript" />
        <Btn kind="outline" icon="plus" type="submit" disabled={!draft.trim()} className="h-9">添加</Btn>
      </form>
    </div>
  )
}
