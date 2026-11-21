// 消息里的各种卡片：本地操作审批、领头人分派、记忆和经验提示，以及几处共用的常量
import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { api, openAuthed } from '../../lib/api'
import { ask } from '../../components/Dialog.jsx'
import { Btn, Icon, IconBtn, Tag } from '../../components/ui.jsx'

export { ACTION } from '../../lib/actionTags.js'
export const statusOf = (m) => (m.content ? '正在输入' : m.reasoning ? '正在思考' : '等待模型响应')
export const enter = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.3, ease: [0.16, 1, 0.3, 1] } }

export function Live({ children, since }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 text-xs text-accent-ink">
      <span className="h-1.5 w-1.5 animate-breathe rounded-full bg-accent" />{children}{since && <Elapsed since={since} />}
    </span>
  )
}

// 已经用了多久：长任务（命令行智能体、复杂分派）时一眼看出它还在动，而不是卡住了
export function Elapsed({ since }) {
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t) }, [])
  const s = Math.max(0, Math.floor(Date.now() / 1000 - since))
  if (s < 3) return null
  const text = s < 60 ? `${s} 秒` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  return <span className="font-mono text-[11px] text-faint tabular-nums">· {text}</span>
}

export function Tools({ m, onDelete, onRetry }) {
  const [copied, setCopied] = useState(false)
  if (m.streaming) return null
  const copy = () => navigator.clipboard?.writeText(m.content).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200) })
  return (
    <div className="flex shrink-0 self-end opacity-100 transition-opacity duration-150 group-hover:opacity-100 focus-within:opacity-100 md:opacity-0">
      {onRetry && <IconBtn icon="refresh" label="重新生成这条回复" size={28} onClick={onRetry} />}
      {m.content && <IconBtn icon={copied ? 'check' : 'copy'} label={copied ? '已复制' : '复制'} size={28} onClick={copy} />}
      <IconBtn icon="trash" label="删除这条消息" size={28} kind="danger" onClick={() => onDelete(m)} />
    </div>
  )
}

// 一次本地操作：待审批 → 执行中 → 结果
export const filePath = (m) => `/files?conv=${m.conv_id}&path=${encodeURIComponent(m.action.path)}`
export const fileFail = (e) => ask(e.message, { title: '打不开', cancel: false, ok: '知道了', danger: false })
export const reveal = (m) => api('POST', '/files/reveal', { conv: m.conv_id, path: m.action.path }).catch(fileFail)
// 在运行本程序的电脑上：用对应的应用打开（Word、Excel、图片……）；在手机等其他设备上：只能在浏览器里查看
export const onThisPc = /^(localhost|127\.|\[::1\])/.test(location.hostname)
export const openLocal = (m) => api('POST', '/files/open', { conv: m.conv_id, path: m.action.path })
  .then((r) => r.message !== '已用默认应用打开' && ask(r.message, { title: '已打开', cancel: false, ok: '知道了', danger: false })).catch(fileFail)
export const KIND = { run: ['terminal', '执行命令'], read: ['file', '读取文件'], write: ['write', '写入文件'], mcp: ['plug', '调用 MCP 工具'],
  fetch: ['search', '读取网页'], skill_find: ['search', '搜索技能与 MCP'], skill_add: ['sparkle', '添加技能'], skill_remove: ['trash', '删除技能'],
  mcp_add: ['plug', '添加 MCP 服务'], mcp_remove: ['trash', '删除 MCP 服务'] }
export const MANAGE = { fetch: (a) => a.url, skill_find: (a) => a.q, skill_add: (a) => a.url || a.path || `${a.name}\n${a.instructions || ''}`, skill_remove: (a) => a.name, mcp_add: (a) => a.raw, mcp_remove: (a) => a.name }
export const STATE = { done: ['ok', '已完成'], failed: ['danger', '执行失败'], denied: ['neutral', '已拒绝'], cancelled: ['neutral', '已取消'] }

