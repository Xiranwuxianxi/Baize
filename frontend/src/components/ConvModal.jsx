import { ask } from './Dialog.jsx'
import { useState } from 'react'
import { api } from '../lib/api'
import { Avatar, Btn, Field, Icon, IconBtn, Modal, Tag, inputCls } from './ui.jsx'
import { ConvUsage } from './Usage.jsx'

export const MODES = [
  { id: 'sequential', icon: 'relay', name: '接力发言', hint: '按顺序依次发言，后面的能看到前面的回答。适合讨论、流水线协作。' },
  { id: 'parallel', icon: 'parallel', name: '并行作答', hint: '所有人同时回答，互相看不到。适合对比不同模型或角色。' },
  { id: 'lead', icon: 'lead', name: '领头统筹', hint: '你只和领头人说话，它把任务分派给成员、审阅后再答复你。' },
]
export const modeOf = (c) => MODES.find((m) => m.id === c.mode) || MODES[0]

function Stepper({ value, min, max, onChange }) {
  return (
    <span className="inline-flex items-center overflow-hidden rounded-xl border border-line bg-raised">
      <button type="button" disabled={value <= min} onClick={() => onChange(value - 1)} className="h-9 w-9 text-lg text-muted hover:bg-sunken disabled:opacity-40" aria-label="减少">−</button>
      <span className="w-9 text-center font-mono text-sm font-semibold text-ink">{value}</span>
      <button type="button" disabled={value >= max} onClick={() => onChange(value + 1)} className="h-9 w-9 text-lg text-muted hover:bg-sunken disabled:opacity-40" aria-label="增加">+</button>
    </span>
  )
}

function Section({ title, extra, children }) {
  return (
    <section>
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <h3 className="text-[13px] font-semibold text-ink">{title}</h3>
        {extra}
      </div>
      {children}
    </section>
  )
}

