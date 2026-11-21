import { ask } from '../components/Dialog.jsx'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { api } from '../lib/api'
import { uploadAttachment } from '../lib/attach'
import { modeOf } from '../components/ConvModal.jsx'
import { Avatar, Icon, IconBtn } from '../components/ui.jsx'
import Composer from './chat/Composer.jsx'
import Members from './chat/Members.jsx'
import { Message } from './chat/Message.jsx'
import TaskBoard from './chat/TaskBoard.jsx'
import { t } from '../lib/i18n'
import { enter } from './chat/cards.jsx'

const STARTERS = {
  lead: ['帮我把「上线一个新功能」拆成任务并安排下去', '找合适的人一起评估：做一款给大学生的记账应用', '你手下有哪些专业智能体？分别擅长什么？'],
  multi: ['大家先各自介绍一下自己的专长', '围绕「远程办公是否更高效」展开讨论', '各自用一句话评价：每周四天工作制'],
  single: ['介绍一下你自己，以及你擅长什么', '帮我把一个模糊的想法整理成计划', '用三句话解释一个你熟悉的概念'],
}
// 同一批并行分派的消息合成一个看板，放在这批第一次出现的位置；其余消息照常一条条显示
// 屏外消息跳过渲染（长会话在手机上不卡）；auto 记住上次高度，滚动条保持稳定
const VIRTUAL = '[content-visibility:auto] [contain-intrinsic-size:auto_160px]'
function withBoards(messages) {
  const out = []
  const boards = {}
  for (const m of messages) {
    if (!m.batch) { out.push({ m }); continue }
    if (!boards[m.batch]) { boards[m.batch] = { board: m.batch, items: [] }; out.push(boards[m.batch]) }
    boards[m.batch].items.push(m)
  }
  return out
}

