// 右侧的成员面板：成员列表、点名、协作方式
import { Avatar, Icon, IconBtn } from '../../components/ui.jsx'
import { modeOf } from '../../components/ConvModal.jsx'
import { statusOf } from './cards.jsx'

export default function Members({ conv, agents, lead, messages, targets, toggleTarget, onAddAgent, onAddExternal, onEditAgent, onSettings, outside }) {
  const mode = modeOf(conv)
  const live = Object.fromEntries((messages || []).filter((m) => m.streaming).map((m) => [m.agent_id, statusOf(m)]))
  return (
    <aside className="hidden w-[272px] shrink-0 flex-col border-l border-line/60 bg-surface/70 backdrop-blur xl:flex">
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-line pr-2 pl-4">
        <span className="text-sm font-semibold text-ink">成员<span className="ml-2 font-mono text-xs font-normal text-faint">{agents.length}</span></span>
        <span className="flex">
          <IconBtn icon="link" label="接入外部智能体（Claude Code、OpenClaw 等）" onClick={onAddExternal} />
          <IconBtn icon="userPlus" label="在这个会话里新建智能体" onClick={onAddAgent} />
        </span>
      </div>
      <ul className="scroll flex-1 overflow-y-auto p-2">
        {agents.map((a) => {
          const on = targets.includes(a.id)
          const busy = live[a.id]
          return (
            <li key={a.id} className={'group/row flex items-center rounded-xl pr-1 transition-colors duration-150 ' + (on ? 'bg-accent-soft' : 'hover:bg-sunken')}>
              <button type="button" aria-pressed={on} title={on ? '取消点名' : '点名让它发言'} onClick={() => toggleTarget(a.id)} className="flex min-w-0 flex-1 items-center gap-2.5 rounded-xl p-2 text-left">
                <span className="relative shrink-0">
                  <Avatar agent={a} size={36} />
                  {busy && <span className="absolute -right-0.5 -bottom-0.5 h-3 w-3 animate-breathe rounded-full border-2 border-surface bg-accent" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-sm font-medium text-ink">{a.name}</span>
                    {lead?.id === a.id && <Icon name="crown" size={13} weight="fill" className="text-accent" />}
                    {a.auto_approve && <Icon name="shield" size={13} weight="fill" className="text-accent" />}
                  </span>
                  <span className={'block truncate text-xs ' + (busy ? 'text-accent-ink' : 'text-faint')}>{busy || a.description || a.model || '待命'}</span>
                </span>
              </button>
              <IconBtn icon="edit" label={`编辑${a.name}`} size={30} onClick={() => onEditAgent(a)} className="opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100" />
            </li>
          )
        })}
        {lead && outside.length > 0 && (
          <li className="mt-3 px-2 pb-1 text-xs leading-relaxed text-faint">{lead.name}可以随时拉进来</li>
        )}
        {lead && outside.map((a) => (
          <li key={a.id} className="flex items-center gap-2.5 rounded-xl p-2 opacity-60">
            <Avatar agent={a} size={28} />
            <span className="min-w-0 flex-1"><span className="block truncate text-[13px] text-ink">{a.name}</span><span className="block truncate text-xs text-faint">{a.description || '暂无简介'}</span></span>
          </li>
        ))}
      </ul>
      <div className="shrink-0 border-t border-line p-3.5">
        <div className="flex items-center gap-2 text-[13px] font-medium text-ink">
          <Icon name={mode.icon} size={16} className="text-accent-ink" />{agents.length > 1 || lead ? mode.name : '一对一'}
          <button type="button" onClick={onSettings} className="ml-auto rounded-md px-1.5 py-0.5 text-xs font-normal text-muted hover:bg-sunken hover:text-ink">调整</button>
        </div>
        <p className="mt-1.5 text-xs leading-relaxed text-muted">{lead ? `你只和${lead.name}对话，它负责安排其他智能体。` : agents.length > 1 ? mode.hint : '只有一个智能体时就是普通对话。'}</p>
      </div>
    </aside>
  )
}
