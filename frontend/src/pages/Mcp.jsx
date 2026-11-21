import { ask } from '../components/Dialog.jsx'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Btn, Chip, Empty, Field, Icon, IconBtn, MobileBar, Modal, Page, Tag, inputCls } from '../components/ui.jsx'
import ManagerBox, { SearchInput } from '../components/ManagerBox.jsx'

const toLines = (obj) => Object.keys(obj || {}).map((k) => `${k}=${obj[k] || ''}`).join('\n')
const fromLines = (text) => Object.fromEntries(text.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const i = l.indexOf('='); return i < 0 ? [l, ''] : [l.slice(0, i).trim(), l.slice(i + 1).trim()] }))

function McpModal({ initial, onClose, onSaved, notify }) {
  const [f, setF] = useState(() => ({
    name: '', transport: 'stdio', command: '', url: '', cwd: '', ...initial,
    args: (initial?.args || []).join(' '), env: toLines(initial?.env), headers: toLines(initial?.headers),
  }))
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const editing = !!initial?.id
  const save = async () => {
    setBusy(true)
    try {
      const body = { ...f, args: f.args.split(/\s+/).filter(Boolean), env: fromLines(f.env), headers: fromLines(f.headers) }
      const r = await (editing ? api('PUT', '/mcp/' + initial.id, body) : api('POST', '/mcp', body))
      notify(r.error ? '已保存，但连接失败：' + r.error : `已连接，发现 ${r.tools.length} 个工具`)
      onSaved()
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }
  const secretHint = editing ? '已保存的值不会显示，留空表示不修改。' : ''
  return (
    <Modal wide title={editing ? '编辑 MCP 服务' : '添加 MCP 服务'} sub="保存后会立即尝试连接并读取它提供的工具。" onClose={onClose}
      footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn kind="primary" disabled={busy} onClick={save}>{busy ? '正在连接…' : editing ? '保存并重新连接' : '添加并连接'}</Btn></>}>
      <Field label="名称" hint="智能体用这个名字调用它，只能用字母、数字、横线。"><input className={inputCls + ' font-mono text-sm'} value={f.name} onChange={set('name')} placeholder="filesystem" /></Field>
      <div>
        <div className="mb-2 text-[13px] font-medium text-ink">接入方式</div>
        <div className="flex gap-1.5">
          <Chip on={f.transport === 'stdio'} onClick={() => setF({ ...f, transport: 'stdio' })}>本地命令（stdio）</Chip>
          <Chip on={f.transport === 'http'} onClick={() => setF({ ...f, transport: 'http' })}>远程地址（HTTP）</Chip>
        </div>
      </div>
      {f.transport === 'stdio' ? (
        <>
          <div className="grid gap-4 md:grid-cols-[180px_1fr]">
            <Field label="命令"><input className={inputCls + ' font-mono text-sm'} value={f.command} onChange={set('command')} placeholder="npx" spellCheck={false} /></Field>
            <Field label="参数" hint="用空格分隔。"><input className={inputCls + ' font-mono text-sm'} value={f.args} onChange={set('args')} placeholder="-y @modelcontextprotocol/server-filesystem D:\\docs" spellCheck={false} /></Field>
          </div>
          <Field label="环境变量（可选）" hint={'每行一个 KEY=值。' + secretHint}><textarea className={inputCls + ' font-mono text-sm'} rows={2} value={f.env} onChange={set('env')} placeholder="API_KEY=..." spellCheck={false} /></Field>
        </>
      ) : (
        <>
          <Field label="地址"><input className={inputCls + ' font-mono text-sm'} value={f.url} onChange={set('url')} placeholder="https://example.com/mcp" spellCheck={false} /></Field>
          <Field label="请求头（可选）" hint={'每行一个 名称=值，例如 Authorization=Bearer xxx。' + secretHint}><textarea className={inputCls + ' font-mono text-sm'} rows={2} value={f.headers} onChange={set('headers')} spellCheck={false} /></Field>
        </>
      )}
    </Modal>
  )
}

function ImportModal({ onClose, onSaved, notify }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true)
    try {
      const r = await api('POST', '/mcp/import', { json: text })
      notify(`导入了 ${r.servers.length} 个服务`)
      onSaved()
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal wide title="从配置导入" sub="粘贴 Claude Desktop、Cursor 等客户端里的 MCP 配置（含 mcpServers 的 JSON）。" onClose={onClose}
      footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn kind="primary" disabled={busy || !text.trim()} onClick={go}>{busy ? '正在连接…' : '导入'}</Btn></>}>
      <textarea className={inputCls + ' font-mono text-sm'} rows={12} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
        placeholder={'{\n  "mcpServers": {\n    "filesystem": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\\\docs"] }\n  }\n}'} />
    </Modal>
  )
}

