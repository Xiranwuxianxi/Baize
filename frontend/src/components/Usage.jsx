import { ask } from './Dialog.jsx'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Icon } from './ui.jsx'

// token 数的简写：1234 → 1.2k，1234567 → 1.23M
export const fmt = (n) => {
  n = n || 0
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + 'k'
  return String(n)
}

function Tile({ label, value, sub }) {
  return (
    <div className="min-w-0 rounded-xl border border-line bg-raised px-4 py-3.5">
      <div className="text-xs text-faint">{label}</div>
      <div className="mt-1 font-mono text-2xl font-semibold tracking-tight text-ink tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 truncate text-xs text-muted">{sub}</div>}
    </div>
  )
}

// 每天用量：单一系列柱状图，悬停看具体数字
// 固定显示最近 14 天，没用的日子记 0：只有一天数据时也不会一根柱子占满整行
const lastDays = (n) => Array.from({ length: n }, (_, i) => {
  const d = new Date(Date.now() - (n - 1 - i) * 86400000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
})

function Daily({ days }) {
  const [hover, setHover] = useState(null)
  const byDay = Object.fromEntries(days.map((d) => [d.day, d]))
  const list = lastDays(14).map((day) => byDay[day] || { day, in: 0, out: 0, calls: 0 })
  const max = Math.max(1, ...list.map((d) => d.in + d.out))
  if (!days.length) return null
  const h = hover != null ? list[hover] : null
  return (
    <div className="rounded-xl border border-line bg-raised p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <div className="text-sm font-medium text-ink">每天用量（输入 + 输出 token）</div>
        <div className="truncate font-mono text-xs text-muted tabular-nums">
          {h ? `${h.day.slice(5)}：${fmt(h.in + h.out)}（输入 ${fmt(h.in)} · 输出 ${fmt(h.out)} · ${h.calls} 次）` : `最近 14 天`}
        </div>
      </div>
      <div className="flex h-28 items-end gap-[2px] border-b border-line" onMouseLeave={() => setHover(null)}>
        {list.map((d, i) => (
          <button key={d.day} type="button" onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)}
            aria-label={`${d.day}：${d.in + d.out} token`} className="flex h-full min-w-0 flex-1 items-end">
            <span className={'mx-auto block w-full max-w-10 rounded-t-[4px] transition-colors duration-150 ' + (!(d.in + d.out) ? 'bg-line' : hover === i ? 'bg-accent-strong' : 'bg-accent')}
              style={{ height: d.in + d.out ? `${Math.max(3, ((d.in + d.out) / max) * 100)}%` : '2px' }} />
          </button>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-[11px] text-faint">
        <span>{list[0].day.slice(5)}</span><span>{list[list.length - 1].day.slice(5)}</span>
      </div>
    </div>
  )
}

function Ranked({ title, rows, name }) {
  if (!rows.length) return null
  const max = Math.max(1, ...rows.map((r) => r.value))
  return (
    <div className="rounded-xl border border-line bg-raised p-4">
      <div className="mb-3 text-sm font-medium text-ink">{title}</div>
      <ul className="space-y-2.5">
        {rows.slice(0, 8).map((r) => (
          <li key={r.key} className="text-[13px]">
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate text-ink" title={r[name]}>{r[name]}</span>
              <span className="shrink-0 font-mono text-xs text-muted tabular-nums">{fmt(r.value)}{r.note ? ' · ' + r.note : ''}</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-sunken">
              <div className="h-full rounded-full bg-accent/70" style={{ width: `${(r.value / max) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

// 设置页：全局用量
export default function Usage({ notify, locked, onOpenConv }) {
  const [u, setU] = useState(null)
  const load = useCallback(() => api('GET', '/usage?days=30').then(setU).catch((e) => notify(e.message)), [notify])
  useEffect(() => { load() }, [load])
  if (!u) return <div className="skeleton h-24 w-full rounded-xl" />
  const t = u.today, r = u.range, all = u.total
  const empty = !all.calls
  const clear = async () => {
    if (!await ask('清空全部用量统计？聊天记录不受影响。')) return
    try { await api('DELETE', '/usage'); load() } catch (e) { notify(e.message) }
  }
  return (
    <div className="space-y-4">
      {empty ? (
        <p className="rounded-xl border border-dashed border-line-strong px-4 py-6 text-center text-[13px] text-faint">还没有用量记录。和智能体聊几句之后，这里会显示每天、每个模型、每个智能体用了多少 token。</p>
      ) : (<>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile label="今天" value={fmt(t.in + t.out)} sub={`${t.calls} 次请求`} />
          <Tile label="近 30 天" value={fmt(r.in + r.out)} sub={`输入 ${fmt(r.in)} · 输出 ${fmt(r.out)}`} />
          <Tile label="省 token 帮你省下" value={fmt(r.saved)} sub={r.in ? `少发了约 ${Math.round((r.saved / (r.in + r.saved)) * 100)}% 的输入` : '近 30 天'} />
          <Tile label="命中接口缓存" value={fmt(r.cached)} sub={r.in ? `占输入 ${Math.round((r.cached / r.in) * 100)}%，这部分更便宜` : '近 30 天'} />
        </div>
        <Daily days={u.days} />
        <div className="grid gap-3 lg:grid-cols-2">
          <Ranked title="按模型" name="name" rows={u.models.map((m) => ({ key: m.model, name: m.model, value: m.in + m.out, note: `${m.calls} 次` }))} />
          <Ranked title="按智能体" name="name" rows={u.agents.map((a) => ({ key: a.agent, name: a.agent, value: a.in + a.out, note: `${a.calls} 次` }))} />
        </div>
        {u.convs.length > 0 && (
          <div className="rounded-xl border border-line bg-raised p-4">
            <div className="mb-2 text-sm font-medium text-ink">用得最多的会话</div>
            <ul className="divide-y divide-line">
              {u.convs.map((c) => (
                <li key={c.id}>
                  <button type="button" disabled={c.title === '（已删除的会话）'} onClick={() => onOpenConv?.(c.id)}
                    className="flex w-full items-center justify-between gap-3 py-2 text-left text-[13px] text-ink hover:text-accent-ink disabled:text-faint">
                    <span className="min-w-0 truncate">{c.title}</span>
                    <span className="shrink-0 font-mono text-xs text-muted tabular-nums">{fmt(c.tokens)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-faint">
          <span>{all.est ? `其中 ${all.est} 次请求的接口没有返回用量，按字数估算。` : '数字来自各家接口返回的真实用量。'} 累计 {fmt(all.in + all.out)}，共 {all.calls} 次。</span>
          {!locked && <button type="button" onClick={clear} className="rounded-md px-2 py-1 text-muted hover:bg-sunken hover:text-danger">清空统计</button>}
        </div>
      </>)}
    </div>
  )
}

// 会话设置里：这个会话的用量
export function ConvUsage({ convId }) {
  const [u, setU] = useState(null)
  useEffect(() => { api('GET', `/conversations/${convId}/usage`).then(setU).catch(() => setU({ total: {}, agents: [] })) }, [convId])
  if (!u) return <div className="skeleton h-16 w-full rounded-xl" />
  const t = u.total
  if (!t.calls) return <p className="rounded-xl border border-dashed border-line-strong px-4 py-5 text-[13px] text-faint">这个会话还没有用量。</p>
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <Tile label="合计" value={fmt(t.in + t.out)} sub={`${t.calls} 次`} />
        <Tile label="输入 / 输出" value={`${fmt(t.in)}/${fmt(t.out)}`} />
        <Tile label="省下" value={fmt(t.saved)} />
      </div>
      <Ranked title="按智能体" name="name" rows={u.agents.map((a) => ({ key: a.agent, name: a.agent, value: a.in + a.out, note: `${a.calls} 次` }))} />
      <p className="flex items-center gap-1.5 text-xs text-faint"><Icon name="coins" size={13} />{t.est ? '部分请求的接口没有返回用量，按字数估算。' : '数字来自接口返回的真实用量。'}</p>
    </div>
  )
}