export default function Chat({ data, conv, messages, running, online, send, retry, stop, member, permit, reloadMessages, notify, onBack, onSettings, onAddAgent, onAddExternal, onEditAgent, onOpenSettings, reload }) {
  const [text, setText] = useState('')
  const [targets, setTargets] = useState([])
  const boxRef = useRef(null)
  const [renaming, setRenaming] = useState(null) // 双击标题后正在编辑的文字
  const saveTitle = async () => {
    const t = (renaming || '').trim()
    setRenaming(null)
    if (!t || t === conv.title) return
    try {
      await api('PUT', '/conversations/' + conv.id, { ...conv, title: t })
      reload()
    } catch (e) {
      notify(e.message)
    }
  }
  const [exporting, setExporting] = useState(false)
  // 导出在浏览器里完成；生成网页要用到服务端渲染，按需加载，不拖慢首屏
  const exportAs = async (format) => {
    setExporting(false)
    try {
      const { exportConversation } = await import('../lib/exportConv.jsx')
      exportConversation(conv, messages, agents, format)
    } catch (e) {
      notify(e.message)
    }
  }
  const [away, setAway] = useState(false) // 离开底部一段距离时显示「回到底部」
  // 服务重启时被打断的会话：提示一下，一键接着做
  const [resumed, setResumed] = useState({})
  const interrupted = (data.interrupted || []).includes(conv.id) && !resumed[conv.id] && !running
  const resume = () => { if (send(conv.id, '', [])) { setResumed((r) => ({ ...r, [conv.id]: true })); stick.current = true } }
  const dismissResume = () => { setResumed((r) => ({ ...r, [conv.id]: true })); api('POST', `/conversations/${conv.id}/interrupted/dismiss`).catch(() => {}) }
  const toBottom = () => {
    const el = boxRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    stick.current = true
  }
  // 重新生成：后端会删掉这条回复及其之后的消息，让同一个智能体重答（只有最后一条回复能这么做）
  const regenerate = (m) => {
    if (retry(conv.id, m.id)) stick.current = true
  }
  const inputRef = useRef(null)
  const stick = useRef(true)
  const agents = conv.agent_ids.map((id) => data.agents.find((a) => a.id === id)).filter(Boolean)
  const byId = Object.fromEntries(data.agents.map((a) => [a.id, a]))
  const local = data.env?.local || {}

  // 待发送的附件：选好就开始上传，发送时只带上传成功的
  const [files, setFiles] = useState([])
  const addFiles = (list) => {
    const room = 10 - files.length
    if (room <= 0) return notify(t('一条消息最多带 10 个附件'))
    for (const file of list.slice(0, room)) {
      const id = Math.random().toString(36).slice(2)
      setFiles((fs) => [...fs, { id, name: file.name || 'image.png', kind: file.type.startsWith('image/') ? 'image' : 'file', busy: true }])
      uploadAttachment(conv.id, file)
        .then((info) => setFiles((fs) => fs.map((f) => (f.id === id ? { ...f, busy: false, info } : f))))
        .catch((e) => { notify(e.message); setFiles((fs) => fs.map((f) => (f.id === id ? { ...f, busy: false, error: true } : f))) })
    }
  }
  const removeFile = (id) => setFiles((fs) => fs.filter((f) => f.id !== id))
  useEffect(() => { setTargets([]); setFiles([]); stick.current = true }, [conv.id])
  useLayoutEffect(() => {
    const el = boxRef.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [messages])

  // 文字里 @ 到的成员也算点名，和下面的点名按钮合并
  const mentioned = () => agents.filter((a) => text.includes('@' + a.name)).map((a) => a.id)
  const submit = () => {
    if (running) return
    const ids = [...new Set([...targets, ...mentioned()])].filter((id) => conv.agent_ids.includes(id))
    if (files.some((f) => f.busy)) { notify(t('附件还在上传，请稍等')); return false }
    const ok = send(conv.id, text, ids, files.filter((f) => f.info).map((f) => f.info))
    if (ok) { setText(''); setTargets([]); setFiles([]); stick.current = true }
    return ok
  }
  const remove = async (m) => {
    await api('DELETE', '/messages/' + m.id).catch((e) => notify(e.message))
    reloadMessages(conv.id)
  }
  const toggleTarget = (id) => setTargets((t) => (t.includes(id) ? t.filter((x) => x !== id) : [...t, id]))

  const multi = agents.length > 1
  const lastId = (messages || []).reduce((id, m) => (m.role === 'agent' ? m.id : id), null) // 最后一条智能体回复：只有它能「重新生成」
  const lead = conv.mode === 'lead' ? agents.find((a) => a.id === conv.lead_id) : null
  const outside = lead ? data.agents.filter((a) => !a.conv_id && !conv.agent_ids.includes(a.id)) : []
  const mode = modeOf(conv)
  const operators = agents.filter((a) => !a.no_tools)
  // 会话顶部的本地操作状态：关着的时候可以在这里直接开，不用离开对话
  const enableLocal = async () => {
    if (!local.can_admin) return onOpenSettings()
    if (!await ask('开启本地操作？\n\n开启后，智能体可以请求在' + (local.in_docker ? ' Docker 容器内' : '这台电脑上') + '执行命令、读写文件。每个操作仍会先弹出卡片让你决定。\n\n工作区：' + local.workspace)) return
    try {
      const view = await api('PUT', '/settings', { local: { enabled: true } })
      await reload()
      if (view.local.usable) notify('已开启本地操作。再发一次消息，智能体就可以提出操作请求了')
      else { notify(view.local.reason); onOpenSettings() }
    } catch (e) {
      notify(e.message)
    }
  }
  const allAuto = local.approval === 'auto' || conv.auto_approve || (operators.length > 0 && operators.every((a) => a.auto_approve))
  const localChip = !local.enabled
    ? { label: '本地操作：关', title: '智能体现在不能操作这台电脑。点击开启', act: enableLocal }
    : !local.usable
    ? { label: '本地操作未生效', title: local.reason, act: onOpenSettings }
    : {
        label: (local.in_docker ? '容器内操作' : '可操作本机') + (allAuto ? ' · 免询问' : conv.approve_left > 0 ? ` · 还可免问 ${conv.approve_left} 次` : ''),
        title: `智能体可以在征得你同意后操作${local.in_docker ? '容器内环境' : '这台电脑'}。工作区：${local.workspace}。点击打开设置`,
        act: onOpenSettings,
      }
  const empty = !text.trim() && !files.some((f) => f.info)
  const canNudge = empty && (messages?.length > 0 || targets.length > 0)
  const blocked = !online ? '连接已断开，正在重连' : !agents.length ? '先为这个会话添加智能体' : empty && !canNudge ? '输入消息后发送' : ''
  const sendLabel = !empty ? '发送' : lead && !targets.length ? `不发言，让${lead.name}继续` : multi && !targets.length ? '不发言，让智能体继续讨论' : '不发言，让智能体直接开口'
  const starters = STARTERS[lead ? 'lead' : multi ? 'multi' : 'single']
  const first = lead || agents[0]

  return (
    <div className="flex min-h-0 flex-1">
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-1 border-b border-line/60 bg-surface/80 pr-2 pl-1 backdrop-blur md:pl-6">
          <IconBtn icon="back" label="返回会话列表" size={40} onClick={onBack} className="md:hidden" />
          <div className="min-w-0 flex-1">
            {renaming != null ? (
              <form onSubmit={(e) => { e.preventDefault(); saveTitle() }}>
                <input autoFocus value={renaming} onChange={(e) => setRenaming(e.target.value)} onBlur={saveTitle}
                  onKeyDown={(e) => e.key === 'Escape' && setRenaming(null)} maxLength={60} aria-label="会话标题"
                  className="w-full max-w-md rounded-md bg-sunken px-1.5 py-0.5 text-[15px] font-semibold text-ink outline-2 outline-accent md:text-base" />
              </form>
            ) : (
              <h1 onDoubleClick={() => setRenaming(conv.title)} title="双击修改标题" className="cursor-text truncate text-[15px] font-semibold text-ink md:text-base">{conv.title}</h1>
            )}
            <p className="truncate text-xs text-muted">
              {lead ? `${lead.name}领头` + (multi ? ` · ${agents.length - 1} 位成员` : outside.length ? ` · 可调度 ${outside.length} 个智能体` : '') : multi ? `${agents.length} 个智能体 · ${mode.name}` : agents[0]?.description || agents[0]?.model || '还没有智能体'}
            </p>
          </div>
          {agents.length > 0 && (
            <button
              type="button"
              onClick={localChip.act}
              title={localChip.title}
              className={'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2 text-xs font-medium transition-colors duration-150 active:scale-[0.98] sm:px-2.5 ' + (local.usable ? 'bg-accent-soft text-accent-ink hover:brightness-95' : 'bg-sunken text-muted hover:text-ink')}
            >
              <Icon name="terminal" size={15} />
              <span className="hidden sm:inline">{localChip.label}</span>
            </button>
          )}
          <IconBtn icon="link" label="接入外部智能体" size={40} onClick={onAddExternal} className="xl:hidden" />
          <IconBtn icon="userPlus" label="在这个会话里新建智能体" size={40} onClick={onAddAgent} className="xl:hidden" />
          {messages?.length > 0 && (
            <div className="relative">
              <IconBtn icon="download" label={t('导出这个会话')} size={40} onClick={() => setExporting((v) => !v)} />
              {exporting && (
                <>
                  <div className="fixed inset-0 z-20" onClick={() => setExporting(false)} />
                  <div role="menu" className="absolute right-0 top-11 z-30 w-52 rounded-xl border border-line bg-surface p-1 shadow-float">
                    {[['md', 'Markdown 文件', '贴进笔记、文档'], ['html', '网页文件', '直接打开、发给别人看']].map(([f, name, hint]) => (
                      <button key={f} type="button" role="menuitem" onClick={() => exportAs(f)} className="flex w-full flex-col rounded-lg px-3 py-2 text-left hover:bg-sunken">
                        <span className="text-sm font-medium text-ink">{t(name)}</span>
                        <span className="text-xs text-muted">{t(hint)}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
          <IconBtn icon="sliders" label="会话设置" size={40} onClick={onSettings} />
        </header>

        <div ref={boxRef} onScroll={(e) => { const el = e.currentTarget; const gap = el.scrollHeight - el.scrollTop - el.clientHeight; stick.current = gap < 80; setAway(gap > 240) }} className="dots scroll flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1180px] space-y-6 px-3 py-6 md:px-8 md:py-8">
            {messages == null ? (
              <div className="space-y-3 py-6" aria-label="正在读取聊天记录"><div className="skeleton h-9 w-2/3 rounded-2xl" /><div className="skeleton ml-auto h-9 w-1/3 rounded-2xl" /><div className="skeleton h-9 w-1/2 rounded-2xl" /></div>
            ) : messages.length === 0 ? (
              <motion.div {...enter} className="flex flex-col items-center px-2 pt-[8vh] text-center">
                {first && <Avatar agent={first} size={64} />}
                <h2 className="mt-5 text-xl font-semibold tracking-tight text-ink">{lead ? `我是${lead.name}，有事交给我` : multi ? `${agents.length} 个智能体已就位` : first ? `和${first.name}聊点什么` : '这个会话还没有智能体'}</h2>
                <p className="mt-2 max-w-[42ch] text-sm leading-relaxed text-muted">
                  {lead
                    ? outside.length || multi ? '说出你要做的事。我能自己办的直接办，需要专业能力时会把合适的智能体拉进来一起做。' : '说出你要做的事。目前还没有其他智能体可调度，可以到「智能体」页多建几个。'
                    : multi ? `发一条消息，它们会以「${mode.name}」的方式回应。也可以点名，只让指定的智能体发言。` : first?.description || '在下方输入消息开始对话。'}
                </p>
                {first && (
                  <div className="mt-6 flex w-full max-w-[460px] flex-col gap-2">
                    {starters.map((s) => (
                      <button key={s} type="button" onClick={() => { setText(s); inputRef.current?.focus() }} className="group/s flex items-center gap-3 rounded-xl border border-line bg-surface px-3.5 py-2.5 text-left text-sm text-muted transition-colors duration-150 hover:border-accent hover:text-ink active:scale-[0.99]">
                        <span className="min-w-0 flex-1">{s}</span>
                        <Icon name="arrow" size={15} className="text-faint transition-transform duration-200 group-hover/s:translate-x-0.5 group-hover/s:text-accent" />
                      </button>
                    ))}
                  </div>
                )}
              </motion.div>
            ) : (
              withBoards(messages).map((it) => it.board
                ? <div key={'board-' + it.board} className={VIRTUAL}><TaskBoard items={it.items} byId={byId} running={running} permit={permit} inDocker={local.in_docker} onEditAgent={onEditAgent}
                  onStopMember={(id) => member?.stop(conv.id, id)} onRetryMember={(id) => member?.retry(conv.id, id, it.board)} /></div>
                : <div key={it.m.id} className={'mx-auto max-w-[820px] ' + VIRTUAL}><Message m={it.m} agent={byId[it.m.agent_id]} byId={byId} onDelete={remove} running={running} permit={permit} inDocker={local.in_docker} onEditAgent={onEditAgent} onRetry={regenerate} canRetry={it.m.id === lastId} /></div>)
            )}
          </div>
        </div>
        {away && (
          <div className="pointer-events-none relative z-10 h-0">
            <button
              type="button" onClick={toBottom} aria-label="回到最新消息"
              className="pointer-events-auto absolute right-5 -top-14 flex h-10 items-center gap-1.5 rounded-full border border-line bg-surface px-3.5 text-[13px] font-medium text-ink shadow-float transition-transform duration-150 hover:-translate-y-0.5 active:scale-95 md:right-8"
            >
              <Icon name="up" size={16} weight="bold" className="rotate-180" />{running ? '最新消息' : '回到底部'}
            </button>
          </div>
        )}

        {interrupted && (
          <div className="mx-auto mb-1 flex w-full max-w-[820px] items-center gap-3 px-3 md:px-8" role="status">
            <div className="flex min-w-0 flex-1 items-center gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-[13px] text-ink">
              <Icon name="warn" size={16} className="shrink-0 text-amber-600" />
              <span className="min-w-0 flex-1">{t('上次服务停止时，这里的回复还没完成。')}</span>
              <button type="button" onClick={dismissResume} className="shrink-0 rounded-md px-2 py-1 text-xs text-muted hover:bg-surface hover:text-ink">{t('不用了')}</button>
              <button type="button" onClick={resume} className="shrink-0 rounded-lg bg-accent px-3 py-1 text-xs font-medium text-on-accent hover:bg-accent-strong">{t('继续')}</button>
            </div>
          </div>
        )}
        <Composer agents={agents} lead={lead} text={text} setText={setText} targets={targets} setTargets={setTargets} inputRef={inputRef}
          running={running} online={online} onSubmit={submit} onStop={() => stop(conv.id)} blocked={blocked} sendLabel={sendLabel} canNudge={canNudge}
          files={files} onAddFiles={agents.length ? addFiles : null} onRemoveFile={removeFile} />
      </section>

      <Members conv={conv} agents={agents} lead={lead} outside={outside} messages={messages} targets={targets} toggleTarget={toggleTarget}
        onAddAgent={onAddAgent} onAddExternal={onAddExternal} onEditAgent={onEditAgent} onSettings={onSettings} />
    </div>
  )
}
