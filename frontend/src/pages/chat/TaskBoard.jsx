// 并行任务看板：领头人一次分派给多人时，成员同时开工，这里把每个人并排成一列，
// 实时看到每个人在想什么、做什么、交付了什么，而不是一条接一条地往下翻。
import { useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import Markdown from '../../components/Markdown.jsx'
import { Avatar, Icon } from '../../components/ui.jsx'
import { ACTION, Elapsed, ToolCard, enter, statusOf } from './cards.jsx'
import { t } from '../../lib/i18n'

// 一列的状态：决定标题旁的小灯和文字
function stateOf(items, running) {
  const pending = items.find((m) => m.role === 'tool' && m.status === 'pending' && running)
  if (pending) return { tone: 'warn', text: t('等你确认') }
  if (items.some((m) => m.role === 'tool' && m.status === 'running')) return { tone: 'live', text: t('正在执行操作') }
  const live = items.find((m) => m.role === 'agent' && m.streaming)
  if (live) return { tone: 'live', text: t(statusOf(live)) }
  const last = [...items].reverse().find((m) => m.role === 'agent')
  if (last?.error) return { tone: 'error', text: t('出错了') }
  if (last && !last.error) return { tone: 'done', text: t('已交付') }
  return { tone: 'live', text: t('准备开工') }
}

const DOT = { live: 'animate-breathe bg-accent', warn: 'bg-amber-500', error: 'bg-danger', done: 'bg-ok' }
const PILL = { live: 'text-accent-ink', warn: 'text-amber-600', error: 'text-danger', done: 'text-ok' }

function Column({ agent, name, items, running, permit, inDocker, onEditAgent, onStop, onRetry }) {
  const [full, setFull] = useState(false)
  const body = useRef(null)
  const state = stateOf(items, running)
  const task = items.find((m) => m.task)?.task
  const size = items.reduce((n, m) => n + (m.content || '').length + (m.reasoning || '').length + (m.status ? 1 : 0), 0)
  // 生成过程中跟着滚到底，能一直看到最新的字
  useEffect(() => { const el = body.current; if (el && state.tone === 'live') el.scrollTop = el.scrollHeight }, [size, state.tone])
  // 交付后回到开头，从第一句读起
  useEffect(() => { const el = body.current; if (el && state.tone === 'done') el.scrollTop = 0 }, [state.tone])
  const who = agent || { name, color: 'slate' }
  return (
    <motion.section {...enter} className="flex min-w-0 flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_8px_24px_-16px_rgb(var(--shadow)/0.25)]">
      <header className="flex items-center gap-2.5 border-b border-line px-3.5 py-2.5">
        <button type="button" onClick={() => agent && onEditAgent(agent)} className="shrink-0" aria-label={name}><Avatar agent={who} size={30} /></button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-ink">{name}</div>
          <div className={'flex items-center gap-1.5 text-xs ' + PILL[state.tone]} aria-live="polite">
            <span className={'h-1.5 w-1.5 shrink-0 rounded-full ' + DOT[state.tone]} />{state.text}
            {state.tone !== 'done' && state.tone !== 'error' && items[0] && <Elapsed since={items[0].created} />}
          </div>
        </div>
        {running && state.tone !== 'done' && state.tone !== 'error' && (
          <button type="button" onClick={onStop} title={t('只停止这一位，其他人继续')} className="shrink-0 rounded-md px-1.5 py-1 text-xs text-muted hover:bg-danger-soft hover:text-danger">{t('停止')}</button>
        )}
        {!running && (
          <button type="button" onClick={onRetry} title={t('让它重新做一遍这项任务')} className={'shrink-0 rounded-md px-1.5 py-1 text-xs hover:bg-sunken ' + (state.tone === 'error' ? 'font-medium text-accent-ink' : 'text-faint hover:text-ink')}>{t('重做')}</button>
        )}
        <button type="button" onClick={() => setFull((v) => !v)} className="shrink-0 rounded-md px-1.5 py-1 text-xs text-faint hover:bg-sunken hover:text-ink" aria-expanded={full}>
          {full ? t('收起') : t('展开')}
        </button>
      </header>
      {task && (
        <div className="flex items-start gap-1.5 border-b border-line bg-sunken/60 px-3.5 py-2 text-[12.5px] leading-relaxed text-muted">
          <Icon name="branch" size={13} className="mt-0.5 shrink-0 text-faint" />
          <span className={full ? 'whitespace-pre-wrap' : 'line-clamp-2'}>{task}</span>
        </div>
      )}
      <div ref={body} className={'scroll space-y-3 overflow-y-auto px-3.5 py-3 ' + (full ? '' : 'max-h-[440px]')}>
        {items.map((m) => {
          if (m.role === 'tool') return <ToolCard key={m.id} m={m} agent={agent} running={running} permit={permit} inDocker={inDocker} />
          const text = (m.content || '').replace(ACTION, '').replace(m.streaming ? /<(run|read|write|agent|mcp|mcp_add|fetch|lesson|remember|skill_\w+)\b[^]*$/ : /$^/, '').trim()
          return (
            <div key={m.id} className="space-y-2">
              {m.reasoning && (
                <details className="text-[12.5px] text-muted" open={m.streaming && !m.content}>
                  <summary className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-medium text-faint select-none hover:text-muted"><Icon name="brain" size={13} />{t('思考过程')}</summary>
                  <div className="mt-1.5 border-l-2 border-line pl-2.5 leading-relaxed whitespace-pre-wrap">{m.reasoning}</div>
                </details>
              )}
              {m.streaming && !m.content && !m.reasoning && <div className="space-y-2 py-1"><div className="skeleton h-3 w-40 max-w-full" /><div className="skeleton h-3 w-24" /></div>}
              {text && <Markdown text={text} className={'text-[14px] ' + (m.streaming ? 'caret' : '')} />}
              {m.error && <p className="rounded-lg bg-danger-soft px-2.5 py-2 text-[13px] text-danger">{m.error}</p>}
            </div>
          )
        })}
      </div>
    </motion.section>
  )
}

export default function TaskBoard({ items, byId, running, permit, inDocker, onEditAgent, onStopMember, onRetryMember }) {
  // 按成员分列，顺序跟领头人分派的顺序一致（谁先出现谁在前）
  const order = []
  const cols = {}
  for (const m of items) {
    if (!cols[m.agent_id]) { cols[m.agent_id] = []; order.push(m.agent_id) }
    cols[m.agent_id].push(m)
  }
  const states = order.map((id) => stateOf(cols[id], running))
  const done = states.filter((s) => s.tone === 'done').length
  const grid = order.length >= 3 ? 'md:grid-cols-2 xl:grid-cols-3' : 'md:grid-cols-2'
  return (
    <div className="rounded-[22px] border border-line/70 bg-sunken/50 p-2.5 md:p-3">
      <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 px-1">
        <span className="flex items-center gap-1.5 text-[13px] font-medium text-ink"><Icon name="parallel" size={15} className="text-accent" />{t('{n} 位成员同时进行', { n: order.length })}</span>
        <span className="text-xs text-muted">{done === order.length ? t('全部交付') : t('{done}/{n} 已交付', { done, n: order.length })}</span>
        <span className="flex -space-x-1.5">
          {order.map((id, i) => (
            <span key={id} className="relative" title={(byId[id]?.name || cols[id][0].agent_name) + ' · ' + states[i].text}>
              <Avatar agent={byId[id] || { name: cols[id][0].agent_name, color: 'slate' }} size={20} />
              <span className={'absolute -right-0.5 -bottom-0.5 h-2 w-2 rounded-full ring-2 ring-sunken ' + DOT[states[i].tone]} />
            </span>
          ))}
        </span>
      </div>
      <div className={'grid grid-cols-1 gap-2.5 ' + grid}>
        {order.map((id) => (
          <Column key={id} agent={byId[id]} name={byId[id]?.name || cols[id][0].agent_name} items={cols[id]} running={running}
            permit={permit} inDocker={inDocker} onEditAgent={onEditAgent} onStop={() => onStopMember?.(id)} onRetry={() => onRetryMember?.(id)} />
        ))}
      </div>
    </div>
  )
}