// 新建会话 / 会话设置 共用
export default function ConvModal({ data, initial, onClose, onSaved, onDeleted, notify, reload, onAddAgent, onEditAgent }) {
  const editing = !!initial?.id
  const [f, setF] = useState(() => ({ title: '', agent_ids: [], mode: 'sequential', lead_id: '', rounds: 1, context_limit: 40, folders: [], ...initial }))
  const [tab, setTab] = useState('members')
  const [busy, setBusy] = useState(false)
  const [folder, setFolder] = useState('')
  const pool = data.agents.filter((a) => !a.conv_id || a.conv_id === f.id)
  const chosen = f.agent_ids.map((id) => pool.find((a) => a.id === id)).filter(Boolean)
  const rest = pool.filter((a) => !f.agent_ids.includes(a.id))
  const leadId = f.agent_ids.includes(f.lead_id) ? f.lead_id : f.agent_ids[0]
  const multi = chosen.length > 1
  const local = data.env?.local || {}

  const set = (patch) => setF((s) => ({ ...s, ...patch }))
  const add = (id) => set({ agent_ids: [...f.agent_ids, id] })
  const drop = (id) => set({ agent_ids: f.agent_ids.filter((x) => x !== id) })
  const move = (i, d) => {
    const ids = [...f.agent_ids]
    ;[ids[i], ids[i + d]] = [ids[i + d], ids[i]]
    set({ agent_ids: ids })
  }

  const save = async () => {
    if (!f.agent_ids.length) { setTab('members'); return notify('至少选择一个智能体') }
    setBusy(true)
    try {
      const body = { ...f, lead_id: leadId }
      onSaved(await (editing ? api('PUT', '/conversations/' + f.id, body) : api('POST', '/conversations', body)))
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }
  const promote = async (a) => { try { await api('POST', `/agents/${a.id}/promote`); await reload(); notify(`「${a.name}」已加入全局`) } catch (e) { notify(e.message) } }
  const clear = async () => {
    if (!await ask('清空这个会话的全部消息？此操作无法撤销。')) return
    await api('DELETE', `/conversations/${f.id}/messages`).catch((e) => notify(e.message))
    onSaved(initial, true)
  }
  const remove = async () => {
    const n = pool.filter((a) => a.conv_id).length
    if (!await ask(`删除会话「${initial.title}」及其全部消息？${n ? `只属于它的 ${n} 个智能体也会一并删除。` : ''}此操作无法撤销。`)) return
    await api('DELETE', '/conversations/' + f.id).catch((e) => notify(e.message))
    onDeleted()
  }

  const TABS = [['members', '成员', chosen.length], ['mode', '协作方式'], ...(editing ? [['access', '权限与文件'], ['usage', '用量'], ['more', '更多']] : [])]

  return (
    <Modal wide title={editing ? '会话设置' : '新建会话'} onClose={onClose}
      footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn kind="primary" disabled={busy} onClick={save}>{editing ? '保存' : '开始会话'}</Btn></>}>
      <input className="-mt-2 w-full border-b border-line bg-transparent pb-2.5 text-lg font-semibold tracking-tight text-ink outline-none placeholder:font-normal placeholder:text-faint focus:border-accent"
        value={f.title} onChange={(e) => set({ title: e.target.value })} placeholder="会话标题（留空则用第一条消息命名）" maxLength={60} aria-label="会话标题" />

      <div className="flex gap-1 rounded-xl bg-sunken p-1" role="tablist">
        {TABS.map(([id, name, n]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={'flex flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 text-[13px] transition-colors duration-150 ' + (tab === id ? 'bg-surface font-medium text-ink shadow-xs' : 'text-muted hover:text-ink')}>
            {name}{n != null && <span className="font-mono text-xs text-faint">{n}</span>}
          </button>
        ))}
      </div>

      {tab === 'members' && (
        <>
          <Section title="已在会话里" extra={<span className="text-xs text-faint">{multi && f.mode !== 'parallel' ? '按这个顺序发言' : ''}</span>}>
            {chosen.length === 0 ? (
              <p className="rounded-xl border border-dashed border-line-strong px-4 py-4 text-[13px] text-faint">从下面点选要加入的智能体。</p>
            ) : (
              <ul className="space-y-1.5">
                {chosen.map((a, i) => (
                  <li key={a.id} className="flex items-center gap-3 rounded-xl border border-line bg-raised py-1.5 pr-1.5 pl-2.5">
                    <span className="w-4 text-center font-mono text-xs text-faint">{i + 1}</span>
                    <Avatar agent={a} size={32} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-sm font-medium text-ink">{a.name}</span>
                        {f.mode === 'lead' && multi && a.id === leadId && <Tag tone="accent"><Icon name="crown" size={11} weight="fill" />领头</Tag>}
                        {a.conv_id && <Tag>仅本会话</Tag>}
                      </span>
                      <span className="block truncate text-xs text-muted">{a.description || a.model || '暂无简介'}</span>
                    </span>
                    {a.conv_id && editing && <button type="button" onClick={() => promote(a)} className="hidden shrink-0 rounded-md px-2 py-1 text-xs text-accent-ink hover:bg-accent-soft sm:block">加入全局</button>}
                    {a.conv_id && editing && <IconBtn icon="edit" label="编辑" size={30} onClick={() => onEditAgent(initial, a)} />}
                    <IconBtn icon="up" label="往前" size={30} disabled={i === 0} onClick={() => move(i, -1)} />
                    <IconBtn icon="up" label="往后" size={30} disabled={i === chosen.length - 1} onClick={() => move(i, 1)} className="[&_svg]:rotate-180" />
                    <IconBtn icon="x" label="移出会话" kind="danger" size={30} onClick={() => drop(a.id)} />
                  </li>
                ))}
              </ul>
            )}
          </Section>
          <Section title="添加成员" extra={editing && <button type="button" onClick={() => onAddAgent(initial)} className="inline-flex items-center gap-1 text-xs font-medium text-accent-ink hover:underline"><Icon name="plus" size={12} weight="bold" />新建一个</button>}>
            {rest.length === 0 ? <p className="text-[13px] text-faint">{pool.length ? '所有智能体都已加入。' : '还没有智能体，先到「智能体」页创建。'}</p> : (
              <div className="flex flex-wrap gap-1.5">
                {rest.map((a) => (
                  <button key={a.id} type="button" onClick={() => add(a.id)} title={a.description || ''}
                    className="inline-flex items-center gap-2 rounded-full border border-line bg-raised py-1 pr-3 pl-1 text-[13px] text-muted transition-colors duration-150 hover:border-accent hover:text-ink active:scale-[0.98]">
                    <Avatar agent={a} size={24} />{a.name}<Icon name="plus" size={12} weight="bold" className="text-faint" />
                  </button>
                ))}
              </div>
            )}
          </Section>
        </>
      )}

      {tab === 'mode' && (
        !multi ? (
          <p className="rounded-xl bg-sunken px-4 py-4 text-[13px] leading-relaxed text-muted">只有一个成员时就是普通的一对一对话。加入两个以上的成员后，可以选择它们的协作方式。</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-1 rounded-xl bg-sunken p-1">
              {MODES.map((m) => (
                <button key={m.id} type="button" aria-pressed={f.mode === m.id} onClick={() => set({ mode: m.id, rounds: m.id === 'lead' ? Math.max(f.rounds, 2) : f.rounds })}
                  className={'flex items-center justify-center gap-1.5 rounded-lg py-2 text-[13px] transition-colors duration-150 ' + (f.mode === m.id ? 'bg-surface font-medium text-accent-ink shadow-xs' : 'text-muted hover:text-ink')}>
                  <Icon name={m.icon} size={16} weight={f.mode === m.id ? 'fill' : 'regular'} />{m.name}
                </button>
              ))}
            </div>
            <p className="-mt-2 text-[13px] leading-relaxed text-muted">{modeOf(f).hint}</p>
            {f.mode === 'lead' && (
              <Section title="谁来领头">
                <div className="flex flex-wrap gap-1.5">
                  {chosen.map((a) => (
                    <button key={a.id} type="button" aria-pressed={a.id === leadId} onClick={() => set({ lead_id: a.id })}
                      className={'inline-flex items-center gap-2 rounded-full border py-1 pr-3 pl-1 text-[13px] transition-colors duration-150 ' + (a.id === leadId ? 'border-accent bg-accent-soft font-medium text-accent-ink' : 'border-line bg-raised text-muted hover:border-line-strong')}>
                      <Avatar agent={a} size={24} />{a.name}{a.id === leadId && <Icon name="crown" size={13} weight="fill" />}
                    </button>
                  ))}
                </div>
              </Section>
            )}
            {f.mode === 'lead' && (
              <div>
                <div className="mb-2 text-[13px] font-medium text-ink">分派出去的任务</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {[[true, '同时进行', '成员各自开工、各自交付，全部完成后领头人统一审阅。快，适合互不依赖的任务。'],
                    [false, '一个接一个', '前一个做完下一个再做，后面的能看到前面的结果。适合环环相扣的任务。']].map(([v, name, hint]) => (
                    <button key={name} type="button" aria-pressed={(f.lead_parallel !== false) === v} onClick={() => set({ lead_parallel: v })}
                      className={'rounded-xl border p-3 text-left transition-colors duration-150 ' + ((f.lead_parallel !== false) === v ? 'border-accent bg-accent-soft' : 'border-line bg-raised hover:border-line-strong')}>
                      <span className="block text-sm font-medium text-ink">{name}</span>
                      <span className="mt-1 block text-xs leading-relaxed text-muted">{hint}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="flex items-center justify-between gap-4 rounded-xl border border-line bg-raised p-3.5">
              <div className="min-w-0">
                <div className="text-sm font-medium text-ink">{f.mode === 'lead' ? '领头人最多分派几轮' : '每次发送后自动讨论几轮'}</div>
                <div className="mt-0.5 text-xs leading-relaxed text-muted">{f.mode === 'lead' ? '每轮：分派、执行、审阅。到上限后必须给出最终答复。' : '大于 1 时，大家会在你发言后继续讨论，随时可以停止。'}</div>
              </div>
              <Stepper value={f.rounds} min={1} max={6} onChange={(v) => set({ rounds: v })} />
            </div>
          </>
        )
      )}

      {tab === 'access' && (
        <>
          {!local.enabled ? (
            <p className="rounded-xl bg-sunken px-4 py-4 text-[13px] leading-relaxed text-muted">本地操作没有开启，智能体不会动这台电脑。可以在会话顶部或「设置」里打开。</p>
          ) : (
            <>
              <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-line bg-raised p-3.5">
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-ink">本会话的操作不再逐条询问</span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted">只在你信任当前任务时打开。</span>
                </span>
                <input type="checkbox" checked={!!f.auto_approve} onChange={(e) => set({ auto_approve: e.target.checked })} className="h-5 w-5 shrink-0 accent-[var(--accent)]" />
              </label>
              {f.approve_left > 0 && (
                <div className="flex items-center gap-3 rounded-xl border border-line bg-raised p-3.5 text-sm">
                  <span className="min-w-0 flex-1 text-ink">还可以免询问操作 <b className="font-mono text-accent-ink">{f.approve_left}</b> 次</span>
                  <Btn kind="ghost" onClick={() => set({ approve_left: 0 })} className="h-8 px-2.5 text-[13px]">收回</Btn>
                </div>
              )}
              <Section title="额外允许操作的文件夹">
                <p className="mb-2 text-xs leading-relaxed text-muted">会话的文件默认都在工作区下它自己的文件夹里。需要它动别的地方时在这里加上。</p>
                {(f.folders || []).length > 0 && (
                  <ul className="mb-2 space-y-1.5">
                    {f.folders.map((p) => (
                      <li key={p} className="flex items-center gap-2 rounded-lg border border-line bg-raised px-3 py-2 text-xs">
                        <Icon name="folder" size={14} className="text-faint" />
                        <span className="min-w-0 flex-1 font-mono text-ink [overflow-wrap:anywhere]">{p}</span>
                        <button type="button" onClick={() => set({ folders: f.folders.filter((x) => x !== p) })} className="shrink-0 text-muted hover:text-danger">移除</button>
                      </li>
                    ))}
                  </ul>
                )}
                <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (folder.trim()) { set({ folders: [...(f.folders || []), folder.trim()] }); setFolder('') } }}>
                  <input className={inputCls + ' min-w-0 flex-1 font-mono text-sm'} value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="D:\Projects\my-app" spellCheck={false} />
                  <Btn type="submit" disabled={!folder.trim()}>添加</Btn>
                </form>
              </Section>
            </>
          )}
        </>
      )}

      {tab === 'usage' && <ConvUsage convId={initial.id} />}

      {tab === 'more' && (
        <>
          <Field label="上下文消息数" hint="每次请求带上最近多少条消息。越大越耗 Token、越慢。">
            <input className={inputCls} type="number" min="2" max="400" value={f.context_limit} onChange={(e) => set({ context_limit: e.target.value })} />
          </Field>
          <div className="rounded-xl border border-danger-soft p-3.5">
            <div className="mb-2.5 text-sm font-medium text-danger">危险操作</div>
            <div className="flex flex-wrap gap-2">
              <Btn onClick={clear}>清空消息</Btn>
              <Btn kind="danger" icon="trash" onClick={remove}>删除会话</Btn>
            </div>
          </div>
        </>
      )}
    </Modal>
  )
}
