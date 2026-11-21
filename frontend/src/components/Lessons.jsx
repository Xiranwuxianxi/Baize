import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { ask } from './Dialog.jsx'
import { Btn, Icon, IconBtn, inputCls } from './ui.jsx'

const day = (ts) => { const d = new Date(ts * 1000); return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}` }
const MAX = 500
const FILTERS = [['all', '全部'], ['active', '生效中'], ['pending', '待确认'], ['pinned', '置顶']]

function Editor({ value, onSave, onCancel, label = '保存' }) {
  const [text, setText] = useState(value)
  return (
    <form className="min-w-0 flex-1 space-y-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) onSave(text.trim()) }}>
      <textarea autoFocus rows={3} maxLength={MAX} className={inputCls + ' resize-y text-[13px] leading-relaxed'} value={text}
        onChange={(e) => setText(e.target.value)} placeholder="写具体做法，例如：给用户的文件链接一律用相对路径"
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (text.trim()) onSave(text.trim()) } if (e.key === 'Escape') onCancel?.() }} />
      <div className="flex items-center gap-2">
        <span className="mr-auto font-mono text-[11px] text-faint">{text.length}/{MAX} · Ctrl+Enter 保存</span>
        {onCancel && <Btn kind="ghost" onClick={onCancel} className="h-8 px-3 text-xs">取消</Btn>}
        <Btn kind="primary" type="submit" disabled={!text.trim()} className="h-8 px-3 text-xs">{label}</Btn>
      </div>
    </form>
  )
}

// 共享经验库：全部经验都能看到、搜索、修改、置顶、删除。
export default function Lessons({ notify, locked }) {
  const [list, setList] = useState(null)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState('')
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const load = useCallback(() => api('GET', '/lessons').then((r) => setList(r.lessons)).catch((e) => notify(e.message)), [notify])
  useEffect(() => { load() }, [load])
  const run = async (fn) => { try { await fn() } catch (e) { notify(e.message) } load() }

  if (!list) return <div className="skeleton h-16 w-full rounded-xl" />
  const count = { all: list.length, active: list.filter((x) => !x.pending).length, pending: list.filter((x) => x.pending).length, pinned: list.filter((x) => x.pinned).length }
  const shown = list.filter((x) => (filter === 'all' || (filter === 'active' && !x.pending) || (filter === 'pending' && x.pending) || (filter === 'pinned' && x.pinned))
    && (!q.trim() || (x.text + ' ' + x.by).toLowerCase().includes(q.trim().toLowerCase())))
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-xl bg-sunken p-1">
          {FILTERS.map(([id, name]) => (
            <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}
              className={'rounded-lg px-2.5 py-1 text-xs transition-colors duration-150 ' + (filter === id ? 'bg-raised font-medium text-ink shadow-xs' : 'text-muted hover:text-ink')}>
              {name} <span className="font-mono text-faint">{count[id]}</span>
            </button>
          ))}
        </div>
        <label className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-xl border border-line bg-raised px-3 text-faint focus-within:border-accent sm:max-w-60">
          <Icon name="search" size={15} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索经验" aria-label="搜索经验" className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-faint" />
        </label>
        {!adding && <Btn kind="primary" icon="plus" disabled={locked} onClick={() => setAdding(true)} className="h-9">手动添加</Btn>}
      </div>

      {adding && (
        <div className="rounded-xl border border-accent/40 bg-raised p-3">
          <Editor value="" label="添加" onCancel={() => setAdding(false)} onSave={(text) => run(async () => { await api('POST', '/lessons', { text }); setAdding(false) })} />
        </div>
      )}

      {shown.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line-strong px-4 py-6 text-center text-[13px] leading-relaxed text-faint">
          {list.length ? '没有符合条件的经验。' : '还没有经验。智能体犯错或被你纠正后会自己记下一条；你也可以手动添加。'}
        </p>
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-raised">
          {shown.map((x) => (
            <li key={x.id} className="flex items-start gap-3 px-4 py-3 text-[13px]">
              <button type="button" disabled={locked} aria-label={x.pinned ? '取消置顶' : '置顶'} title={x.pinned ? '取消置顶' : '置顶：每次都带上这一条'}
                onClick={() => run(() => api('PUT', '/lessons/' + x.id, { ...x, pinned: !x.pinned }))}
                className={'mt-0.5 shrink-0 ' + (x.pinned ? 'text-accent' : 'text-line-strong hover:text-muted')}><Icon name="star" size={16} weight={x.pinned ? 'fill' : 'regular'} /></button>
              {editing === x.id ? (
                <Editor value={x.text} onCancel={() => setEditing('')} onSave={(text) => run(async () => { await api('PUT', '/lessons/' + x.id, { ...x, text }); setEditing('') })} />
              ) : (
                <>
                  <div className="min-w-0 flex-1">
                    <p className={'whitespace-pre-wrap leading-relaxed [overflow-wrap:anywhere] ' + (x.pending ? 'text-muted' : 'text-ink')}>{x.text}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-faint">
                      <span>{x.by}</span><span>{day(x.created)}</span>
                      {x.pending ? <span className="text-amber-600">待确认，还没生效</span> : x.pinned ? <span className="text-accent-ink">每次都带上</span> : <span>和问题相关时带上</span>}
                    </div>
                  </div>
                  {x.pending && <Btn kind="primary" disabled={locked} onClick={() => run(() => api('PUT', '/lessons/' + x.id, { ...x, pending: false }))} className="h-7 px-2.5 text-xs">采纳</Btn>}
                  <IconBtn icon="edit" label="编辑" size={30} disabled={locked} onClick={() => setEditing(x.id)} />
                  <IconBtn icon="trash" label="删除" kind="danger" size={30} disabled={locked}
                    onClick={async () => { if (await ask('删除这条经验？\n' + x.text)) run(() => api('DELETE', '/lessons/' + x.id)) }} />
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs leading-relaxed text-faint">置顶的经验每次都会发给模型；其余的只在和当前问题相关时才带上（经验很少时全部带上）。过时或不对的直接改掉或删掉。</p>
    </div>
  )
}