export function TeamCard({ m, agent, running, permit }) {
  const a = m.action
  const waiting = m.status === 'pending' && running
  const hire = a.kind === 'hire'
  const tag = m.status === 'done' ? ['ok', '已同意'] : m.status === 'denied' ? ['neutral', '未同意'] : m.status === 'cancelled' ? ['neutral', '已取消'] : null
  return (
    <motion.div {...enter} className="flex gap-2.5 md:gap-3">
      <span className="w-9 shrink-0" />
      <div className={'min-w-0 max-w-[min(640px,100%)] flex-1 overflow-hidden rounded-xl border bg-surface ' + (waiting ? 'border-accent shadow-card' : 'border-line')}>
        <div className="flex items-center gap-2 px-3 py-2 text-[13px]">
          <Icon name={hire ? 'userPlus' : 'trash'} size={16} className="text-accent-ink" />
          <span className="min-w-0 flex-1 truncate text-muted"><b className="font-medium text-ink">{agent?.name || m.agent_name}</b> {waiting ? '想要' : ''}{hire ? '新建智能体' : '移除智能体'}「{a.name}」</span>
          {tag && !waiting && <Tag tone={tag[0]}>{tag[1]}</Tag>}
        </div>
        {hire && (
          <div className="border-t border-line bg-sunken px-3 py-2 text-[13px] leading-relaxed">
            {a.description && <p className="text-ink">{a.description}</p>}
            {a.prompt && <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-muted">{a.prompt}</p>}
          </div>
        )}
        {!hire && <p className="border-t border-line px-3 py-2 text-[13px] text-muted">{a.local ? '它只属于这个会话，移除后会被删除。' : '它会离开这个会话，全局智能体本身保留。'}</p>}
        {waiting && (
          <div className="flex gap-2 border-t border-line px-3 py-2.5">
            <Btn kind="ghost" onClick={() => permit(m.id, 'deny')}>不允许</Btn>
            <Btn kind="primary" icon="check" onClick={() => permit(m.id, 'once')}>{hire ? '同意新建' : '同意移除'}</Btn>
          </div>
        )}
        {m.granted && <p className="border-t border-line px-3 py-1.5 text-xs text-faint">授权方式：{m.granted}（可在「设置」里修改）</p>}
      </div>
    </motion.div>
  )
}

export function ToolCard({ m, agent, running, permit, inDocker }) {
  const [icon, label] = KIND[m.action.kind] || KIND.run
  const target = MANAGE[m.action.kind] ? MANAGE[m.action.kind](m.action) : m.action.kind === 'run' ? m.action.command : m.action.kind === 'mcp' ? `${m.action.server} / ${m.action.tool}\n${JSON.stringify(m.action.args || {}, null, 2)}` : m.action.path
  const waiting = m.status === 'pending' && running
  const st = STATE[m.status] || (m.status === 'pending' ? ['neutral', '未处理'] : null)
  const [copied, setCopied] = useState(false)
  const copyPath = () => navigator.clipboard?.writeText(m.path || m.cwd).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200) })
  return (
    <motion.div {...enter} className="flex gap-2.5 md:gap-3">
      <span className="w-9 shrink-0" />
      <div className={'min-w-0 max-w-[min(640px,100%)] flex-1 overflow-hidden rounded-xl border bg-surface ' + (waiting ? 'border-accent shadow-card' : 'border-line')}>
        <div className="flex items-center gap-2 px-3 py-2 text-[13px]">
          <Icon name={icon} size={16} className="text-accent-ink" />
          <span className="min-w-0 flex-1 truncate text-muted"><b className="font-medium text-ink">{agent?.name || m.agent_name}</b> {waiting ? '请求' : ''}{label}</span>
          {m.status === 'running' && <Live since={m.created}>执行中</Live>}
          {st && !waiting && <Tag tone={st[0]}>{st[1]}{m.code != null && m.code !== 0 ? ` · 退出码 ${m.code}` : ''}</Tag>}
        </div>
        <pre className="scroll overflow-x-auto border-t border-line bg-sunken px-3 py-2 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap text-ink [overflow-wrap:anywhere]">{target}</pre>
        {(m.path || m.cwd) && (
          <div className="flex items-start gap-2 border-t border-line px-3 py-2 text-xs leading-relaxed text-muted">
            <Icon name="folder" size={14} className="mt-0.5 text-faint" />
            <span className="shrink-0">{m.path ? (m.action.kind === 'write' ? '写入位置' : '文件位置') : '执行目录'}</span>
            <span className="min-w-0 flex-1 font-mono text-ink [overflow-wrap:anywhere]">{m.path || m.cwd}</span>
            <button type="button" title="复制路径" onClick={copyPath} className="shrink-0 rounded px-1 text-accent-ink hover:underline">{copied ? '已复制' : '复制'}</button>
          </div>
        )}
        {m.action.kind === 'write' && (
          <details className="border-t border-line text-[13px]">
            <summary className="cursor-pointer px-3 py-2 text-muted select-none hover:text-ink">查看要写入的内容（{m.action.content.length} 个字符）</summary>
            <pre className="scroll max-h-64 overflow-auto bg-sunken px-3 py-2 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap text-ink">{m.action.content}</pre>
          </details>
        )}
        {waiting && (
          <div className="border-t border-line px-3 py-2.5">
            <p className="mb-2.5 text-xs leading-relaxed text-muted">{inDocker ? '将在 Docker 容器内执行，影响不到宿主机。' : '将在这台电脑上执行。'}看清内容和位置再决定。</p>
            <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
              <Btn kind="ghost" onClick={() => permit(m.id, 'deny')} title="不执行，并告诉智能体被拒绝了">不允许</Btn>
              <Btn kind="primary" icon="check" onClick={() => permit(m.id, 'once')} title="只放行这一个操作">允许一次</Btn>
              <Btn onClick={() => permit(m.id, 'five')} title="这一次，以及本会话里接下来的四次操作">允许五次</Btn>
              <Btn onClick={() => permit(m.id, 'forever')} title={`以后${agent?.name || m.agent_name}的本地操作都不再询问，可在「设置」里撤销`}>永久允许</Btn>
            </div>
          </div>
        )}
        {m.granted && !waiting && m.status !== 'denied' && <p className="border-t border-line px-3 py-1.5 text-xs text-faint">授权方式：{m.granted}</p>}
        {m.output && m.action.kind !== 'write' && (
          <details className="border-t border-line text-[13px]" open={m.status === 'failed'}>
            <summary className="cursor-pointer px-3 py-2 text-muted select-none hover:text-ink">{m.action.kind === 'read' ? '查看文件内容' : '查看输出'}</summary>
            <pre className="scroll max-h-72 overflow-auto bg-[var(--code)] px-3 py-2.5 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap text-[var(--code-ink)]">{m.output}</pre>
          </details>
        )}
        {m.status === 'done' && (m.action.kind === 'read' || m.action.kind === 'write') && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3 py-2 text-[13px]">
            {onThisPc && !inDocker ? (<>
              <button type="button" onClick={() => openLocal(m)} className="inline-flex items-center gap-1.5 font-medium text-accent-ink hover:underline"><Icon name="file" size={14} />打开文件</button>
              <button type="button" onClick={() => reveal(m)} className="inline-flex items-center gap-1.5 text-muted hover:text-ink"><Icon name="folder" size={14} />在文件夹中显示</button>
            </>) : (
              <button type="button" onClick={() => openAuthed(filePath(m)).catch(fileFail)} className="inline-flex items-center gap-1.5 font-medium text-accent-ink hover:underline"><Icon name="file" size={14} />在浏览器里查看</button>
            )}
          </div>
        )}
        {m.output && m.action.kind === 'write' && <p className={'border-t border-line px-3 py-2 text-[13px] [overflow-wrap:anywhere] ' + (m.status === 'done' ? 'text-muted' : 'text-danger')}>{m.output}</p>}
      </div>
    </motion.div>
  )
}

