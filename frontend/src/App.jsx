import { t } from './lib/i18n'
import { ask, DialogHost } from './components/Dialog.jsx'
import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { api, getToken, setToken, wsUrl } from './lib/api'
import AgentModal from './components/AgentModal.jsx'
import ExternalModal from './components/ExternalModal.jsx'
import ContextMenu from './components/ContextMenu.jsx'
import ConvModal from './components/ConvModal.jsx'
import { Btn, ConvAvatar, Icon, IconBtn, Logo, inputCls } from './components/ui.jsx'
import Agents from './pages/Agents.jsx'
import Chat from './pages/Chat.jsx'
import Providers from './pages/Providers.jsx'
import Settings from './pages/Settings.jsx'
import Skills from './pages/Skills.jsx'
import Mcp from './pages/Mcp.jsx'
import Welcome from './pages/Welcome.jsx'

const NAV = [
  { id: 'chat', icon: 'chat', name: '消息' },
  { id: 'agents', icon: 'agents', name: '智能体' },
  { id: 'providers', icon: 'plug', name: '渠道' },
  { id: 'skills', icon: 'sparkle', name: '技能' },
  { id: 'mcp', icon: 'terminal', name: 'MCP' },
  { id: 'settings', icon: 'gear', name: '设置' },
]

const upsert = (list, m) => {
  const i = list.findIndex((x) => x.id === m.id)
  if (i < 0) return [...list, m]
  const next = list.slice()
  next[i] = m
  return next
}

