import { describe, expect, it } from 'vitest'
import { toHTML, toMarkdown } from './exportConv.jsx'

const conv = { title: '周报 <草稿>' }
const members = [{ name: '小李' }, { name: '小王' }]
const messages = [
  { id: '1', role: 'user', content: '帮我写周报', created: 1700000000 },
  { id: '2', role: 'agent', agent_id: 'a', agent_name: '小李', model: 'glm-4.7', content: '好的，**马上**分派。', created: 1700000001 },
  { id: '3', role: 'agent', agent_id: 'b', agent_name: '小王', batch: 'x', task: '整理数据', content: '数据如下', created: 1700000002 },
  { id: '4', role: 'tool', agent_id: 'b', agent_name: '小王', batch: 'x', action: { kind: 'run', command: 'ls' }, status: 'done', created: 1700000003 },
  { id: '5', role: 'agent', agent_id: 'c', agent_name: '小张', batch: 'x', task: '写结论', content: '结论', created: 1700000004 },
]

describe('导出会话', () => {
  it('Markdown 带标题、发言人和并行任务分组', () => {
    const md = toMarkdown(conv, messages, members)
    expect(md).toContain('# 周报 <草稿>')
    expect(md).toContain('### 小李（glm-4.7）')
    expect(md).toContain('## 并行任务（2 位成员同时进行）')
    expect(md).toContain('> 受派任务：整理数据')
    expect(md).toContain('> 小王：执行命令：ls（已完成）')
  })
  it('HTML 是独立网页，转义标题，渲染 Markdown', () => {
    const html = toHTML(conv, messages, members)
    expect(html.startsWith('<!doctype html>')).toBe(true)
    expect(html).toContain('周报 &lt;草稿&gt;')
    expect(html).toContain('<strong>马上</strong>')
    expect(html).toContain('class="board"')
    expect(html).not.toContain('<script')
  })
})
