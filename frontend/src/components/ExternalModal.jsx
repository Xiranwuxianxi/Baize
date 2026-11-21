import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Avatar, Btn, Chip, Field, Icon, Modal, inputCls } from './ui.jsx'

// 类型、颜色、头像、本机命令行（直接调用模式的预设命令；题目从标准输入给它）
const KINDS = [
  ['Claude Code', 'slate', 'ph:Code', 'claude -p --output-format text'],
  ['Kimi Code', 'teal', 'ph:Lightning', 'kimi --quiet'],
  ['Codex', 'olive', 'ph:Code', 'codex exec -'],
  ['OpenClaw', 'rose', 'ph:Robot', ''],
  ['Hermes', 'amber', 'ph:Lightning', ''],
  ['WorkBuddy', 'pine', 'ph:Wrench', ''],
  ['其他', 'plum', 'ph:Robot', ''],
]
const NOTES = {
  'Claude Code': '每轮调用一次 claude -p。需要它改文件、跑命令时，Claude Code 默认会拒绝未授权的操作。',
  'Kimi Code': '注意：kimi 的 --quiet（print 模式）会自动加上 --yolo，它自己的所有操作都不再询问。',
  Codex: '这台电脑上没检测到 codex，装好后才能用。',
}
const kindOf = (k) => KINDS.find((x) => x[0] === k) || KINDS[KINDS.length - 1]