// 会话列表右侧的时间：今天显示时分，更早显示月日
const clock = (ts) => {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return d.toDateString() === new Date().toDateString() ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : `${d.getMonth() + 1}/${d.getDate()}`
}
const ACTION = /<run>[\s\S]*?<\/run>|<read>[\s\S]*?<\/read>|<write\s+path=["'][^"']+["']\s*>[\s\S]*?<\/write>|<agent\s+name=["'][^"'<>]+["'][^>]*>[\s\S]*?<\/agent>|<remove\s+name=["'][^"'<>]+["']\s*\/?>|<mcp\s+server=[\s\S]*?<\/mcp>|<(fetch|skill_find|skill_remove|mcp_remove)\s[^>]*\/?>(\s*<\/\1>)?|<skill_add\s+url=[^>]*\/?>|<skill_add[\s\S]*?<\/skill_add>|<mcp_add>[\s\S]*?<\/mcp_add>|<lesson>[\s\S]*?<\/lesson>|<remember>[\s\S]*?<\/remember>|<skill_add\s+path=[^>]*\/?>/g
const previewOf = (m) => {
  if (m.role === 'tool') return { who: m.agent_name, text: '请求本地操作', at: m.created }
  const text = (m.content || '').replace(ACTION, '').replace(/[*#`>]+/g, '').replace(/\s+/g, ' ').trim()
  return { who: m.agent_name || '', text: text.slice(0, 80) || m.error || '', at: m.created }
}

function TokenGate({ onDone }) {
  const [v, setV] = useState('')
  const go = (e) => { e.preventDefault(); setToken(v); onDone() }
  return (
    <div className="flex h-dvh items-center justify-center bg-canvas p-6">
      <form className="w-full max-w-sm rounded-2xl border border-line bg-surface p-8 shadow-float" onSubmit={go}>
        <Logo size={40} />
        <h1 className="mt-6 text-2xl font-semibold tracking-tight text-ink">输入访问口令</h1>
        <p className="mt-2 mb-6 text-sm leading-relaxed text-muted">这台控制台开启了口令保护，口令在 config.yaml 的 server.token 或环境变量 MAC_TOKEN 里。</p>
        <input className={inputCls} type="password" value={v} onChange={(e) => setV(e.target.value)} placeholder="访问口令" aria-label="访问口令" autoFocus />
        <button type="submit" className="mt-3 h-11 w-full rounded-[10px] bg-accent text-sm font-medium text-on-accent transition-[background-color,transform] duration-150 hover:bg-accent-strong active:scale-[0.98]">进入控制台</button>
      </form>
    </div>
  )
}

export default function App() {
  const [data, setData] = useState(null)
  const [msgs, setMsgs] = useState({})
  const [running, setRunning] = useState({})
  const [view, setView] = useState('chat')
  const [active, setActive] = useState(() => localStorage.getItem('mac_active') || '')
  const [inChat, setInChat] = useState(false) // 手机上：是否已进入某个会话（否则显示会话列表）
  const [query, setQuery] = useState('')
  // 会话列表宽度可拖动调整，记在本机
  const [listW, setListW] = useState(() => Number(localStorage.getItem('mac_list_w')) || 304)
  useEffect(() => { localStorage.setItem('mac_list_w', String(listW)) }, [listW])
  const startDrag = (e) => {
    e.preventDefault()
    const x0 = e.clientX
    const w0 = listW
    const move = (ev) => setListW(Math.max(220, Math.min(Math.round(window.innerWidth * 0.5), w0 + ev.clientX - x0)))
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); document.body.style.cursor = '' }
    document.body.style.cursor = 'col-resize'
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const [hits, setHits] = useState({}) // 会话 id -> 聊天记录里命中的片段
  useEffect(() => {
    const q = query.trim()
    if (!q) { setHits({}); return }
    const t = setTimeout(() => {
      api('GET', '/search?q=' + encodeURIComponent(q)).then((r) => setHits(Object.fromEntries(r.hits.map((h) => [h.conv_id, h])))).catch(() => {})
    }, 250)
    return () => clearTimeout(t)
  }, [query])
  const [locked, setLocked] = useState(false)
  const [online, setOnline] = useState(false)
  const [toast, setToast] = useState('')
  const [convModal, setConvModal] = useState(null)
  const [agentModal, setAgentModal] = useState(null) // { conv, initial? }
  const [extModal, setExtModal] = useState(null) // { conv }
  const [menuAt, setMenuAt] = useState(null) // 右键菜单 { x, y, conv }
  const [failed, setFailed] = useState('')
  const wsRef = useRef(null)
  const activeRef = useRef(active)
  activeRef.current = active

  const notify = useCallback((text) => {
    setToast(text)
    clearTimeout(notify.t)
    notify.t = setTimeout(() => setToast(''), 3500)
  }, [])

  const reload = useCallback(async () => {
    try {
      const d = await api('GET', '/state')
      setData(d)
      setRunning(Object.fromEntries(d.running.map((id) => [id, true])))
      setLocked(false)
      setFailed('')
    } catch (e) {
      if (e.status === 401) setLocked(true)
      else setFailed(e.message || '无法连接后端')
    }
  }, [])

  const loadMessages = useCallback(async (cid) => {
    if (!cid) return
    try {
      const r = await api('GET', `/conversations/${cid}/messages`)
      setMsgs((m) => ({ ...m, [cid]: r.messages }))
    } catch { /* 会话可能已被删除 */ }
  }, [])

  // WebSocket：断线自动重连，重连后刷新状态
  useEffect(() => {
    if (locked) return
    let closed = false
    let timer
    const connect = () => {
      const ws = new WebSocket(wsUrl())
      wsRef.current = ws
      ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: encodeURIComponent(getToken()) }))
      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data)
        if (ev.type === 'ready') {
          setOnline(true)
          reload()
          loadMessages(activeRef.current)
        } else if (ev.type === 'unauthorized') {
          setLocked(true)
        } else if (ev.type === 'message') {
          const m = ev.message
          setMsgs((s) => (s[m.conv_id] ? { ...s, [m.conv_id]: upsert(s[m.conv_id], m) } : s))
          if (!m.streaming) {
            setData((d) => d && { ...d, conversations: d.conversations.map((c) => (c.id === m.conv_id ? { ...c, last: previewOf(m) } : c)) })
          }
        } else if (ev.type === 'delta') {
          setMsgs((s) => {
            const list = s[ev.conv_id]
            const i = list ? list.findIndex((x) => x.id === ev.id) : -1
            if (i < 0) return s
            const key = ev.kind === 'think' ? 'reasoning' : 'content'
            const next = list.slice()
            next[i] = { ...list[i], [key]: (list[i][key] || '') + ev.text }
            return { ...s, [ev.conv_id]: next }
          })
        } else if (ev.type === 'removed') {
          setMsgs((s) => (s[ev.conv_id] ? { ...s, [ev.conv_id]: s[ev.conv_id].filter((x) => !ev.ids.includes(x.id)) } : s))
        } else if (ev.type === 'running') {
          setRunning((r) => ({ ...r, [ev.conv_id]: ev.running }))
        } else if (ev.type === 'conversation') {
          setData((d) => d && { ...d, conversations: upsert(d.conversations, { ...d.conversations.find((c) => c.id === ev.conversation.id), ...ev.conversation }) })
        } else if (ev.type === 'refresh') {
          reload()
        } else if (ev.type === 'error') {
          notify(ev.text)
        }
      }
      ws.onclose = () => {
        setOnline(false)
        if (!closed) timer = setTimeout(connect, 1500)
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      wsRef.current?.close()
    }
  }, [locked, reload, loadMessages, notify])

  useEffect(() => {
    localStorage.setItem('mac_active', active)
    if (active && !msgs[active]) loadMessages(active)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps

  const wsSend = (payload) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== 1) { notify('连接已断开，正在重连，稍后再试'); return false }
    ws.send(JSON.stringify(payload))
    return true
  }
  const send = (conv_id, content, targets, attachments = []) => wsSend({ type: 'send', conv_id, content, targets, attachments })
  const retry = (conv_id, message_id) => wsSend({ type: 'retry', conv_id, message_id })
  const stop = (conv_id) => wsSend({ type: 'stop', conv_id })
  // 任务看板上单独控制某一位成员：停止它（其他人继续）、重做它的那项任务
  const member = {
    stop: (conv_id, agent_id) => wsSend({ type: 'stop_member', conv_id, agent_id }),
    retry: (conv_id, agent_id, batch) => wsSend({ type: 'retry_member', conv_id, agent_id, batch }),
  }
  const permit = (id, decision) => wsSend({ type: 'permit', id, decision })
  const open = (id) => { setActive(id); setView('chat'); setInChat(true) }
  const go = (v) => { setView(v); setInChat(false) }

  const convAction = async (c, kind) => {
    try {
      if (kind === 'pin') await api('PUT', '/conversations/' + c.id, { ...c, pinned: !c.pinned })
      if (kind === 'rename') {
        const t = await ask('重命名会话', { input: c.title, ok: '保存' })
        if (!t || !t.trim() || t.trim() === c.title) return
        await api('PUT', '/conversations/' + c.id, { ...c, title: t.trim() })
      }
      if (kind === 'delete') {
        if (!await ask(`删除会话「${c.title}」及其全部消息？此操作无法撤销。`)) return
        await api('DELETE', '/conversations/' + c.id)
        if (active === c.id) { setActive(''); setInChat(false) }
      }
      reload()
    } catch (e) {
      notify(e.message)
    }
  }

  // 交给管家：把用户的话发到管家的会话里。inline 时留在当前页，由页面上的安装小窗显示进度
  const askManager = async (text, { inline = false } = {}) => {
    try {
      const r = await api('POST', '/manager')
      const cid = r.conversation.id
      await reload()
      await loadMessages(cid) // 先把消息载入，后续的实时推送才有地方落
      if (running[cid]) { notify('管家还在忙上一件事，稍等一下'); return null }
      if (!inline) open(cid)
      send(cid, text, [])
      return cid
    } catch (e) {
      notify(e.message)
      return null
    }
  }
  const manager = { msgs, running, permit, open }

  const chatWith = async (agent) => {
    const exist = data.conversations.find((c) => c.agent_ids.length === 1 && c.agent_ids[0] === agent.id && c.mode !== 'lead')
    if (exist) return open(exist.id)
    try {
      const conv = await api('POST', '/conversations', { title: '与' + agent.name + '的对话', agent_ids: [agent.id] })
      await reload()
      open(conv.id)
    } catch (e) {
      notify(e.message)
    }
  }

  if (locked) return <TokenGate onDone={() => { setLocked(false); reload() }} />
  if (!data) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-5 bg-canvas px-6 text-center">
        <Logo size={44} />
        {failed ? (
          <>
            <p className="max-w-[40ch] text-sm leading-relaxed text-muted">连不上后端服务：{failed}。请确认启动窗口还开着。</p>
            <Btn icon="refresh" onClick={reload}>重新连接</Btn>
          </>
        ) : (
          <div className="skeleton h-1.5 w-28" aria-label="正在读取数据" />
        )}
      </div>
    )
  }

  const globals = data.agents.filter((a) => !a.conv_id)
  const chief = globals.find((a) => a.chief)
  const conv = data.conversations.find((c) => c.id === active)
  const customConv = () => setConvModal({})
  // 新会话默认交给总智能体接待，由它按需把专业智能体拉进来
  const newConv = async () => {
    if (!chief) return customConv()
    try {
      const c = await api('POST', '/conversations', { title: '', agent_ids: [chief.id], mode: 'lead', lead_id: chief.id, rounds: 3 })
      await reload()
      open(c.id)
    } catch (e) {
      notify(e.message)
    }
  }

  const list = [...data.conversations]
    .sort((a, b) => (!!b.pinned - !!a.pinned) || (b.last?.at || b.created) - (a.last?.at || a.created))
    .filter((c) => !query.trim() || c.title.toLowerCase().includes(query.trim().toLowerCase()) || hits[c.id])
  const showChat = view === 'chat' && conv && inChat // 手机上进入会话后隐藏列表与底栏
  const hasConvs = data.conversations.length > 0

  const navBtn = (n, mobile) => {
    const on = view === n.id
    if (mobile) {
      return (
        <button key={n.id} type="button" aria-current={on ? 'page' : undefined} onClick={() => go(n.id)}
          className={'relative flex h-12 flex-1 flex-col items-center justify-center gap-0.5 text-[10px] transition-colors duration-150 ' + (on ? 'font-medium text-accent-ink' : 'text-muted hover:text-ink')}>
          <Icon name={n.icon} size={22} weight={on ? 'fill' : 'regular'} />
          <span>{t(n.name)}</span>
        </button>
      )
    }
    // 桌面：图标下面直接写名字，不用悬停去猜每个图标是什么
    return (
      <button key={n.id} type="button" aria-current={on ? 'page' : undefined} onClick={() => go(n.id)}
        className={'group/nav flex w-[60px] flex-col items-center gap-1 py-1 text-[11px] leading-none transition-colors duration-150 ' + (on ? 'font-medium text-accent-ink' : 'text-muted hover:text-ink')}>
        <span className={'relative flex h-9 w-12 items-center justify-center rounded-[14px] transition-colors duration-150 ' + (on ? 'text-on-accent' : 'group-hover/nav:bg-sunken')}>
          {on && <motion.span layoutId="rail-pill" transition={{ type: 'spring', stiffness: 380, damping: 32 }} className="absolute inset-0 rounded-[14px] bg-accent shadow-[0_6px_16px_-6px_var(--accent)]" />}
          <Icon name={n.icon} size={20} weight={on ? 'fill' : 'regular'} className="relative" />
        </span>
        <span>{t(n.name)}</span>
      </button>
    )
  }

  return (
    <div className="aurora flex h-dvh flex-col overflow-hidden md:flex-row md:gap-3 md:p-3">
      {/* 桌面：最左侧图标导航栏 */}
      <nav className="glass hidden w-[72px] shrink-0 flex-col items-center gap-2 rounded-[26px] py-3 md:flex">
        <div className="mb-4"><Logo size={38} /></div>
        {NAV.map((n) => navBtn(n, false))}
        <span className="flex-1" />
        <span title={online ? '已连接到后端' : '正在连接后端'} className={'mb-2 h-2 w-2 rounded-full ' + (online ? 'bg-ok' : 'animate-breathe bg-danger')} />
      </nav>

      {/* 会话列表 */}
      {view === 'chat' && (
        <aside style={{ '--list-w': listW + 'px' }} className={'min-h-0 w-full flex-1 flex-col bg-surface md:w-[var(--list-w)] md:flex-none md:rounded-[24px] md:shadow-sheet ' + (showChat || !hasConvs ? 'hidden md:flex' : 'flex')}>
          <div className="flex h-14 shrink-0 items-center gap-1 pr-2 pl-4">
            <h1 className="flex-1 text-lg font-semibold tracking-tight text-ink">消息</h1>
            <IconBtn icon="agents" label="自选智能体建群" onClick={customConv} />
            <IconBtn icon="plus" weight="bold" label={chief ? `新会话（由${chief.name}接待）` : '新建会话'} kind="primary" size={32} onClick={newConv} className="mr-1 rounded-lg" />
          </div>
          <div className="px-3 pb-2">
            <label className="flex h-9 items-center gap-2 rounded-lg bg-sunken px-2.5 text-faint focus-within:outline-2 focus-within:outline-accent">
              <Icon name="search" size={16} />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索标题或聊天内容" aria-label="搜索会话" className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-faint" />
            </label>
          </div>
          <div className="scroll flex-1 overflow-y-auto pb-2">
            {!hasConvs && <p className="px-4 py-6 text-sm leading-relaxed text-faint">还没有会话。点右上角的加号开始。</p>}
            {hasConvs && list.length === 0 && <p className="px-4 py-6 text-sm text-faint">标题和聊天记录里都没有找到「{query}」</p>}
            {list.map((c) => {
              const members = c.agent_ids.map((id) => data.agents.find((a) => a.id === id)).filter(Boolean)
              const on = c.id === active
              return (
                <button key={c.id} type="button" onClick={() => open(c.id)} onContextMenu={(e) => { e.preventDefault(); setMenuAt({ x: e.clientX, y: e.clientY, conv: c }) }}
                  className={'flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors duration-150 ' + (on ? 'bg-accent-soft' : c.pinned ? 'bg-sunken/60 hover:bg-sunken' : 'hover:bg-sunken')}>
                  <ConvAvatar agents={members} size={44} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-ink">{c.pinned && <Icon name="pin" size={12} weight="fill" className="mr-1 inline -translate-y-px text-accent" />}{c.title}</span>
                      <span className="shrink-0 font-mono text-[11px] text-faint">{clock(c.last?.at || c.created)}</span>
                    </span>
                    <span className="mt-0.5 flex items-center gap-1.5 text-[13px] text-muted">
                      {running[c.id] ? (
                        <><span className="h-1.5 w-1.5 shrink-0 animate-breathe rounded-full bg-accent" /><span className="truncate text-accent-ink">正在回复…</span></>
                      ) : (
                        <span className="truncate">{query.trim() && hits[c.id] ? <><span className="text-accent-ink">{hits[c.id].who ? hits[c.id].who + '：' : ''}</span>{hits[c.id].text}</> : c.last?.text ? (c.last.who ? c.last.who + '：' : '') + c.last.text : members.length > 1 ? `${members.length} 个智能体` : '还没有消息'}</span>
                      )}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>
        </aside>
      )}
      {view === 'chat' && (
        <div
          role="separator" aria-orientation="vertical" aria-label="拖动调整会话列表宽度" title="拖动调整宽度，双击恢复默认"
          onPointerDown={startDrag} onDoubleClick={() => setListW(304)}
          className="group/drag relative z-10 -mx-3 hidden w-3 shrink-0 cursor-col-resize md:block"
        >
          <span className="absolute top-1/2 left-1/2 h-10 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-transparent transition-colors duration-150 group-hover/drag:bg-accent" />
        </div>
      )}

      <main className={'min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-sunken md:rounded-[24px] md:shadow-sheet ' + (view === 'chat' && !showChat && hasConvs ? 'hidden md:flex' : 'flex')}>
        {view === 'agents' && <Agents data={data} reload={reload} notify={notify} onChat={chatWith} />}
        {view === 'providers' && <Providers data={data} reload={reload} notify={notify} />}
        {view === 'settings' && <Settings data={data} reload={reload} notify={notify} openConv={open} />}
        {view === 'skills' && <Skills data={data} notify={notify} askManager={askManager} manager={manager} />}
        {view === 'mcp' && <Mcp data={data} notify={notify} reload={reload} askManager={askManager} manager={manager} />}
        {view === 'chat' && conv && (
          <Chat
            data={data} conv={conv} messages={msgs[conv.id]} running={!!running[conv.id]} online={online}
            send={send} retry={retry} stop={stop} member={member} permit={permit} reloadMessages={loadMessages} notify={notify}
            onBack={() => setInChat(false)}
            onSettings={() => setConvModal(conv)}
            onAddAgent={() => setAgentModal({ conv })}
            onAddExternal={() => setExtModal({ conv })}
            onEditAgent={(a) => setAgentModal({ conv, initial: a })}
            onOpenSettings={() => go('settings')}
            reload={reload}
          />
        )}
        {view === 'chat' && !conv && <Welcome data={data} go={go} newConv={newConv} />}
      </main>

      {/* 手机：底部标签栏（进入会话后隐藏） */}
      {!showChat && (
        <nav className="glass mx-3 mb-[max(0.5rem,env(safe-area-inset-bottom))] flex shrink-0 rounded-[22px] px-1 md:hidden">
          {NAV.map((n) => navBtn(n, true))}
        </nav>
      )}

      {convModal && (
        <ConvModal
          data={data}
          initial={convModal.id ? convModal : null}
          notify={notify}
          reload={reload}
          onAddAgent={(c) => { setConvModal(null); setAgentModal({ conv: c }) }}
          onEditAgent={(c, a) => { setConvModal(null); setAgentModal({ conv: c, initial: a }) }}
          onClose={() => setConvModal(null)}
          onSaved={async (c, cleared) => {
            setConvModal(null)
            await reload()
            if (cleared) loadMessages(c.id)
            open(c.id)
          }}
          onDeleted={() => { setConvModal(null); setActive(''); setInChat(false); reload() }}
        />
      )}
      {menuAt && (
        <ContextMenu x={menuAt.x} y={menuAt.y} onClose={() => setMenuAt(null)} items={[
          { icon: 'pin', label: menuAt.conv.pinned ? '取消置顶' : '置顶', onClick: () => convAction(menuAt.conv, 'pin') },
          { icon: 'edit', label: '重命名', onClick: () => convAction(menuAt.conv, 'rename') },
          { icon: 'sliders', label: '会话设置', onClick: () => setConvModal(menuAt.conv) },
          { icon: 'trash', label: '删除', danger: true, onClick: () => convAction(menuAt.conv, 'delete') },
        ]} />
      )}
      <DialogHost />
      {extModal && <ExternalModal data={data} conv={extModal.conv} notify={notify} reload={reload} onClose={() => { setExtModal(null); reload() }} onSaved={() => { setExtModal(null); reload() }} />}
      {agentModal && (
        <AgentModal
          data={data}
          conv={agentModal.conv}
          initial={agentModal.initial || null}
          reload={reload}
          notify={notify}
          onClose={() => setAgentModal(null)}
          onSaved={() => { setAgentModal(null); reload() }}
        />
      )}
      {toast && (
        <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-24 z-[60] flex justify-center px-4">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 300, damping: 30 }} className="max-w-md rounded-xl bg-ink px-4 py-2.5 text-[13px] leading-relaxed text-surface shadow-float">{toast}</motion.div>
        </div>
      )}
    </div>
  )
}
