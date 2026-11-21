// 一条消息：用户 / 智能体气泡、思考过程、操作卡片、用量
import { memo } from 'react'
import { motion } from 'motion/react'
import Markdown from '../../components/Markdown.jsx'
import Attachments from '../../components/Attachments.jsx'
import { Avatar, Icon, Tag, hueOf } from '../../components/ui.jsx'
import { fmt } from '../../components/Usage.jsx'
import { ACTION, LessonChip, Live, MemoryChip, TeamCard, Tools, ToolCard, enter, statusOf } from './cards.jsx'


export const Message = memo(function Message({ m, agent, onDelete, byId, running, permit, inDocker, onEditAgent, onRetry, canRetry }) {
  if (m.role === 'notice') {
    return <motion.div {...enter} className="flex justify-center"><span className="rounded-full bg-line/70 px-3 py-1 text-xs text-muted">{m.content}</span></motion.div>
  }
  if (m.role === 'tool' && (m.action.kind === 'hire' || m.action.kind === 'fire')) return <TeamCard m={m} agent={agent} running={running} permit={permit} />
  if (m.role === 'tool') return <ToolCard m={m} agent={agent} running={running} permit={permit} inDocker={inDocker} />
  if (m.role === 'user') {
    return (
      <motion.div {...enter} className="group flex justify-end gap-1">
        <Tools m={m} onDelete={onDelete} />
        <div className="flex max-w-[82%] flex-col items-end gap-1.5 md:max-w-[68%]">
          <Attachments conv={m.conv_id} items={m.attachments} />
          {m.content && <div className="rounded-[20px] rounded-tr-md bg-gradient-to-br from-accent to-accent-strong px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-on-accent shadow-[0_6px_18px_-10px_var(--accent)] [overflow-wrap:anywhere]">{m.content}</div>}
        </div>
      </motion.div>
    )
  }
  const who = agent || { name: m.agent_name, color: 'slate' }
  const waiting = m.streaming && !m.content && !m.reasoning
  // 操作标签不显示在气泡里（下面有对应的操作卡片）；生成途中尚未写完的标签也先藏起来
  const text = (m.content || '').replace(ACTION, '').replace(m.streaming ? /<(run|read|write|agent|mcp|mcp_add|fetch|lesson|remember|skill_\w+)\b[^]*$/ : /$^/, '').trim()
  return (
    <motion.div {...enter} className="group flex gap-2.5 md:gap-3" style={{ '--h': hueOf(who) }}>
      <Avatar agent={who} size={36} />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex h-5 items-center gap-2">
          <span className="name-hue truncate text-[13px] font-medium">{m.agent_name || who.name}</span>
          {m.lead && <Tag tone="accent"><Icon name="crown" size={11} weight="fill" />领头</Tag>}
          {m.model && <span className="hidden truncate font-mono text-[11px] text-faint sm:inline">{m.model}</span>}
          {m.tokens_in > 0 && !m.streaming && (
            <span title={`输入 ${m.tokens_in} · 输出 ${m.tokens_out || 0}${m.tokens_cached ? ` · 命中缓存 ${m.tokens_cached}` : ''}${m.tokens_saved ? ` · 省下 ${m.tokens_saved}` : ''}${m.tokens_est === false ? '（接口返回的真实用量）' : '（估算）'}`}
              className="hidden font-mono text-[11px] text-faint/80 sm:inline">{m.tokens_est === false ? '' : '≈'}{fmt(m.tokens_in)}↑ {fmt(m.tokens_out)}↓</span>
          )}
          {m.streaming && <Live since={m.created}>{statusOf(m)}</Live>}
        </div>
        <div className="flex items-end gap-1">
          <div className="max-w-[min(680px,100%)] min-w-0 rounded-[20px] rounded-tl-md bg-surface px-4 py-3 shadow-[0_1px_2px_rgb(var(--shadow)/0.04),0_8px_24px_-14px_rgb(var(--shadow)/0.18)]">
            {m.task && (
              <div className="mb-2.5 flex items-start gap-2 rounded-lg bg-sunken px-2.5 py-2 text-[13px] leading-relaxed text-muted">
                <Icon name="branch" size={15} className="mt-0.5 text-faint" />
                <span className="line-clamp-3 min-w-0 whitespace-pre-wrap"><b className="mr-1.5 font-medium text-ink">受派任务</b>{m.task}</span>
              </div>
            )}
            {m.reasoning && (
              <details className="mb-2 text-[13px] text-muted" open={m.streaming && !m.content}>
                <summary className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-medium text-faint select-none hover:text-muted"><Icon name="brain" size={14} />思考过程</summary>
                <div className="mt-1.5 border-l-2 border-line pl-3 leading-relaxed whitespace-pre-wrap">{m.reasoning}</div>
              </details>
            )}
            {waiting && <div className="space-y-2 py-1" aria-label="等待模型响应"><div className="skeleton h-3 w-52 max-w-full" /><div className="skeleton h-3 w-32" /></div>}
            {text && <Markdown text={text} className={'text-[15px] ' + (m.streaming ? 'caret' : '')} />}
            {m.hired?.length > 0 && (
              <div className="mt-3 overflow-hidden rounded-xl border border-line">
                <div className="flex items-center gap-2 bg-sunken px-3 py-1.5 text-xs font-medium text-muted"><Icon name="userPlus" size={14} />新建了 {m.hired.length} 个智能体</div>
                <ul className="divide-y divide-line">
                  {m.hired.map((a) => {
                    const made = byId?.[a.agent_id]
                    return (
                      <li key={a.agent_id} className="flex items-center gap-2.5 px-3 py-2 text-[13px] leading-relaxed">
                        <Avatar agent={made || { name: a.name, color: 'slate' }} size={26} />
                        <span className="min-w-0 flex-1"><b className="font-medium text-ink">{a.name}</b><span className="ml-2 text-muted">{a.description || '没有写简介'}</span></span>
                        {made
                          ? <button type="button" onClick={() => onEditAgent(made)} className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-accent-ink hover:bg-accent-soft">查看设定</button>
                          : <span className="shrink-0 text-xs text-faint">已删除</span>}
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
            {m.assignments?.length > 0 && (
              <div className="mt-3 overflow-hidden rounded-xl border border-line">
                <div className="flex items-center gap-2 bg-sunken px-3 py-1.5 text-xs font-medium text-muted"><Icon name="lead" size={14} />已分派给 {m.assignments.length} 位成员</div>
                <ul className="divide-y divide-line">
                  {m.assignments.map((a) => (
                    <li key={a.agent_id} className="flex items-start gap-2.5 px-3 py-2 text-[13px] leading-relaxed">
                      <Avatar agent={byId?.[a.agent_id] || { name: a.name, color: 'slate' }} size={22} className="mt-px" />
                      <span className="min-w-0"><b className="font-medium text-ink">{a.name}</b><span className="ml-2 whitespace-pre-wrap text-muted">{a.task}</span></span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {m.lessons?.length > 0 && m.lessons.map((l) => <LessonChip key={l.id || l} lesson={l} />)}
            {m.memories?.length > 0 && m.memories.map((x) => <MemoryChip key={x.id} memory={x} />)}
            {m.truncated && !m.streaming && <p className="mt-2 text-xs text-faint">回复因长度上限被截断。输入框留空点「继续」可以让它接着说。</p>}
            {m.error && (
              <div role="alert" className={'flex items-start gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-[13px] leading-relaxed text-danger [overflow-wrap:anywhere] ' + (text ? 'mt-2.5' : '')}>
                <Icon name="warn" size={16} weight="fill" className="mt-0.5" /><span className="min-w-0 flex-1">{m.error}</span>
                {onRetry && agent && !running && canRetry && (
                  <button type="button" onClick={() => onRetry(m)} className="shrink-0 rounded-md bg-surface px-2 py-0.5 text-xs font-medium text-ink shadow-xs hover:bg-sunken">重新回答</button>
                )}
              </div>
            )}
          </div>
          <Tools m={m} onDelete={onDelete} onRetry={canRetry && agent && !running && onRetry ? () => onRetry(m) : null} />
        </div>
      </div>
    </motion.div>
  )
})

// 右侧成员面板