// 智能体记下的经验：待确认时可以采纳或忽略（结果只在本地记一下，刷新后以经验库为准）
// 智能体给自己记下的一条记忆：可以当场撤销（删除这条记忆）
export function MemoryChip({ memory }) {
  const [gone, setGone] = useState(false)
  if (gone) return null
  const undo = () => api('DELETE', '/memories/' + memory.id).then(() => setGone(true)).catch(() => setGone(true))
  return (
    <div className="mt-2 flex items-start gap-2 rounded-lg bg-sunken px-3 py-1.5 text-[13px] leading-relaxed text-muted">
      <Icon name="brain" size={15} className="mt-0.5 shrink-0 text-accent" />
      <span className="min-w-0 flex-1">{memory.updated ? '更新了记忆：' : '记住了：'}{memory.text}</span>
      <button type="button" onClick={undo} className="shrink-0 rounded-md px-2 py-0.5 text-xs hover:bg-surface hover:text-ink">撤销</button>
    </div>
  )
}

export function LessonChip({ lesson }) {
  const l = typeof lesson === 'string' ? { text: lesson } : lesson
  const [state, setState] = useState(l.pending ? 'pending' : 'kept')
  const act = async (keep) => {
    try {
      if (keep) await api('PUT', '/lessons/' + l.id, { text: l.text, pending: false })
      else await api('DELETE', '/lessons/' + l.id)
      setState(keep ? 'kept' : 'dropped')
    } catch (e) {
      setState(e.status === 404 ? 'dropped' : state)
    }
  }
  if (state === 'dropped') return null
  return (
    <div className="mt-2.5 flex items-start gap-2 rounded-lg bg-accent-soft/60 px-3 py-2 text-[13px] leading-relaxed text-accent-ink">
      <Icon name="lightbulb" size={15} weight="fill" className="mt-0.5 shrink-0" />
      <span className="min-w-0 flex-1">{state === 'pending' ? '想记入团队经验：' : '已记入团队经验：'}{l.text}</span>
      {state === 'pending' && l.id && (
        <span className="flex shrink-0 gap-1">
          <button type="button" onClick={() => act(true)} className="rounded-md bg-surface px-2 py-0.5 text-xs font-medium text-ink shadow-xs hover:bg-sunken">采纳</button>
          <button type="button" onClick={() => act(false)} className="rounded-md px-2 py-0.5 text-xs text-muted hover:bg-surface">忽略</button>
        </span>
      )}
      {state === 'kept' && l.id && (
        <button type="button" onClick={() => act(false)} className="shrink-0 rounded-md px-2 py-0.5 text-xs text-muted hover:bg-surface">撤销</button>
      )}
    </div>
  )
}