export default function Mcp({ data, notify, reload, askManager, manager }) {
  const [list, setList] = useState(null)
  const [q, setQ] = useState('')
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const shown = (list || []).filter((m) => words.every((w) => (m.name + ' ' + m.tools.map((t) => t.name + ' ' + t.description).join(' ')).toLowerCase().includes(w)))
  const [modal, setModal] = useState(null)
  const [importing, setImporting] = useState(false)
  const [open, setOpen] = useState({})
  const load = useCallback(() => api('GET', '/mcp').then((r) => setList(r.servers)).catch((e) => notify(e.message)), [notify])
  const mcpCount = (data.mcp || []).length // 管家在后台装好后会推送刷新：数量一变就重新拉列表
  useEffect(() => { load() }, [load, mcpCount])
  const users = (id) => data.agents.filter((a) => (a.mcps || []).includes(id)).map((a) => a.name)
  const act = async (fn) => { try { await fn() } catch (e) { notify(e.message) } load(); reload() }
  return (
    <>
      <MobileBar title="MCP"><IconBtn icon="plus" label="添加 MCP 服务" size={40} onClick={() => setModal({})} /></MobileBar>
      <Page title="MCP 服务" lead="接入外部工具（文件系统、浏览器、数据库、各种 API）。在智能体设置里勾选后它就能调用，每次调用前都会请你确认。"
        action={<div className="hidden gap-2 md:flex"><Btn onClick={() => setImporting(true)}>从配置导入</Btn><Btn kind="primary" icon="plus" onClick={() => setModal({})}>添加服务</Btn></div>}>
        <ManagerBox askManager={askManager} manager={manager} onDone={() => { load(); reload() }} placeholder="粘贴 MCP 项目网址或远程地址，管家会读说明、配好启动方式"
          examples={['我想让智能体能操作浏览器，帮我找个合适的 MCP', '检查一下哪些 MCP 连不上']} />
        {(list || []).length > 0 && <div className="mb-4"><SearchInput value={q} onChange={setQ} placeholder="搜索服务名和工具" /></div>}
        {list == null ? <div className="skeleton h-3 w-40" /> : list.length === 0 ? (
          <Empty icon="plug" title="还没有 MCP 服务" text="添加一个，或者把别的客户端里的 mcpServers 配置粘贴过来。">
            <div className="flex gap-2"><Btn kind="primary" icon="plus" onClick={() => setModal({})}>添加服务</Btn><Btn onClick={() => setImporting(true)}>从配置导入</Btn></div>
          </Empty>
        ) : (
          <ul className="space-y-3">
            {shown.length === 0 && <li className="rounded-2xl border border-dashed border-line-strong px-5 py-6 text-sm text-faint">没有匹配「{q}」的服务</li>}
            {shown.map((m) => {
              const used = users(m.id)
              return (
                <li key={m.id} className="rounded-2xl border border-line bg-raised p-5">
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[15px] font-semibold text-ink">{m.name}</span>
                        <Tag>{m.transport === 'http' ? 'HTTP' : 'stdio'}</Tag>
                        {m.error ? <Tag tone="danger">连接失败</Tag> : <Tag tone="ok">{m.tools.length} 个工具</Tag>}
                        {!m.enabled && <Tag>已停用</Tag>}
                        {used.length > 0 && <Tag tone="accent">{used.join('、')} 在用</Tag>}
                      </div>
                      <p className="mt-1 truncate font-mono text-xs text-faint">{m.transport === 'http' ? m.url : [m.command, ...m.args].join(' ')}</p>
                    </div>
                    <IconBtn icon="refresh" label="重新连接" onClick={() => act(() => api('POST', `/mcp/${m.id}/refresh`))} />
                    <IconBtn icon="edit" label="编辑" onClick={() => setModal(m)} />
                    <IconBtn icon="trash" label="删除" kind="danger" onClick={async () => (await ask(`删除 MCP 服务「${m.name}」？`)) && act(() => api('DELETE', '/mcp/' + m.id))} />
                  </div>
                  {m.error && <p className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger [overflow-wrap:anywhere]">{m.error}</p>}
                  <div className="mt-3 flex items-center gap-4 text-[13px]">
                    <label className="flex items-center gap-2 text-muted">
                      <input type="checkbox" checked={m.enabled} onChange={(e) => act(() => api('PUT', '/mcp/' + m.id, { ...m, enabled: e.target.checked }))} className="h-4 w-4 accent-[var(--accent)]" />启用
                    </label>
                    {m.tools.length > 0 && <button type="button" onClick={() => setOpen({ ...open, [m.id]: !open[m.id] })} className="inline-flex items-center gap-1 text-accent-ink hover:underline"><Icon name="terminal" size={14} />{open[m.id] ? '收起工具' : '查看工具'}</button>}
                  </div>
                  {open[m.id] && (
                    <ul className="mt-3 divide-y divide-line rounded-xl border border-line">
                      {m.tools.map((t) => (
                        <li key={t.name} className="px-3.5 py-2 text-[13px]">
                          <span className="font-mono font-medium text-ink">{t.name}</span>
                          <span className="ml-2 font-mono text-xs text-faint">({t.params.join(', ')})</span>
                          {t.description && <p className="mt-0.5 line-clamp-2 text-muted">{t.description}</p>}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Page>
      {modal && <McpModal initial={modal.id ? modal : null} notify={notify} onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); reload() }} />}
      {importing && <ImportModal notify={notify} onClose={() => setImporting(false)} onSaved={() => { setImporting(false); load(); reload() }} />}
    </>
  )
}
