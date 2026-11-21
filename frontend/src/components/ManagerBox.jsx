import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { Icon } from './ui.jsx'

const STEP = {
  fetch: '读取网页', skill_find: '查找已有内容', skill_add: '添加技能', skill_remove: '删除技能',
  mcp_add: '添加 MCP 服务', mcp_remove: '删除 MCP 服务', run: '执行命令', read: '读取文件', write: '写入文件',
}
const TAGS = /<[a-z_]+[\s\S]*?(\/>|<\/[a-z_]+>)/g

// 安装小窗：只显示几步进度，需要确认就在这里点；成功后自动消失
function InstallPanel({ job, messages, running, permit, onDone }) {
  const [seenRun, setSeenRun] = useState(false)
  const [open, setOpen] = useState(false) // 展开看每一步的输出和管家的完整回复，就在这里看，不跳走
  const timer = useRef(null)
  if (running && !seenRun) setSeenRun(true)
  const mine = (messages || []).filter((m) => m.created >= job.at - 2 && m.role !== 'user' && m.role !== 'notice')
  const steps = mine.filter((m) => m.role === 'tool')
  const replies = mine.filter((m) => m.role === 'agent' && !m.streaming)
  const last = replies[replies.length - 1]
  const finished = seenRun && !running && !!last
  const failed = finished && (last.error || steps.some((s) => s.status === 'failed' || s.status === 'denied'))
  const summary = last ? (last.error || last.content.replace(TAGS, '').replace(/[*#`>]/g, '').trim()) : ''

  useEffect(() => {
    if (finished && !failed && !open) timer.current = setTimeout(onDone, 2600) // 展开看详情时不自动关
    return () => clearTimeout(timer.current)
  }, [finished, failed, open, onDone])
  const full = replies.map((r) => r.error || r.content.replace(TAGS, '').trim()).filter(Boolean).join('\n\n')

  return (
    <motion.div initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.98 }}
      transition={{ type: 'spring', stiffness: 360, damping: 30 }}
      className="mb-6 overflow-hidden rounded-2xl border border-line bg-raised shadow-float" role="status" aria-live="polite">
      <div className="flex items-center gap-3 px-4 py-3">
        <span className={'flex h-8 w-8 shrink-0 items-center justify-center rounded-full ' + (failed ? 'bg-danger-soft text-danger' : finished ? 'bg-ok-soft text-ok' : 'bg-accent-soft text-accent-ink')}>
          {finished ? <Icon name={failed ? 'warn' : 'check'} size={16} weight="bold" /> : <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink">{finished ? (failed ? '没有完成' : '已完成') : '管家正在处理…'}</div>
          <div className="truncate text-xs text-faint">{job.text}</div>
        </div>
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
          className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-muted hover:bg-sunken hover:text-ink">
          {open ? '收起' : '详情'}<Icon name="chevron" size={12} className={'transition-transform duration-200 ' + (open ? 'rotate-180' : '')} />
        </button>
        {finished && <button type="button" onClick={onDone} aria-label="关闭" className="shrink-0 rounded-md p-1 text-faint hover:bg-sunken hover:text-ink"><Icon name="x" size={14} /></button>}
      </div>
      {(steps.length > 0 || summary) && (
        <div className="space-y-1.5 border-t border-line px-4 py-3 text-[13px]">
          {steps.map((s) => {
            const pending = s.status === 'pending' && running
            return (
              <div key={s.id}>
                <div className="flex items-center gap-2">
                  <span className={'h-1.5 w-1.5 shrink-0 rounded-full ' + (s.status === 'done' ? 'bg-ok' : s.status === 'failed' || s.status === 'denied' ? 'bg-danger' : 'animate-breathe bg-accent')} />
                  <span className="shrink-0 text-ink">{STEP[s.action.kind] || '操作'}</span>
                  <span className="min-w-0 flex-1 truncate font-mono text-xs text-faint">{s.action.url || s.action.name || s.action.command || s.action.path || ''}</span>
                  <span className="shrink-0 text-xs text-faint">{s.status === 'done' ? '完成' : s.status === 'failed' ? '失败' : s.status === 'denied' ? '已拒绝' : pending ? '等你确认' : '进行中'}</span>
                </div>
                {open && s.output && (
                  <pre className="mt-1.5 ml-3.5 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sunken px-3 py-2 font-mono text-[11px] leading-relaxed text-muted">{s.output.slice(-4000)}</pre>
                )}
                {pending && (
                  <div className="mt-1.5 ml-3.5 flex gap-1.5">
                    <button type="button" onClick={() => permit(s.id, 'once')} className="rounded-lg bg-accent px-3 py-1 text-xs font-medium text-on-accent hover:bg-accent-strong">允许</button>
                    <button type="button" onClick={() => permit(s.id, 'forever')} className="rounded-lg border border-line px-3 py-1 text-xs text-ink hover:bg-sunken">以后都允许管家</button>
                    <button type="button" onClick={() => permit(s.id, 'deny')} className="rounded-lg px-3 py-1 text-xs text-muted hover:bg-sunken">不允许</button>
                  </div>
                )}
              </div>
            )
          })}
          {open
            ? full && <p className="max-h-60 overflow-auto whitespace-pre-wrap pt-0.5 text-xs leading-relaxed text-muted">{full}</p>
            : finished && summary && <p className="line-clamp-3 pt-0.5 text-xs leading-relaxed text-muted">{summary}</p>}
        </div>
      )}
      {open && steps.length === 0 && !full && <p className="border-t border-line px-4 py-3 text-xs text-faint">管家正在思考，还没有开始操作…</p>}
    </motion.div>
  )
}

// 「交给管家」：贴网址或一句需求，就在当前页面完成，不跳到聊天
export default function ManagerBox({ askManager, manager, placeholder, examples = [], onDone }) {
  const [text, setText] = useState('')
  const [job, setJob] = useState(null) // { conv, text, at }
  const go = async (value) => {
    const v = (value ?? text).trim()
    if (!v || job) return
    const conv = await askManager(v, { inline: true })
    if (conv) { setJob({ conv, text: v, at: Date.now() / 1000 }); setText('') }
  }
  const close = () => { setJob(null); onDone?.() }
  return (
    <>
      <AnimatePresence>
        {job && (
          <InstallPanel key={job.at} job={job} messages={manager.msgs[job.conv]} running={!!manager.running[job.conv]} permit={manager.permit}
            onDone={close} />
        )}
      </AnimatePresence>
      {!job && (
        <div className="mb-6 overflow-hidden rounded-2xl border border-line bg-raised shadow-card">
          <form className="flex items-center gap-2 p-2.5 pl-4" onSubmit={(e) => { e.preventDefault(); go() }}>
            <Icon name="wrench" size={17} className="shrink-0 text-accent" />
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} aria-label="交给管家"
              className="h-10 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-faint" />
            <button type="submit" disabled={!text.trim()}
              className="flex h-10 shrink-0 items-center gap-1.5 rounded-xl bg-accent px-4 text-sm font-medium text-on-accent transition-[background-color,transform] duration-150 hover:bg-accent-strong active:scale-[0.97] disabled:opacity-40">
              交给管家<Icon name="arrow" size={15} weight="bold" />
            </button>
          </form>
          {examples.length > 0 && (
            <div className="no-bar flex gap-1.5 overflow-x-auto px-3 pb-3">
              {examples.map((x) => (
                <button key={x} type="button" onClick={() => go(x)} className="shrink-0 rounded-full border border-line px-3 py-1 text-xs text-muted transition-colors duration-150 hover:border-accent hover:text-accent-ink">{x}</button>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  )
}

export function SearchInput({ value, onChange, placeholder }) {
  return (
    <label className="flex h-10 min-w-0 flex-1 basis-full items-center gap-2 rounded-xl border border-line bg-raised px-3 text-faint focus-within:border-accent sm:basis-auto sm:max-w-xs">
      <Icon name="search" size={16} />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder}
        className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-faint" />
    </label>
  )
}
