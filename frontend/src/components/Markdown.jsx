import { memo, useState } from 'react'

// 轻量 Markdown 渲染：直接生成 React 节点，不拼 HTML，不依赖第三方组件。

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g

function inline(text) {
  const out = []
  let last = 0
  let m
  INLINE.lastIndex = 0
  while ((m = INLINE.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const key = m.index
    if (m[1]) out.push(<code key={key}>{m[1].slice(1, -1)}</code>)
    else if (m[2]) out.push(<strong key={key}>{m[2].slice(2, -2)}</strong>)
    else out.push(<a key={key} href={m[4]} target="_blank" rel="noreferrer noopener">{m[3]}</a>)
    last = INLINE.lastIndex
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function CodeBlock({ lang, code }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }
  return (
    <pre>
      <div className="flex items-center justify-between bg-white/5 px-3 py-1 text-xs text-white/55">
        <span>{lang || 'code'}</span>
        <button type="button" onClick={copy} className="rounded px-1.5 py-0.5 hover:bg-white/10">{copied ? '已复制' : '复制'}</button>
      </div>
      <code>{code}</code>
    </pre>
  )
}

const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())

function parse(src) {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const fence = /^\s*```(.*)$/.exec(line)
    if (fence) {
      const buf = []
      i++
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++])
      i++
      blocks.push(<CodeBlock key={blocks.length} lang={fence[1].trim()} code={buf.join('\n')} />)
      continue
    }
    if (!line.trim()) { i++; continue }
    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    if (h) {
      const Tag = 'h' + h[1].length
      blocks.push(<Tag key={blocks.length}>{inline(h[2])}</Tag>)
      i++
      continue
    }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { blocks.push(<hr key={blocks.length} />); i++; continue }
    if (/^\s*>/.test(line)) {
      const buf = []
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ''))
      blocks.push(<blockquote key={blocks.length}><p>{inline(buf.join('\n'))}</p></blockquote>)
      continue
    }
    const list = /^\s*([-*+]|\d+[.)])\s+/.exec(line)
    if (list) {
      const ordered = /\d/.test(list[1])
      const re = ordered ? /^\s*\d+[.)]\s+(.*)$/ : /^\s*[-*+]\s+(.*)$/
      const items = []
      while (i < lines.length) {
        const m = re.exec(lines[i])
        if (m) items.push(m[1])
        else if (items.length && /^\s{2,}\S/.test(lines[i])) items[items.length - 1] += '\n' + lines[i].trim()
        else break
        i++
      }
      const Tag = ordered ? 'ol' : 'ul'
      blocks.push(<Tag key={blocks.length}>{items.map((t, k) => <li key={k}>{inline(t)}</li>)}</Tag>)
      continue
    }
    if (line.includes('|') && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || '') && (lines[i + 1] || '').includes('|')) {
      const head = cells(line)
      const rows = []
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]))
      blocks.push(
        <table key={blocks.length}>
          <thead><tr>{head.map((c, k) => <th key={k}>{inline(c)}</th>)}</tr></thead>
          <tbody>{rows.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody>
        </table>
      )
      continue
    }
    const buf = []
    while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,4}\s|>|([-*+]|\d+[.)])\s)/.test(lines[i])) buf.push(lines[i++])
    if (!buf.length) buf.push(lines[i++])
    blocks.push(<p key={blocks.length}>{inline(buf.join('\n'))}</p>)
  }
  return blocks
}

export default memo(function Markdown({ text, className = '' }) {
  return <div className={'md ' + className}>{parse(text || '')}</div>
})
