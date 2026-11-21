import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import Markdown from './Markdown.jsx'

// 智能体的回复是不可信内容（可能来自被诱导的网页）：渲染时绝不能执行 HTML 或脚本。
const html = (text) => renderToStaticMarkup(<Markdown text={text} />)

describe('Markdown 渲染的安全性', () => {
  it('原始 HTML 只当文字显示，不会变成标签', () => {
    const out = html('<script>alert(1)</script> <img src=x onerror=alert(1)> <iframe src="https://evil.test"></iframe>')
    expect(out).not.toContain('<script')
    expect(out).not.toContain('<img')
    expect(out).not.toContain('<iframe')
    expect(out).toContain('&lt;script&gt;')
  })

  it('只有 http / https 链接会变成可点击的链接', () => {
    expect(html('[文档](https://example.com/a)')).toContain('<a href="https://example.com/a" target="_blank" rel="noreferrer noopener">文档</a>')
    for (const bad of ['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', 'vbscript:msgbox(1)', 'JaVaScRiPt:alert(1)']) {
      expect(html(`[点我](${bad})`)).not.toContain('<a ')
    }
  })

  it('代码块里的内容原样显示', () => {
    const out = html('```html\n<b onclick="x()">hi</b>\n```')
    expect(out).toContain('&lt;b onclick=&quot;x()&quot;&gt;hi&lt;/b&gt;')
    expect(out).not.toContain('<b onclick')
  })

  it('常用格式正常渲染', () => {
    const out = html('# 标题\n\n**加粗** 和 `代码`\n\n- 一\n- 二\n\n| a | b |\n|---|---|\n| 1 | 2 |')
    expect(out).toContain('<h1>标题</h1>')
    expect(out).toContain('<strong>加粗</strong>')
    expect(out).toContain('<code>代码</code>')
    expect(out).toContain('<li>一</li>')
    expect(out).toContain('<td>1</td>')
  })
})
