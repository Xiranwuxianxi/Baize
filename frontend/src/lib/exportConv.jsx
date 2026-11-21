// 导出一个会话：Markdown（方便贴进笔记、文档）或独立的 HTML 网页（直接打开、发给别人看）。
// 在浏览器里生成，不经过服务器；智能体回复里的操作标签去掉，操作写成一行说明。
import { renderToStaticMarkup } from 'react-dom/server'
import Markdown from '../components/Markdown.jsx'
import { ACTION } from './actionTags.js'

const KIND = { run: '执行命令', read: '读取文件', write: '写入文件', mcp: '调用 MCP 工具', skill_read: '读取技能', fetch: '读取网页',
  skill_find: '搜索技能与 MCP', skill_add: '添加技能', skill_remove: '删除技能', mcp_add: '添加 MCP 服务', mcp_remove: '删除 MCP 服务',
  hire: '新建智能体', fire: '移除智能体' }
const STATUS = { done: '已完成', failed: '失败', denied: '被拒绝', cancelled: '已取消', pending: '未处理', running: '进行中' }

const clean = (text) => (text || '').replace(ACTION, '').trim()
const when = (ts) => new Date(ts * 1000).toLocaleString()
const files = (m) => (m.attachments || []).map((a) => `> 附件：${a.name}（${a.path}）`)

function opLine(m) {
  const a = m.action || {}
  const what = a.command || a.path || a.url || a.name || (a.server ? `${a.server}/${a.tool}` : '') || a.q || ''
  return `${KIND[a.kind] || '操作'}${what ? '：' + what : ''}（${STATUS[m.status] || m.status}）`
}

// 把消息整理成「段」：普通消息一条一段；同一批并行分派合成一段
function sections(messages) {
  const out = []
  const boards = {}
  for (const m of messages) {
    if (!m.batch) { out.push({ m }); continue }
    if (!boards[m.batch]) { boards[m.batch] = { board: true, items: [] }; out.push(boards[m.batch]) }
    boards[m.batch].items.push(m)
  }
  return out
}

function byMember(items) {
  const cols = {}
  const order = []
  for (const m of items) {
    if (!cols[m.agent_id]) { cols[m.agent_id] = []; order.push(m.agent_id) }
    cols[m.agent_id].push(m)
  }
  return order.map((id) => cols[id])
}

export function toMarkdown(conv, messages, members) {
  const lines = [`# ${conv.title}`, '', `导出于 ${new Date().toLocaleString()} · 成员：${members.map((a) => a.name).join('、') || '无'}`, '']
  const one = (m, level = '###') => {
    if (m.role === 'notice') return lines.push(`*${m.content}*`, '')
    if (m.role === 'user') return lines.push(`**你**（${when(m.created)}）`, '', m.content || '', '', ...files(m), '')
    if (m.role === 'tool') return lines.push(`> ${m.agent_name}：${opLine(m)}`, '')
    lines.push(`${level} ${m.agent_name}${m.model ? `（${m.model}）` : ''}`, '')
    if (m.task) lines.push(`> 受派任务：${m.task}`, '')
    const text = clean(m.content)
    if (text) lines.push(text, '')
    if (m.error) lines.push(`> 出错：${m.error}`, '')
  }
  for (const s of sections(messages)) {
    if (!s.board) { one(s.m); continue }
    const cols = byMember(s.items)
    lines.push(`## 并行任务（${cols.length} 位成员同时进行）`, '')
    for (const col of cols) col.forEach((m) => one(m, '####'))
  }
  return lines.join('\n').replace(/\n{3,}/g, '\n\n') + '\n'
}

const CSS = `body{font:15px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#1f2328;background:#f6f7f7;margin:0}
main{max-width:820px;margin:0 auto;padding:40px 20px 80px}h1{font-size:26px;margin:0 0 4px}.meta{color:#6b7280;font-size:13px;margin-bottom:28px}
.msg{margin:18px 0}.who{font-size:13px;font-weight:600;color:#0f766e;margin-bottom:4px}.who small{color:#9ca3af;font-weight:400;margin-left:6px}
.bubble{background:#fff;border-radius:14px;padding:12px 16px;box-shadow:0 1px 2px rgba(0,0,0,.05)}.user .bubble{background:#0f766e;color:#fff}
.task,.op{font-size:13px;color:#4b5563;background:#f1f3f4;border-radius:8px;padding:6px 10px;margin:6px 0}.err{color:#b91c1c}
.notice{text-align:center;color:#6b7280;font-size:12px}.board{border:1px solid #e5e7eb;border-radius:16px;padding:12px;background:#eef1f1}
.board h2{font-size:14px;margin:0 0 10px}.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
.col{background:#fff;border-radius:12px;padding:10px 12px}.md pre{background:#111827;color:#e5e7eb;padding:10px;border-radius:8px;overflow:auto}
.md table{border-collapse:collapse}.md td,.md th{border:1px solid #e5e7eb;padding:4px 8px}.md pre div{display:none}`

const esc = (s) => String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])
const md = (text) => renderToStaticMarkup(<Markdown text={text} />)

export function toHTML(conv, messages, members) {
  const one = (m) => {
    if (m.role === 'notice') return `<p class="notice">${esc(m.content)}</p>`
    if (m.role === 'user') return `<div class="msg user"><div class="who">你<small>${esc(when(m.created))}</small></div><div class="bubble">${esc(m.content).replace(/\n/g, '<br>')}${files(m).map((f) => `<div class="op">${esc(f.slice(2))}</div>`).join('')}</div></div>`
    if (m.role === 'tool') return `<div class="op">${esc(m.agent_name)}：${esc(opLine(m))}</div>`
    return `<div class="msg"><div class="who">${esc(m.agent_name)}<small>${esc(m.model || '')}</small></div><div class="bubble">`
      + (m.task ? `<div class="task">受派任务：${esc(m.task)}</div>` : '') + md(clean(m.content))
      + (m.error ? `<p class="err">出错：${esc(m.error)}</p>` : '') + '</div></div>'
  }
  const body = sections(messages).map((s) => {
    if (!s.board) return one(s.m)
    const cols = byMember(s.items)
    return `<div class="board"><h2>并行任务 · ${cols.length} 位成员同时进行</h2><div class="cols">`
      + cols.map((col) => `<div class="col">${col.map(one).join('')}</div>`).join('') + '</div></div>'
  }).join('\n')
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(conv.title)}</title><style>${CSS}</style></head><body><main><h1>${esc(conv.title)}</h1>
<p class="meta">导出于 ${esc(new Date().toLocaleString())} · 成员：${esc(members.map((a) => a.name).join('、') || '无')}</p>${body}</main></body></html>`
}

export function download(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type: type + ';charset=utf-8' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
}

export function exportConversation(conv, messages, members, format) {
  const name = (conv.title || '会话').replace(/[\\/:*?"<>|\s]+/g, '-').slice(0, 40)
  if (format === 'html') download(name + '.html', toHTML(conv, messages, members), 'text/html')
  else download(name + '.md', toMarkdown(conv, messages, members), 'text/markdown')
}