// 接入外部智能体：它自己有身份和能力，这里只要选一下是谁、怎么联系它
export default function ExternalModal({ data, initial, conv, onClose, onSaved, notify, reload }) {
  const [kind, setKind] = useState(initial?.ext_kind || 'Claude Code')
  const [name, setName] = useState(initial?.name || 'Claude Code')
  const [desc, setDesc] = useState(initial?.description || '')
  const [mode, setMode] = useState(initial?.ext_mode || (kindOf(initial?.ext_kind || 'Claude Code')[3] ? 'cli' : 'poll'))
  const [cmd, setCmd] = useState(initial?.ext_cmd || kindOf(initial?.ext_kind || 'Claude Code')[3])
  const [limit, setLimit] = useState(initial?.ext_timeout || 15) // 一轮最多等几分钟
  const [agent, setAgent] = useState(initial || null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const online = agent && (data.ext_online || []).includes(agent.id)
  const [net, setNet] = useState(null) // 本机的局域网地址、自定义的外网地址
  const [addr, setAddr] = useState('')
  const [pub, setPub] = useState('')
  useEffect(() => {
    api('GET', '/settings').then((s) => {
      setNet(s)
      setPub(s.public_url || '')
      const here = /^(localhost|127\.|\[::1\])/.test(location.hostname) ? '' : location.origin
      setAddr(s.public_url || here || s.lan_urls[0] || location.origin)
    }).catch(() => setAddr(location.origin))
  }, [])
  const choices = net ? [...new Set([net.public_url, ...net.lan_urls, location.origin].filter(Boolean))] : []
  // 100.64.0.0/10 是 Tailscale 等组网工具用的地址段：不在同一个 Wi‑Fi 也能连
  const labelOf = (u) => u === net?.public_url ? '其他网络'
    : /\/\/(localhost|127\.|\[::1\])/.test(u) ? '仅这台电脑'
    : /\/\/100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(u) ? '跨网络（Tailscale 等）' : '同一局域网'
  const join = agent ? `你被邀请加入一个多智能体协作会话。请读取 ${addr || location.origin}/join/${agent.ext_token} 的内容，并严格按里面的说明操作（只需要用 curl 发 HTTP 请求）。` : ''
  const savePub = async () => {
    try {
      const s = await api('PUT', '/settings', { public_url: pub })
      setNet(s)
      if (s.public_url) setAddr(s.public_url)
      notify(s.public_url ? '已保存，连接指令改用这个地址' : '已清除外网地址')
    } catch (e) { notify(e.message) }
  }
  const pick = (k) => {
    if (!agent && (name === kind || !name.trim())) setName(k === '其他' ? '' : k)
    setKind(k)
    const preset = kindOf(k)[3]
    setCmd(preset)
    setMode(preset ? 'cli' : 'poll')
  }
  const body = () => {
    const [, color, avatar] = kindOf(kind)
    return { name: name.trim(), description: desc, external: true, ext_kind: kind, ext_mode: mode, ext_cmd: mode === 'cli' ? cmd.trim() : '', ext_timeout: Number(limit) || 15, color, avatar, no_tools: true, global: true }
  }
  const create = async () => {
    if (!name.trim()) return notify('起个名字，会话里用它称呼这个智能体')
    if (mode === 'cli' && !cmd.trim()) return notify('填写调用它的命令')
    setBusy(true)
    try {
      const r = conv ? await api('POST', `/conversations/${conv.id}/agents`, body()) : await api('POST', '/agents', body())
      await reload()
      if (mode === 'cli') { notify(`「${name.trim()}」已接入，轮到它时会直接调用`); onSaved(); return }
      setAgent(r.agent || r)
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }
  const saveEdit = async () => {
    setBusy(true)
    try {
      await api('PUT', '/agents/' + agent.id, { ...agent, ...body() })
      onSaved()
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }
  const copy = () => navigator.clipboard?.writeText(join).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
  const showJoin = agent && mode === 'poll' && agent.ext_token

  return (
    <Modal title={initial ? `外部智能体 · ${initial.name}` : '接入外部智能体'}
      sub={conv && !initial ? `接好后直接加入「${conv.title}」。` : '它用自己的身份和能力工作，不需要在这里设定角色。'} onClose={onClose}
      footer={initial
        ? <><Btn kind="ghost" onClick={onClose}>关闭</Btn><Btn kind="primary" disabled={busy} onClick={saveEdit}>保存</Btn></>
        : agent ? <><Btn kind="primary" onClick={onSaved}>完成</Btn></>
        : <><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn kind="primary" disabled={busy} onClick={create}>{mode === 'cli' ? '接入' : '生成连接指令'}</Btn></>}>
      <div>
        <div className="mb-2 text-[13px] font-medium text-ink">它是谁</div>
        <div className="flex flex-wrap gap-1.5">
          {KINDS.map(([k, color, avatar]) => (
            <Chip key={k} on={kind === k} onClick={() => pick(k)} className="pl-1"><Avatar agent={{ name: k, color, avatar }} size={22} />{k}</Chip>
          ))}
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="在会话里叫它"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="Claude Code" maxLength={40} /></Field>
        <Field label="擅长什么（可选）" hint="领头智能体靠这句话决定派什么活给它。"><input className={inputCls} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="写代码、改项目文件" maxLength={200} /></Field>
      </div>

      <div>
        <div className="mb-2 text-[13px] font-medium text-ink">怎么联系它</div>
        <div className="grid gap-2 sm:grid-cols-2">
          {[['cli', '直接调用', '装在这台电脑上的命令行智能体。轮到它时直接调用一次，不用专门开窗口等着。'],
            ['poll', '连接指令', '在别的电脑、或者没有命令行的智能体。复制一段话给它，它保持在线等任务。']].map(([id, title, hint]) => (
            <button key={id} type="button" aria-pressed={mode === id} onClick={() => setMode(id)}
              className={'rounded-xl border p-3 text-left transition-colors duration-150 ' + (mode === id ? 'border-accent bg-accent-soft' : 'border-line bg-raised hover:border-line-strong')}>
              <span className="flex items-center gap-1.5 text-sm font-medium text-ink">{title}{id === 'cli' && <span className="rounded bg-accent px-1 text-[10px] text-on-accent">推荐</span>}</span>
              <span className="mt-1 block text-xs leading-relaxed text-muted">{hint}</span>
            </button>
          ))}
        </div>
      </div>

      {mode === 'cli' && (
        <Field label="调用命令" hint={(NOTES[kind] ? NOTES[kind] + ' ' : '') + '会话内容从标准输入传给它，它的输出就是回复；在这个会话的文件夹里执行。命令里写 {prompt_file} 则改为传文件路径。'}>
          <input className={inputCls + ' font-mono text-sm'} value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder="例如 claude -p" spellCheck={false} />
        </Field>
      )}
      <Field label="一轮最多等多久（分钟）" hint="写代码、跑测试这类大任务可能要十几分钟。到时还没做完就结束它，会话里会说明原因。输出会边写边显示，不用干等。">
        <input className={inputCls + ' w-32'} type="number" min="1" max="120" value={limit} onChange={(e) => setLimit(e.target.value)} />
      </Field>

      {showJoin && (
        <div className="rounded-2xl border border-accent bg-accent-soft/40 p-4">
          <div className="mb-2.5 flex items-center gap-2 text-[13px]">
            <span className="font-medium text-ink">把这段话发给它</span>
            <span className={'inline-flex items-center gap-1.5 text-xs ' + (online ? 'text-ok' : 'text-muted')}>
              <span className={'h-1.5 w-1.5 rounded-full ' + (online ? 'bg-ok' : 'animate-breathe bg-accent')} />{online ? '已连接' : '等待它连接…'}
            </span>
            <span className="flex-1" />
            <Btn kind="primary" icon={copied ? 'check' : 'copy'} onClick={copy} className="h-8 px-3 text-[13px]">{copied ? '已复制' : '复制'}</Btn>
          </div>
          {choices.length > 0 && (
            <div className="mb-2.5">
              <div className="mb-1.5 text-xs text-muted">它在哪里连过来</div>
              <div className="flex flex-wrap gap-1.5">
                {choices.map((u) => (
                  <button key={u} type="button" aria-pressed={addr === u} onClick={() => setAddr(u)}
                    className={'rounded-lg border px-2.5 py-1 text-left text-xs transition-colors duration-150 ' + (addr === u ? 'border-accent bg-surface text-ink' : 'border-line text-muted hover:text-ink')}>
                    <span className="font-medium">{labelOf(u)}</span> <span className="font-mono">{u.replace(/^https?:\/\//, '')}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <p className="rounded-xl bg-surface px-3 py-2.5 font-mono text-xs leading-relaxed text-ink [overflow-wrap:anywhere]">{join}</p>
          {net && !net.lan_bind_ok && (
            <p role="alert" className="mt-2.5 flex items-start gap-1.5 rounded-lg bg-danger-soft px-3 py-2 text-xs leading-relaxed text-danger">
              <Icon name="warn" size={14} className="mt-px shrink-0" />程序现在只监听本机（host 为 127.0.0.1），别的电脑连不上。把配置里的 server.host 改成 0.0.0.0 后重启。
            </p>
          )}
          <ul className="mt-2.5 space-y-1 text-xs leading-relaxed text-muted">
            <li className="flex items-start gap-1.5"><Icon name="chat" size={14} className="mt-px shrink-0" />在它的对话框里粘贴发送，那个窗口要一直开着。装在本机的命令行智能体建议改用「直接调用」。</li>
            <li className="flex items-start gap-1.5"><Icon name="shield" size={14} className="mt-px shrink-0" />只开放这个智能体自己的连接口（带专属口令），不需要打开整个控制台的局域网访问。</li>
            <li className="flex items-start gap-1.5"><Icon name="warn" size={14} className="mt-px shrink-0" />同一局域网仍连不上：在这台电脑的防火墙里放行 {net?.lan_urls[0]?.split(':').pop() || '18760'} 端口。可以先在那台电脑的浏览器里打开上面的网址试试。</li>
          </ul>
          <details className="mt-2.5 text-xs text-muted">
            <summary className="cursor-pointer select-none hover:text-ink">不在同一个网络？填一个外网地址</summary>
            <p className="mt-1.5 leading-relaxed">用 Tailscale、ZeroTier、frp 等让那台电脑能访问到这里，把它能访问的地址填进来（例如 http://100.64.0.5:18760 或 https://agents.example.com）。</p>
            <div className="mt-2 flex gap-2">
              <input className={inputCls + ' h-8 min-w-0 flex-1 py-1 font-mono text-xs'} value={pub} onChange={(e) => setPub(e.target.value)} placeholder="http://100.64.0.5:18760" spellCheck={false} />
              <Btn kind="outline" disabled={net && !net.can_admin} onClick={savePub} className="h-8 px-3 text-xs">保存</Btn>
            </div>
          </details>
        </div>
      )}
    </Modal>
  )
}
